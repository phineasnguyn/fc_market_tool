"""UI state machine for renewing one FC Online market purchase order."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from threading import Event
from typing import Callable, Protocol

from PIL import Image

from vision import FastOcr, MarketView, analyze, dialog_button_centers, renew_button_visible, state_from_pixels


RENEW_X, RENEW_Y = 1487, 273

# Tọa độ hộp thoại Mua cầu thủ (1920x1080)
BUY_CANCEL_X, BUY_CANCEL_Y = 1443, 861
BUY_ACTION_X, BUY_ACTION_Y = 1235, 861
BUY_MIN_PRICE_ROW_X, BUY_MIN_PRICE_ROW_Y = 1449, 400
BUY_MAX_PRICE_ROW_X, BUY_MAX_PRICE_ROW_Y = 1449, 440

# Tọa độ hộp thoại Bán cầu thủ (1920x1080)
SELL_CANCEL_X, SELL_CANCEL_Y = 1430, 895
SELL_ACTION_X, SELL_ACTION_Y = 1230, 895
SELL_MIN_PRICE_ROW_X, SELL_MIN_PRICE_ROW_Y = 1449, 480
SELL_MAX_PRICE_ROW_X, SELL_MAX_PRICE_ROW_Y = 1449, 520

CANCEL_X, CANCEL_Y = BUY_CANCEL_X, BUY_CANCEL_Y
BUY_X, BUY_Y = BUY_ACTION_X, BUY_ACTION_Y
ACTION_BTN_X, ACTION_BTN_Y = BUY_ACTION_X, BUY_ACTION_Y
MIN_PRICE_ROW_X, MIN_PRICE_ROW_Y = BUY_MIN_PRICE_ROW_X, BUY_MIN_PRICE_ROW_Y
MAX_PRICE_ROW_X, MAX_PRICE_ROW_Y = BUY_MAX_PRICE_ROW_X, BUY_MAX_PRICE_ROW_Y


class MarketDesktop(Protocol):
    def screenshot(self) -> Image.Image: ...
    def click_ref(self, x: int, y: int) -> None: ...
    def move_ref(self, x: int, y: int) -> None: ...


@dataclass(frozen=True)
class OrderTarget:
    player_name: str = ""
    row_index: int = 1
    max_buyers_ahead: int = 4
    retry_ms: int = 250
    max_cycles: int = 1000
    max_price_click_x: int = MAX_PRICE_ROW_X
    max_price_click_y: int = MAX_PRICE_ROW_Y
    min_price_click_x: int = MIN_PRICE_ROW_X
    min_price_click_y: int = MIN_PRICE_ROW_Y
    read_timeout_sec: float = 1.5
    max_consecutive_errors: int = 5
    mode: str = "BUY"  # "BUY", "SELL_MIN", "SELL_MAX"


def clean_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).casefold()
    return re.sub(r"[^a-z0-9]", "", normalized)


def same_player(found: str, target: str) -> bool:
    a, b = clean_name(found), clean_name(target)
    return bool(a and b and (a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.88))


def ready_to_buy(view: MarketView, limit: int) -> bool:
    """Điều kiện (c): Giá đăng ký = giá tối đa và số lượt đặt phía trước <= limit."""
    return (
        view.state in ("buy_dialog", "sell_dialog")
        and view.registered_price_bp is not None
        and view.max_price_bp is not None
        and view.registered_price_bp == view.max_price_bp
        and view.buyers_at_max is not None
        and view.buyers_at_max <= limit
    )


def ready_to_complete(view: MarketView, target: OrderTarget) -> bool:
    """Kiểm tra điều kiện hoàn thành theo chế độ Mua / Bán."""
    if view.state not in ("buy_dialog", "sell_dialog") or view.registered_price_bp is None:
        return False

    limit = target.max_buyers_ahead
    if target.mode == "SELL_MIN":
        if view.min_price_bp is None or view.registered_price_bp != view.min_price_bp:
            return False
        return view.sellers_at_min is not None and view.sellers_at_min <= limit
    elif target.mode == "SELL_MAX":
        if view.max_price_bp is None or view.registered_price_bp != view.max_price_bp:
            return False
        return view.sellers_at_max is not None and view.sellers_at_max <= limit
    else:  # "BUY"
        return ready_to_buy(view, limit)


def wait_for_state(
    desktop: MarketDesktop,
    expected: str | tuple[str, ...],
    row_index: int,
    stop: Event,
    timeout: float = 2.0,
) -> Image.Image | None:
    deadline = time.monotonic() + timeout
    expected_set = (expected,) if isinstance(expected, str) else expected
    while not stop.is_set() and time.monotonic() < deadline:
        image = desktop.screenshot()
        if state_from_pixels(image, row_index) in expected_set:
            return image
        stop.wait(0.04)
    return None


def wait_for_renew_button(desktop: MarketDesktop, row_index: int, stop: Event, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    renew_y = RENEW_Y + (row_index - 1) * 61
    while not stop.is_set() and time.monotonic() < deadline:
        image = desktop.screenshot()
        if renew_button_visible(image, row_index):
            return True
        desktop.move_ref(RENEW_X, renew_y)
        if stop.wait(0.15):
            return False
    return False


def run_market_bot(
    desktop: MarketDesktop,
    ocr: FastOcr,
    target: OrderTarget,
    stop: Event,
    report: Callable[[str], None],
    dry_run: bool = True,
) -> None:
    if not 1 <= target.row_index <= 5:
        raise ValueError("Hàng phải từ 1 đến 5.")
    if not 0 <= target.max_buyers_ahead <= 100:
        raise ValueError("Giới hạn lệnh phía trước phải từ 0 đến 100.")
    if not 0 <= target.retry_ms <= 60000 or not 1 <= target.max_cycles <= 10000:
        raise ValueError("Thời gian thử lại hoặc số lượt kiểm tra không hợp lệ.")
    if target.mode not in ("BUY", "SELL_MIN", "SELL_MAX"):
        raise ValueError("Chế độ phải là BUY, SELL_MIN hoặc SELL_MAX.")

    consecutive_errors = 0
    max_errors = max(1, target.max_consecutive_errors)
    expected_dialog_state = "buy_dialog" if target.mode == "BUY" else "sell_dialog"
    observed_player_name = ""

    for cycle in range(1, target.max_cycles + 1):
        if stop.is_set():
            report("Đã dừng theo yêu cầu.")
            return

        image = desktop.screenshot()
        state = state_from_pixels(image, target.row_index)

        if state == "my_list":
            deadline = time.monotonic() + target.read_timeout_sec
            view = analyze(image, ocr, target.row_index)
            while not stop.is_set():
                if view.registered_price_bp is not None or time.monotonic() >= deadline:
                    break
                if stop.wait(0.1):
                    report("Đã dừng theo yêu cầu.")
                    return
                image = desktop.screenshot()
                view = analyze(image, ocr, target.row_index)

            if view.registered_price_bp is None:
                consecutive_errors += 1
                if consecutive_errors >= max_errors:
                    report("Đã dừng: không đọc được giá đăng ký trên hàng đã chọn.")
                    return
                report(f"Chưa đọc được giá đăng ký ở hàng {target.row_index} (lần {consecutive_errors}/{max_errors}); đợi 0.5s rồi thử lại...")
                if stop.wait(0.5):
                    report("Đã dừng theo yêu cầu.")
                    return
                continue

            if target.player_name:
                if not view.player_name:
                    report("Đã dừng: OCR không đọc được tên cầu thủ ở hàng đã chọn.")
                    return
                if not same_player(view.player_name, target.player_name):
                    report(f"Đã dừng: hàng {target.row_index} là '{view.player_name}', cần '{target.player_name}'.")
                    return
            elif view.player_name:
                observed_player_name = view.player_name

            name_info = f"{view.player_name}, " if view.player_name else ""
            report(f"Lượt {cycle}: {name_info}giá đang đăng ký {view.registered_price_bp} BP.")
            if dry_run:
                report("Mô phỏng: sẽ bấm Đăng ký lại để kiểm tra giá và số lượt đặt.")
                return

            if not renew_button_visible(image, target.row_index):
                if not wait_for_renew_button(desktop, target.row_index, stop, timeout=1.5):
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        report("Đã dừng: nút Đăng ký lại chưa hiện ở hàng đã chọn.")
                        return
                    report(f"Nút Đăng ký lại chưa hiện (lần {consecutive_errors}/{max_errors}); đợi 0.5s rồi thử lại...")
                    if stop.wait(0.5):
                        report("Đã dừng theo yêu cầu.")
                        return
                    continue

            desktop.click_ref(RENEW_X, RENEW_Y + (target.row_index - 1) * 61)
            image = wait_for_state(desktop, ("buy_dialog", "sell_dialog"), target.row_index, stop)
            if image is None:
                consecutive_errors += 1
                if consecutive_errors >= max_errors:
                    report("Đã dừng: bấm Đăng ký lại nhưng không thấy hộp thao tác cầu thủ.")
                    return
                report(f"Bấm Đăng ký lại nhưng chưa thấy hộp thao tác cầu thủ (lần {consecutive_errors}/{max_errors}); thử lại...")
                if stop.wait(0.5):
                    report("Đã dừng theo yêu cầu.")
                    return
                continue

        elif state not in ("buy_dialog", "sell_dialog"):
            consecutive_errors += 1
            if consecutive_errors >= max_errors:
                report("Đã dừng: không nhận ra màn hình DS của bạn hoặc hộp thao tác.")
                return
            report(f"Chưa nhận ra màn hình DS hoặc hộp thao tác (lần {consecutive_errors}/{max_errors}); đợi 0.5s rồi thử lại...")
            if stop.wait(0.5):
                report("Đã dừng theo yêu cầu.")
                return
            continue

        dialog_state = state_from_pixels(image, target.row_index)
        if dialog_state != expected_dialog_state:
            report(
                f"Đã dừng: chế độ {target.mode} cần hộp "
                f"{'Mua' if expected_dialog_state == 'buy_dialog' else 'Bán'}, nhưng màn hình hiện tại không khớp."
            )
            return

        # Đang ở hộp thoại Mua/Bán cầu thủ
        deadline = time.monotonic() + target.read_timeout_sec
        view = analyze(image, ocr, target.row_index)
        while not stop.is_set():
            if target.mode == "SELL_MIN":
                has_prices = view.min_price_bp is not None and view.registered_price_bp is not None
                has_data = has_prices and view.sellers_at_min is not None
            elif target.mode == "SELL_MAX":
                has_prices = view.max_price_bp is not None and view.registered_price_bp is not None
                has_data = has_prices and view.sellers_at_max is not None
            else:  # BUY
                has_prices = view.max_price_bp is not None and view.registered_price_bp is not None
                has_data = has_prices and view.buyers_at_max is not None

            has_table = bool(view.price_rows)
            if has_data or (has_prices and (has_table or time.monotonic() >= deadline)):
                break
            if time.monotonic() >= deadline:
                break
            if stop.wait(0.1):
                report("Đã dừng theo yêu cầu.")
                return
            image = desktop.screenshot()
            view = analyze(image, ocr, target.row_index)

        expected_player = target.player_name or observed_player_name
        if expected_player:
            if not view.player_name:
                report("Đã dừng: OCR không đọc được tên cầu thủ trong hộp thao tác.")
                return
            if not same_player(view.player_name, expected_player):
                report(f"Đã dừng: hộp thao tác là '{view.player_name}', cần '{expected_player}'.")
                return

        buttons = dialog_button_centers(image, expected_dialog_state)
        if buttons is None or buttons[0] != expected_dialog_state:
            report("Đã dừng: không định vị chắc chắn được nút thao tác và nút Hủy.")
            return
        _, (action_btn_x, action_btn_y), (cancel_btn_x, cancel_btn_y) = buttons

        if target.mode == "SELL_MIN":
            target_price = view.min_price_bp
            target_x = target.min_price_click_x if target.min_price_click_x != MIN_PRICE_ROW_X else SELL_MIN_PRICE_ROW_X
            target_y = target.min_price_click_y if target.min_price_click_y != MIN_PRICE_ROW_Y else SELL_MIN_PRICE_ROW_Y
            queue_count = view.sellers_at_min
            action_name = "Bán cầu thủ"
            price_name = "giá sàn"
            queue_name = "số lượt bán tại giá sàn"
        elif target.mode == "SELL_MAX":
            target_price = view.max_price_bp
            target_x = target.max_price_click_x if target.max_price_click_x != MAX_PRICE_ROW_X else SELL_MAX_PRICE_ROW_X
            target_y = target.max_price_click_y if target.max_price_click_y != MAX_PRICE_ROW_Y else SELL_MAX_PRICE_ROW_Y
            queue_count = view.sellers_at_max
            action_name = "Bán cầu thủ"
            price_name = "giá trần"
            queue_name = "số lượt bán tại giá trần"
        else:
            target_price = view.max_price_bp
            target_x, target_y = target.max_price_click_x, target.max_price_click_y
            queue_count = view.buyers_at_max
            action_name = "Mua cầu thủ"
            price_name = "giá tối đa"
            queue_name = "số lượt tại giá tối đa"

        report(
            f"Lượt {cycle}: giá đăng ký={view.registered_price_bp}, "
            f"{price_name}={target_price}, {queue_name}={queue_count}."
        )

        if target_price is None or view.registered_price_bp is None:
            consecutive_errors += 1
            if consecutive_errors >= max_errors:
                report(f"Đã dừng: OCR chưa đọc được giá đăng ký hoặc {price_name}.")
                return
            report(f"OCR chưa đọc được giá (lần {consecutive_errors}/{max_errors}); bấm Hủy để đóng hộp và thử lại...")
            desktop.click_ref(cancel_btn_x, cancel_btn_y)
            wait_for_state(desktop, "my_list", target.row_index, stop, timeout=2.0)
            if stop.wait(0.5):
                report("Đã dừng theo yêu cầu.")
                return
            continue

        if queue_count is None:
            consecutive_errors += 1
            if consecutive_errors >= max_errors:
                report(f"Đã dừng: OCR không đọc được {queue_name}; không bấm lệnh khi dữ liệu chưa chắc chắn.")
                return
            report(
                f"Chưa đọc được {queue_name} (lần {consecutive_errors}/{max_errors}); "
                "bấm Hủy và đọc lại, chưa đặt lệnh."
            )
            desktop.click_ref(cancel_btn_x, cancel_btn_y)
            if wait_for_state(desktop, "my_list", target.row_index, stop, timeout=2.0) is None:
                report("Đã dừng: bấm Hủy nhưng không trở về DS của bạn.")
                return
            if stop.wait(0.5):
                report("Đã dừng theo yêu cầu.")
                return
            continue

        # Thành công đọc giá: reset bộ đếm lỗi liên tiếp
        consecutive_errors = 0

        if ready_to_complete(view, target):
            if dry_run:
                report("Mô phỏng: điều kiện đã đạt; sẽ bấm Hủy để đóng hộp và dừng.")
                return
            desktop.click_ref(cancel_btn_x, cancel_btn_y)
            if wait_for_state(desktop, "my_list", target.row_index, stop, timeout=2.0) is None:
                desktop.click_ref(cancel_btn_x, cancel_btn_y)
                if wait_for_state(desktop, "my_list", target.row_index, stop, timeout=1.0) is None:
                    report("Đã dừng: điều kiện đạt nhưng không xác nhận được hộp thao tác đã đóng.")
                    return
            report(f"Hoàn thành: giá đăng ký bằng {price_name} và số lệnh không quá giới hạn; đã bấm Hủy và dừng.")
            return

        if dry_run:
            report(f"Mô phỏng: chưa đạt điều kiện; sẽ bấm chọn {price_name} tại ({target_x}, {target_y}), bấm {action_name} rồi lặp lại.")
            return
        desktop.click_ref(target_x, target_y)
        if stop.wait(0.1):
            report("Đã dừng theo yêu cầu.")
            return
        desktop.click_ref(action_btn_x, action_btn_y)
        if wait_for_state(desktop, "my_list", target.row_index, stop, timeout=3.0) is None:
            consecutive_errors += 1
            if consecutive_errors >= max_errors:
                report(f"Đã bấm {action_name} nhưng chưa xác nhận được màn hình DS của bạn; hãy kiểm tra game.")
                return
            report(f"Chưa xác nhận được màn hình DS sau khi bấm {action_name} (lần {consecutive_errors}/{max_errors}); đợi 1s rồi kiểm tra tiếp...")
            if stop.wait(1.0):
                report("Đã dừng theo yêu cầu.")
                return
            continue
        report(f"Lượt {cycle}: đã bấm chọn {price_name} và {action_name}; tiếp tục kiểm tra.")
        if stop.wait(target.retry_ms / 1000.0):
            report("Đã dừng theo yêu cầu.")
            return

    report("Đã dừng: đạt số lượt kiểm tra tối đa.")
