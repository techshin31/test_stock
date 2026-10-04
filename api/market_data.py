"""Observed market-series calculations; no network requests or HTTP routes."""
import datetime as dt
import math
from zoneinfo import ZoneInfo

from core.utils.trading_calendar import is_krx_trading_day, previous_krx_trading_day

SEOUL = ZoneInfo("Asia/Seoul")


def _finite_float(value: object) -> float | None:
    """Return a finite numeric value without coercing missing data to zero."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def _latest_volume(frame: object) -> int | None:
    """Read the latest reported volume, preserving unavailable values as None."""
    try:
        if "Volume" not in frame:
            return None
        value = _finite_float(frame["Volume"].iloc[-1])
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return int(value) if value is not None and value >= 0 else None

def _index_history_points(
    kospi: object, kosdaq: object, limit: int = 60
) -> list[dict]:
    """Build only overlapping, observed KOSPI/KOSDAQ closes for the UI chart."""
    try:
        if "Close" not in kospi or "Close" not in kosdaq:
            return []
        common_dates = kospi.index.intersection(kosdaq.index)
    except (AttributeError, TypeError):
        return []

    history: list[dict] = []
    for value_date in common_dates[-limit:]:
        try:
            kospi_close = _finite_float(kospi.loc[value_date, "Close"])
            kosdaq_close = _finite_float(kosdaq.loc[value_date, "Close"])
        except (KeyError, TypeError):
            continue
        if kospi_close is None or kosdaq_close is None:
            continue
        date_text = (
            value_date.strftime("%Y-%m-%d")
            if hasattr(value_date, "strftime")
            else str(value_date)[:10]
        )
        history.append(
            {
                "date": date_text,
                "KOSPI": round(kospi_close, 2),
                "KOSDAQ": round(kosdaq_close, 2),
            }
        )
    return history

def _close_history_points(frame: object, limit: int = 60) -> list[dict]:
    """Return observed close-only points without filling missing market sessions."""
    try:
        closes = frame["Close"].dropna().tail(limit)
    except (AttributeError, KeyError, TypeError):
        return []

    history: list[dict] = []
    for value_date, close in closes.items():
        close_value = _finite_float(close)
        if close_value is None:
            continue
        date_text = (
            value_date.strftime("%Y-%m-%d")
            if hasattr(value_date, "strftime")
            else str(value_date)[:10]
        )
        history.append({"date": date_text, "close": round(close_value, 2)})
    return history

def _frame_observation_date(frame: object) -> dt.date | None:
    """Return the date of the last observed daily bar without inventing one."""
    try:
        value = frame.index[-1]
    except (AttributeError, IndexError, TypeError):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None

def _market_observation_status(
    observation_date: dt.date | None,
    now: dt.datetime,
) -> str:
    """Classify a live quote without calling an in-progress day a final close."""
    if observation_date is None:
        return "UNAVAILABLE"
    current = now.astimezone(SEOUL)
    if (
        observation_date == current.date()
        and is_krx_trading_day(current.date().isoformat())
        and current.time() < dt.time(15, 30)
    ):
        return "INTRADAY"
    if observation_date == _expected_completed_krx_date(current):
        return "COMPLETED"
    return "STALE"

def _completed_market_frame(frame: object, now: dt.datetime) -> object:
    """Exclude the still-open KRX session from close-based charts and volatility."""
    observation_date = _frame_observation_date(frame)
    if _market_observation_status(observation_date, now) != "INTRADAY":
        return frame
    try:
        return frame.iloc[:-1]
    except (AttributeError, IndexError, TypeError):
        return frame

def _annualized_realized_volatility(
    frame: object, window: int = 20
) -> float | None:
    """Calculate observed close-to-close volatility, annualised over 252 sessions."""
    if window < 2:
        raise ValueError("window must be at least 2")
    points = _close_history_points(frame, limit=window + 1)
    if len(points) < window + 1:
        return None

    returns: list[float] = []
    for previous, current in zip(points, points[1:]):
        previous_close = previous["close"]
        current_close = current["close"]
        if previous_close <= 0:
            return None
        returns.append((current_close / previous_close) - 1)
    if len(returns) < 2:
        return None

    average = sum(returns) / len(returns)
    variance = sum((value - average) ** 2 for value in returns) / (len(returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(252) * 100, 2)

def _expected_completed_krx_date(now: dt.datetime | None = None) -> dt.date:
    """Return the latest KRX session expected to have a completed close."""
    current = (now or dt.datetime.now(SEOUL)).astimezone(SEOUL)
    today = current.date()
    if is_krx_trading_day(today.isoformat()) and current.time() >= dt.time(15, 30):
        return today
    return previous_krx_trading_day(today)
