"""Coordinate based FC Online clicker prototype for Windows."""

from __future__ import annotations

import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image

from engine import Step, run_sequence
from market_bot import OrderTarget, run_market_bot
from vision import FastOcr, analyze, renew_button_visible
from windows import BackgroundGameDesktop, GameDesktop, WindowsDesktop, activate_game, cursor_position, find_game_title, key_down


APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = APP_DIR / "settings.json"
VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11 = 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A


def find_tesseract_exe() -> Path:
    env_path = os.environ.get("TESSERACT_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)
    for candidate in (
        APP_DIR / "Tesseract-OCR" / "tesseract.exe",
        APP_DIR / "tesseract" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ):
        if candidate.exists():
            return candidate
    which_path = shutil.which("tesseract")
    if which_path and Path(which_path).exists():
        return Path(which_path)
    return Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


TESSERACT_EXE = find_tesseract_exe()

MODE_DISPLAY = {
    "BUY": "Chèn mua (Giá trần)",
    "SELL_MIN": "Chèn bán (Giá sàn)",
    "SELL_MAX": "Chèn bán (Giá trần)",
}
MODE_FROM_DISPLAY = {v: k for k, v in MODE_DISPLAY.items()}


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("FC Market Clicker")
        self.root.geometry("770x745")
        self.root.minsize(680, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.desktop = WindowsDesktop()
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self.pending_start: str | None = None
        self.messages: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.previous_keys = {vk: False for vk in (VK_F6, VK_F7, VK_F8, VK_F9, VK_F10, VK_F11)}
        self.steps: list[Step] = []
        self.target = tk.StringVar()
        self.delay = tk.StringVar(value="150")
        self.repeats = tk.StringVar(value="1")
        self.pause = tk.StringVar(value="500")
        self.dry_run = tk.BooleanVar(value=True)
        self.background_mode = tk.BooleanVar(value=False)
        self.player_name = tk.StringVar()
        self.mode_display = tk.StringVar(value=MODE_DISPLAY["BUY"])
        self.row_index = tk.StringVar(value="1")
        self.max_buyers_ahead = tk.StringVar(value="4")
        self.retry_ms = tk.StringVar(value="250")
        self.max_cycles = tk.StringVar(value="1000")
        self.status = tk.StringVar(value="Sẵn sàng. F7 chọn game, F6 ghi điểm bấm.")
        self.build_ui()
        self.load()
        self.choose_window()
        self.root.after(40, self.poll)

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="FC Market Clicker", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(
            main,
            text="F7 chọn game   •   F10 đọc màn hình   •   F11 chạy/dừng   •   F9 dừng ngay",
        ).pack(anchor="w", pady=(3, 12))

        target_row = ttk.Frame(main)
        target_row.pack(fill="x", pady=(0, 8))
        ttk.Label(target_row, text="Cửa sổ FC Online:").pack(side="left")
        ttk.Entry(target_row, textvariable=self.target).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(target_row, text="Tìm FC Online", command=self.choose_window).pack(side="left")

        notebook = ttk.Notebook(main)
        notebook.pack(fill="both", expand=True)
        market = ttk.Frame(notebook, padding=14)
        manual = ttk.Frame(notebook, padding=14)
        notebook.add(market, text="Tự động Chèn Mua / Bán")
        notebook.add(manual, text="Click thủ công")

        ttk.Label(
            market,
            text="Tự động canh hàng, chọn giá tối ưu (sàn/trần) và đặt lệnh. Đạt điều kiện số lượng xếp hàng ≤ giới hạn: Hủy và hoàn thành.",
            wraplength=680,
        ).pack(anchor="w", pady=(0, 16))
        form = ttk.LabelFrame(market, text="Cấu hình lệnh TTCN", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Chế độ hoạt động").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=self.mode_display, values=tuple(MODE_DISPLAY.values()), width=24, state="readonly").grid(row=0, column=1, sticky="w", padx=10, pady=6)
        ttk.Label(form, text="Tên cầu thủ (khuyên dùng để chống nhầm hàng)").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.player_name).grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ttk.Label(form, text="Hàng trong DS của bạn").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=self.row_index, values=("1", "2", "3", "4", "5"), width=6, state="readonly").grid(row=2, column=1, sticky="w", padx=10, pady=6)
        ttk.Label(form, text="Số lệnh xếp hàng phía trước tối đa (để dừng)").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(form, textvariable=self.max_buyers_ahead, values=("0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"), width=6, state="readonly").grid(row=3, column=1, sticky="w", padx=10, pady=6)
        ttk.Label(form, text="Nghỉ giữa các lần (ms)").grid(row=4, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.retry_ms, width=10).grid(row=4, column=1, sticky="w", padx=10, pady=6)
        ttk.Label(form, text="Số lần kiểm tra tối đa").grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(form, textvariable=self.max_cycles, width=10).grid(row=5, column=1, sticky="w", padx=10, pady=6)

        market_actions = ttk.Frame(market)
        market_actions.pack(fill="x", pady=16)
        ttk.Button(market_actions, text="Phân tích ảnh mẫu", command=self.inspect_file).pack(side="left")
        ttk.Button(market_actions, text="Bắt đầu chạy (F11)", command=self.start_market).pack(side="left", padx=8)
        ttk.Button(market_actions, text="Kiểm tra màn hình game", command=self.inspect_live).pack(side="left", padx=(0, 8))
        ttk.Button(market_actions, text="Dừng", command=self.stop_clicking).pack(side="left")

        ttk.Label(manual, text="F6 ghi vị trí chuột trên game. F8 chạy hoặc dừng chuỗi bấm đã lưu.").pack(anchor="w", pady=(0, 10))
        grid = ttk.Frame(manual)
        grid.pack(fill="both", expand=True)
        self.table = ttk.Treeview(grid, columns=("number", "x", "y", "delay"), show="headings", height=8)
        for key, label, width in (
            ("number", "Bước", 70), ("x", "X", 110), ("y", "Y", 110), ("delay", "Chờ sau bấm (ms)", 160)
        ):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, anchor="center")
        self.table.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(grid, orient="vertical", command=self.table.yview).pack(side="right", fill="y")

        edit = ttk.Frame(manual)
        edit.pack(fill="x", pady=8)
        ttk.Label(edit, text="Chờ sau mỗi điểm (ms):").pack(side="left")
        ttk.Entry(edit, textvariable=self.delay, width=8).pack(side="left", padx=6)
        ttk.Button(edit, text="Xóa điểm chọn", command=self.remove_step).pack(side="left", padx=8)
        ttk.Button(edit, text="Xóa tất cả", command=self.clear_steps).pack(side="left")

        options = ttk.Frame(manual)
        options.pack(fill="x", pady=(3, 8))
        ttk.Label(options, text="Số lần chạy:").pack(side="left")
        ttk.Entry(options, textvariable=self.repeats, width=7).pack(side="left", padx=(5, 15))
        ttk.Label(options, text="Nghỉ giữa các lần (ms):").pack(side="left")
        ttk.Entry(options, textvariable=self.pause, width=8).pack(side="left", padx=5)
        actions = ttk.Frame(manual)
        actions.pack(fill="x", pady=(0, 7))
        ttk.Button(actions, text="Bắt đầu sau 5 giây", command=self.start_delayed).pack(side="left")
        ttk.Button(actions, text="Dừng", command=self.stop_clicking).pack(side="left", padx=8)

        common = ttk.Frame(main)
        common.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(common, text="Mô phỏng, không bấm thật", variable=self.dry_run).pack(side="left")
        ttk.Checkbutton(common, text="Chạy nền, không chiếm chuột (thử nghiệm)", variable=self.background_mode).pack(side="left", padx=12)
        ttk.Button(common, text="Lưu cấu hình", command=self.save).pack(side="right")
        ttk.Label(main, textvariable=self.status, foreground="#095b97", wraplength=710).pack(anchor="w", pady=(8, 0))

        self.log = tk.Text(main, height=6, wrap="word", state="disabled")
        self.log.pack(fill="x", pady=(7, 0))

    def refresh_steps(self) -> None:
        self.table.delete(*self.table.get_children())
        for i, step in enumerate(self.steps, 1):
            self.table.insert("", "end", values=(i, step.x, step.y, step.delay_ms))

    def add_step(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            delay = int(self.delay.get())
            if not 0 <= delay <= 60000:
                raise ValueError
        except ValueError:
            messagebox.showerror("Thời gian", "Nhập thời gian chờ từ 0 đến 60000 ms.")
            return
        x, y = cursor_position()
        self.steps.append(Step(x, y, delay))
        self.refresh_steps()
        self.status.set(f"Đã lưu điểm {len(self.steps)}: ({x}, {y}).")

    def remove_step(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        selected = self.table.selection()
        if selected:
            index = self.table.index(selected[0])
            self.steps.pop(index)
            self.refresh_steps()

    def clear_steps(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.steps.clear()
        self.refresh_steps()

    def start_delayed(self) -> None:
        if self.pending_start is not None:
            self.root.after_cancel(self.pending_start)
        self.status.set("Chuyển sang FC Online; bắt đầu sau 5 giây...")
        self.pending_start = self.root.after(5000, self.start_after_delay)

    def start_after_delay(self) -> None:
        self.pending_start = None
        self.start()

    def start(self) -> None:
        if self.pending_start is not None:
            self.root.after_cancel(self.pending_start)
            self.pending_start = None
        if self.worker and self.worker.is_alive():
            return
        try:
            repeats = int(self.repeats.get())
            pause = int(self.pause.get())
            if not self.steps or not self.target.get().strip() or not 1 <= repeats <= 10000 or not 0 <= pause <= 60000:
                raise ValueError
        except ValueError:
            self.status.set("Cần chọn cửa sổ, ghi ít nhất một điểm và nhập số lần/thời gian hợp lệ.")
            return
        self.stop = threading.Event()
        steps = list(self.steps)
        target = self.target.get().strip()
        dry_run = self.dry_run.get()
        self.worker = threading.Thread(
            target=self.run_worker,
            args=(steps, target, repeats, pause, dry_run, self.stop),
            daemon=True,
        )
        self.worker.start()
        self.status.set("Đang mô phỏng..." if dry_run else "Đang bấm thật...")

    def run_worker(self, steps: list[Step], target: str, repeats: int, pause: int, dry_run: bool, stop: threading.Event) -> None:
        try:
            run_sequence(self.desktop, steps, target, repeats, pause, dry_run, stop, self.messages.put)
        except Exception as exc:
            self.messages.put(f"Lỗi: {exc}")
        finally:
            self.messages.put("__FINISHED__")

    def stop_clicking(self) -> None:
        if self.pending_start is not None:
            self.root.after_cancel(self.pending_start)
            self.pending_start = None
        self.stop.set()
        self.status.set("Đã yêu cầu dừng.")

    def start_market_delayed(self) -> None:
        if self.pending_start is not None:
            self.root.after_cancel(self.pending_start)
        self.status.set("Chuyển sang FC Online; bắt đầu chèn sau 5 giây...")
        self.pending_start = self.root.after(5000, self.start_market_after_delay)

    def start_market_after_delay(self) -> None:
        self.pending_start = None
        self.start_market()

    def start_market(self) -> None:
        if self.pending_start is not None:
            self.root.after_cancel(self.pending_start)
            self.pending_start = None
        if self.worker and self.worker.is_alive():
            return
        try:
            mode = MODE_FROM_DISPLAY.get(self.mode_display.get(), "BUY")
            target = OrderTarget(
                player_name=self.player_name.get().strip(),
                row_index=int(self.row_index.get()),
                max_buyers_ahead=int(self.max_buyers_ahead.get()),
                retry_ms=int(self.retry_ms.get()),
                max_cycles=int(self.max_cycles.get()),
                mode=mode,
            )
            if not self.target.get().strip() or not TESSERACT_EXE.exists():
                raise ValueError
        except ValueError:
            self.status.set("Chọn cửa sổ FC ONLINE và kiểm tra Tesseract OCR.")
            return
        background_mode = self.background_mode.get()
        if not background_mode and not activate_game(self.target.get().strip()):
            self.status.set("Không thể đưa FC Online ra trước. Hãy mở game rồi thử lại.")
            return
        self.stop = threading.Event()
        self.worker = threading.Thread(
            target=self.run_market_worker,
            args=(self.target.get().strip(), target, self.dry_run.get(), background_mode, self.stop),
            daemon=True,
        )
        self.worker.start()
        self.status.set("Đang đọc màn hình và kiểm tra điều kiện...")

    def run_market_worker(self, title: str, target: OrderTarget, dry_run: bool, background_mode: bool, stop: threading.Event) -> None:
        ocr = None
        try:
            ocr = FastOcr(TESSERACT_EXE)
            desktop = BackgroundGameDesktop(title) if background_mode else GameDesktop(title)
            run_market_bot(desktop, ocr, target, stop, self.messages.put, dry_run)
        except Exception as exc:
            self.messages.put(f"Lỗi: {exc}")
        finally:
            if ocr is not None:
                ocr.close()
            self.messages.put("__FINISHED__")

    def inspect_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        try:
            with Image.open(path) as image:
                ocr = FastOcr(TESSERACT_EXE)
                try:
                    view = analyze(image, ocr, int(self.row_index.get()))
                finally:
                    ocr.close()
            self.messages.put(f"Ảnh: {view}")
        except Exception as exc:
            self.messages.put(f"Không phân tích được ảnh: {exc}")

    def inspect_live(self) -> None:
        if self.worker and self.worker.is_alive():
            self.status.set("Hãy dừng lượt đang chạy trước khi kiểm tra màn hình.")
            return
        if not self.target.get().strip():
            self.status.set("Bấm 'Tìm FC Online' để chọn cửa sổ game.")
            return
        background_mode = self.background_mode.get()
        if not background_mode and not activate_game(self.target.get().strip()):
            self.status.set("Không thể đưa FC Online ra trước để đọc màn hình.")
            return
        self.worker = threading.Thread(
            target=self.inspect_live_worker,
            args=(self.target.get().strip(), int(self.row_index.get()), background_mode),
            daemon=True,
        )
        self.worker.start()

    def inspect_live_worker(self, title: str, row_index: int, background_mode: bool) -> None:
        ocr = None
        try:
            ocr = FastOcr(TESSERACT_EXE)
            desktop = BackgroundGameDesktop(title) if background_mode else GameDesktop(title)
            left, top, right, bottom = desktop.viewport_box()
            self.messages.put(f"Vùng game đã crop: {right - left} × {bottom - top}, góc ({left}, {top}).")
            image = desktop.screenshot()
            view = analyze(image, ocr, row_index)
            self.messages.put(f"Màn hình game: {view}")
            if view.state == "my_list":
                visible = renew_button_visible(image, row_index)
                if not visible:
                    desktop.move_ref(1487, 273 + (row_index - 1) * 61)
                    threading.Event().wait(0.15)
                    visible = renew_button_visible(desktop.screenshot(), row_index)
                self.messages.put(f"Nút Đăng ký lại tại hàng {row_index}: {'đã hiện' if visible else 'chưa hiện'}.")
        except Exception as exc:
            self.messages.put(f"Không đọc được màn hình game: {exc}")
        finally:
            if ocr is not None:
                ocr.close()
            if not background_mode:
                self.messages.put("__RETURN_TO_APP__")
            self.messages.put("__FINISHED__")

    def poll(self) -> None:
        for vk, action in ((VK_F6, self.add_step), (VK_F7, self.choose_window), (VK_F8, self.toggle), (VK_F9, self.stop_clicking), (VK_F10, self.inspect_live), (VK_F11, self.toggle_market)):
            pressed = key_down(vk)
            if pressed and not self.previous_keys[vk]:
                action()
            self.previous_keys[vk] = pressed
        while not self.messages.empty():
            message = self.messages.get_nowait()
            if message == "__FINISHED__":
                if self.status.get().startswith("Đang"):
                    self.status.set("Đã kết thúc lượt chạy. F11 để chạy lại.")
            elif message == "__RETURN_TO_APP__":
                self.root.lift()
                self.root.focus_force()
            else:
                if message.startswith(("Hoàn thành:", "Đã dừng:", "Lỗi chèn mua:", "Lỗi:")):
                    self.status.set(message)
                self.log.configure(state="normal")
                self.log.insert("end", message + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        self.root.after(40, self.poll)

    def choose_window(self) -> None:
        title = find_game_title()
        if title:
            self.target.set(title)
            self.status.set(f"Đã chọn cửa sổ: {title}")
        else:
            self.status.set("Chưa tìm thấy cửa sổ FC ONLINE. Mở game rồi bấm 'Tìm FC Online'.")

    def toggle(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_clicking()
        else:
            self.start()

    def toggle_market(self) -> None:
        if self.worker and self.worker.is_alive():
            self.stop_clicking()
        else:
            self.start_market()

    def save(self) -> None:
        payload = {
            "mode": MODE_FROM_DISPLAY.get(self.mode_display.get(), "BUY"),
            "target": self.target.get(),
            "steps": [step.__dict__ for step in self.steps],
            "delay": self.delay.get(),
            "repeats": self.repeats.get(),
            "pause": self.pause.get(),
            "dry_run": self.dry_run.get(),
            "background_mode": self.background_mode.get(),
            "player_name": self.player_name.get(),
            "row_index": self.row_index.get(),
            "max_buyers_ahead": self.max_buyers_ahead.get(),
            "retry_ms": self.retry_ms.get(),
            "max_cycles": self.max_cycles.get(),
        }
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.set(f"Đã lưu cấu hình: {CONFIG_PATH}")

    def load(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            saved_mode = str(payload.get("mode", "BUY"))
            self.mode_display.set(MODE_DISPLAY.get(saved_mode, MODE_DISPLAY["BUY"]))
            self.target.set(str(payload.get("target", "")))
            self.steps = [Step(**item) for item in payload.get("steps", [])]
            self.delay.set(str(payload.get("delay", "150")))
            self.repeats.set(str(payload.get("repeats", "1")))
            self.pause.set(str(payload.get("pause", "500")))
            self.dry_run.set(bool(payload.get("dry_run", True)))
            self.background_mode.set(bool(payload.get("background_mode", False)))
            self.player_name.set(str(payload.get("player_name", "")))
            self.row_index.set(str(payload.get("row_index", "1")))
            self.max_buyers_ahead.set(str(payload.get("max_buyers_ahead", "4")))
            self.retry_ms.set(str(payload.get("retry_ms", "100")))
            self.max_cycles.set(str(payload.get("max_cycles", "1000")))
            self.refresh_steps()
        except (ValueError, TypeError, KeyError) as exc:
            self.status.set(f"Không đọc được cấu hình cũ: {exc}")

    def close(self) -> None:
        self.stop.set()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
