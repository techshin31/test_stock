"""Shared point-in-time validation of distinct consolidated financial quarters.

The latest visible amendment wins, including invalid amendments. A quarter
requires BS, IS/CIS and CF with verifiable DART identity and availability.
One cutoff-date parameter is required by this CTE fragment.
"""

VALID_FINANCIAL_QUARTERS_CTE = """
report_versions AS (
    SELECT f.stock_code, f.bsns_year, f.reprt_code, f.source_rcept_no,
           f.available_date, f.revision_no,
           BOOL_OR(f.sj_div = 'BS') AS has_bs,
           BOOL_OR(f.sj_div IN ('IS', 'CIS')) AS has_is,
           BOOL_OR(f.sj_div = 'CF') AS has_cf,
           BOOL_AND(COALESCE(
               d.corp_code = f.corp_code
               AND d.rcept_dt = f.rcept_dt
               AND d.rcept_dt = f.available_date
               AND f.period_end IS NOT NULL
               AND f.period_end <= f.available_date,
               FALSE
           )) AS valid_source
    FROM financial_statements f
    LEFT JOIN dart_events d ON d.stock_code = f.stock_code
      AND d.rcept_no = f.source_rcept_no
    WHERE f.available_date <= %s
      AND f.fs_div = 'CFS'
      AND f.reprt_code IN ('11013', '11012', '11014', '11011')
      AND f.source_rcept_no NOT LIKE 'LEGACY:%%'
    GROUP BY f.stock_code, f.bsns_year, f.reprt_code, f.source_rcept_no,
             f.available_date, f.revision_no
), latest_quarters AS (
    SELECT DISTINCT ON (stock_code, bsns_year, reprt_code) *
    FROM report_versions
    ORDER BY stock_code, bsns_year, reprt_code, available_date DESC,
             revision_no DESC, source_rcept_no DESC
), report_counts AS (
    SELECT stock_code, COUNT(*) FILTER (
        WHERE has_bs AND has_is AND has_cf AND valid_source
    ) AS report_count
    FROM latest_quarters
    GROUP BY stock_code
)
"""
