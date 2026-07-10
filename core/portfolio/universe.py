"""포트폴리오 유니버스 상태 관리.

분기 교체 전략에서 종목은 ACTIVE, SELL_ONLY, REMOVED 중 하나의 상태를 가진다.
이 모듈은 상태 저장과 필터링만 담당하고, 실제 교체 규칙은 rotation.py가 담당한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.constant.types import UniverseStatus


@dataclass
class UniverseEntry:
    """포트폴리오 유니버스의 단일 종목 상태."""

    ticker: str
    status: UniverseStatus = UniverseStatus.ACTIVE
    added_at: date | None = None
    sell_only_since: date | None = None
    force_exit_date: date | None = None
    removed_at: date | None = None
    reason: str | None = None


class PortfolioUniverse:
    """종목별 UniverseStatus를 관리하는 컨테이너."""

    def __init__(self, entries: list[UniverseEntry] | None = None) -> None:
        self._entries: dict[str, UniverseEntry] = {}
        for entry in entries or []:
            self._entries[entry.ticker] = entry

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    def get(self, ticker: str) -> UniverseEntry | None:
        """종목 상태 객체를 반환한다. 없으면 None."""
        return self._entries.get(ticker)

    def get_status(
        self,
        ticker: str,
        default: UniverseStatus = UniverseStatus.REMOVED,
    ) -> UniverseStatus:
        """종목의 UniverseStatus를 반환한다."""
        entry = self.get(ticker)
        return entry.status if entry is not None else default

    def set_active(
        self,
        ticker: str,
        added_at: date | None = None,
        reason: str | None = None,
    ) -> UniverseEntry:
        """종목을 정상 매매 가능 상태로 등록한다."""
        entry = self._entries.get(ticker)
        if entry is None:
            entry = UniverseEntry(ticker=ticker)
            self._entries[ticker] = entry

        entry.status = UniverseStatus.ACTIVE
        entry.added_at = added_at or entry.added_at
        entry.sell_only_since = None
        entry.force_exit_date = None
        entry.removed_at = None
        entry.reason = reason
        return entry

    def set_sell_only(
        self,
        ticker: str,
        sell_only_since: date | None = None,
        force_exit_date: date | None = None,
        reason: str | None = None,
    ) -> UniverseEntry:
        """종목을 매도 전용 상태로 전환한다."""
        entry = self._entries.get(ticker)
        if entry is None:
            entry = UniverseEntry(ticker=ticker)
            self._entries[ticker] = entry

        entry.status = UniverseStatus.SELL_ONLY
        entry.sell_only_since = sell_only_since
        entry.force_exit_date = force_exit_date
        entry.reason = reason
        return entry

    def remove(
        self,
        ticker: str,
        removed_at: date | None = None,
        reason: str | None = None,
    ) -> UniverseEntry:
        """종목을 유니버스 제거 상태로 전환한다."""
        entry = self._entries.get(ticker)
        if entry is None:
            entry = UniverseEntry(ticker=ticker)
            self._entries[ticker] = entry

        entry.status = UniverseStatus.REMOVED
        entry.removed_at = removed_at
        entry.reason = reason
        return entry

    def by_status(self, status: UniverseStatus) -> list[str]:
        """특정 상태의 종목 목록을 반환한다."""
        return [
            ticker
            for ticker, entry in self._entries.items()
            if entry.status == status
        ]

    def active_tickers(self) -> list[str]:
        """정상 매매 가능 종목 목록."""
        return self.by_status(UniverseStatus.ACTIVE)

    def sell_only_tickers(self) -> list[str]:
        """매도 전용 종목 목록."""
        return self.by_status(UniverseStatus.SELL_ONLY)

    def removed_tickers(self) -> list[str]:
        """제거 완료 종목 목록."""
        return self.by_status(UniverseStatus.REMOVED)

    def tradable_tickers(self, include_sell_only: bool = True) -> list[str]:
        """신호 생성/청산 검토 대상 종목 목록."""
        tickers = self.active_tickers()
        if include_sell_only:
            tickers += self.sell_only_tickers()
        return tickers
