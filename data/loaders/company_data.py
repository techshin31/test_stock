"""기업 재무제표 및 DART 이벤트 로더.

DB 캐시 우선 전략:
- financial_statements: 종목·연도 단위로 캐시 확인 → 없으면 DART API 수집 → DB 저장
- dart_events: 최근 공시일 이후 기간만 증분 수집
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

from data.collectors.dart_collector import (
    fetch_company_detail as _fetch_company_detail,
    fetch_corp_codes as _fetch_corp_codes,
    fetch_dart_events as _fetch_dart_events,
    fetch_financial_statements as _fetch_fs,
    split_by_statement_type,
)
from data.collectors.krx_collector import (
    fetch_krx_market_map as _fetch_krx_market_map,
    fetch_krx_suspended_codes as _fetch_krx_suspended_codes,
)
from data.preprocess.financial_statements import calc_fa_metrics_from_db_rows
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.company_repo import (
    fetch_analysis_companies,
    fetch_all_companies,
    upsert_companies,
)
from storage.postgres.repositories.wics_repo import fetch_distinct_stock_codes
from storage.postgres.repositories.dart_event_repo import (
    fetch_dart_events,
    fetch_event_date_bounds,
    fetch_latest_regular_report,
    upsert_dart_events,
)
from storage.postgres.repositories.financial_repo import (
    fetch_collected_receipts,
    fetch_financial_statements,
    fetch_latest_fa_metrics,
    upsert_fa_metrics,
    upsert_financial_statements,
)


_REPORT_CONTRACT = {
    "11013": ("Q1_REPORT", 3),
    "11012": ("SEMI_ANNUAL_REPORT", 6),
    "11014": ("Q3_REPORT", 9),
    "11011": ("ANNUAL_REPORT", 12),
}


def collect_companies_from_wics(
    db: PostgreDB,
    *,
    show_progress: bool = True,
) -> int:
    """wics_companies 종목 중 companies에 없는 것만 DART에서 조회해 저장한다.

    Parameters
    ----------
    db : PostgreDB
    show_progress : bool
        콘솔 출력 여부

    Returns
    -------
    int
        새로 저장한 기업 수
    """
    wics_codes = set(fetch_distinct_stock_codes(db))
    if not wics_codes:
        if show_progress:
            print("[COMPANY] wics_companies가 비어 있음 — companies 수집 생략")
        return 0

    existing_codes = {c["stock_code"] for c in fetch_all_companies(db)}
    missing = wics_codes - existing_codes
    if not missing:
        if show_progress:
            print("[COMPANY] companies 테이블 최신 상태 — 신규 저장 없음")
        return 0

    if show_progress:
        print(f"[COMPANY] DART corp 목록 다운로드 중... (신규 {len(missing)}개 종목)")

    corp_map = _fetch_corp_codes()
    market_map = _fetch_krx_market_map()
    suspended = _fetch_krx_suspended_codes()

    records = [
        {
            "stock_code":        code,
            "corp_code":         corp_map[code]["corp_code"],
            "company_name":      corp_map[code]["company_name"],
            "market_type_code":  market_map.get(code),
            "status_code":       "SUSPENDED" if code in suspended else "ACTIVE",
        }
        for code in sorted(missing)
        if code in corp_map
    ]

    if records:
        upsert_companies(db, records)

    if show_progress:
        print(f"[COMPANY] companies 저장 완료: {len(records)}건")

    return len(records)


def sync_company_status(
    db: PostgreDB,
    *,
    show_progress: bool = True,
) -> int:
    """KRX 현재 상장 목록과 비교해 companies 전체의 market_type_code·status_code를 동기화한다.

    상태 판정 규칙:
    - KRX 목록에 없음           → DELISTED
    - KRX 목록에 있고 거래정지  → SUSPENDED
    - KRX 목록에 있고 정상      → ACTIVE

    Returns
    -------
    int
        업데이트된 행 수
    """
    all_companies = fetch_all_companies(db)
    if not all_companies:
        if show_progress:
            print("[COMPANY] companies 테이블이 비어 있음 — 상태 동기화 생략")
        return 0

    if show_progress:
        print(f"[COMPANY] KRX 상장 목록 조회 중... (전체 {len(all_companies)}개 종목)")

    market_map = _fetch_krx_market_map()
    if not market_map:
        print("[WARN] KRX 전체 조회 실패 — 상태 동기화 생략 (기존 상태 유지)")
        return 0
    suspended = _fetch_krx_suspended_codes()

    records = []
    for c in all_companies:
        code = c["stock_code"]
        if code not in market_map:
            status = "DELISTED"
            market = c.get("market_type_code")   # 상폐 종목은 기존 값 유지
        elif code in suspended:
            status = "SUSPENDED"
            market = market_map[code]
        else:
            status = "ACTIVE"
            market = market_map[code]

        records.append({
            "stock_code":       code,
            "corp_code":        c["corp_code"],
            "company_name":     c["company_name"],
            "market_type_code": market,
            "status_code":      status,
        })

    if records:
        upsert_companies(db, records)

    if show_progress:
        from collections import Counter
        counts = Counter(r["status_code"] for r in records)
        print(
            f"[COMPANY] 상태 동기화 완료 — "
            f"ACTIVE {counts['ACTIVE']}, "
            f"SUSPENDED {counts['SUSPENDED']}, "
            f"DELISTED {counts['DELISTED']}"
        )

    return len(records)


def _df_to_records(
    df: pd.DataFrame,
    stock_code: str,
    corp_code: str,
    bsns_year: int,
    reprt_code: str,
    fs_div: str,
    sj_div: str,
    report: dict,
) -> list[dict]:
    """DART API DataFrame 행을 DB upsert용 dict 목록으로 변환한다."""
    if df.empty:
        return []
    records = []
    for _, row in df.iterrows():
        records.append({
            "stock_code":       stock_code,
            "corp_code":        corp_code,
            "bsns_year":        bsns_year,
            "reprt_code":       reprt_code,
            "fs_div":           fs_div,
            "sj_div":           sj_div,
            "account_id":       row.get("account_id"),
            "account_nm":       str(row.get("account_nm", "")),
            "source_rcept_no":  report["rcept_no"],
            "rcept_dt":         report["rcept_dt"],
            "available_date":   report["rcept_dt"],
            "period_start":     report["period_start"],
            "period_end":       report["period_end"],
            "thstrm_amount":    _to_int(row.get("thstrm_amount")),
            "frmtrm_amount":    _to_int(row.get("frmtrm_amount")),
            "bfefrmtrm_amount": _to_int(row.get("bfefrmtrm_amount")),
            "thstrm_add_amount": _to_int(row.get("thstrm_add_amount")),
            "frmtrm_add_amount": _to_int(row.get("frmtrm_add_amount")),
            "revision_no":      int(report["revision_no"]),
        })
    return records


def _to_int(val) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def collect_financial_statements(
    db: PostgreDB,
    years: list[int],
    *,
    fs_div: str = "CFS",
    reprt_codes: tuple[str, ...] = ("11013", "11012", "11014", "11011"),
    company_size_codes: list[str] | None = None,
    sleep_seconds: float = 0.5,
    show_progress: bool = True,
) -> int:
    """companies 테이블의 전체 종목 재무제표를 수집해 DB에 저장한다.

    캐시 우선 전략: 이미 수집된 (종목, 연도) 조합은 DART API를 호출하지 않는다.

    Parameters
    ----------
    db : PostgreDB
    years : list[int]
        수집할 사업연도 목록 (예: [2022, 2023, 2024])
    fs_div : str
        CFS=연결, OFS=별도
    reprt_codes : tuple[str, ...]
        DART 정기보고서 코드. 기본값은 1분기·반기·3분기·사업보고서 전체.
    sleep_seconds : float
        DART API 호출 간 대기 시간
    show_progress : bool
        tqdm 진행바 출력 여부

    Returns
    -------
    int
        새로 수집한 (종목, 연도) 조합 수
    """
    companies = fetch_analysis_companies(db, company_size_codes)
    if not companies:
        return 0

    iterator = _tqdm(companies, desc="재무제표 수집") if (show_progress and _HAS_TQDM) else companies
    collected = 0
    acc_mt_cache: dict[str, int | None] = {}  # corp_code → acc_mt (세션 내 메모리 캐시)

    for company in iterator:
        stock_code = company["stock_code"]
        corp_code  = company["corp_code"]

        collected_receipts = fetch_collected_receipts(db, stock_code)
        if corp_code not in acc_mt_cache:
            detail = _fetch_company_detail(corp_code)
            acc_mt_cache[corp_code] = detail["acc_mt"] if detail else None
        acc_mt = acc_mt_cache[corp_code]

        for year in years:
            for reprt_code in reprt_codes:
                subtype, period_month = _REPORT_CONTRACT[reprt_code]
                period_label = f"{year}.{period_month:02d}"
                receipt = fetch_latest_regular_report(
                    db, stock_code, subtype, period_label
                )
                if not receipt:
                    continue

                if receipt["rcept_no"] in collected_receipts:
                    # 원본 적재 후 지표 계산만 실패한 경우에도 다음 실행에서 복구한다.
                    if reprt_code == "11011":
                        fs_rows = fetch_financial_statements(
                            db, stock_code, year, fs_div, reprt_code
                        )
                        metrics = calc_fa_metrics_from_db_rows(
                            fs_rows, stock_code, year, fs_div, acc_mt=acc_mt
                        )
                        if metrics:
                            upsert_fa_metrics(db, [metrics])
                    continue

                report = {
                    **receipt,
                    "period_start": date(year, 1, 1),
                    "period_end": date(year, period_month, 1) + (
                        timedelta(days=31)
                    ),
                }
                report["period_end"] = report["period_end"].replace(day=1) - timedelta(days=1)

                time.sleep(sleep_seconds)
                try:
                    df_all = _fetch_fs(
                        corp_code, year, reprt_code=reprt_code, fs_div=fs_div
                    )
                except Exception as exc:
                    print(
                        f"[WARN] {company['company_name']}({stock_code}) "
                        f"{year}/{reprt_code} 수집 실패: {exc}"
                    )
                    continue
                if df_all.empty:
                    continue

                tables = split_by_statement_type(df_all)
                records: list[dict] = []
                for sj_div, statement in (
                    ("BS", tables["BS"]),
                    ("IS", tables["IS"]),
                    ("CF", tables["CF"]),
                ):
                    records.extend(
                        _df_to_records(
                            statement, stock_code, corp_code, year,
                            reprt_code, fs_div, sj_div, report,
                        )
                    )
                if not records:
                    continue

                upsert_financial_statements(db, records)
                collected_receipts.add(receipt["rcept_no"])

                if reprt_code == "11011":
                    fs_rows = fetch_financial_statements(
                        db, stock_code, year, fs_div, reprt_code
                    )
                    metrics = calc_fa_metrics_from_db_rows(
                        fs_rows, stock_code, year, fs_div, acc_mt=acc_mt
                    )
                    if metrics:
                        upsert_fa_metrics(db, [metrics])
                collected += 1

    return collected


def collect_dart_events(
    db: PostgreDB,
    start_date: str,
    end_date: str,
    *,
    sleep_seconds: float = 0.2,
    show_progress: bool = True,
    company_size_codes: list[str] | None = None,
) -> int:
    """companies 테이블의 전체 종목 DART 이벤트를 수집해 DB에 저장한다.

    종목별로 가장 최근 공시일 이후 기간만 증분 수집한다.

    Parameters
    ----------
    db : PostgreDB
    start_date, end_date : str
        수집 기간 (YYYYMMDD). 이미 수집된 데이터가 있으면 최근 공시일+1일부터 수집.

    Returns
    -------
    int
        새로 수집한 이벤트 수
    """
    companies = fetch_analysis_companies(db, company_size_codes)
    if not companies:
        return 0

    iterator = _tqdm(companies, desc="DART 이벤트 수집") if (show_progress and _HAS_TQDM) else companies
    total = 0

    for company in iterator:
        stock_code = company["stock_code"]
        corp_code  = company["corp_code"]

        # Re-read a short overlap so same-day filings and later corrections
        # cannot be missed. rcept_no upsert keeps this idempotent.
        bounds = fetch_event_date_bounds(db, stock_code)
        earliest = bounds.get("earliest")
        latest = bounds.get("latest")
        effective_start = start_date
        requested_start = pd.Timestamp(start_date).date()
        has_historical_start = earliest is not None and earliest <= requested_start
        if latest is not None and has_historical_start:
            overlap_start = (latest - timedelta(days=7)).strftime("%Y%m%d")
            if overlap_start > start_date:
                effective_start = overlap_start

        if effective_start > end_date:
            continue

        try:
            df = _fetch_dart_events(
                corp_code, effective_start, end_date,
                sleep_seconds=sleep_seconds,
            )
        except Exception as e:
            print(f"[WARN] {company['company_name']}({stock_code}) 이벤트 수집 실패: {e}")
            continue

        if df.empty:
            continue

        records = [
            {
                "stock_code":          stock_code,
                "corp_code":           corp_code,
                "rcept_no":            row["rcept_no"],
                "rcept_dt":            row["rcept_dt"],
                "report_nm":           row["report_nm"],
                "pblntf_ty":           row["pblntf_ty"],
                "event_category_code": row["event_category_code"],
                "event_subtype_code":  row["event_subtype_code"],
                "flr_nm":              row.get("flr_nm"),
                "corp_cls":            row.get("corp_cls"),
                "rm":                  row.get("rm"),
            }
            for _, row in df.iterrows()
        ]
        upsert_dart_events(db, records)
        total += len(records)

    return total


def load_fa_metrics_df(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    fs_div: str = "CFS",
) -> pd.DataFrame:
    """최신 FA 지표를 피벗 DataFrame으로 반환한다.

    Returns
    -------
    pd.DataFrame
        index: stock_code, columns: roe, roa, operating_margin, debt_ratio, current_ratio, fcf
    """
    rows = fetch_latest_fa_metrics(db, stock_codes, fs_div)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.set_index("stock_code")
    metric_cols = ["roe", "roa", "operating_margin", "debt_ratio", "current_ratio", "fcf"]
    return df[[c for c in metric_cols if c in df.columns]]


def rebuild_annual_fa_metrics(db: PostgreDB, *, batch_size: int = 200) -> int:
    """최신 정정공시 기준으로 연간 FA 캐시와 버전 원장을 재생성한다."""
    groups = db.fetch_all(
        """
        SELECT DISTINCT stock_code, bsns_year, fs_div
        FROM financial_statements
        WHERE reprt_code = '11011'
          AND source_rcept_no NOT LIKE 'LEGACY:%%'
        ORDER BY stock_code, bsns_year, fs_div
        """
    )
    pending = []
    rebuilt = 0
    for group in groups:
        rows = fetch_financial_statements(
            db, group["stock_code"], group["bsns_year"], group["fs_div"], "11011"
        )
        metric = calc_fa_metrics_from_db_rows(
            rows, group["stock_code"], group["bsns_year"], group["fs_div"]
        )
        if metric:
            pending.append(metric)
        if len(pending) >= batch_size:
            rebuilt += upsert_fa_metrics(db, pending)
            pending.clear()
    if pending:
        rebuilt += upsert_fa_metrics(db, pending)
    return rebuilt


def load_dart_events_df(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    event_categories: list[str] | None = None,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    """DART 이벤트를 DataFrame으로 반환한다."""
    rows = fetch_dart_events(db, stock_codes, event_categories, start_date, end_date)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
