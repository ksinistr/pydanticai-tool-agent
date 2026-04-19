from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os
import signal
import subprocess
import sys
import time

from app.config import AppConfig


@dataclass(slots=True)
class ManagedProcess:
    name: str
    command: tuple[str, ...]
    stop_signal: int
    process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(self.command, start_new_session=True)

    def exit_code(self) -> int | None:
        if self.process is None:
            return None
        return self.process.poll()


def main() -> None:
    config = AppConfig.from_env()
    config.require_telegram_bot_token()

    processes = [
        ManagedProcess(
            name="agent-web",
            command=(sys.executable, "-m", "app.web.app"),
            stop_signal=signal.SIGTERM,
        ),
        ManagedProcess(
            name="telegram-bot",
            command=(sys.executable, "-m", "app.bot.telegram_app"),
            stop_signal=signal.SIGINT,
        ),
    ]

    for process in processes:
        process.start()

    print(f"Web UI: http://{config.web_host}:{config.web_port}")
    print("Telegram polling: started")

    _install_signal_handlers()

    exit_code = 0
    try:
        while True:
            finished = _first_exited_process(processes)
            if finished is None:
                time.sleep(0.2)
                continue
            exit_code = finished.exit_code() or 0
            break
    except KeyboardInterrupt:
        exit_code = 0
    finally:
        _interrupt_processes(processes)
        _join_processes(processes)

    raise SystemExit(exit_code)


def _first_exited_process(processes: Sequence[ManagedProcess]) -> ManagedProcess | None:
    for process in processes:
        if process.exit_code() is not None:
            return process
    return None


def _interrupt_processes(processes: Sequence[ManagedProcess]) -> None:
    for process in processes:
        pid = process.process.pid if process.process is not None else None
        if pid is None or process.exit_code() is not None:
            continue
        os.killpg(pid, process.stop_signal)


def _join_processes(processes: Sequence[ManagedProcess]) -> None:
    for process in processes:
        child = process.process
        if child is None:
            continue
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)

    for process in processes:
        child = process.process
        if child is not None:
            child.wait()


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)


def _raise_keyboard_interrupt(signum: int, frame) -> None:
    del signum, frame
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
