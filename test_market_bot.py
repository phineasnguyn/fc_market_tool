"""Checks that market clicks follow verified screen states."""

import os
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image

from market_bot import (
    BUY_ACTION_X,
    BUY_ACTION_Y,
    BUY_CANCEL_X,
    BUY_CANCEL_Y,
    BUY_X,
    BUY_Y,
    CANCEL_X,
    CANCEL_Y,
    MAX_PRICE_ROW_X,
    MAX_PRICE_ROW_Y,
    MIN_PRICE_ROW_X,
    MIN_PRICE_ROW_Y,
    RENEW_X,
    RENEW_Y,
    SELL_ACTION_X,
    SELL_ACTION_Y,
    SELL_CANCEL_X,
    SELL_CANCEL_Y,
    SELL_MAX_PRICE_ROW_X,
    SELL_MAX_PRICE_ROW_Y,
    SELL_MIN_PRICE_ROW_X,
    SELL_MIN_PRICE_ROW_Y,
    OrderTarget,
    ready_to_complete,
    run_market_bot,
)
from vision import FastOcr, MarketView, PriceRow, analyze


SAMPLES_DIR = Path(os.environ.get("FC_SAMPLE_DIR", Path(__file__).parent / "samples"))
LIST_IMAGE = Path(os.environ.get("FC_LIST_IMAGE", SAMPLES_DIR / "list.png"))
BUY_IMAGE = Path(os.environ.get("FC_BUY_IMAGE", SAMPLES_DIR / "buy.png"))
SELL_IMAGE = Path(os.environ.get("FC_SELL_IMAGE", SAMPLES_DIR / "sell.png"))
TESSERACT_EXE = Path(os.environ.get("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))


class FakeDesktop:
    def __init__(self, is_sell=False):
        self.state = "my_list"
        self.clicks = []
        self.is_sell = is_sell

    def screenshot(self):
        return self.state

    def click_ref(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == (RENEW_X, RENEW_Y):
            self.state = "sell_dialog" if self.is_sell else "buy_dialog"
        elif (x, y) in ((CANCEL_X, CANCEL_Y), (BUY_X, BUY_Y), (SELL_CANCEL_X, SELL_CANCEL_Y), (SELL_ACTION_X, SELL_ACTION_Y)):
            self.state = "my_list"

    def move_ref(self, x, y):
        pass


class MarketBotTests(unittest.TestCase):
    def run_scenario(self, queues, target=None):
        if target is None:
            target = OrderTarget("F. Lampard", retry_ms=0, max_cycles=5, read_timeout_sec=0.05)

        desktop = FakeDesktop(is_sell=(target.mode in ("SELL_MIN", "SELL_MAX")))
        messages = []
        reads = iter(queues)

        def read(image, _ocr, _row):
            reg = 700_000_000 if target.mode == "SELL_MIN" else 865_000_000
            if image == "my_list":
                return MarketView("my_list", "F. Lampard", registered_price_bp=reg)
            try:
                count = next(reads)
            except StopIteration:
                count = None
            rows = (PriceRow(850_000_000, 1),)
            if target.mode == "SELL_MIN":
                return MarketView(
                    "buy_dialog",
                    "F. Lampard",
                    registered_price_bp=700_000_000,
                    min_price_bp=700_000_000,
                    max_price_bp=865_000_000,
                    price_rows=rows,
                    sellers_at_min=count,
                )
            elif target.mode == "SELL_MAX":
                return MarketView(
                    "buy_dialog",
                    "F. Lampard",
                    registered_price_bp=865_000_000,
                    min_price_bp=700_000_000,
                    max_price_bp=865_000_000,
                    price_rows=rows,
                    sellers_at_max=count,
                )
            return MarketView(
                "buy_dialog",
                "F. Lampard",
                865_000_000,
                865_000_000,
                price_rows=rows,
                buyers_at_max=count,
            )

        with patch("market_bot.analyze", side_effect=read), patch("market_bot.state_from_pixels", side_effect=lambda image, row: image), patch("market_bot.renew_button_visible", return_value=True):
            run_market_bot(desktop, object(), target, Event(), messages.append, dry_run=False)
        return desktop.clicks, messages

    def test_buys_when_condition_fails_then_cancels_when_met(self):
        clicks, messages = self.run_scenario([28, 3])
        self.assertEqual(clicks, [(RENEW_X, RENEW_Y), (1449, 440), (BUY_X, BUY_Y), (RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in message for message in messages))

    def test_four_is_allowed_five_is_not(self):
        clicks, _ = self.run_scenario([5, 4])
        self.assertEqual(clicks[1:3], [(1449, 440), (BUY_X, BUY_Y)])
        self.assertEqual(clicks[-1], (CANCEL_X, CANCEL_Y))

    def test_condition_met_immediately_cancels_without_buying(self):
        clicks, messages = self.run_scenario([4])
        self.assertEqual(clicks, [(RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in message for message in messages))

    def test_missing_queue_still_buys(self):
        # Khi số lượng đặt max là None (thị trường reset giá), bot vẫn bấm mua và chỉ dừng khi số lượng <= cài đặt
        clicks, messages = self.run_scenario([None, 3])
        self.assertEqual(clicks, [(RENEW_X, RENEW_Y), (1449, 440), (BUY_X, BUY_Y), (RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in message for message in messages))

    def test_retries_when_buy_dialog_not_ready(self):
        # Lần đọc đầu tiên là chưa load xong (None), lần đọc thứ hai là 3 (đủ điều kiện)
        desktop = FakeDesktop()
        messages = []
        dialog_states = iter([(None, None), (865_000_000, 3)])

        def read(image, _ocr, _row):
            if image == "my_list":
                return MarketView("my_list", "F. Lampard", registered_price_bp=865_000_000)
            max_p, buyers = next(dialog_states)
            return MarketView("buy_dialog", "F. Lampard", max_p, max_p, buyers_at_max=buyers)

        target = OrderTarget("F. Lampard", retry_ms=0, max_cycles=5, read_timeout_sec=0.5)
        with patch("market_bot.analyze", side_effect=read), patch("market_bot.state_from_pixels", side_effect=lambda image, row: image), patch("market_bot.renew_button_visible", return_value=True):
            run_market_bot(desktop, object(), target, Event(), messages.append, dry_run=False)
        self.assertEqual(desktop.clicks, [(RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in message for message in messages))

    def test_recovers_and_retries_on_unreadable_dialog(self):
        # Lượt 1: buy_dialog đọc ra None (lag/lỗi) -> bấm CANCEL để đóng hộp và thử lại
        # Lượt 2: buy_dialog đọc ra 3 (thành công <= 4) -> bấm CANCEL và hoàn thành
        desktop = FakeDesktop()
        messages = []
        attempts = {"count": 0}

        def read(image, _ocr, _row):
            if image == "my_list":
                return MarketView("my_list", "F. Lampard", registered_price_bp=865_000_000)
            attempts["count"] += 1
            # 3 lần gọi đầu (của lượt 1) đều là None, từ lần thứ 4 (lượt 2) là 3
            buyers = 3 if attempts["count"] >= 4 else None
            max_p = 865_000_000 if buyers is not None else None
            return MarketView("buy_dialog", "F. Lampard", max_p, max_p, buyers_at_max=buyers)

        target = OrderTarget("F. Lampard", retry_ms=0, max_cycles=5, read_timeout_sec=0.02, max_consecutive_errors=3)
        with patch("market_bot.analyze", side_effect=read), patch("market_bot.state_from_pixels", side_effect=lambda image, row: image), patch("market_bot.renew_button_visible", return_value=True):
            run_market_bot(desktop, object(), target, Event(), messages.append, dry_run=False)

        self.assertEqual(desktop.clicks, [(RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y), (RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in m for m in messages))

    def test_uses_configured_max_price_coordinates(self):
        desktop = FakeDesktop()
        messages = []
        dialog_reads = iter([(800_000_000, 3), (865_000_000, 3)])

        def read(image, _ocr, _row):
            if image == "my_list":
                return MarketView("my_list", "F. Lampard", registered_price_bp=800_000_000)
            registered, buyers = next(dialog_reads)
            return MarketView("buy_dialog", "F. Lampard", 865_000_000, registered, buyers_at_max=buyers)

        target = OrderTarget("F. Lampard", retry_ms=0, max_cycles=3, max_price_click_x=1400, max_price_click_y=430)
        with patch("market_bot.analyze", side_effect=read), patch("market_bot.state_from_pixels", side_effect=lambda image, row: image), patch("market_bot.renew_button_visible", return_value=True):
            run_market_bot(desktop, object(), target, Event(), messages.append, dry_run=False)
        self.assertEqual(desktop.clicks, [(RENEW_X, RENEW_Y), (1400, 430), (BUY_X, BUY_Y), (RENEW_X, RENEW_Y), (CANCEL_X, CANCEL_Y)])
        self.assertTrue(any("Hoàn thành" in message for message in messages))

    def test_sell_min_places_order_then_cancels_when_met(self):
        target = OrderTarget(mode="SELL_MIN", retry_ms=0, max_cycles=5, read_timeout_sec=0.05)
        clicks, messages = self.run_scenario([15, 2], target=target)
        self.assertEqual(
            clicks,
            [(RENEW_X, RENEW_Y), (SELL_MIN_PRICE_ROW_X, SELL_MIN_PRICE_ROW_Y), (SELL_ACTION_X, SELL_ACTION_Y), (RENEW_X, RENEW_Y), (SELL_CANCEL_X, SELL_CANCEL_Y)],
        )
        self.assertTrue(any("Hoàn thành" in m for m in messages))

    def test_sell_min_missing_queue_still_sells(self):
        # Khi giá đăng ký ban đầu chưa phải giá sàn và số lượng đặt bán là None, bot bấm bán tại giá sàn rồi hoàn thành
        target = OrderTarget(mode="SELL_MIN", retry_ms=0, max_cycles=5, read_timeout_sec=0.05)
        desktop = FakeDesktop(is_sell=True)
        messages = []
        cycle_count = {"n": 0}

        def read(image, _ocr, _row):
            sold = (SELL_ACTION_X, SELL_ACTION_Y) in desktop.clicks
            reg = 700_000_000 if sold else 800_000_000
            if image == "my_list":
                return MarketView("my_list", "F. Lampard", registered_price_bp=reg)
            return MarketView(
                "sell_dialog",
                "F. Lampard",
                registered_price_bp=reg,
                min_price_bp=700_000_000,
                max_price_bp=865_000_000,
                sellers_at_min=None,
            )

        with patch("market_bot.analyze", side_effect=read), patch("market_bot.state_from_pixels", side_effect=lambda image, row: image), patch("market_bot.renew_button_visible", return_value=True):
            run_market_bot(desktop, object(), target, Event(), messages.append, dry_run=False)

        self.assertEqual(
            desktop.clicks,
            [(RENEW_X, RENEW_Y), (SELL_MIN_PRICE_ROW_X, SELL_MIN_PRICE_ROW_Y), (SELL_ACTION_X, SELL_ACTION_Y), (RENEW_X, RENEW_Y), (SELL_CANCEL_X, SELL_CANCEL_Y)],
        )
        self.assertTrue(any("Hoàn thành" in m for m in messages))

    def test_sell_max_places_order_then_cancels_when_met(self):
        target = OrderTarget(mode="SELL_MAX", retry_ms=0, max_cycles=5, read_timeout_sec=0.05)
        clicks, messages = self.run_scenario([20, 1], target=target)
        self.assertEqual(
            clicks,
            [(RENEW_X, RENEW_Y), (SELL_MAX_PRICE_ROW_X, SELL_MAX_PRICE_ROW_Y), (SELL_ACTION_X, SELL_ACTION_Y), (RENEW_X, RENEW_Y), (SELL_CANCEL_X, SELL_CANCEL_Y)],
        )
        self.assertTrue(any("Hoàn thành" in m for m in messages))

    def test_ready_to_complete_logic(self):
        # BUY
        v_buy = MarketView("buy_dialog", max_price_bp=100, registered_price_bp=100, buyers_at_max=4)
        self.assertTrue(ready_to_complete(v_buy, OrderTarget(mode="BUY", max_buyers_ahead=4)))
        self.assertFalse(ready_to_complete(v_buy, OrderTarget(mode="BUY", max_buyers_ahead=3)))

        # SELL_MIN
        v_sell_min = MarketView("sell_dialog", min_price_bp=50, registered_price_bp=50, sellers_at_min=2)
        self.assertTrue(ready_to_complete(v_sell_min, OrderTarget(mode="SELL_MIN", max_buyers_ahead=2)))
        self.assertFalse(ready_to_complete(v_sell_min, OrderTarget(mode="SELL_MIN", max_buyers_ahead=1)))
        # Khi không có cột số lượng (hộp thoại bán chuẩn), đã khớp giá sàn là hoàn thành
        v_sell_min_none = MarketView("sell_dialog", min_price_bp=50, registered_price_bp=50, sellers_at_min=None)
        self.assertTrue(ready_to_complete(v_sell_min_none, OrderTarget(mode="SELL_MIN", max_buyers_ahead=4)))
        # Nếu chưa khớp giá sàn thì chưa hoàn thành
        v_sell_min_diff = MarketView("sell_dialog", min_price_bp=50, registered_price_bp=60, sellers_at_min=None)
        self.assertFalse(ready_to_complete(v_sell_min_diff, OrderTarget(mode="SELL_MIN", max_buyers_ahead=4)))

        # SELL_MAX
        v_sell_max = MarketView("sell_dialog", max_price_bp=100, registered_price_bp=100, sellers_at_max=3)
        self.assertTrue(ready_to_complete(v_sell_max, OrderTarget(mode="SELL_MAX", max_buyers_ahead=3)))
        self.assertFalse(ready_to_complete(v_sell_max, OrderTarget(mode="SELL_MAX", max_buyers_ahead=2)))
        v_sell_max_none = MarketView("sell_dialog", max_price_bp=100, registered_price_bp=100, sellers_at_max=None)
        self.assertTrue(ready_to_complete(v_sell_max_none, OrderTarget(mode="SELL_MAX", max_buyers_ahead=4)))

    @unittest.skipUnless(
        LIST_IMAGE.exists() and BUY_IMAGE.exists() and TESSERACT_EXE.exists(),
        "Ảnh mẫu hoặc Tesseract OCR không có trên máy này"
    )
    def test_sample_images(self):
        ocr = FastOcr(TESSERACT_EXE)
        try:
            with Image.open(LIST_IMAGE) as image:
                self.assertEqual(analyze(image, ocr).registered_price_bp, 865_000_000)
            with Image.open(BUY_IMAGE) as image:
                view = analyze(image, ocr)
                self.assertEqual((view.max_price_bp, view.buyers_at_max), (865_000_000, 28))
            if SELL_IMAGE.exists():
                with Image.open(SELL_IMAGE) as image:
                    view = analyze(image, ocr)
                    self.assertEqual(view.state, "sell_dialog")
                    self.assertEqual(view.player_name, "F. Ljungberg")
                    self.assertEqual(view.min_price_bp, 16_400_000)
                    self.assertEqual(view.max_price_bp, 20_000_000)
                    self.assertEqual(view.registered_price_bp, 18_200_000)
        finally:
            ocr.close()


if __name__ == "__main__":
    unittest.main()
