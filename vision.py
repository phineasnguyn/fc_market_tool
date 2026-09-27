"""Read the FC Online market panels at a normalized 1920 x 1080 layout."""

from __future__ import annotations

import re
import ctypes
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


REFERENCE_SIZE = (1920, 1080)
MARKET_CROP = (240, 48, 1680, 995)
BUY_NAME = (800, 260, 1050, 320)
BUY_PRICE_TABLE = (750, 320, 1070, 560)
BUY_MAX_PRICE = (1380, 400, 1605, 475)
DIALOG_MIN_PRICE = (1380, 360, 1605, 430)
BUY_REGISTERED_PRICE = (1380, 550, 1605, 630)

SELL_NAME = (790, 315, 1000, 375)
SELL_PRICE_TABLE = (750, 415, 1070, 750)
SELL_MIN_PRICE = (1370, 420, 1610, 485)
SELL_MAX_PRICE = (1370, 465, 1610, 535)
SELL_REGISTERED_PRICE = (1200, 600, 1610, 730)

LIST_NAME = (440, 245, 642, 298)
LIST_REGISTERED_PRICE = (1172, 250, 1284, 300)
PRICE_RE = re.compile(r"(\d[\d,.]*)\s*([MBT])", re.IGNORECASE)
ROW_RE = re.compile(r"(?:(\d+)\s+)?(\d[\d,.]*\s*[MBT])(?:\s+(\d+))?", re.IGNORECASE)


@dataclass(frozen=True)
class PriceRow:
    price_bp: int
    buyers: int = 0
    sellers: int = 0


@dataclass(frozen=True)
class MarketView:
    state: str
    player_name: str = ""
    max_price_bp: int | None = None
    registered_price_bp: int | None = None
    price_rows: tuple[PriceRow, ...] = ()
    buyers_at_max: int | None = None
    min_price_bp: int | None = None
    sellers_at_min: int | None = None
    sellers_at_max: int | None = None


