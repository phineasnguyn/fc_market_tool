"""Coordinate and message checks for pointer-free window input."""

import unittest

from windows import BackgroundGameDesktop, MK_LBUTTON, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE


class RecordingDesktop(BackgroundGameDesktop):
    def __init__(self):
        super().__init__("test")
        self.messages = []

    def client_box(self):
        return 0, 0, 1920, 1080

    def post_mouse(self, message, x, y, buttons=0):
        self.messages.append((message, x, y, buttons))


class BackgroundInputTests(unittest.TestCase):
    def test_click_posts_window_messages_without_cursor_input(self):
        desktop = RecordingDesktop()
        desktop.click_ref(1449, 440)
        self.assertEqual(desktop.messages, [
            (WM_MOUSEMOVE, 1449, 440, 0),
            (WM_LBUTTONDOWN, 1449, 440, MK_LBUTTON),
            (WM_LBUTTONUP, 1449, 440, 0),
        ])

    def test_reference_coordinate_uses_center_cropped_client(self):
        desktop = RecordingDesktop()
        desktop.client_box = lambda: (0, 29, 1920, 1049)
        x, y = desktop.client_point(960, 540)
        self.assertEqual((x, y), (959, 510))


if __name__ == "__main__":
    unittest.main()
