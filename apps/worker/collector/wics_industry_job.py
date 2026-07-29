"""Collect raw KOSPI constituent closes for WICS index reconstruction."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.collectors.yfinance_collector import _yf_download_with_retry
from data.loaders.kospi_data import download_stock_ohlcv
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.wics_industry_repo import (
    fetch_latest_constituent_price_dates,
    upsert_wics_constituent_prices,
)
from storage.postgres.repositories.wics_repo import fetch_kospi_wics_stock_codes


_YAHOO_BATCH_SIZE = 100

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _refresh_derived_industry_prices(db: PostgreDB, cutoff_date: date) -> int:
    """Materialize the point-in-time derived industry series after raw prices load."""
    from apps.worker.analyzer.config import load_config
    from apps.worker.analyzer.sector_job import refresh_industry_prices

    return refresh_industry_prices(db, cutoff_date, load_config())


def _batch_close_records(
    stock_codes: list[str],
    start: date,
    end: date,
) -> tuple[dict[str, list[dict]], list[str]]:
    """Fetch many KOSPI closes in one Yahoo request, retaining exact source labels."""
    if not stock_codes:
        return {}, []
    tickers = [f"{stock_code}.KS" for stock_code in stock_codes]
    try:
        quotes = _yf_download_with_retry(
            tickers=tickers,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            actions=False,
            group_by="ticker",
            threads=True,
            timeout=20,
            max_attempts=1,
        )
    except Exception:
        return {}, stock_codes
    if getattr(quotes, "empty", True):
        return {}, stock_codes

    records_by_code: dict[str, list[dict]] = {}
    for stock_code, ticker in zip(stock_codes, tickers):
        try:
            if getattr(quotes.columns, "nlevels", 1) > 1:
                if ticker in quotes.columns.get_level_values(0):
                    frame = quotes[ticker]
                elif ticker in quotes.columns.get_level_values(1):
                    frame = quotes.xs(ticker, axis=1, level=1)
                else:
                    continue
            else:
                frame = quotes
            closes = frame["Close"].dropna()
        except (AttributeError, KeyError, TypeError):
            continue
        rows = []
        for timestamp, value in closes.items():
            try:
                close = float(value)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            rows.append(
                {
                    "stock_code": stock_code,
                    "price_date": timestamp.date(),
                    "close": close,
                    "source_code": "YAHOO",
                }
            )
        if rows:
            records_by_code[stock_code] = rows
    missing = [code for code in stock_codes if code not in records_by_code]
    return records_by_code, missing


def run(
    db: PostgreDB,
    start: str | None = None,
    end: str | None = None,
    show_progress: bool = True,
    rebuild_industry_prices: bool = False,
    single_symbol_fallback: bool = False,
    max_batches: int | None = None,
) -> dict[str, object]:
    """Incrementally collect raw closes and optionally rebuild derived WICS levels.

    The raw constituent data remains the source of truth.  Rebuilding is opt-in
    for direct callers so historical tooling can load prices alone; the normal
    ``collect wics`` and ``collect all`` paths enable it.  Batch misses are
    retried on later incremental runs by default; callers can opt into a
    slower single-symbol fallback for targeted repair.
    """
    if max_batches is not None and max_batches < 1:
        raise ValueError("max_batches must be positive when provided")
    effective_end = date.fromisoformat(end) if end else _today_kst()
    default_start = effective_end - timedelta(days=365 * 3 + 30)
    requested_start = date.fromisoformat(start) if start else default_start
    latest_by_stock = fetch_latest_constituent_price_dates(db)
    stock_codes = fetch_kospi_wics_stock_codes(db)

    saved = 0
    failed: list[str] = []
    deferred: list[str] = []
    processed_batches = 0
    iterator = (
        _tqdm(stock_codes, desc="WICS 가격", unit="종목")
        if (show_progress and _HAS_TQDM)
        else stock_codes
    )
    pending_by_start: dict[date, list[str]] = {}
    for stock_code in iterator:
        effective_start = requested_start
        if stock_code in latest_by_stock:
            effective_start = max(
                effective_start,
                latest_by_stock[stock_code] + timedelta(days=1),
            )
        if effective_start > effective_end:
            continue
        pending_by_start.setdefault(effective_start, []).append(stock_code)

    for effective_start, pending_codes in pending_by_start.items():
        # A normal daily update has many symbols with the same missing window.
        # Batch them to avoid serial Yahoo calls.  Missing quotes are reported
        # for the next bounded retry rather than turning one delayed vendor
        # response into hundreds of blocking single-symbol requests.
        batch_records: dict[str, list[dict]] = {}
        missing_codes = pending_codes
        if len(pending_codes) >= 5:
            missing_codes = []
            for offset in range(0, len(pending_codes), _YAHOO_BATCH_SIZE):
                code_batch = pending_codes[offset : offset + _YAHOO_BATCH_SIZE]
                if max_batches is not None and processed_batches >= max_batches:
                    deferred.extend(code_batch)
                    continue
                batch_records, batch_missing = _batch_close_records(
                    code_batch,
                    effective_start,
                    effective_end,
                )
                processed_batches += 1
                for records in batch_records.values():
                    saved += upsert_wics_constituent_prices(db, records)
                missing_codes.extend(batch_missing)

            if not single_symbol_fallback:
                failed.extend(missing_codes)
                missing_codes = []

        for stock_code in missing_codes:
            frame = download_stock_ohlcv(
                f"{stock_code}.KS",
                effective_start.isoformat(),
                (effective_end + timedelta(days=1)).isoformat(),
            )
            if frame is None or frame.empty:
                failed.append(stock_code)
                continue
            records = [
                {
                    "stock_code": stock_code,
                    "price_date": timestamp.date(),
                    "close": float(row["close"]),
                    "source_code": "YAHOO",
                }
                for timestamp, row in frame.iterrows()
            ]
            saved += upsert_wics_constituent_prices(db, records)

    derived_rows = 0
    if rebuild_industry_prices and not failed and not deferred:
        derived_rows = _refresh_derived_industry_prices(db, effective_end)

    print(
        f"[WICS-PRICE] 완료: {saved}건 저장, "
        f"실패 {len(failed)}종목"
    )
    if rebuild_industry_prices:
        if failed or deferred:
            print(
                "[WICS-PRICE] 파생 업종 지수 재구성 보류: "
                f"조회실패 {len(failed)}종목, 다음 배치 {len(deferred)}종목"
            )
        else:
            print(f"[WICS-PRICE] 파생 업종 지수: {derived_rows}건 저장")
    result: dict[str, object] = {
        "saved_rows": saved,
        "failed_stock_codes": failed,
    }
    if deferred:
        # Keep normal CLI output bounded.  The deferred symbols will be picked
        # up by the next incremental collection, so returning hundreds of
        # codes is log noise rather than actionable operational information.
        result["deferred_stock_count"] = len(deferred)
    return result
