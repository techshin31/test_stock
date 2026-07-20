-- Read-only packaging query for the 2026-07-20 13:10 KST implementation
-- validation snapshot. Values were independently reviewed from pytest output,
-- logs/dry_run/operational_health.jsonl, and promotion report JSON.
WITH summary AS (
    SELECT
        158::integer AS tests_passed,
        158::integer AS tests_total,
        1.0::numeric AS freshness_rate,
        0.995::numeric AS freshness_target,
        1.0::numeric AS risk_coverage,
        1.0::numeric AS risk_target,
        0::integer AS actual_orders,
        1::integer AS observed_days,
        1::integer AS paper_days_target
),
controls(control, attainment, status, current_value, target_value, evidence) AS (
    VALUES
        ('Regression tests', 1.0::numeric, 'PASS', 158::numeric, 158::numeric, '158/158'),
        ('Data freshness', 1.0::numeric, 'PASS', 1.0::numeric, 0.995::numeric, '29/29 completed scans'),
        ('Risk checks', 1.0::numeric, 'PASS', 168::numeric, 168::numeric, '168/168'),
        ('No live orders', 1.0::numeric, 'PASS', 0::numeric, 0::numeric, '0 actual orders'),
        ('PAPER observation window', 1.0::numeric, 'PASS', 1::numeric, 1::numeric, '1/1 trading day'),
        ('FINAL EOD report', 0.0::numeric, 'BLOCKED', 0::numeric, 1::numeric, 'Intraday report until 15:30 KST')
),
implementation(priority, component, status, evidence, operator_action) AS (
    VALUES
        (1, 'Account-scoped NAV ledger', 'VERIFIED', 'Scoped JSONL created and masked account observed', 'Keep DRY_RUN'),
        (2, 'EOD performance and KPI generator', 'VERIFIED', 'DRY_RUN/PAPER reports and real_readiness.json generated', 'Review 15:30 report'),
        (3, 'PAPER baseline gate', 'BLOCKED AS DESIGNED', 'FINAL EOD and baseline are required', 'Automatic transition after FINAL EOD'),
        (4, 'REAL promotion gate', 'BLOCKED AS DESIGNED', 'Missing operational/performance evidence returns exit code 2', 'Accumulate 60 PAPER days'),
        (5, 'BAT account revalidation', 'VERIFIED', 'Snapshot-only account match required before PAPER/REAL', 'Review any mismatch'),
        (6, 'DRY_RUN scheduler', 'ACTIVE', 'Restarted on new code with zero actual orders', 'Review market-close report')
)
SELECT 'summary' AS dataset, to_jsonb(summary) AS row_data FROM summary
UNION ALL
SELECT 'controls', to_jsonb(controls) FROM controls
UNION ALL
SELECT 'implementation', to_jsonb(implementation) FROM implementation;
