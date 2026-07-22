from types import SimpleNamespace

from core.utils.scheduler_supervisor import (
    run_recovery_self_test,
    run_supervised,
    supervise_existing,
)


def _runner(exit_codes, calls):
    remaining = iter(exit_codes)

    def run(command, *, check):
        calls.append((command, check))
        return SimpleNamespace(returncode=next(remaining))

    return run


def test_paper_recovers_after_unexpected_exit():
    calls = []
    sleeps = []
    events = []

    result = run_supervised(
        ["python", "scheduler.py", "--paper"],
        mode="PAPER",
        max_restarts=2,
        restart_delay_seconds=3,
        runner=_runner([1, 0], calls),
        sleeper=sleeps.append,
        event_sink=events.append,
    )

    assert result == 0
    assert len(calls) == 2
    assert sleeps == [3]
    assert [row["event"] for row in events] == [
        "PROCESS_EXIT",
        "AUTO_RESTART_SCHEDULED",
        "PROCESS_EXIT",
    ]


def test_real_never_restarts_automatically():
    calls = []
    events = []

    result = run_supervised(
        ["python", "scheduler.py", "--live"],
        mode="REAL",
        max_restarts=5,
        restart_delay_seconds=0,
        runner=_runner([1], calls),
        sleeper=lambda _: None,
        event_sink=events.append,
    )

    assert result == 1
    assert len(calls) == 1
    assert events[-1]["event"] == "AUTO_RESTART_DENIED"


def test_safety_refusal_exit_two_is_not_retried():
    calls = []

    result = run_supervised(
        ["python", "scheduler.py", "--paper"],
        mode="PAPER",
        max_restarts=5,
        restart_delay_seconds=0,
        runner=_runner([2], calls),
        sleeper=lambda _: None,
    )

    assert result == 2
    assert len(calls) == 1


def test_restart_limit_is_bounded():
    calls = []
    events = []

    result = run_supervised(
        ["python", "scheduler.py", "--paper"],
        mode="PAPER",
        max_restarts=2,
        restart_delay_seconds=0,
        runner=_runner([1, 1, 1], calls),
        sleeper=lambda _: None,
        event_sink=events.append,
    )

    assert result == 1
    assert len(calls) == 3
    assert events[-1]["event"] == "RESTART_LIMIT_REACHED"


def test_self_test_proves_fail_then_recover_without_order_permission(tmp_path):
    output = tmp_path / "scheduler_recovery_evidence.json"

    payload = run_recovery_self_test(output)

    assert payload["status"] == "READY"
    assert payload["broker_loaded"] is False
    assert payload["order_permission"] == "DENIED_BY_DESIGN"
    assert payload["real_auto_restart_allowed"] is False
    assert payload["process_exit_codes"] == [1, 0]
    assert output.exists()


def test_attach_preserves_existing_process_until_it_exits():
    checks = iter([True, True, False])
    calls = []
    sleeps = []
    events = []

    result = supervise_existing(
        1234,
        ["python", "scheduler.py", "--paper"],
        mode="PAPER",
        max_restarts=2,
        restart_delay_seconds=3,
        poll_seconds=5,
        process_checker=lambda pid: next(checks),
        runner=_runner([0], calls),
        sleeper=sleeps.append,
        event_sink=events.append,
    )

    assert result == 0
    assert sleeps == [5, 5]
    assert len(calls) == 1
    assert events[0]["event"] == "ATTACHED_TO_EXISTING"
    assert events[1]["event"] == "ATTACHED_PROCESS_EXITED"
