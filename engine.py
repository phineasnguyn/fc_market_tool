"""Small, testable click sequence runner. No game specific logic lives here."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable, Protocol


@dataclass(frozen=True)
class Step:
    x: int
    y: int
    delay_ms: int = 150


class Desktop(Protocol):
    def foreground_title(self) -> str: ...
    def click(self, x: int, y: int) -> None: ...


def run_sequence(
    desktop: Desktop,
    steps: list[Step],
    target_title: str,
    repeats: int,
    pause_ms: int,
    dry_run: bool,
    stop: Event,
    report: Callable[[str], None],
) -> None:
    """Run only while the selected game window remains in the foreground."""
    if not steps:
        raise ValueError("Cần ít nhất một điểm bấm.")
    if not target_title.strip():
        raise ValueError("Cần chọn cửa sổ FC Online.")
    if not 1 <= repeats <= 10000:
        raise ValueError("Số lần lặp phải từ 1 đến 10000.")
    if not 0 <= pause_ms <= 60000:
        raise ValueError("Khoảng nghỉ phải từ 0 đến 60000 ms.")
    if any(s.x < 0 or s.y < 0 or not 0 <= s.delay_ms <= 60000 for s in steps):
        raise ValueError("Tọa độ hoặc thời gian chờ không hợp lệ.")

    for attempt in range(1, repeats + 1):
        if stop.is_set():
            break
        for index, step in enumerate(steps, 1):
            if stop.is_set():
                break
            active_title = desktop.foreground_title()
            if active_title != target_title:
                report(f"Đã dừng: cửa sổ hiện tại là '{active_title}'.")
                return
            if dry_run:
                report(f"Thử {attempt}, bước {index}: sẽ bấm ({step.x}, {step.y}).")
            else:
                desktop.click(step.x, step.y)
                report(f"Lần {attempt}, bước {index}: đã bấm ({step.x}, {step.y}).")
            if stop.wait(step.delay_ms / 1000):
                break
        if attempt < repeats and stop.wait(pause_ms / 1000):
            break
    report("Đã kết thúc.")
