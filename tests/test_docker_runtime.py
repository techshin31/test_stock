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


def test_dashboard_and_trader_wait_for_a_healthy_api():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'curl -fsS http://localhost:8000/api/healthz >/dev/null || exit 1' in compose
    assert compose.count("condition: service_healthy") >= 4


def test_dashboard_healthcheck_probes_the_served_ui():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'wget -q -O /dev/null http://127.0.0.1/ || exit 1' in compose


def test_trader_healthcheck_requires_live_scheduler_evidence():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "core.utils.runtime_health --quiet || exit 1" in compose


def test_compose_does_not_embed_database_credentials_or_expose_services_by_default():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    postgres_compose = (PROJECT_ROOT / "storage" / "postgres" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:" in compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:" in postgres_compose
    assert "POSTGRES_PASSWORD: admin" not in compose
    assert "POSTGRES_PASSWORD: admin" not in postgres_compose
    assert '${POSTGRES_HOST_BIND:-127.0.0.1}:5433:5432' in compose
    assert '${POSTGRES_HOST_BIND:-127.0.0.1}:5433:5432' in postgres_compose
    assert '${API_HOST_BIND:-127.0.0.1}:8000:8000' in compose
    assert '${DASHBOARD_HOST_BIND:-127.0.0.1}:3000:80' in compose


def test_example_environment_requires_nonsecret_configuration():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=replace-with-a-strong-unique-secret" in example
    assert "POSTGRES_HOST_BIND=127.0.0.1" in example
