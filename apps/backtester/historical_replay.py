from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json

import pandas as pd

from apps.backtester.config import build_db_config, load_env
from apps.worker.analyzer.config import load_config as load_analyzer_config
from apps.worker.analyzer.pipeline import build_request, run
from storage.postgres.connection import PostgreDB


def _month_cutoffs(db: PostgreDB, start: dt.date, end: dt.date) -> list[dt.date]:
    rows = db.fetch_all(
        """SELECT MAX(price_date) AS cutoff
           FROM wics_constituent_prices
           WHERE price_date BETWEEN %s AND %s
           GROUP BY DATE_TRUNC('month', price_date)
           ORDER BY cutoff""",
        (start, end),
    )
    return [row["cutoff"] for row in rows]


def backfill_replays(
    db: PostgreDB,
    *,
    strategy_name: str,
    start: dt.date,
    end: dt.date,
) -> list[dict]:
    config = load_analyzer_config(strategy_name)
    results = []
    for cutoff in _month_cutoffs(db, start, end):
        existing = db.fetch_one(
            """SELECT r.id, r.status_code
               FROM fa_analysis_runs r
               JOIN strategies s ON s.id = r.strategy_id
               WHERE s.name = %s
                 AND r.analysis_month = %s::date
                 AND r.cutoff_date = %s::date
                 AND r.status_code IN ('PASS','WARNING','PUBLISHED')
               ORDER BY r.run_version DESC LIMIT 1""",
            (strategy_name, cutoff.replace(day=1), cutoff),
        )
        if existing:
            results.append({
                "analysis_month": cutoff.replace(day=1).isoformat(),
                "cutoff_date": cutoff.isoformat(),
                "run_id": existing["id"],
                "status": existing["status_code"],
                "created": False,
            })
            continue
        request = build_request(
            target="all",
            analysis_month=cutoff.replace(day=1),
            cutoff_date=cutoff,
            effective_date=cutoff,
            reuse_quarter_scores=True,
            force=True,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            context = run(db, request, config, show_progress=False)
        row = db.fetch_one(
            "SELECT status_code FROM fa_analysis_runs WHERE id = %s",
            (context.run_id,),
        )
        results.append({
            "analysis_month": cutoff.replace(day=1).isoformat(),
            "cutoff_date": cutoff.isoformat(),
            "run_id": context.run_id,
            "status": row["status_code"],
            "created": context.created,
        })
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-name", default="aggressive")
    parser.add_argument("--start", default="2023-05-01")
    parser.add_argument("--end", default="2026-06-30")
    args = parser.parse_args()
    load_env()
    db = PostgreDB(build_db_config())
    try:
        rows = backfill_replays(
            db,
            strategy_name=args.strategy_name,
            start=dt.date.fromisoformat(args.start),
            end=dt.date.fromisoformat(args.end),
        )
    finally:
        db.close()
    counts = pd.Series([row["status"] for row in rows]).value_counts().to_dict()
    print(json.dumps({"runs": len(rows), "statuses": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
