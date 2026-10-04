"""Portfolio limits and order planning without submitting broker orders."""
import hashlib
import logging

import pandas as pd

from apps.worker.fa_contract import DEFAULT_CONFIG as FA_CONTRACT
from core.broker.kis_api import normalize_symbol
from core.constant.types import Tickers


class OrderPlanningMixin:
    def _apply_portfolio_limits(self, targets, details, positions):
        """Allocate 90% exposure by FA conviction above the entry threshold."""
        result = dict(targets)
        active = [ticker for ticker, weight in result.items() if weight > 0]
        protected = {
            ticker
            for ticker in active
            if str(details.get(ticker, {}).get("signal_reason", "")).endswith("_HOLD")
            or str(details.get(ticker, {}).get("signal_reason", "")).startswith(
                "INVERSE_HEDGE_"
            )
        }
        protected_total = sum(result[ticker] for ticker in protected)
        allocatable = [ticker for ticker in active if ticker not in protected]
        allocation_budget = max(0.90 - protected_total, 0.0)
        max_weight = getattr(self, "max_position_weight", 0.15)
        fa_scores = {
            ticker: max(
                float(details.get(ticker, {}).get("fa_score") or 0.0)
                - float(FA_CONTRACT.minimum_company_fa_score),
                0.0,
            )
            for ticker in allocatable
        }
        if allocatable:
            remaining = set(allocatable)
            remaining_budget = min(allocation_budget, max_weight * len(remaining))
            raw_weights = {}
            use_scores = sum(fa_scores.values()) > 0
            convictions = {
                ticker: fa_scores[ticker] if use_scores else 1.0 for ticker in remaining
            }
            while remaining and remaining_budget > 0:
                conviction_total = sum(convictions[ticker] for ticker in remaining)
                capped = []
                for ticker in remaining:
                    proposed = remaining_budget * convictions[ticker] / conviction_total
                    if proposed >= max_weight:
                        raw_weights[ticker] = max_weight
                        capped.append(ticker)
                if not capped:
                    for ticker in remaining:
                        raw_weights[ticker] = (
                            remaining_budget * convictions[ticker] / conviction_total
                        )
                    break
                for ticker in capped:
                    remaining.remove(ticker)
                    remaining_budget -= max_weight
            for ticker in allocatable:
                result[ticker] = round(raw_weights.get(ticker, 0.0), 4)
        return result

    def _apply_transition_exposure_cap(self, targets, details, market_regime):
        """Cap total PAPER/strategy exposure while the market is transitioning."""
        if market_regime != "TRANSITION":
            return dict(targets)

        cap = float(getattr(self, "transition_max_gross_exposure", 0.30))
        result = dict(targets)
        active = [ticker for ticker, weight in result.items() if weight > 0]
        total = sum(float(result[ticker]) for ticker in active)
        if not active or total <= cap:
            return result

        scale = cap / total
        for ticker in active:
            result[ticker] = round(float(result[ticker]) * scale, 4)
            details.setdefault(ticker, {})["transition_exposure_scale"] = round(
                scale, 6
            )
            details[ticker]["target_position"] = result[ticker]
        return result

    @staticmethod
    def _apply_entry_circuit_breaker(
        targets,
        details,
        positions,
        total_eval,
        reason,
    ):
        """Block exposure increases while preserving all sell/risk-exit targets."""
        result = dict(targets)
        for ticker, target_weight in list(result.items()):
            position = positions.get(ticker)
            if not position:
                if target_weight > 0:
                    result[ticker] = 0.0
                    details.setdefault(ticker, {})["signal_reason"] = reason
                continue
            price = float(
                position.get("current_price") or position.get("avg_price") or 0.0
            )
            current_weight = (
                float(position.get("qty") or 0.0) * price / total_eval
                if total_eval > 0 else 0.0
            )
            if target_weight > current_weight:
                result[ticker] = current_weight
                details.setdefault(ticker, {})["signal_reason"] = reason
        return result

    @staticmethod
    def _hedge_exit_prerequisites_met(order, results):
        """Require every planned long exit to be fully filled before hedging."""
        required = set(order.get("requires_prior_sell_fills") or [])
        if not required:
            return True, []
        filled = {
            row.get("ticker")
            for row in results
            if row.get("type") == "SELL" and row.get("status") == "FILLED"
        }
        missing = sorted(required - filled)
        return not missing, missing

    def _calculate_orders(
        self,
        total_eval,
        current_positions,
        target_positions,
        ohlcv_store,
        target_details=None,
    ):
        """현재 비중과 타겟 비중을 비교하여 실제 매수/매도할 주식 수 계산 (부분 매수/매도 포함 리밸런싱)"""
        orders = []
        self.last_order_suppressions = []
        target_details = target_details or {}

        # 상태 기반 중복 방지. 거부 주문은 제한 횟수 내에서만 재시도한다.
        today_str = self._trading_date().isoformat()
        strategy_name, execution_venue, account_scope = self._order_scope()
        if getattr(getattr(self, "broker", None), "is_simulated", False):
            rows = []
        else:
            try:
                rows = self.db.fetch_all(
                    """SELECT o.symbol, o.order_side_code, o.order_status_code,
                              EXISTS (
                                  SELECT 1 FROM order_status_history h
                                  WHERE h.order_id = o.id
                                    AND h.event_type = 'UNKNOWN_RESULT'
                              ) AS had_unknown_result,
                              (
                                  SELECT h.message FROM order_status_history h
                                  WHERE h.order_id = o.id
                                    AND h.event_type = 'UNKNOWN_RESULT'
                                  ORDER BY h.created_at DESC
                                  LIMIT 1
                              ) AS unknown_result_message
                       FROM orders o
                       JOIN strategies s ON s.id = o.strategy_id
                       WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date = %s::date
                         AND s.name = %s
                         AND o.execution_venue_code = %s
                         AND o.account_scope = %s""",
                    (today_str, strategy_name, execution_venue, account_scope)
                )
            except Exception as e:
                raise RuntimeError(f"당일 주문 이력 조회 실패로 주문 계산을 중단합니다: {e}") from e

        open_statuses = {'PENDING', 'SUBMITTED', 'ACCEPTED', 'PARTIAL'}
        open_keys = {
            (normalize_symbol(r['symbol']), r['order_side_code'])
            for r in rows if r['order_status_code'] in open_statuses
        }
        filled_keys = {
            (normalize_symbol(r['symbol']), r['order_side_code'])
            for r in rows if r['order_status_code'] == 'FILLED'
        }
        # An UNKNOWN_RESULT is a same-day retry blocker only while its final
        # broker outcome remains unresolved.  Reconciliation can later prove
        # that the broker did not receive the order and mark it REJECTED; in
        # that case the normal bounded retry path is safe and must not remain
        # permanently hidden behind the historical UNKNOWN_RESULT event.
        terminal_order_statuses = {"FILLED", "REJECTED", "CANCELLED"}
        ambiguous_messages = {
            (normalize_symbol(r['symbol']), r['order_side_code']): r.get(
                'unknown_result_message'
            )
            for r in rows
            if r.get('had_unknown_result')
            and r['order_status_code'] not in terminal_order_statuses
        }
        retry_counts = {}
        attempt_counts = {}
        for row in rows:
            key = (normalize_symbol(row['symbol']), row['order_side_code'])
            attempt_counts[key] = attempt_counts.get(key, 0) + 1
            if row['order_status_code'] in {'REJECTED', 'CANCELLED'}:
                retry_counts[key] = retry_counts.get(key, 0) + 1

        urgent_exit_reasons = {
            "HARD_STOP_LOSS",
            "TRAILING_STOP",
            "COMPANY_RISK_BLOCKED",
            "DOWNTREND",
            "DOWNTREND_EXIT",
            "INVERSE_HEDGE_STOP_LOSS",
            "INVERSE_HEDGE_MAX_HOLD",
            "FA_SCORE_DETERIORATED",
            "TA_MOMENTUM_LOSS",
        }

        def can_order(ticker, side, reason=None):
            key = (normalize_symbol(ticker), side)
            if self._price_guard_blocked(ticker, side):
                logging.info(f"[{ticker}] price guard cooldown is active for {side}")
                self.last_order_suppressions.append({
                    "ticker": ticker, "side": side, "reason": "PRICE_GUARD_COOLDOWN"
                })
                return False
            if key in ambiguous_messages:
                logging.warning(
                    f"[{ticker}] ambiguous {side} broker result occurred today; "
                    "same-day retry is blocked"
                )
                suppression = {
                    "ticker": ticker,
                    "side": side,
                    "reason": "AMBIGUOUS_RESULT_SAME_DAY",
                }
                suppression["incident_code"] = self._safe_broker_failure_code(
                    ambiguous_messages[key], "BROKER_UNKNOWN_RESULT"
                )
                self.last_order_suppressions.append(suppression)
                return False
            if key in open_keys:
                logging.info(f"[{ticker}] 오늘 열린 {side} 주문이 존재하여 스킵합니다.")
                self.last_order_suppressions.append({
                    "ticker": ticker, "side": side, "reason": "OPEN_ORDER_TODAY"
                })
                return False
            urgent_exit = side == "SELL" and reason in urgent_exit_reasons
            forced_transition_topup = (
                getattr(self, "force_rebalance", False)
                and self.execution_venue == "PAPER"
                and side == "BUY"
                and str(reason or "").startswith("TRANSITION_ENTRY_TOPUP")
            )
            if key in filled_keys and not urgent_exit and not forced_transition_topup:
                logging.info(f"[{ticker}] 오늘 체결된 {side} 주문이 존재하여 스킵합니다.")
                self.last_order_suppressions.append({
                    "ticker": ticker, "side": side, "reason": "FILLED_ORDER_TODAY"
                })
                return False
            if retry_counts.get(key, 0) >= self.max_order_attempts:
                logging.warning(f"[{ticker}] 오늘 {side} 주문 재시도 한도에 도달했습니다.")
                self.last_order_suppressions.append({
                    "ticker": ticker, "side": side, "reason": "RETRY_LIMIT"
                })
                return False
            return True

        def add_identity(order):
            key = (normalize_symbol(order['ticker']), order['type'])
            attempt = attempt_counts.get(key, 0) + 1
            raw = (
                f"{today_str}:{strategy_name}:{execution_venue}:{account_scope}:"
                f"{key[0]}:{key[1]}:{attempt}"
            )
            order['idempotency_key'] = hashlib.sha256(raw.encode()).hexdigest()
            return order

        # 1. 매도 주문 계산 (현금 확보를 위해 먼저 실행)
        for ticker, pos in current_positions.items():
            target_weight = target_positions.get(ticker, 0.0)
            current_price = float(pos.get('current_price') or 0.0)
            if (
                current_price <= 0
                and ticker in ohlcv_store
                and not ohlcv_store[ticker].empty
            ):
                current_price = float(ohlcv_store[ticker].iloc[-1]['close'])
            if current_price <= 0:
                continue

            current_value = pos['qty'] * current_price
            target_value = total_eval * target_weight

            candidate = None
            if target_weight == 0.0:
                # 전량 매도
                candidate = {
                    "type": "SELL",
                    "ticker": ticker,
                    "qty": pos['qty'],
                    "expected_price": float(current_price),
                    "reason": target_details.get(ticker, {}).get(
                        "signal_reason", "TARGET_WEIGHT_ZERO"
                    )
                }
            elif current_value > target_value * (
                1 + getattr(self, "rebalance_band", 0.10)
            ):
                sell_qty = int((current_value - target_value) // current_price)
                if sell_qty > 0:
                    candidate = {
                        "type": "SELL",
                        "ticker": ticker,
                        "qty": sell_qty,
                        "expected_price": float(current_price),
                        "reason": f"REBALANCE_WEIGHT_REDUCTION_FROM_{int(current_value/total_eval*100)}%_TO_{int(target_weight*100)}%"
                    }
            if candidate:
                candidate["price_reference_source"] = "BROKER_BALANCE"
            if candidate and can_order(ticker, 'SELL', candidate.get("reason")):
                orders.append(add_identity(candidate))

        hedge_exit_tickers = sorted(
            ticker
            for ticker in current_positions
            if ticker != Tickers.INVERSE_ETF.ticker
            and target_positions.get(ticker, 0.0) == 0.0
        )

        # 2. 매수 주문 계산
        for ticker, weight in target_positions.items():
            if weight <= 0.0:
                continue
            signal_reason = str(
                target_details.get(ticker, {}).get("signal_reason", "")
            )
            hedge_buy_reason = (
                signal_reason if signal_reason.startswith("INVERSE_HEDGE_") else None
            )
            if ticker in current_positions:
                current_price = float(
                    current_positions[ticker].get('current_price') or 0.0
                )
            else:
                current_price = 0.0
            if current_price <= 0:
                df_ticker = ohlcv_store.get(ticker)
                if df_ticker is None or not isinstance(df_ticker, pd.DataFrame) or df_ticker.empty:
                    continue
                current_price = float(df_ticker.iloc[-1]['close'])

            if current_price <= 0:
                continue

            target_value = total_eval * weight

            candidate = None
            if ticker in current_positions:
                pos = current_positions[ticker]
                current_value = pos['qty'] * current_price
                if current_value < target_value * (
                    1 - getattr(self, "rebalance_band", 0.10)
                ):
                    buy_qty = int((target_value - current_value) // current_price)
                    if buy_qty > 0:
                        candidate = {
                            "type": "BUY",
                            "ticker": ticker,
                            "qty": buy_qty,
                            "expected_price": float(current_price),
                            "reason": (
                                hedge_buy_reason
                                or (
                                    f"TRANSITION_ENTRY_TOPUP_TO_{int(weight * 100)}%"
                                    if signal_reason == "TRANSITION_ENTRY_TOPUP"
                                    else f"REBALANCE_WEIGHT_INCREASE_TO_{int(weight*100)}%"
                                )
                            ),
                        }
            else:
                # 신규 진입
                target_qty = int(target_value // current_price)
                if target_qty > 0:
                    candidate = {
                        "type": "BUY",
                        "ticker": ticker,
                        "qty": target_qty,
                        "expected_price": float(current_price),
                        "reason": (
                            hedge_buy_reason
                            or f"FA+TA MOMENTUM ENTRY_{int(weight*100)}%"
                        ),
                    }
            if (
                candidate
                and ticker == Tickers.INVERSE_ETF.ticker
                and candidate.get("reason") in {
                    "INVERSE_HEDGE_ENTRY",
                    "INVERSE_HEDGE_SCALE_UP",
                }
                and hedge_exit_tickers
            ):
                candidate["requires_prior_sell_fills"] = hedge_exit_tickers
            if candidate:
                candidate["price_reference_source"] = (
                    "BROKER_BALANCE" if ticker in current_positions else "SIGNAL_CLOSE"
                )
            if candidate and can_order(ticker, 'BUY', candidate.get("reason")):
                orders.append(add_identity(candidate))

        return orders
