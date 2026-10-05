# Fixed public-source workflow sample

`workflow-public-sample.json.gz` contains 24 G2010 companies (enough original peers for the unchanged minimum cohort of 10), their original public DART financial facts and disclosure identities, historical WICS membership, constituent/industry closes and macro observations. Actual OHLCV and KOSPI prices were retained from the earlier real-source snapshot. It contains no operational orders, account credentials or tokens.

Uncompressed JSON SHA256: `76f45da8a95602c9ac08aef2fef4798de2cadeb84145bd3bb149ea64338791fd`.
Source snapshot: `quantpilot_system_validation_20261004_ea98dba0`, copied read-only from the validated source database. Financial cutoff 2026-10-02; rehearsal effective date 2026-10-06. This is a limited CI sample, not a representative investment universe or performance study. Test clocks are fixed and all external loaders/brokers are blocked.

The sample keeps original observations for 24 companies; recent listings 062040 and 443060 were excluded from this three-year-price-history fixture. Production eligibility/history rules were unchanged. All retained financial facts and price observations are actual source rows; nothing was filled or fabricated. `collection-public-sample.json` retains the completed five-type public policy feed's original page hashes and explicit financial gaps. Its observation clock is set only inside the isolated test, and it is never an operational collection record.

The CI test runs the production analyzer, publication and audit, real SQL repositories, Trader FA enrichment, signal evaluation, order planning and local broker. Default and explicit PAPER policies both execute; the separately tested inverse hedge is disabled because this stock-only sample contains no ETF quotes. Each mode uses a new temporary DB and account, verifies positive selections/fills, repeated publication and restarted-account idempotency, and refuses external HTTP/broker calls.
