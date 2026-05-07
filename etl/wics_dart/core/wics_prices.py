from __future__ import annotations

from pathlib import Path
import zipfile

import pandas as pd


# ============================================================
# WICS local price helpers
#
# The WICS company files do not store a direct close column.
# They store market cap and applied share count, so we estimate:
#
#   close_est = MKT_VAL * 1,000,000 / APT_SHR_CNT
#
# MKT_VAL is stored in million KRW units in the local WICS files.
# ============================================================


WICS_USE_COLUMNS = [
    "DATE",
    "CMP_CD",
    "CMP_KOR",
    "SEC_CD",
    "SEC_NM_KOR",
    "MKT_VAL",
    "APT_SHR_CNT",
    "INFO_TRD_AMT",
]


def default_wics_data_dir(root: Path) -> Path:
    return root / "etl" / "wics" / "data" / "csv"


def wics_company_path(wics_data_dir: Path, year: int) -> Path:
    zip_path = wics_data_dir / f"wics_company_{year}.zip"
    csv_path = wics_data_dir / f"wics_company_{year}.csv"
    if zip_path.exists():
        return zip_path
    if csv_path.exists():
        return csv_path
    raise FileNotFoundError(f"WICS company file not found for {year}: {zip_path} or {csv_path}")


def read_wics_company_file(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    columns = usecols or WICS_USE_COLUMNS
    dtype = {"DATE": str, "CMP_CD": str}

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = archive.namelist()
            if not members:
                return pd.DataFrame(columns=columns)
            with archive.open(members[0]) as file:
                return pd.read_csv(file, dtype=dtype, usecols=columns)

    return pd.read_csv(path, dtype=dtype, usecols=columns)


def normalize_wics_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.rename(
        columns={
            "DATE": "date",
            "CMP_CD": "stock_code",
            "CMP_KOR": "company_name",
            "SEC_CD": "wics_large_code",
            "SEC_NM_KOR": "wics_large",
            "MKT_VAL": "market_cap_wics_raw",
            "APT_SHR_CNT": "shares_applied",
            "INFO_TRD_AMT": "trading_value_wics_raw",
        }
    ).copy()

    result["stock_code"] = result["stock_code"].astype(str).str.split(".").str[0].str.zfill(6)
    result["date"] = pd.to_datetime(result["date"], format="%Y%m%d", errors="coerce")
    result["market_cap_wics_raw"] = pd.to_numeric(result["market_cap_wics_raw"], errors="coerce")
    result["shares_applied"] = pd.to_numeric(result["shares_applied"], errors="coerce")
    result["trading_value_wics_raw"] = pd.to_numeric(result["trading_value_wics_raw"], errors="coerce")

    valid = result["date"].notna() & result["shares_applied"].gt(0) & result["market_cap_wics_raw"].gt(0)
    result = result.loc[valid].copy()
    result["close_est"] = result["market_cap_wics_raw"] * 1_000_000 / result["shares_applied"]

    result = result.drop_duplicates(
        subset=["date", "stock_code"],
        keep="last",
    )
    return result.sort_values(["date", "stock_code"]).reset_index(drop=True)


def load_wics_price_panel(
    years: list[int],
    *,
    root: Path,
    stock_codes: set[str] | None = None,
    wics_large: str | None = None,
) -> pd.DataFrame:
    """Load local WICS stock rows and estimate daily close prices."""
    wics_data_dir = default_wics_data_dir(root)
    frames: list[pd.DataFrame] = []

    normalized_codes = None
    if stock_codes is not None:
        normalized_codes = {str(code).split(".")[0].zfill(6) for code in stock_codes}

    for year in years:
        path = wics_company_path(wics_data_dir, year)
        frame = read_wics_company_file(path)

        if normalized_codes is not None:
            frame["CMP_CD"] = frame["CMP_CD"].astype(str).str.split(".").str[0].str.zfill(6)
            frame = frame.loc[frame["CMP_CD"].isin(normalized_codes)]

        if wics_large is not None:
            frame = frame.loc[frame["SEC_NM_KOR"] == wics_large]

        frames.append(normalize_wics_price_frame(frame))

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True).sort_values(["date", "stock_code"]).reset_index(drop=True)


def first_price_on_or_after(prices: pd.DataFrame, stock_code: str, target_date: pd.Timestamp) -> pd.Series | None:
    rows = prices.loc[(prices["stock_code"] == stock_code) & (prices["date"] >= target_date)]
    if rows.empty:
        return None
    return rows.sort_values("date").iloc[0]


def last_price_on_or_before(prices: pd.DataFrame, stock_code: str, target_date: pd.Timestamp) -> pd.Series | None:
    rows = prices.loc[(prices["stock_code"] == stock_code) & (prices["date"] <= target_date)]
    if rows.empty:
        return None
    return rows.sort_values("date").iloc[-1]


def holding_return_from_panel(
    prices: pd.DataFrame,
    stock_code: str,
    buy_date: pd.Timestamp,
    sell_date: pd.Timestamp,
) -> dict:
    buy = first_price_on_or_after(prices, stock_code, buy_date)
    sell = last_price_on_or_before(prices, stock_code, sell_date)

    if buy is None or sell is None:
        return {
            "stock_code": stock_code,
            "buy_date_actual": pd.NaT,
            "sell_date_actual": pd.NaT,
            "buy_close": pd.NA,
            "sell_close": pd.NA,
            "holding_return": pd.NA,
        }

    return {
        "stock_code": stock_code,
        "buy_date_actual": buy["date"],
        "sell_date_actual": sell["date"],
        "buy_close": buy["close_est"],
        "sell_close": sell["close_est"],
        "holding_return": sell["close_est"] / buy["close_est"] - 1,
    }


def holding_returns_for_codes(
    prices: pd.DataFrame,
    stock_codes: list[str],
    buy_date: pd.Timestamp,
    sell_date: pd.Timestamp,
) -> pd.DataFrame:
    """Vectorized holding returns for many stocks over one holding window."""
    codes = pd.Series(stock_codes, name="stock_code").astype(str).str.split(".").str[0].str.zfill(6)
    base = pd.DataFrame({"stock_code": codes.drop_duplicates().tolist()})

    scoped = prices.loc[prices["stock_code"].isin(base["stock_code"])].copy()
    if scoped.empty:
        base["buy_date_actual"] = pd.NaT
        base["sell_date_actual"] = pd.NaT
        base["buy_close"] = pd.NA
        base["sell_close"] = pd.NA
        base["holding_return"] = pd.NA
        return base

    buy = (
        scoped.loc[scoped["date"] >= buy_date]
        .sort_values(["stock_code", "date"])
        .groupby("stock_code", as_index=False)
        .first()
        .loc[:, ["stock_code", "date", "close_est"]]
        .rename(columns={"date": "buy_date_actual", "close_est": "buy_close"})
    )
    sell = (
        scoped.loc[scoped["date"] <= sell_date]
        .sort_values(["stock_code", "date"])
        .groupby("stock_code", as_index=False)
        .last()
        .loc[:, ["stock_code", "date", "close_est"]]
        .rename(columns={"date": "sell_date_actual", "close_est": "sell_close"})
    )

    result = base.merge(buy, on="stock_code", how="left").merge(sell, on="stock_code", how="left")
    result["holding_return"] = result["sell_close"] / result["buy_close"] - 1
    return result
