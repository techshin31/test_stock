"""Broker submission and cumulative fill recording for the live trader."""
import datetime
import hashlib
import logging
from zoneinfo import ZoneInfo

from core.broker.kis_api import BrokerResponseError, normalize_symbol


class OrderExecutionMixin:
    def _execute_orders(self, orders):
        if getattr(self, "execution_venue", None) == "DRY_RUN":
            return [{**order, "status": "DRY_RUN", "filled_qty": 0} for order in orders]
        if getattr(self.broker, "is_simulated", False):
            return self._execute_simulation_orders(orders)
        import time
        from storage.postgres.repositories.order_repo import (
            DuplicateOrderError, attach_broker_order_id, create_order,
            mark_order_submitted, update_order_status,
        )

        # 실시간 계좌 잔고를 다시 조회하여 당일 가용 현금 획득
        try:
            balance_info = self.broker.get_balance()
            today_cash = float(balance_info.get("today_cash", balance_info.get("cash", 0.0)))
            logging.info(f"[주문 실행 전 잔고 검증] 실시간 당일 가용 예수금: {today_cash:,.0f}원")
        except Exception as e:
            failure_code = self._safe_broker_failure_code(
                e, "BROKER_BALANCE_LOOKUP_FAILED"
            )
            logging.error("Broker balance lookup failed; all orders halted: %s", failure_code)
            raise RuntimeError(
                f"Broker balance check failed; all orders halted: {failure_code}"
            ) from None

        live_positions = balance_info.get("positions", {})
        results = []

        for order in orders:
            from core.execution.session_guard import submission_blocker
            blocked = submission_blocker(order["type"], session=getattr(self.broker, "order_session_date", None))
            if blocked:
                results.append({**order, "status": "SKIPPED", "message": blocked})
                continue
            prerequisites_met, missing_exits = self._hedge_exit_prerequisites_met(
                order, results
            )
            if not prerequisites_met:
                self.last_order_suppressions = list(
                    getattr(self, "last_order_suppressions", []) or []
                )
                self.last_order_suppressions.append({
                    "ticker": order["ticker"],
                    "side": "BUY",
                    "reason": "HEDGE_EXIT_UNFILLED",
                    "blocked_by": missing_exits,
                })
                results.append({
                    **order,
                    "status": "SKIPPED",
                    "message": "HEDGE_EXIT_UNFILLED",
                })
                continue
            # ponytail: 한국투자증권 API의 모의투자 초당 거래제한(2 TPS)을 초과하지 않도록 0.6초 딜레이 부여
            time.sleep(0.6)
            ticker = order['ticker']
            qty = order['qty']
            action = order['type']

            try:
                if getattr(self.broker, "is_simulated", False):
                    current_price = float(order["expected_price"])
                    self.broker.set_market_price(ticker, current_price)
                else:
                    current_price = self.broker.get_current_price(ticker)
            except Exception as e:
                failure_code = self._safe_broker_failure_code(
                    e, "BROKER_PRICE_LOOKUP_FAILED"
                )
                logging.error(
                    "[%s] current-price lookup failed; order skipped: %s",
                    ticker,
                    failure_code,
                )
                results.append({
                    **order,
                    "status": "SKIPPED",
                    "message": failure_code,
                    "execution_stage": "PRICE_LOOKUP",
                    "broker_failure_code": failure_code,
                })
                continue

            expected_price = float(order.get("expected_price") or current_price)
            deviation = abs(current_price - expected_price) / expected_price
            reference_source = str(
                order.get("price_reference_source") or "EXPLICIT"
            )
            order["price_reference_source"] = reference_source
            order["signal_reference_price"] = expected_price
            order["observed_price"] = current_price
            order["signal_reference_deviation"] = round(deviation, 8)
            order["price_observed_at"] = datetime.datetime.now(
                ZoneInfo("Asia/Seoul")
            ).isoformat(timespec="seconds")
            # A generated market order carries the previous validated close as a
            # signal reference, not a limit price.  Use the fresh broker quote
            # for sizing and fill accounting while retaining the drift in audit.
            if action == "BUY" and reference_source == "SIGNAL_CLOSE":
                order["price_guard_status"] = "REFERENCE_ONLY"
                expected_price = current_price
                deviation = 0.0
            if action == "BUY" and deviation > self.max_price_deviation:
                msg = f"가격 편차 {deviation:.2%}가 허용치 {self.max_price_deviation:.2%}를 초과"
                logging.warning(f"[{ticker}] {msg}")
                self._record_price_guard(ticker, action, deviation)
                order["execution_stage"] = "PRICE_GUARD"
                results.append({**order, "status": "SKIPPED", "message": msg})
                continue

            if action == "SELL":
                held_qty = int(live_positions.get(ticker, {}).get("qty", 0))
                if held_qty <= 0:
                    results.append({**order, "status": "SKIPPED", "message": "실시간 보유수량 없음"})
                    continue
                qty = min(qty, held_qty)

            # 매수 시 당일 가용 예수금 검증 및 동적 조절
            if action == "BUY":
                buffered_price = current_price * self.buy_cash_buffer
                order_amount = qty * buffered_price
                if today_cash < buffered_price:
                    msg = f"당일 예수금 부족으로 주문 전송 취소 (필요 최소금액: {buffered_price:,.0f}원, 가용 현금: {today_cash:,.0f}원)"
                    logging.warning(f"[{ticker}] {msg}")
                    results.append({**order, "status": "SKIPPED", "message": msg})
                    continue
                elif today_cash < order_amount:
                    new_qty = int(today_cash // buffered_price)
                    msg = f"당일 예수금 부족으로 수량 축소 조정 ({qty}주 -> {new_qty}주, 가용 예수금: {today_cash:,.0f}원)"
                    logging.info(f"[{ticker}] {msg}")
                    qty = new_qty
                    order_amount = qty * buffered_price
                    order['qty'] = qty # 객체 수량 업데이트
                    order['reason'] += f" (수량 축소: {msg})"

            print(f"[주문 실행] {action} {ticker} 수량: {qty}주 (사유: {order['reason']})")

            # DB에 주문 의도를 선점하지 못하면 실제 주문을 절대 전송하지 않는다.
            order_id = None
            order["execution_stage"] = "DB_CLAIM"
            try:
                order_id = create_order(self.db, {
                    "symbol": normalize_symbol(ticker),
                    "order_side_code": action,
                    "strategy_name": self.strategy_name,
                    "qty": qty,
                    "price": current_price,
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK",
                    "order_type_code": "MARKET",
                    "execution_venue_code": getattr(self, "execution_venue", "PAPER"),
                    "account_scope": getattr(self.broker, "masked_account", "UNKNOWN"),
                    "idempotency_key": order.get("idempotency_key") or self._idempotency_key(order),
                })
            except DuplicateOrderError as e:
                logging.warning(f"[{ticker}] 중복 주문 차단: {e}")
                results.append({**order, "status": "SKIPPED", "message": str(e)})
                continue
            except Exception as e:
                raise RuntimeError(f"[{ticker}] 주문 DB 선점 실패로 실행을 중단합니다: {e}") from e

            # SUBMITTED 전환 실패 시에는 브로커를 호출하지 않는다.
            try:
                mark_order_submitted(self.db, order_id)
            except Exception as e:
                raise RuntimeError(f"[{ticker}] 주문 제출 상태 기록 실패: {e}") from e

            # API 호출
            try:
                order["execution_stage"] = "BROKER_SUBMIT"
                if action == "BUY":
                    resp = self.broker.place_market_buy(ticker, qty)
                else:
                    resp = self.broker.place_market_sell(ticker, qty)
                output = resp.get("output", {})
                odno = output.get("ODNO") if isinstance(output, dict) else None
                if not odno:
                    failure_code = self._safe_broker_failure_code(
                        resp.get("msg1"), "BROKER_REJECTED"
                    )
                    update_order_status(
                        self.db,
                        order_id,
                        "REJECTED",
                        note=failure_code,
                        raw_payload={"incident_code": failure_code},
                    )
                    results.append({
                        **order,
                        "status": "REJECTED",
                        "message": failure_code,
                        "broker_failure_code": failure_code,
                    })
                    continue

                attach_broker_order_id(self.db, order_id, odno, resp)
                order["execution_stage"] = "BROKER_STATUS"
                final_status = "ACCEPTED"
                poll_errors = []
                poll_attempts = 0
                for _ in range(max(self.fill_poll_attempts, 1)):
                    poll_attempts += 1
                    try:
                        status = self.broker.get_order_status(odno)
                        final_status = self._record_broker_status(
                            order_id, ticker, action, expected_price, odno, status
                        )
                        if final_status in {"FILLED", "CANCELLED", "REJECTED"}:
                            break
                    except BrokerResponseError as poll_error:
                        failure_code = self._safe_broker_failure_code(
                            poll_error, "BROKER_STATUS_LOOKUP_FAILED"
                        )
                        poll_errors.append(failure_code)
                        logging.warning(
                            "[%s] fill-status lookup deferred: %s",
                            ticker,
                            failure_code,
                        )
                    time.sleep(self.fill_poll_interval)

                if self.broker.is_mock and final_status == "ACCEPTED":
                    inferred = self._infer_paper_fill_from_balance(
                        ticker, action, qty, current_price, live_positions
                    )
                    if inferred is not None:
                        final_status = self._record_broker_status(
                            order_id, ticker, action, expected_price, odno, inferred
                        )

                if action == "BUY" and final_status in {"ACCEPTED", "PARTIAL", "FILLED"}:
                    today_cash -= qty * current_price
                order["broker_status_poll_attempts"] = poll_attempts
                order["broker_status_poll_errors"] = poll_errors
                results.append({**order, "status": final_status, "broker_order_id": odno})
            except BrokerResponseError as e:
                failure_code = self._safe_broker_failure_code(e, "BROKER_REJECTED")
                logging.error("[%s] broker order rejected: %s", ticker, failure_code)
                update_order_status(
                    self.db,
                    order_id,
                    "REJECTED",
                    note=failure_code,
                    event_type="BROKER_REJECTED",
                )
                results.append({
                    **order,
                    "status": "REJECTED",
                    "message": failure_code,
                    "broker_failure_code": failure_code,
                })
            except Exception as e:
                # 네트워크 타임아웃은 주문 성공 여부가 불명확하므로 REJECTED로 단정하지 않는다.
                failure_code = self._safe_broker_failure_code(
                    e, "BROKER_UNKNOWN_RESULT"
                )
                logging.error(
                    "[%s] broker order outcome is unknown: %s", ticker, failure_code
                )
                inferred = None
                if self.broker.is_mock:
                    inferred = self._infer_paper_fill_from_balance(
                        ticker, action, qty, current_price, live_positions
                    )
                if inferred is not None:
                    final_status = self._record_broker_status(
                        order_id, ticker, action, expected_price,
                        "BALANCE", inferred,
                    )
                    results.append({**order, "status": final_status})
                    continue
                if order_id:
                    try:
                        update_order_status(
                            self.db,
                            order_id,
                            "SUBMITTED",
                            note=f"UNKNOWN_BROKER_RESULT: {failure_code}",
                            event_type="UNKNOWN_RESULT",
                        )
                    except Exception as status_error:
                        logging.error(f"주문 결과 불명 상태 기록에도 실패했습니다: {status_error}")
                results.append({
                    **order,
                    "status": "UNKNOWN",
                    "message": failure_code,
                    "broker_failure_code": failure_code,
                })

        return results

    def _execute_simulation_orders(self, orders):
        results = []
        for order in orders:
            prerequisites_met, missing_exits = self._hedge_exit_prerequisites_met(
                order, results
            )
            if not prerequisites_met:
                self.last_order_suppressions = list(
                    getattr(self, "last_order_suppressions", []) or []
                )
                self.last_order_suppressions.append({
                    "ticker": order["ticker"],
                    "side": "BUY",
                    "reason": "HEDGE_EXIT_UNFILLED",
                    "blocked_by": missing_exits,
                })
                results.append({
                    **order,
                    "status": "SKIPPED",
                    "message": "HEDGE_EXIT_UNFILLED",
                })
                continue
            ticker = order["ticker"]
            try:
                if order["type"] not in {"BUY", "SELL"}:
                    raise ValueError("simulation order side must be BUY or SELL")
                qty = self.broker.validate_quantity(order["qty"])
                price = order["expected_price"]
                self.broker.set_market_price(ticker, price)
                if order["type"] == "BUY":
                    response = self.broker.place_market_buy(
                        ticker, qty, idempotency_key=order.get("idempotency_key")
                    )
                else:
                    response = self.broker.place_market_sell(
                        ticker, qty, idempotency_key=order.get("idempotency_key")
                    )
                order_id = response["output"]["ODNO"]
                status = self.broker.get_order_status(order_id)
                results.append({
                    **order,
                    "status": status["status"],
                    "broker_order_id": order_id,
                    "fill_price": status["avg_fill_price"],
                })
            except Exception as exc:
                logging.exception(f"[{ticker}] local simulation order failed: {exc}")
                results.append({**order, "status": "REJECTED", "message": str(exc)})
        return results

    def _idempotency_key(self, order):
        strategy_name, execution_venue, account_scope = self._order_scope()
        raw = ":".join([
            self._trading_date().isoformat(), strategy_name,
            execution_venue, account_scope,
            normalize_symbol(order['ticker']), order['type'], str(order.get('reason', 'manual')),
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    def _record_broker_status(self, order_id, ticker, action, expected_price, broker_order_id, status):
        from storage.postgres.repositories.execution_repo import (
            fetch_execution_totals_by_order, insert_execution,
        )
        from storage.postgres.repositories.order_repo import update_order_status

        totals = fetch_execution_totals_by_order(self.db, order_id)
        cumulative_qty = float(status['filled_qty'])
        cumulative_amount = float(status.get('total_fill_amount') or 0)
        if cumulative_amount <= 0 and cumulative_qty > 0:
            cumulative_amount = cumulative_qty * float(status['avg_fill_price'])
        delta_qty = cumulative_qty - totals['qty']
        delta_amount = cumulative_amount - totals['amount']

        if delta_qty > 0:
            fill_price = delta_amount / delta_qty
            slippage = (
                (fill_price - expected_price) if action == 'BUY'
                else (expected_price - fill_price)
            ) * delta_qty
            net_amount = -delta_amount if action == 'BUY' else delta_amount
            insert_execution(self.db, order_id, {
                "symbol": normalize_symbol(ticker), "order_side_code": action,
                "qty": delta_qty, "price": fill_price, "amount": delta_amount,
                "net_amount": net_amount, "market_type_code": "KOSPI",
                "instrument_type_code": "STOCK", "commission": 0.0,
                "tax": 0.0, "slippage": slippage,
            })

        update_order_status(
            self.db, order_id, status['status'], filled_qty=cumulative_qty,
            avg_fill_price=float(status.get('avg_fill_price') or 0) or None,
            remaining_qty=float(status['remaining_qty']), broker_order_id=broker_order_id,
            event_type="STATUS_POLL", raw_payload=status.get('raw'),
            note="KIS 주문/체결 조회로 동기화",
        )
        return status['status']

    def _infer_paper_fill_from_balance(
        self, ticker, action, ordered_qty, current_price, before_positions
    ):
        """Infer VTS fills from balance changes when daily order inquiry is empty."""
        try:
            after_positions = self.broker.get_balance().get("positions", {})
        except Exception as exc:
            logging.warning(f"[{ticker}] paper balance fallback failed: {exc}")
            return None

        before_qty = int(before_positions.get(ticker, {}).get("qty", 0))
        after_qty = int(after_positions.get(ticker, {}).get("qty", 0))
        filled_qty = (
            max(before_qty - after_qty, 0)
            if action == "SELL"
            else max(after_qty - before_qty, 0)
        )
        filled_qty = min(filled_qty, int(ordered_qty))
        if filled_qty <= 0:
            return None
        return {
            "status": "FILLED" if filled_qty >= int(ordered_qty) else "PARTIAL",
            "ordered_qty": int(ordered_qty),
            "filled_qty": filled_qty,
            "remaining_qty": max(int(ordered_qty) - filled_qty, 0),
            "avg_fill_price": float(current_price),
            "total_fill_amount": filled_qty * float(current_price),
            "raw": {"source": "PAPER_BALANCE_FALLBACK"},
        }
