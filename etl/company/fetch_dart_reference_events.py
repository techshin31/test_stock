from __future__ import annotations

import os
import time
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
COMPANY_PATH = ROOT / "etl" / "company" / "data" / "dart_company_2026.csv"
OUTPUT_DIR = ROOT / "etl" / "company" / "data"
ENV_PATH = ROOT / "etl" / "company" / ".env"


EVENT_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("shareholder_return", "cash_dividend", ("현금ㆍ현물배당결정", "현금배당결정", "주식배당결정")),
    ("shareholder_return", "buyback", ("자기주식취득결정", "자기주식취득 신탁계약 체결결정")),
    ("shareholder_return", "treasury_disposal", ("자기주식처분결정",)),
    ("shareholder_return", "share_cancellation", ("주식소각결정",)),
    ("capital_change", "paid_in_capital_increase", ("유상증자결정",)),
    ("capital_change", "bonus_issue", ("무상증자결정",)),
    ("capital_change", "convertible_bond", ("전환사채권발행결정",)),
    ("capital_change", "bond_with_warrant", ("신주인수권부사채권발행결정",)),
    ("capital_change", "exchange_bond", ("교환사채권발행결정",)),
    ("pipeline_event", "clinical_trial", ("임상", "임상시험")),
    ("pipeline_event", "approval", ("품목허가", "승인", "허가")),
    ("pipeline_event", "technology_transfer", ("기술수출", "기술이전", "라이선스아웃", "license-out")),
    ("business_event", "major_contract", ("단일판매ㆍ공급계약체결", "공급계약", "판매계약")),
    ("business_event", "investment_decision", ("투자판단 관련 주요경영사항",)),
]


def load_company_codes() -> pd.DataFrame:
    df = pd.read_csv(COMPANY_PATH, dtype=str)
    df["CMP_CD"] = df["CMP_CD"].str.zfill(6)
    df["DART_CD"] = df["DART_CD"].str.split(".").str[0].str.zfill(8)
    return df.loc[:, ["CMP_CD", "CMP_KOR", "DART_CD"]].rename(
        columns={
            "CMP_CD": "stock_code",
            "CMP_KOR": "company_name",
            "DART_CD": "corp_code",
        }
    )


def import_dart():
    load_dotenv(ENV_PATH)
    try:
        import OpenDartReader
    except ImportError as exc:
        raise RuntimeError(
            "OpenDartReader가 설치되어 있지 않습니다. "
            "먼저 `pip install -r etl\\company\\requirements.txt`를 실행해 주세요."
        ) from exc

    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        raise RuntimeError("환경변수 DART_API_KEY가 필요합니다.")
    return OpenDartReader(api_key)


def classify_report(report_name: str) -> tuple[str, str]:
    text = str(report_name or "")
    for category, subtype, keywords in EVENT_RULES:
        if any(keyword in text for keyword in keywords):
            return category, subtype
    return "other", "unclassified"


def normalize_event_rows(df: pd.DataFrame, *, stock_code: str, company_name: str, corp_code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    events = df.copy()
    if "report_nm" not in events.columns:
        return pd.DataFrame()

    classified = events["report_nm"].apply(classify_report)
    events["event_category"] = classified.str[0]
    events["event_subtype"] = classified.str[1]
    events["stock_code"] = stock_code
    events["company_name"] = company_name
    events["corp_code"] = corp_code

    ordered = [
        "stock_code",
        "company_name",
        "corp_code",
        "corp_cls",
        "rcept_no",
        "report_nm",
        "flr_nm",
        "rcept_dt",
        "rm",
        "event_category",
        "event_subtype",
    ]
    for column in ordered:
        if column not in events.columns:
            events[column] = pd.NA
    return events[ordered]


def fetch_company_events(dart, *, corp_code: str, stock_code: str, company_name: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        reports = dart.list(corp_code=corp_code, start=start_date, end=end_date, final=True)
    except TypeError:
        reports = dart.list(corp_code, start=start_date, end=end_date, final=True)

    normalized = normalize_event_rows(
        reports,
        stock_code=stock_code,
        company_name=company_name,
        corp_code=corp_code,
    )
    if normalized.empty:
        return normalized

    relevant = normalized.loc[normalized["event_category"] != "other"].copy()
    return relevant.sort_values(["rcept_dt", "report_nm"], ascending=[False, True])


def fetch_all_events(start_date: str, end_date: str, *, limit: int | None = None, sleep_seconds: float = 0.2) -> pd.DataFrame:
    dart = import_dart()
    companies = load_company_codes()
    if limit is not None:
        companies = companies.head(limit)

    frames: list[pd.DataFrame] = []
    for row in companies.itertuples(index=False):
        try:
            company_events = fetch_company_events(
                dart,
                corp_code=row.corp_code,
                stock_code=row.stock_code,
                company_name=row.company_name,
                start_date=start_date,
                end_date=end_date,
            )
            if not company_events.empty:
                frames.append(company_events)
        except Exception as exc:
            print(f"[WARN] {row.company_name}({row.stock_code}) 수집 실패: {exc}")
        time.sleep(sleep_seconds)

    if not frames:
        return pd.DataFrame(
            columns=[
                "stock_code",
                "company_name",
                "corp_code",
                "corp_cls",
                "rcept_no",
                "report_nm",
                "flr_nm",
                "rcept_dt",
                "rm",
                "event_category",
                "event_subtype",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="DART 공시에서 배당/자사주/증자/이벤트 참조데이터를 수집합니다.")
    parser.add_argument("--start-date", required=True, help="조회 시작일 (YYYYMMDD)")
    parser.add_argument("--end-date", required=True, help="조회 종료일 (YYYYMMDD)")
    parser.add_argument("--limit", type=int, help="테스트용 회사 수 제한")
    parser.add_argument("--sleep", type=float, default=0.2, help="회사별 요청 간 대기 시간(초)")
    return parser


def main() -> None:
    parser = parse_args()
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    events = fetch_all_events(
        args.start_date,
        args.end_date,
        limit=args.limit,
        sleep_seconds=args.sleep,
    )
    output_path = OUTPUT_DIR / f"dart_reference_events_{args.start_date}_{args.end_date}.csv"
    events.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved DART reference events: {output_path}")
    print(f"Rows: {len(events)}")


if __name__ == "__main__":
    main()
