from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_python_runtime_image_contains_benchmark_data_package():
    dockerfile = (PROJECT_ROOT / "Dockerfile.app").read_text(encoding="utf-8")

    assert "COPY data /app/data" in dockerfile


def test_paper_container_has_explicit_safe_runtime_scope():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "KIS_ENV: paper" in compose
    assert 'ALLOW_LIVE_ORDER: "false"' in compose
    assert "QUANTPILOT_RUNTIME_ID: paper-trader" in compose
