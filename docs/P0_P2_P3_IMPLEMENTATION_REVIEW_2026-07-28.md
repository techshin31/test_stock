# P0 · P2 · P3 implementation review — 2026-07-28 KST

## Scope and decision

`P3` was not defined in the original improvement roadmap.  For this delivery it
means the implementation QA, security review, and handoff report documented
here.  The running PAPER containers were deliberately not rebuilt or restarted:
this is a source-and-verification delivery, not a production deployment.

Source-review decision: **approved for a planned PAPER deployment**.  REAL
trading remains blocked by the existing full-system readiness gate and is out
of scope.

## Deployment addendum — applied 2026-07-28 15:22 KST

The user approved the PAPER restart after review.  `docker compose up -d
--build` rebuilt the API, dashboard, and trader images, then recreated all
services.  Two pre-existing, never-started PostgreSQL containers blocked the
name allocation; both were removed only after confirming `created` status and
the same host bind-mounted database directory.  No database directory or
volume was deleted.

Post-deployment verification confirmed:

- PostgreSQL is healthy; API, dashboard, and PAPER trader are running.
- PostgreSQL/API/dashboard publish only to `127.0.0.1`.
- `logs/paper/scheduler_recovery_state.json` reports `PAPER`, `READY`, and
  zero failed cold-start attempts.
- The running trader imports both `C_CAP10`/`C_CAP08` and the 300-second retry
  cap.

The cap challengers will begin collecting their first live observation on the
next eligible PAPER intraday cycle.  Database password rotation was not
performed automatically because it changes a separate credential value; source
credentials are no longer tracked, but the existing `.env` value remains in
use until an explicit rotation is performed.

## P0 — operating resilience and security

| Control | Implementation | Verification |
| --- | --- | --- |
| Cold-start failure flood | The scheduler now uses `10, 20, 40, 80, 160, 300` seconds of bounded exponential retry delay and writes `logs/<mode>/scheduler_recovery_state.json`. | Unit test covers the sequence, due time, persisted degraded state, and reset. |
| Individual-stock provider resilience | Yahoo remains primary; FinanceDataReader is used only after a failed or stale Yahoo response.  Yahoo data is retained where present and FDR fills only missing/newer rows. | Failure and stale-data merge tests pass. |
| State-write integrity | Premarket candidate, dashboard, and EOD status writes use atomic replace through the existing JSON state writer. | Atomic state writer test passes; no direct dashboard write remains in the trader source. |
| Secret and port hardening | Both Compose files read database credentials from ignored `.env`; tracked examples contain placeholders.  PostgreSQL, API, and dashboard default to `127.0.0.1` binds. | Both Compose definitions validate without interpolation; tracked Compose credential scan passes. |

The old running container still performs its previous direct dashboard writes.
During a read-only inspection, the concurrently written dashboard file could be
observed mid-write and was not parseable.  That is expected until the planned
PAPER restart loads this atomic-write change; no trading data was modified by
the inspection.

## P2 — PAPER portfolio-cap challengers

`C_CAP10` and `C_CAP08` are implemented in
`core.analytics.paper_portfolio_cap_shadow` and are invoked only in PAPER mode
after production allocation and entry-circuit-breaker application.  They:

- copy production target weights before calculating a counterfactual;
- persist their state/history under `logs/paper/`;
- always report `observe_only: true` and `order_permission: DENIED_BY_DESIGN`;
- are not passed to the order calculator and do not alter production targets.

This is an observation-only concentration experiment, not a parameter change.
It requires fresh runtime sessions after deployment before it can accumulate
performance evidence.

## P3 — QA and review evidence

Executed from the repository root on 2026-07-28 KST:

| Check | Result |
| --- | --- |
| Targeted P0/P2 tests | 51 passed |
| Full regression suite | 275 passed |
| Root Compose schema (`--no-interpolate`) | passed |
| Standalone PostgreSQL Compose schema (`--no-interpolate`) | passed |
| Tracked Compose plaintext-credential scan | passed |
| Patch whitespace check | pending final handoff check |
| Ruff | unavailable in the configured `uv` environment; not treated as a passing lint result |

One pre-existing test referenced a scheduler batch file at the old repository
root.  The script now lives in `scripts/`; the test was corrected to the
tracked location and the complete suite then passed.

## Deployment acceptance checklist

1. Schedule a short PAPER maintenance window and rebuild/restart the Compose
   services.  This activates the retry, fallback, atomic-write, P2, and
   loopback-bind changes.
2. Rotate the database password before or during that maintenance window.  The
   source removal does not rotate an already-created database credential.
3. After restart, verify `logs/paper/scheduler_recovery_state.json` is `READY`
   and the dashboard JSON parses repeatedly while the scheduler is active.
4. Confirm Docker publishes PostgreSQL, API, and dashboard only on localhost
   unless an intentional remote bind variable is supplied.
5. Collect at least 10 independent PAPER sessions for the two cap challengers;
   compare drawdown, concentration, turnover, and execution quality before any
   proposal to alter production limits.

Until these checks are complete, the correct operating decision is **continue
PAPER only; do not promote to REAL**.
