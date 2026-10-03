"""Explicit original-XBRL backfill; public financial filings only, no risk feed."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import json
from zoneinfo import ZoneInfo

from apps.worker.config import load_config, build_db_config
from core.utils.io import write_json
from data.collectors.public_dart_xbrl import PublicDartClient, PublicDartError, parse_archive
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.company_repo import upsert_companies
from storage.postgres.repositories.financial_repo import fetch_collected_receipts


def run(db, client, *, start, end, years, stock_codes=None, output=None):
    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in db.fetch_all("""
            SELECT stock_code FROM wics_companies
            WHERE base_date=(SELECT MAX(base_date) FROM wics_companies WHERE base_date<=%s)
              AND company_size_code='LARGE' ORDER BY mkt_val DESC, stock_code
        """, (end,))]
    summary = dict(source="DART_PUBLIC_ORIGINAL_XBRL", status="RUNNING", companies=0,
                   reports=0, financial_rows=0, cached_reports=0, skipped_non_kospi=0,
                   risk_disclosure_coverage="NOT_COLLECTED", failures=[], manifests=[])
    if not stock_codes:
        raise PublicDartError("PUBLIC_DART_NO_REQUESTED_COMPANIES")
    try:
        for code in stock_codes:
            company = client.company(code)
            upsert_companies(db, [company])
            summary["companies"] += 1
            if company["market_type_code"] != "KOSPI":
                summary["skipped_non_kospi"] += 1
                continue
            filings = client.filings(company, start, end)
            if not any(f.period_end.year in years for f in filings):
                summary["failures"].append(dict(stock_code=code, reason="NO_ELIGIBLE_FINANCIAL_FILINGS"))
            collected = fetch_collected_receipts(db, code)
            for f in filings:
                if f.period_end.year not in years:
                    continue
                if f.receipt in collected:
                    summary["cached_reports"] += 1
                    continue
                try:
                    rows, manifest = parse_archive(client.archive(f), f)
                except PublicDartError as exc:
                    if str(exc).startswith("PUBLIC_DART_TRANSPORT"):
                        raise
                    summary["failures"].append(dict(stock_code=code, receipt=f.receipt, reason=str(exc)))
                    continue
                # One receipt and all its validated statements commit together.
                # Do not mark an incomplete filing collected by writing only a subset.
                with db.transaction() as conn:
                    conn.execute("""
                        INSERT INTO dart_events(stock_code,corp_code,rcept_no,rcept_dt,report_nm,
                            pblntf_ty,event_category_code,event_subtype_code,corp_cls,rm)
                        VALUES (%s,%s,%s,%s,%s,'A','REGULAR_REPORT',%s,'Y','DART_PUBLIC_ORIGINAL_XBRL; FINANCIAL_FILINGS_ONLY')
                        ON CONFLICT(rcept_no) DO UPDATE SET report_nm=EXCLUDED.report_nm,
                            event_subtype_code=EXCLUDED.event_subtype_code
                    """, (code, f.corp_code, f.receipt, f.received, f.title,
                          {"11013":"Q1_REPORT","11012":"SEMI_ANNUAL_REPORT","11014":"Q3_REPORT","11011":"ANNUAL_REPORT"}[f.report_code]))
                    with conn.cursor() as cur:
                        cur.executemany("""
                            INSERT INTO financial_statements(stock_code,corp_code,bsns_year,reprt_code,
                                fs_div,sj_div,account_id,account_nm,source_rcept_no,rcept_dt,available_date,
                                period_start,period_end,thstrm_amount,thstrm_add_amount,revision_no)
                            VALUES (%(stock_code)s,%(corp_code)s,%(bsns_year)s,%(reprt_code)s,%(fs_div)s,
                                %(sj_div)s,%(account_id)s,%(account_nm)s,%(source_rcept_no)s,%(rcept_dt)s,
                                %(available_date)s,%(period_start)s,%(period_end)s,%(thstrm_amount)s,
                                %(thstrm_add_amount)s,%(revision_no)s)
                            ON CONFLICT DO NOTHING
                        """, rows)
                summary["reports"] += 1
                summary["financial_rows"] += len(rows)
                summary["manifests"].append(manifest)
                if output:
                    write_json(Path(output), summary)
            print(json.dumps({k:summary[k] for k in ["companies","reports","financial_rows","cached_reports"]} | {
                "stock_code":code,"failures":len(summary["failures"])}, ensure_ascii=False), flush=True)
        summary["status"] = "PARTIAL" if summary["failures"] else "PASS"
        return summary
    except Exception:
        summary["status"] = "FAILED"
        raise
    finally:
        if output:
            write_json(Path(output), summary)


def main():
    p=argparse.ArgumentParser(description="공식 공개 원본 XBRL 재무 이력 보충 (키·주문 없음)")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--years", nargs="+", type=int, required=True)
    p.add_argument("--stocks", nargs="+")
    p.add_argument("--cache-dir", type=Path, default=Path("logs/public-dart-xbrl"))
    p.add_argument("--output", type=Path, default=Path("reports/public-finance-backfill.json"))
    args=p.parse_args()
    if args.start > args.end or args.end > datetime.now(ZoneInfo("Asia/Seoul")).date():
        p.error("valid historical dates are required")
    if args.stocks and any(len(c)!=6 or not c.isdigit() for c in args.stocks):
        p.error("stocks must be six-digit identifiers")
    load_config()
    db=PostgreDB(build_db_config())
    try:
        report=run(db, PublicDartClient(args.cache_dir), start=args.start, end=args.end,
                   years=set(args.years), stock_codes=args.stocks, output=args.output)
        print(json.dumps({k:v for k,v in report.items() if k not in ("manifests","failures")}, ensure_ascii=False))
        return 0 if report["status"]=="PASS" else 2
    except PublicDartError as exc:
        print(json.dumps({"status":"FAILED","reason":str(exc)}))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
