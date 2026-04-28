from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
MASTER_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
MARKET_DIR = ROOT / "etl" / "stock" / "data"
COMPANY_DATA_DIR = ROOT / "etl" / "company" / "data"
REFERENCE_BUNDLE_PATH = OUTPUT_DIR / "company_reference_bundle_latest.csv"
REFERENCE_MAPPING_PATH = OUTPUT_DIR / "available_reference_mapping.md"


def latest_market_snapshot_path() -> Path | None:
    candidates = list(MARKET_DIR.glob("market_reference_snapshot_*.csv"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def latest_dart_events_path() -> Path | None:
    candidates = list(COMPANY_DATA_DIR.glob("dart_reference_events_*.csv"))
    return max(candidates, key=lambda path: (path.stat().st_size, path.stat().st_mtime)) if candidates else None


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    result = numerator / denominator
    return result.where(denominator.notna() & (denominator != 0))


def load_latest_bundle() -> tuple[pd.DataFrame, Path | None]:
    master = pd.read_csv(MASTER_PATH)
    master["fiscal_year"] = pd.to_numeric(master["fiscal_year"], errors="coerce")
    master["stock_code"] = master["stock_code"].astype(str).str.split(".").str[0].str.zfill(6)
    master["corp_code"] = master["corp_code"].astype(str).str.split(".").str[0].str.zfill(8)
    master = master.sort_values(["stock_code", "fiscal_year"])

    master["operating_income_prev"] = master.groupby("stock_code")["operating_income"].shift(1)
    master["net_income_prev"] = master.groupby("stock_code")["net_income"].shift(1)
    master["operating_income_growth_yoy"] = safe_ratio(
        master["operating_income"] - master["operating_income_prev"],
        master["operating_income_prev"],
    )
    master["net_income_growth_yoy"] = safe_ratio(
        master["net_income"] - master["net_income_prev"],
        master["net_income_prev"],
    )

    latest_year = int(master["fiscal_year"].dropna().max())
    latest = master.loc[master["fiscal_year"] == latest_year].copy()

    market_path = latest_market_snapshot_path()
    if market_path is not None:
        market = pd.read_csv(market_path, dtype={"stock_code": str, "corp_code": str})
        market["stock_code"] = market["stock_code"].str.zfill(6)
        market["corp_code"] = market["corp_code"].astype(str).str.split(".").str[0].str.zfill(8)
        latest["stock_code"] = latest["stock_code"].astype(str).str.zfill(6)
        latest = latest.merge(
            market,
            on=["stock_code", "company_name", "corp_code"],
            how="left",
            suffixes=("", "_market"),
        )

    ordered_columns = [
        "company_name",
        "stock_code",
        "corp_code",
        "fiscal_year",
        "wics_large",
        "wics_index_name",
        "revenue",
        "revenue_prev",
        "revenue_growth_yoy",
        "operating_income",
        "operating_income_prev",
        "operating_income_growth_yoy",
        "operating_margin",
        "net_income",
        "net_income_prev",
        "net_income_growth_yoy",
        "roe",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "debt_ratio",
        "current_assets",
        "current_liabilities",
        "current_ratio",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "ocf_to_revenue",
        "snapshot_date",
        "market_cap_wics_raw",
        "trading_value_wics_raw",
        "shares_outstanding",
        "data_provider",
    ]
    existing_columns = [column for column in ordered_columns if column in latest.columns]
    return latest.loc[:, existing_columns].sort_values(["wics_large", "company_name"]), market_path


def build_mapping_markdown(bundle: pd.DataFrame, market_path: Path | None) -> str:
    market_path_text = str(market_path) if market_path is not None else "없음"
    dart_events_path = latest_dart_events_path()
    dart_events_text = str(dart_events_path) if dart_events_path is not None else "없음"
    lines = [
        "# 현재 확보된 FA 참조데이터 연결표",
        "",
        "이 문서는 현재 워크스페이스에서 실제로 확보되어 있거나 생성 가능한 참조데이터만 기준으로 정리한다.",
        "",
        "## 현재 사용 가능한 파일",
        "",
        f"- 재무·지표 마스터: `{MASTER_PATH}`",
        f"- 최신 참조 번들: `{REFERENCE_BUNDLE_PATH}`",
        f"- 최신 시장 스냅샷: `{market_path_text}`",
        f"- 최신 DART 이벤트 스냅샷: `{dart_events_text}`",
        f"- 손익계산서 원본: `{ROOT / 'etl' / 'company' / 'data' / 'income_statement_2025.csv'}`",
        f"- 재무상태표 원본: `{ROOT / 'etl' / 'company' / 'data' / 'balance_sheet_2025.csv'}`",
        f"- 현금흐름표 원본: `{ROOT / 'etl' / 'company' / 'data' / 'cash_flow_2025.csv'}`",
        f"- WICS 분류 원본: `{ROOT / 'etl' / 'wics' / 'data' / 'csv' / 'wics_company_2026.csv'}`",
        "",
        "## 평가항목별 연결",
        "",
        "| 평가항목 | 지금 바로 볼 파일 | 바로 확인할 컬럼 | 비고 |",
        "|---|---|---|---|",
        f"| 수익성 | `{REFERENCE_BUNDLE_PATH.name}` | `revenue`, `operating_income`, `net_income`, `operating_margin`, `roe` | 2025 최신 기준으로 바로 확인 가능 |",
        f"| 성장성 | `{REFERENCE_BUNDLE_PATH.name}` | `revenue_prev`, `revenue_growth_yoy`, `operating_income_prev`, `operating_income_growth_yoy`, `net_income_prev`, `net_income_growth_yoy` | 전년 대비 추이까지 계산해 둠 |",
        f"| 재무안정성 | `{REFERENCE_BUNDLE_PATH.name}` | `total_assets`, `total_liabilities`, `total_equity`, `debt_ratio`, `current_ratio` | 부채비율·유동비율 확인 가능 |",
        f"| 현금흐름 | `{REFERENCE_BUNDLE_PATH.name}` | `operating_cash_flow`, `investing_cash_flow`, `financing_cash_flow`, `ocf_to_revenue` | FCF는 CAPEX 원천을 추가 연결해야 더 정확함 |",
        f"| 밸류에이션 | `{REFERENCE_BUNDLE_PATH.name}` | `market_cap_wics_raw`, `trading_value_wics_raw`, `shares_outstanding`, `snapshot_date` | 현재는 WICS 로컬 스냅샷 기반. 주가/PER/PBR은 외부 수집 추가 필요 |",
        f"| 주주환원 | `{dart_events_path.name if dart_events_path is not None else '현재 구조화 파일 없음'}` | `event_category='shareholder_return'`, `event_subtype in (cash_dividend, buyback, treasury_disposal, share_cancellation)` | 배당·자사주·소각 공시 확인 가능 |",
        f"| 재무생존성 | `{REFERENCE_BUNDLE_PATH.name}` | `total_equity`, `operating_cash_flow`, `financing_cash_flow` | 현금및현금성자산/단기금융자산은 원본 현금흐름·재무상태표 계정 추가 추출 필요 |",
        f"| 파이프라인/이벤트 | `{dart_events_path.name if dart_events_path is not None else '현재 구조화 파일 없음'}` | `event_category='pipeline_event'`, `event_subtype in (clinical_trial, approval, technology_transfer)` | 임상·허가·기술수출 이벤트 확인 가능 |",
        f"| 비용통제 | `{ROOT / 'etl' / 'company' / 'data' / 'income_statement_2025.csv'}` | 원본 계정에서 `판관비`, `연구개발비` 계정 직접 추출 필요 | 아직 마스터에는 미반영 |",
        f"| 매출발생력 | `{REFERENCE_BUNDLE_PATH.name}` + 사업보고서 원문 | `revenue` + 사업부문/제품 매출 관련 본문 | 세부 매출구성은 사업보고서 본문 확장 필요 |",
        "",
        "## 현재 즉시 활용 가능한 핵심 컬럼",
        "",
        f"- 총 기업 수: `{len(bundle)}`",
        f"- 최신 기준연도: `{int(pd.to_numeric(bundle['fiscal_year'], errors='coerce').dropna().max()) if not bundle.empty else '없음'}`",
        "",
        "### 바로 점수화 가능한 항목",
        "",
        "- 수익성",
        "- 성장성",
        "- 재무안정성",
        "- 현금흐름",
        "- 일부 밸류에이션(시총/거래대금 기준)",
        "",
        "### 아직 추가 수집이 필요한 항목",
        "",
        "- 비용통제 세부 계정",
        "- 매출발생력 세부 구분",
        "- 주가/PER/PBR 등 완전한 밸류에이션 지표",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle, market_path = load_latest_bundle()
    bundle.to_csv(REFERENCE_BUNDLE_PATH, index=False, encoding="utf-8-sig")
    REFERENCE_MAPPING_PATH.write_text(build_mapping_markdown(bundle, market_path), encoding="utf-8")
    print(f"Saved reference bundle: {REFERENCE_BUNDLE_PATH}")
    print(f"Saved reference mapping: {REFERENCE_MAPPING_PATH}")
    print(f"Rows: {len(bundle)}")


if __name__ == "__main__":
    main()
