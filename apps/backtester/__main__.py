from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.backtester",
        description="QuantPilot 위험중립형 전략 백테스터",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="백테스트를 실행하고 결과를 저장한다")
    run_p.add_argument("--strategy-name", default="risk_neutral", help="strategies 테이블 조회 키")
    run_p.add_argument(
        "--fa-source-strategy", default="risk_neutral",
        help="fa-published 유니버스를 제공하는 분석 전략 이름",
    )
    run_p.add_argument(
        "--universe-source", choices=["random", "fa-published"], default="random",
        help="유니버스 원천: 랜덤 데모 또는 PUBLISHED FA 실행",
    )
    run_p.add_argument("--start", default="2018-01-01", help="백테스트 시작일 (YYYY-MM-DD)")
    run_p.add_argument("--end", default="2025-12-31", help="백테스트 종료일 (YYYY-MM-DD)")
    run_p.add_argument("--capital", type=float, default=10_000_000.0, help="초기 투자금 (원)")
    run_p.add_argument("--risk-free-rate", type=float, default=0.030, help="무위험 이자율 (Sharpe/Sortino 계산용)")
    run_p.add_argument("--universe-size", type=int, default=5, help="초기 유니버스 종목 수")
    run_p.add_argument("--rotation-size", type=int, default=2, help="교체 시점당 편출/편입 종목 수")
    run_p.add_argument("--rotation-interval-years", type=int, default=2, help="종목 교체 주기 (년)")
    run_p.add_argument("--seed", type=int, default=42, help="랜덤 유니버스 생성 시드")
    run_p.add_argument("--output-dir", default=None, help="결과 저장 경로 (기본: reports/backtester/<timestamp>)")
    run_p.add_argument("--no-charts", action="store_true", help="차트 PNG 저장을 건너뛴다")

    return parser.parse_args()


def run_backtest_command(args: argparse.Namespace) -> None:
    from apps.backtester.config import BacktesterConfig, build_db_config, load_env
    from apps.backtester.pipeline import run_backtest_pipeline
    from apps.backtester.report import save_report
    from storage.postgres.connection import PostgreDB

    load_env()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    output_dir = (
        Path(args.output_dir) if args.output_dir
        else Path("reports/backtester") / datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    cfg = BacktesterConfig(
        strategy_name=args.strategy_name,
        universe_source=args.universe_source,
        start_date=start_date,
        end_date=end_date,
        initial_capital=args.capital,
        risk_free_rate=args.risk_free_rate,
        universe_size=args.universe_size,
        rotation_size=args.rotation_size,
        rotation_interval_years=args.rotation_interval_years,
        random_seed=args.seed,
        output_dir=output_dir,
        save_charts=not args.no_charts,
        fa_source_strategy=args.fa_source_strategy,
    )

    print(
        f"[BACKTESTER] 전략={cfg.strategy_name} | 기간={cfg.start_date}~{cfg.end_date} | "
        f"초기자본={cfg.initial_capital:,.0f}원 | 유니버스={cfg.universe_source}"
    )

    db = PostgreDB(build_db_config())
    try:
        pipeline_result = run_backtest_pipeline(cfg, db)
    finally:
        db.close()

    save_report(pipeline_result, cfg.output_dir, save_charts=cfg.save_charts)


def main() -> None:
    args = _parse_args()
    if args.command == "run":
        run_backtest_command(args)


if __name__ == "__main__":
    main()
