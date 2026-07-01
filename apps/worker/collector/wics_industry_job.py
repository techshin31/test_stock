"""Collect raw KOSPI constituent closes for WICS index reconstruction."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from data.loaders.kospi_data import download_stock_ohlcv
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.wics_industry_repo import (
    fetch_latest_constituent_price_dates,
    upsert_wics_constituent_prices,
)
from storage.postgres.repositories.wics_repo import fetch_kospi_wics_stock_codes

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def run(
    db: PostgreDB,
    start: str | None = None,
    end: str | None = None,
    show_progress: bool = True,
) -> dict[str, object]:
    """Incrementally collect raw closes without calculating industry returns."""
    effective_end = date.fromisoformat(end) if end else _today_kst()
    default_start = effective_end - timedelta(days=365 * 3 + 30)
    requested_start = date.fromisoformat(start) if start else default_start
    latest_by_stock = fetch_latest_constituent_price_dates(db)
    stock_codes = fetch_kospi_wics_stock_codes(db)

    saved = 0
    failed: list[str] = []
    iterator = (
        _tqdm(stock_codes, desc="WICS 가격", unit="종목")
        if (show_progress and _HAS_TQDM)
        else stock_codes
    )
    for stock_code in iterator:
        effective_start = requested_start
        if stock_code in latest_by_stock:
            effective_start = max(
                effective_start,
                latest_by_stock[stock_code] + timedelta(days=1),
            )
        if effective_start > effective_end:
            continue
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

    print(
        f"[WICS-PRICE] 완료: {saved}건 저장, "
        f"실패 {len(failed)}종목"
    )
    return {"saved_rows": saved, "failed_stock_codes": failed}
