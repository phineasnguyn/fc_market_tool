"""Windows desktop input through the standard Win32 API."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def find_game_title() -> str:
    """Find the game's top-level window, even when another app is active."""
    return "FC ONLINE" if user32.FindWindowW(None, "FC ONLINE") else ""


def activate_game(title: str) -> bool:
    """Restore the selected game and bring it forward after a user action in this app."""
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + 2.5
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            time.sleep(0.25)
            return True
        time.sleep(0.05)
    return False


def cursor_position() -> tuple[int, int]:
    point = POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    return point.x, point.y


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def click(x: int, y: int) -> None:
    if not user32.SetCursorPos(x, y):
        raise ctypes.WinError(ctypes.get_last_error())
    events = (INPUT * 2)(
        INPUT(0, INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, 0x0002, 0, 0))),
        INPUT(0, INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, 0))),
    )
    if user32.SendInput(2, events, ctypes.sizeof(INPUT)) != 2:
        raise ctypes.WinError(ctypes.get_last_error())


class WindowsDesktop:
    foreground_title = staticmethod(foreground_title)
    click = staticmethod(click)


class GameDesktop(WindowsDesktop):
    def __init__(self, target_title: str) -> None:
        self.target_title = target_title

    def client_box(self) -> tuple[int, int, int, int]:
        if foreground_title() != self.target_title:
            raise RuntimeError("Cửa sổ FC Online không còn ở phía trước.")
        hwnd = user32.GetForegroundWindow()
        return client_box_for(hwnd)

    def viewport_box(self) -> tuple[int, int, int, int]:
        """Center-crop the game's 16:9 canvas from its possibly wider client area."""
        left, top, right, bottom = self.client_box()
        width, height = right - left, bottom - top
        scale = min(width / 1920, height / 1080)
        viewport_width = round(1920 * scale)
        viewport_height = round(1080 * scale)
        crop_left = left + (width - viewport_width) // 2
        crop_top = top + (height - viewport_height) // 2
        return crop_left, crop_top, crop_left + viewport_width, crop_top + viewport_height

    def screenshot(self):
        from PIL import ImageGrab

        return ImageGrab.grab(bbox=self.viewport_box(), all_screens=True)

    def click_ref(self, x: int, y: int) -> None:
        left, top, right, bottom = self.viewport_box()
        click(left + round(x * (right - left) / 1920), top + round(y * (bottom - top) / 1080))

    def move_ref(self, x: int, y: int) -> None:
        left, top, right, bottom = self.viewport_box()
        screen_x = left + round(x * (right - left) / 1920)
        screen_y = top + round(y * (bottom - top) / 1080)
        if not user32.SetCursorPos(screen_x, screen_y):
            raise RuntimeError("Windows không cho di chuyển chuột vào game; kiểm tra quyền chạy của app và game.")


def client_box_for(hwnd: int) -> tuple[int, int, int, int]:
    if not hwnd:
        raise RuntimeError("Không tìm thấy cửa sổ FC Online.")
    rect = RECT()
    origin = POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right, rect.bottom
    if width <= 0 or height <= 0:
        raise RuntimeError("Không đọc được kích thước vùng hiển thị của FC Online.")
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


class BackgroundGameDesktop(GameDesktop):
    """Experimental window capture and mouse messages without touching the user's pointer."""

    def hwnd(self) -> int:
        hwnd = user32.FindWindowW(None, self.target_title)
        if not hwnd:
            raise RuntimeError("Không tìm thấy cửa sổ FC Online để chạy nền.")
        if user32.IsIconic(hwnd):
            raise RuntimeError("Hãy để cửa sổ FC Online không bị thu nhỏ khi chạy nền.")
        return hwnd

    def client_box(self) -> tuple[int, int, int, int]:
        return client_box_for(self.hwnd())

    def screenshot(self):
        from PIL import ImageGrab

        image = ImageGrab.grab(window=self.hwnd())
        client_left, client_top, client_right, client_bottom = self.client_box()
        if image.size != (client_right - client_left, client_bottom - client_top):
            raise RuntimeError("Kích thước ảnh cửa sổ chạy nền không khớp vùng game.")
        left, top, right, bottom = self.viewport_box()
        image = image.crop((left - client_left, top - client_top, right - client_left, bottom - client_top))
        if image.width < 100 or image.height < 100:
            raise RuntimeError("Không chụp được nội dung cửa sổ game khi chạy nền.")
        return image

    def client_point(self, x: int, y: int) -> tuple[int, int]:
        viewport_left, viewport_top, viewport_right, viewport_bottom = self.viewport_box()
        client_left, client_top, _, _ = self.client_box()
        return (
            viewport_left - client_left + round(x * (viewport_right - viewport_left) / 1920),
            viewport_top - client_top + round(y * (viewport_bottom - viewport_top) / 1080),
        )

    def post_mouse(self, message: int, x: int, y: int, buttons: int = 0) -> None:
        client_x, client_y = self.client_point(x, y)
        lparam = (client_x & 0xFFFF) | ((client_y & 0xFFFF) << 16)
        if not user32.PostMessageW(self.hwnd(), message, buttons, lparam):
            raise ctypes.WinError(ctypes.get_last_error())

    def move_ref(self, x: int, y: int) -> None:
        self.post_mouse(WM_MOUSEMOVE, x, y)

    def click_ref(self, x: int, y: int) -> None:
        self.post_mouse(WM_MOUSEMOVE, x, y)
        self.post_mouse(WM_LBUTTONDOWN, x, y, MK_LBUTTON)
        self.post_mouse(WM_LBUTTONUP, x, y)
