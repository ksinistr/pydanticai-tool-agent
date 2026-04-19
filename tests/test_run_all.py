from __future__ import annotations

from types import SimpleNamespace

from app.run_all import ManagedProcess, _first_exited_process


def test_first_exited_process_returns_none_when_all_processes_are_running() -> None:
    processes = [
        ManagedProcess("web", ("python",), 15, process=SimpleNamespace(poll=lambda: None)),
        ManagedProcess("telegram", ("python",), 2, process=SimpleNamespace(poll=lambda: None)),
    ]

    assert _first_exited_process(processes) is None


def test_first_exited_process_returns_first_finished_process() -> None:
    running = ManagedProcess("web", ("python",), 15, process=SimpleNamespace(poll=lambda: None))
    finished = ManagedProcess("telegram", ("python",), 2, process=SimpleNamespace(poll=lambda: 1))

    assert _first_exited_process([running, finished]) is finished
