"""Open-order, execution-ledger and account reconciliation."""
import datetime
import logging
from zoneinfo import ZoneInfo

from core.broker.kis_api import normalize_symbol


class OrderReconciliationMixin:
    def _assert_no_unresolved_orders(self):
        strategy_name, execution_venue, account_scope = self._order_scope()
        row = self.db.fetch_one(
            """SELECT COUNT(*) AS count
               FROM orders o
               JOIN strategies s ON s.id = o.strategy_id
               WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                     (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                 AND o.order_status_code IN ('PENDING','SUBMITTED','ACCEPTED','PARTIAL')
                 AND s.name = %s
                 AND o.execution_venue_code = %s
                 AND o.account_scope = %s""",
            (strategy_name, execution_venue, account_scope),
        )
        count = int((row or {}).get("count") or 0)
        if count:
            raise RuntimeError(
                f"unresolved order circuit breaker: {count} open orders require reconciliation"
            )

    def _daily_execution_ledger_health(self):
        """Verify that today's terminal fills have matching execution quantities.

        This is an entry-only safety input. A missing execution row must never be
        silently treated as a clean ledger, but it also must not prevent a risk
        exit from reducing an existing PAPER position.
        """
        strategy_name, execution_venue, account_scope = self._order_scope()
        row = self.db.fetch_one(
            """
            WITH filled_orders AS (
                SELECT o.id, o.filled_qty
                FROM orders o
                JOIN strategies s ON s.id = o.strategy_id
                WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                      (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                  AND o.order_status_code = 'FILLED'
                  AND COALESCE(o.filled_qty, 0) > 0
                  AND s.name = %s
                  AND o.execution_venue_code = %s
                  AND o.account_scope = %s
            ), execution_totals AS (
                SELECT e.order_id, COALESCE(SUM(e.qty), 0) AS execution_qty
                FROM executions e
                JOIN filled_orders f ON f.id = e.order_id
                GROUP BY e.order_id
            )
            SELECT
                COUNT(*) AS filled_order_count,
                COUNT(*) FILTER (
                    WHERE COALESCE(x.execution_qty, 0) > 0
                ) AS execution_linked_order_count,
                COUNT(*) FILTER (
                    WHERE ABS(COALESCE(x.execution_qty, 0) - f.filled_qty) < 0.000001
                ) AS quantity_matched_order_count
            FROM filled_orders f
            LEFT JOIN execution_totals x ON x.order_id = f.id
            """,
            (strategy_name, execution_venue, account_scope),
        ) or {}
        filled = int(row.get("filled_order_count") or 0)
        linked = int(row.get("execution_linked_order_count") or 0)
        matched = int(row.get("quantity_matched_order_count") or 0)
        link_coverage = linked / filled if filled else 1.0
        quantity_match_rate = matched / filled if filled else 1.0
        ready = linked == filled and matched == filled
        return {
            "status": "READY" if ready else "BLOCKED",
            "filled_order_count": filled,
            "execution_linked_order_count": linked,
            "quantity_matched_order_count": matched,
            "missing_execution_order_count": max(filled - linked, 0),
            "quantity_mismatch_order_count": max(filled - matched, 0),
            "execution_link_coverage": link_coverage,
            "quantity_match_rate": quantity_match_rate,
        }

    def _reconcile_open_orders(self, live_positions=None):
        """이전 실행에서 남은 접수/부분체결 주문을 브로커 원장과 동기화한다."""
        from storage.postgres.repositories.order_repo import (
            attach_broker_order_id, update_order_status,
        )

        strategy_name, execution_venue, account_scope = self._order_scope()
        scope_params = (strategy_name, execution_venue, account_scope)
        try:
            rows = self.db.fetch_all(
                """SELECT o.id::text, o.broker_order_id, o.symbol, o.order_side_code,
                          o.price, o.qty, o.created_at
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE o.order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL')
                     AND (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                         (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s""",
                scope_params,
            )
            all_linked_rows = self.db.fetch_all(
                """SELECT o.broker_order_id
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                         (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                     AND o.broker_order_id IS NOT NULL
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s""",
                scope_params,
            )
        except Exception as e:
            raise RuntimeError(f"열린 주문 조회 실패: {e}") from e
        daily_broker_rows = None
        linked_ids = {
            str(row['broker_order_id']).lstrip('0') or '0' for row in all_linked_rows
        }
        for row in rows:
            if not row['broker_order_id']:
                try:
                    if daily_broker_rows is None:
                        daily_broker_rows = self.broker.fetch_daily_orders()
                    matches = self._match_unknown_broker_order(row, daily_broker_rows, linked_ids)
                    if len(matches) != 1:
                        if len(matches) == 0 and self._unknown_order_grace_elapsed(row):
                            update_order_status(
                                self.db, row['id'], 'REJECTED',
                                note=(
                                    'AUTO_RECONCILED_NOT_FOUND: successful KIS daily-order '
                                    'query found no matching order after grace period'
                                ),
                                event_type='AUTO_RECONCILE_NOT_FOUND',
                                raw_payload={
                                    'source': 'KIS_DAILY_ORDER_RECONCILIATION',
                                    'broker_order_count': len(daily_broker_rows),
                                },
                            )
                            logging.warning(
                                f"[auto reconcile] order {row['id']} was not found in "
                                "the KIS daily-order list; marked REJECTED"
                            )
                            continue
                        logging.error(
                            f"[정산 필요] 로컬 주문 {row['id']}의 브로커 주문 후보가 "
                            f"{len(matches)}건입니다. 자동 재주문하지 않습니다."
                        )
                        continue
                    broker_order_id = str(matches[0].get('odno') or matches[0].get('ODNO'))
                    attach_broker_order_id(self.db, row['id'], broker_order_id, matches[0])
                    row['broker_order_id'] = broker_order_id
                    linked_ids.add(broker_order_id.lstrip('0') or '0')
                except Exception as e:
                    logging.warning(f"주문번호 미확인 주문 {row['id']} 자동 복구 보류: {e}")
                    continue
            try:
                status = self.broker.get_order_status(row['broker_order_id'])
                final_status = self._record_broker_status(
                    row['id'], row['symbol'], row['order_side_code'],
                    float(row['price'] or 0), row['broker_order_id'], status,
                )
                if final_status in {"FILLED", "CANCELLED", "REJECTED"}:
                    self._append_trade_history_reconciliation(
                        row['broker_order_id'], final_status, status
                    )
            except Exception as e:
                logging.warning(f"열린 주문 {row['id']} 정산 보류: {e}")

        if self.broker.is_mock and live_positions is not None:
            remaining = self.db.fetch_all(
                """SELECT o.id::text, o.broker_order_id, o.symbol, o.order_side_code,
                          o.price, o.qty, o.created_at
                   FROM orders o
                   JOIN strategies s ON s.id = o.strategy_id
                   WHERE o.order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL')
                     AND (o.created_at AT TIME ZONE 'Asia/Seoul')::date =
                         (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date
                     AND s.name = %s
                     AND o.execution_venue_code = %s
                     AND o.account_scope = %s""",
                scope_params,
            )
            for row in remaining:
                ticker = f"{normalize_symbol(row['symbol'])}.KS"
                if row['order_side_code'] != 'SELL':
                    continue
                ordered_qty = int(row['qty'])
                held_qty = int(live_positions.get(ticker, {}).get('qty', 0))
                if held_qty >= ordered_qty:
                    continue
                filled_qty = ordered_qty - held_qty
                synthetic = {
                    "status": "FILLED" if held_qty == 0 else "PARTIAL",
                    "ordered_qty": ordered_qty,
                    "filled_qty": filled_qty,
                    "remaining_qty": held_qty,
                    "avg_fill_price": float(row['price']),
                    "total_fill_amount": filled_qty * float(row['price']),
                    "raw": {"source": "PAPER_POSITION_RECONCILIATION"},
                }
                final_status = self._record_broker_status(
                    row['id'], ticker, 'SELL', float(row['price']),
                    row['broker_order_id'] or 'BALANCE', synthetic,
                )
                if final_status in {"FILLED", "CANCELLED", "REJECTED"}:
                    self._append_trade_history_reconciliation(
                        row['broker_order_id'], final_status, synthetic
                    )

    def _unknown_order_grace_elapsed(self, row, now=None):
        created_at = row.get('created_at')
        if not isinstance(created_at, datetime.datetime):
            return False
        now = now or datetime.datetime.now(datetime.timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        grace = max(int(getattr(self, 'unknown_order_grace_seconds', 300)), 0)
        return (now - created_at).total_seconds() >= grace

    @staticmethod
    def _match_unknown_broker_order(local_order, broker_rows, linked_ids):
        """응답 유실 주문을 2분 이내의 유일한 KIS 주문과만 연결한다."""
        created_at = local_order.get('created_at')
        if not isinstance(created_at, datetime.datetime):
            return []
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(ZoneInfo("Asia/Seoul"))
        local_time = created_at.timetz().replace(tzinfo=None)
        local_seconds = local_time.hour * 3600 + local_time.minute * 60 + local_time.second
        expected_side = '02' if local_order['order_side_code'] == 'BUY' else '01'
        matches = []
        for broker_row in broker_rows:
            broker_id = str(broker_row.get('odno') or broker_row.get('ODNO') or '')
            if not broker_id or (broker_id.lstrip('0') or '0') in linked_ids:
                continue
            order_time = str(broker_row.get('ord_tmd') or '')
            if len(order_time) != 6 or not order_time.isdigit():
                continue
            broker_seconds = int(order_time[:2]) * 3600 + int(order_time[2:4]) * 60 + int(order_time[4:])
            if abs(broker_seconds - local_seconds) > 120:
                continue
            side = str(broker_row.get('sll_buy_dvsn_cd') or '')
            symbol = normalize_symbol(broker_row.get('pdno') or '')
            qty = int(broker_row.get('ord_qty') or 0)
            if (
                side == expected_side
                and symbol == normalize_symbol(local_order['symbol'])
                and qty == int(local_order['qty'])
            ):
                matches.append(broker_row)
        return matches

    def _sync_balance_and_positions(self, balance_info, total_eval):
        cash = balance_info['cash']
        positions = balance_info['positions']
        stock_value = total_eval - cash
        account_scope = getattr(self.broker, "masked_account", "UNKNOWN")
        if account_scope in {None, "", "UNKNOWN"}:
            raise RuntimeError("account scope is required for balance synchronization")

        # 1. balance_history 저장
        from storage.postgres.repositories.balance_repo import insert_balance_history
        try:
            insert_balance_history(self.db, self.strategy_name, {
                "cash": cash,
                "stock_value": stock_value,
                "total_value": total_eval,
                "date": datetime.datetime.now(ZoneInfo("Asia/Seoul"))
            }, execution_venue_code=self.execution_venue, account_scope=account_scope)
            logging.info("[DB 동기화] balance_history 기록 완료")
        except Exception as e:
            raise RuntimeError(f"balance_history 기록 실패: {e}") from e

        # 2. positions 테이블 저장
        from storage.postgres.repositories.position_repo import (
            delete_position, fetch_active_position_symbols, upsert_position,
            zero_out_position,
        )
        try:
            db_symbols = fetch_active_position_symbols(
                self.db,
                self.strategy_name,
                execution_venue_code=self.execution_venue,
                account_scope=account_scope,
            )

            for symbol, pos in positions.items():
                upsert_position(self.db, self.strategy_name, normalize_symbol(symbol), {
                    "qty": pos["qty"],
                    "avg_cost": pos["avg_price"],
                    "market_type_code": "KOSPI",
                    "instrument_type_code": "STOCK"
                }, execution_venue_code=self.execution_venue, account_scope=account_scope)

            for db_symbol in db_symbols:
                if db_symbol != normalize_symbol(db_symbol):
                    delete_position(
                        self.db,
                        self.strategy_name,
                        db_symbol,
                        execution_venue_code=self.execution_venue,
                        account_scope=account_scope,
                    )
                    continue
                if normalize_symbol(db_symbol) not in {normalize_symbol(s) for s in positions}:
                    zero_out_position(
                        self.db,
                        self.strategy_name,
                        db_symbol,
                        execution_venue_code=self.execution_venue,
                        account_scope=account_scope,
                    )
            logging.info("[DB 동기화] positions 테이블 갱신 완료")
        except Exception as e:
            raise RuntimeError(f"positions 테이블 갱신 실패: {e}") from e