def parse_price(text: str) -> int | None:
    cleaned_spaces = text.replace(" ", "")
    match = PRICE_RE.search(cleaned_spaces)
    if match:
        raw_number = match.group(1)
        if "," in raw_number and "." not in raw_number:
            parts = raw_number.split(",")
            # OCR hoặc locale có thể dùng dấu phẩy cho phần thập phân (1,03B).
            # FC Online dùng nhóm 3 chữ số cho giá lớn (615,000B).
            normalized_number = ".".join(parts) if len(parts) == 2 and len(parts[1]) <= 2 else "".join(parts)
        else:
            normalized_number = raw_number.replace(",", "")
        number = float(normalized_number)
        unit = match.group(2).upper()
        multiplier = {"M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[unit]
        return round(number * multiplier)

    # Thử xử lý nhầm lẫn OCR: 'M' bị nhận diện thành 'h' hoặc 'm' (ví dụ 20h, 16.4m)
    alt_match = re.search(r"(\d[\d,.]*)\s*([hH])\b", cleaned_spaces)
    if alt_match:
        number = float(alt_match.group(1).replace(",", ""))
        return round(number * 1_000_000)

    # Thử xử lý 'M' bị đọc thành '1' hoặc 'l' sau 1 chữ số thập phân (ví dụ 16.41, 16.4l)
    stem_match = re.search(r"(\d+\.\d)[1l|]\b", cleaned_spaces)
    if stem_match:
        return round(float(stem_match.group(1)) * 1_000_000)

    # Thử xử lý '20M' bị đọc thành 'Z0M' hoặc 'ZUM' (Z -> 2, U/O -> 0)
    z_match = re.search(r"\b[zZ]([0uUoO])\s*([mM])\b", cleaned_spaces)
    if z_match:
        return 20_000_000

    # Thử tìm số nguyên có dấu phẩy hoặc chấm định dạng tiền tệ trước (ví dụ 18,200,000 hoặc 18.200.000)
    currency_match = re.search(r"\b(\d{1,3}(?:[.,]\d{3})+)\b", text)
    if currency_match:
        digits = re.sub(r"[^\d]", "", currency_match.group(1))
        if len(digits) >= 6:
            return int(digits)

    # Thử theo từng dòng nếu có nhiều dòng
    for line in text.splitlines():
        line_clean = re.sub(r"[^\d]", "", line)
        if len(line_clean) >= 6:
            return int(line_clean)

    # Đọc số nguyên dạng đầy đủ (ví dụ 18200000)
    cleaned = re.sub(r"[^\d]", "", text)
    if cleaned and len(cleaned) >= 6:
        return int(cleaned)

    # Trường hợp số thập phân bị mất chữ M (ví dụ 16.4 -> 16.4M)
    dec_match = re.search(r"(\d+\.\d)\b", cleaned_spaces)
    if dec_match:
        val = float(dec_match.group(1))
        if 0.1 <= val < 10000:
            return round(val * 1_000_000)

    return None


def parse_rows(text: str) -> tuple[PriceRow, ...]:
    rows = []
    for line in text.splitlines():
        match = ROW_RE.search(line)
        if match:
            sellers = int(match.group(1)) if match.group(1) else 0
            price = parse_price(match.group(2))
            buyers = int(match.group(3)) if match.group(3) else 0
            if price is not None:
                rows.append(PriceRow(price, buyers, sellers))
    return tuple(rows)


def normalized(image: Image.Image) -> Image.Image:
    if image.size != REFERENCE_SIZE:
        return image.resize(REFERENCE_SIZE, Image.Resampling.BICUBIC)
    return image


def crop_market(image: Image.Image) -> Image.Image:
    return normalized(image).crop(MARKET_CROP)


def state_from_pixels(image: Image.Image, row_index: int = 1) -> str:
    image = normalized(image).convert("RGB")
    # Các điểm này nằm trên nền hộp thoại, tránh vùng ảnh thẻ cầu thủ.
    dialog_points = ((1100, 200), (1100, 700), (600, 750), (1550, 700), (1000, 700))
    bright_points = sum(1 for point in dialog_points if min(image.getpixel(point)) >= 215)
    if bright_points >= 4:
        buttons = dialog_button_centers(image)
        if buttons is not None:
            return buttons[0]
        return "unknown"

    # Màn hình DS có bảng trung tâm tối. Chấp nhận cả giao diện xám cũ và tím mới.
    list_points = ((500, 350), (960, 350), (1350, 350), (960, 650), (1500, 650))
    dark_points = sum(1 for point in list_points if max(image.getpixel(point)) <= 190)
    header = image.getpixel((960, 75))
    if dark_points >= 4 and 30 <= max(header) <= 210:
        return "my_list"
    return "unknown"


def dialog_button_centers(
    image: Image.Image,
    expected_state: str | None = None,
) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    """Find action/cancel buttons so vertical UI shifts do not break clicks."""
    image = normalized(image).convert("RGB")
    orange: list[tuple[int, int]] = []
    blue: list[tuple[int, int]] = []
    for x in range(1080, 1401, 4):
        for y in range(780, 941, 4):
            r, g, b = image.getpixel((x, y))
            if r > 180 and 30 < g < 170 and b < 120:
                orange.append((x, y))
            elif b > 160 and g > 80 and r < 130:
                blue.append((x, y))

    candidates: list[tuple[str, list[tuple[int, int]], int]] = [
        ("buy_dialog", orange, 210),
        ("sell_dialog", blue, 205),
    ]
    if expected_state:
        candidates.sort(key=lambda item: item[0] != expected_state)
    for state, pixels, cancel_offset in candidates:
        if len(pixels) < 30:
            continue
        left = min(x for x, _ in pixels)
        right = max(x for x, _ in pixels)
        top = min(y for _, y in pixels)
        bottom = max(y for _, y in pixels)
        action = ((left + right) // 2, (top + bottom) // 2)
        cancel = (action[0] + cancel_offset, action[1])
        return state, action, cancel
    return None


def renew_button_visible(image: Image.Image, row_index: int = 1) -> bool:
    image = normalized(image).convert("RGB")
    dy = (row_index - 1) * 61
    button = image.crop((1440, 252 + dy, 1535, 293 + dy))
    green_pixels = sum(1 for r, g, b in button.getdata() if g > 100 and g > r * 1.4 and g > b * 1.15)
    return green_pixels >= 10


def ocr_region(image: Image.Image, box: tuple[int, int, int, int], tesseract: Path) -> str:
    if hasattr(tesseract, "read_region"):
        return tesseract.read_region(image, box)
    region = image.crop(box)
    region = region.resize((region.width * 4, region.height * 4), Image.Resampling.BICUBIC)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp:
        path = Path(temp.name)
    try:
        region.save(path)
        result = subprocess.run(
            [str(tesseract), str(path), "stdout", "-l", "eng", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        )
        return result.stdout.strip()
    finally:
        path.unlink(missing_ok=True)


class FastOcr:
    """Keep Tesseract loaded between frames to reduce recognition latency."""

    def __init__(self, tesseract_exe: Path) -> None:
        folder = tesseract_exe.parent
        self.dll_directory = os.add_dll_directory(str(folder))
        self.lib = ctypes.CDLL(str(folder / "libtesseract-5.dll"))
        self.lib.TessBaseAPICreate.restype = ctypes.c_void_p
        self.lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.lib.TessBaseAPIInit3.restype = ctypes.c_int
        self.lib.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
        self.lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
        self.lib.TessDeleteText.argtypes = [ctypes.c_void_p]
        self.lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
        self.api = self.lib.TessBaseAPICreate()
        if not self.api or self.lib.TessBaseAPIInit3(self.api, str(folder / "tessdata").encode(), b"eng") != 0:
            raise RuntimeError("Không khởi tạo được Tesseract OCR.")
        self.lib.TessBaseAPISetPageSegMode(self.api, 6)

    def read_region(self, image: Image.Image, box: tuple[int, int, int, int]) -> str:
        region = image.crop(box)
        region = region.resize((region.width * 4, region.height * 4), Image.Resampling.BICUBIC).convert("L")
        pixels = ctypes.create_string_buffer(region.tobytes())
        self.lib.TessBaseAPISetImage(self.api, pixels, region.width, region.height, 1, region.width)
        result = self.lib.TessBaseAPIGetUTF8Text(self.api)
        if not result:
            return ""
        try:
            return ctypes.string_at(result).decode("utf-8", errors="replace").strip()
        finally:
            self.lib.TessDeleteText(result)

    def close(self) -> None:
        if self.api:
            self.lib.TessBaseAPIDelete(self.api)
            self.api = None
        self.dll_directory.close()


def first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def shifted(box: tuple[int, int, int, int], dy: int) -> tuple[int, int, int, int]:
    return box[0], box[1] + dy, box[2], box[3] + dy


def analyze(image: Image.Image, tesseract: Path, row_index: int = 1) -> MarketView:
    image = normalized(image)
    state = state_from_pixels(image, row_index)
    if state == "buy_dialog":
        name = first_line(ocr_region(image, BUY_NAME, tesseract))
        rows = parse_rows(ocr_region(image, BUY_PRICE_TABLE, tesseract))
        min_price = parse_price(ocr_region(image, DIALOG_MIN_PRICE, tesseract))
        max_price = parse_price(ocr_region(image, BUY_MAX_PRICE, tesseract))
        registered_price = parse_price(ocr_region(image, BUY_REGISTERED_PRICE, tesseract))
        buyers = next((row.buyers for row in rows if row.price_bp == max_price and row.buyers > 0), None)
        sellers_min = next((row.sellers for row in rows if row.price_bp == min_price and row.sellers > 0), None)
        sellers_max = next((row.sellers for row in rows if row.price_bp == max_price and row.sellers > 0), None)
        return MarketView(
            state=state,
            player_name=name,
            max_price_bp=max_price,
            registered_price_bp=registered_price,
            price_rows=rows,
            buyers_at_max=buyers,
            min_price_bp=min_price,
            sellers_at_min=sellers_min,
            sellers_at_max=sellers_max,
        )
    if state == "sell_dialog":
        name = first_line(ocr_region(image, SELL_NAME, tesseract))
        rows = parse_rows(ocr_region(image, SELL_PRICE_TABLE, tesseract))
        min_price = parse_price(ocr_region(image, SELL_MIN_PRICE, tesseract))
        max_price = parse_price(ocr_region(image, SELL_MAX_PRICE, tesseract))
        registered_price = parse_price(ocr_region(image, SELL_REGISTERED_PRICE, tesseract))
        buyers = next((row.buyers for row in rows if row.price_bp == max_price and row.buyers > 0), None)
        sellers_min = next((row.sellers for row in rows if row.price_bp == min_price and row.sellers > 0), None)
        sellers_max = next((row.sellers for row in rows if row.price_bp == max_price and row.sellers > 0), None)
        return MarketView(
            state=state,
            player_name=name,
            max_price_bp=max_price,
            registered_price_bp=registered_price,
            price_rows=rows,
            buyers_at_max=buyers,
            min_price_bp=min_price,
            sellers_at_min=sellers_min,
            sellers_at_max=sellers_max,
        )
    if state == "my_list":
        if not 1 <= row_index <= 5:
            raise ValueError("Hàng phải từ 1 đến 5.")
        dy = (row_index - 1) * 61
        name = first_line(ocr_region(image, shifted(LIST_NAME, dy), tesseract))
        registered_price = parse_price(ocr_region(image, shifted(LIST_REGISTERED_PRICE, dy), tesseract))
        return MarketView(state, name, registered_price_bp=registered_price)
    return MarketView(state)
