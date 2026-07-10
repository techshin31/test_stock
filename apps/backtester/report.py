from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

from core.analytics.report import (
    build_investor_commentary,
    generate_investor_report,
    generate_report,
    print_summary,
    to_dict,
    to_markdown,
)
from data.loaders.kospi_data import get_ticker_name

from apps.backtester.pipeline import BacktestPipelineResult


def save_report(pipeline_result: BacktestPipelineResult, output_dir: Path, save_charts: bool = True) -> Path:
    """백테스트 결과를 output_dir에 markdown 리포트 + JSON 지표 + (옵션) 차트로 저장한다."""
    output_dir.mkdir(parents=True, exist_ok=True)

    print_summary(pipeline_result.result, pipeline_result.performance)

    commentary = build_investor_commentary(
        pipeline_result.result, pipeline_result.performance, pipeline_result.compare_summary,
    )
    report_md = to_markdown(pipeline_result.result, pipeline_result.performance)
    if commentary:
        report_md += "\n## 해석\n\n" + "\n".join(f"- {line}" for line in commentary) + "\n"
    (output_dir / "report.md").write_text(report_md, encoding="utf-8")

    metrics = to_dict(pipeline_result.performance)
    metrics["compare_summary"] = pipeline_result.compare_summary.to_dict(orient="records")
    metrics["initial_universe"] = pipeline_result.initial_universe
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )

    if save_charts:
        figures_dir = output_dir / "figures"
        figures_dir.mkdir(exist_ok=True)
        figures = generate_report(pipeline_result.result, pipeline_result.performance)
        figures += generate_investor_report(
            pipeline_result.result,
            kospi_index=pipeline_result.kospi_index,
            get_ticker_name=get_ticker_name,
        )
        for i, fig in enumerate(figures):
            fig.savefig(figures_dir / f"{i:02d}.png", dpi=120, bbox_inches="tight")
            plt.close(fig)
        print(f"[BACKTESTER] 차트 {len(figures)}개 저장: {figures_dir}")

    print(f"[BACKTESTER] 리포트 저장 완료: {output_dir}")
    return output_dir
