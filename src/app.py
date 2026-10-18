from __future__ import annotations

import calendar
import os
import queue
import threading
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from database import Account, ChatSummary, date_bounds, scan_account
from exporter import export_chat
from key_scan import extract_candidates

CJK_FONT = "仿宋"
LATIN_FONT = "Times New Roman"


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "—"


class PillButton(tk.Canvas):
    RENDER_SCALE = 4
    FONT_CACHE = {}
    PALETTES = {
        "primary": ("#246BCE", "#2F7FE6", "#1D5BAC", "#246BCE", "#FFFFFF", "#151515"),
        "secondary": ("#2B2B2B", "#353535", "#424242", "#3B3B3B", "#E8E8E8", "#151515"),
        "soft": ("#202020", "#2D2D2D", "#3A3A3A", "#303030", "#B7B7B7", "#151515"),
    }

    def __init__(self, master, text: str, command, *, width=110, height=44, style="secondary", background="#242424"):
        self.label = text
        self.command = command
        self.button_width = width
        self.button_height = height
        self.variant = style
        self.selected = False
        self.enabled = True
        self.hovered = False
        self.pressed = False
        self.focused = False
        self.scale = 1.0
        super().__init__(master, width=width, height=height, background=background, highlightthickness=0, bd=0, takefocus=True, cursor="hand2")
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", lambda _event: self._set_focus(True))
        self.bind("<FocusOut>", lambda _event: self._set_focus(False))
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)
        self._draw()

    def set_text(self, text: str):
        self.label = text
        self._draw()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_selected(self, selected: bool):
        self.selected = selected
        self._draw()

    def _set_focus(self, focused: bool):
        self.focused = focused
        self._draw()

    def _on_enter(self, _event):
        self.hovered = True
        self._draw()

    def _on_leave(self, _event):
        self.hovered = False
        self._draw()

    def _on_press(self, _event):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self.scale = 0.95
            self._draw()

    def _on_release(self, event):
        invoke = self.enabled and self.pressed and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self.pressed = False
        if invoke:
            self._animate_click()
        else:
            self.scale = 1.0
            self._draw()

    def _on_key(self, _event):
        if self.enabled:
            self._animate_click()
        return "break"

    def _animate_click(self):
        self.pressed = True
        self.scale = 0.95
        self._draw()
        self.after(40, self._invoke)
        self.after(55, self._bounce)

    def _bounce(self):
        self.pressed = False
        self.scale = 1.03
        self._draw()
        self.after(75, self._reset_scale)

    def _reset_scale(self):
        self.scale = 1.0
        self._draw()

    def _invoke(self):
        if self.enabled:
            self.command()

    def _draw(self):
        self.delete("all")
        width = max(self.button_width, self.winfo_width())
        height = max(self.button_height, self.winfo_height())
        body_height = min(44, height - 8) * self.scale
        body_width = max(body_height, width - 6) * self.scale
        x1, x2 = (width - body_width) / 2, (width + body_width) / 2
        center_y = (height - 2) / 2
        y1, y2 = center_y - body_height / 2, center_y + body_height / 2
        palette = self.PALETTES["primary"] if self.selected else self.PALETTES[self.variant]
        base, hover, down, border, foreground, shadow = palette
        if not self.enabled:
            base, hover, down, border, foreground, shadow = "#303030", "#303030", "#303030", "#303030", "#777777", "#151515"
        fill = down if self.pressed else hover if self.hovered else base
        edge = "#78A9F8" if self.focused and self.enabled else border
        factor = self.RENDER_SCALE
        image = Image.new("RGBA", (width * factor, height * factor), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        def rect(y_offset=0):
            return tuple(round(value * factor) for value in (x1, y1 + y_offset, x2, y2 + y_offset))

        draw.rounded_rectangle(rect(2), radius=round(body_height * factor / 2), fill=shadow)
        draw.rounded_rectangle(
            rect(), radius=round(body_height * factor / 2), fill=fill, outline=edge,
            width=(2 if self.focused else 1) * factor,
        )
        cjk = any("\u4e00" <= char <= "\u9fff" for char in self.label)
        font_name = "simfang.ttf" if cjk else "timesbd.ttf"
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / font_name
        font_size = round(16 * factor)
        font_key = (str(font_path), font_size)
        font = self.FONT_CACHE.get(font_key)
        if font is None:
            font = ImageFont.truetype(str(font_path), font_size)
            self.FONT_CACHE[font_key] = font
        draw.text((width * factor / 2, center_y * factor), self.label, fill=foreground, font=font, anchor="mm")
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        self._image = ImageTk.PhotoImage(image)
        self.create_image(0, 0, anchor="nw", image=self._image)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("微信聊天记录导出器 0.1.0")
        self.root.geometry("1240x860")
        self.root.minsize(1040, 700)
        self.colors = {
            "background": "#1A1A1A", "card": "#222222", "heading": "#ECECEC",
            "muted": "#9B9B9B", "border": "#343434", "blue": "#83B3FF",
        }
        self._configure_theme()
        self.events: queue.Queue = queue.Queue()
        self.account: Account | None = None
        self.all_chats: list[ChatSummary] = []
        self.scan_enabled = True
        self.worker_running = False
        self.busy = False

        default_db = Path.home() / "Documents" / "xwechat_files"
        self.db_folder = tk.StringVar(value=str(default_db) if default_db.exists() else "")
        self.export_folder = tk.StringVar(value=str(Path.home() / "Documents" / "微信聊天记录导出"))
        self.search = tk.StringVar()
        self.start_date = tk.StringVar()
        self.end_date = tk.StringVar()
        self.export_formats = {"TXT": tk.BooleanVar(value=True), "PDF": tk.BooleanVar(value=False)}
        self.format_buttons: dict[str, PillButton] = {}
        self.include_images = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="请打开并登录微信。程序正在检测密钥；检测成功后会自动加载聊天列表。")

        self._build()
        self.search.trace_add("write", lambda *_: self._render_chats())
        self.root.after(100, self._scan_cycle)
        self.root.after(150, self._drain_events)

    def _configure_theme(self):
        self.root.configure(background=self.colors["background"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=self.colors["background"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="solid", borderwidth=1, bordercolor=self.colors["border"], lightcolor=self.colors["border"], darkcolor=self.colors["border"])
        style.configure("TLabel", background=self.colors["background"], foreground=self.colors["heading"], font=(CJK_FONT, 11))
        style.configure("Title.TLabel", font=(CJK_FONT, 20, "bold"), foreground=self.colors["heading"])
        style.configure("Subtitle.TLabel", font=(CJK_FONT, 11), foreground=self.colors["muted"])
        style.configure("Section.TLabel", background=self.colors["card"], font=(CJK_FONT, 14, "bold"), foreground=self.colors["heading"])
        style.configure("Muted.TLabel", background=self.colors["card"], font=(CJK_FONT, 11), foreground=self.colors["muted"])
        style.configure("Latin.TLabel", background=self.colors["card"], foreground=self.colors["muted"], font=(LATIN_FONT, 11))
        style.configure("Badge.TLabel", background="#2A2A2A", foreground=self.colors["blue"], font=(CJK_FONT, 11, "bold"), padding=(11, 6))
        style.configure("Status.TFrame", background="#202A37", relief="flat")
        style.configure("Status.TLabel", background="#202A37", foreground="#BFD7F5", font=(CJK_FONT, 11))
        style.configure("TEntry", fieldbackground="#1D1D1D", foreground="#E8E8E8", padding=(9, 7), bordercolor="#383838", lightcolor="#383838", darkcolor="#383838", font=(CJK_FONT, 12))
        style.configure("Latin.TEntry", font=(LATIN_FONT, 12))
        style.map("TEntry", fieldbackground=[("focus", "#222222")], foreground=[("disabled", "#777777")], bordercolor=[("focus", "#3478D4")])
        style.configure("TCheckbutton", background=self.colors["card"], foreground="#BDBDBD", focuscolor=self.colors["card"], font=(CJK_FONT, 11))
        style.map("TCheckbutton", background=[("active", self.colors["card"])], foreground=[("disabled", "#707070")])
        style.configure("TRadiobutton", background=self.colors["card"], foreground="#BDBDBD", focuscolor=self.colors["card"], font=(CJK_FONT, 11))
        style.map("TRadiobutton", background=[("active", self.colors["card"])], foreground=[("disabled", "#707070")])
        style.configure("Chat.Treeview", background="#1F1F1F", fieldbackground="#1F1F1F", foreground="#E5E5E5", rowheight=40, borderwidth=0, font=(LATIN_FONT, 12))
        style.configure("Chat.Treeview.Heading", background="#262626", foreground="#AFAFAF", relief="flat", padding=(10, 10), font=(CJK_FONT, 11, "bold"))
        style.map("Chat.Treeview", background=[("selected", "#29466C")], foreground=[("selected", "#F4F4F4")])
        style.map("Chat.Treeview.Heading", background=[("active", "#303030")])
        style.configure("Dark.Vertical.TScrollbar", background="#3A3A3A", darkcolor="#3A3A3A", lightcolor="#3A3A3A", bordercolor=self.colors["background"], troughcolor=self.colors["background"], arrowcolor="#888888", relief="flat", width=9, arrowsize=10)
        style.map("Dark.Vertical.TScrollbar", background=[("pressed", "#696969"), ("active", "#555555")], arrowcolor=[("active", "#C4C4C4")])

    def _build(self):
        outer = ttk.Frame(self.root, style="App.TFrame", padding=22)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        logo = tk.Canvas(header, width=46, height=46, background=self.colors["background"], highlightthickness=0)
        logo.create_oval(3, 3, 43, 43, fill="#2D2D2D", outline="#383838")
        logo.create_text(23, 23, text="✦", fill="#9BC3FF", font=(CJK_FONT, 19))
        logo.pack(side="left", padx=(0, 12))
        heading = ttk.Frame(header, style="App.TFrame")
        heading.pack(side="left", anchor="center")
        ttk.Label(heading, text="微信聊天记录导出器", style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text="本地读取 · 原始数据库只读 · 密钥仅在本次运行使用", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(header, text="本地 · 只读", style="Badge.TLabel").pack(side="right", anchor="center")

        path_card = ttk.Frame(outer, style="Card.TFrame", padding=(12, 8))
        path_card.pack(fill="x", pady=(0, 14))
        path_row = ttk.Frame(path_card, style="Card.TFrame")
        path_row.pack(fill="x")
        ttk.Label(path_row, text="微信数据目录", style="Section.TLabel").pack(side="left", padx=(0, 12))
        self.db_entry = ttk.Entry(path_row, textvariable=self.db_folder, state="readonly", style="Latin.TEntry")
        self.db_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.browse_db_button = PillButton(path_row, "浏览目录", self._browse_db, width=100, style="secondary")
        self.browse_db_button.pack(side="left")
        reference_path = ttk.Frame(path_card, style="Card.TFrame")
        reference_path.pack(fill="x", pady=(5, 0))
        ttk.Label(reference_path, text="默认路径参考：", style="Muted.TLabel").pack(side="left")
        ttk.Label(reference_path, text=r"C:\Users\<用户名>\Documents\xwechat_files", style="Latin.TLabel").pack(side="left")
        list_header = ttk.Frame(outer, style="App.TFrame")
        list_header.pack(fill="x", pady=(0, 8))
        ttk.Label(list_header, text="聊天列表", style="Title.TLabel", font=(CJK_FONT, 15, "bold")).pack(side="left")
        self.chat_count = ttk.Label(list_header, text="尚未加载聊天列表", style="Subtitle.TLabel")
        self.chat_count.pack(side="left", padx=(10, 0), pady=(3, 0))
        ttk.Label(list_header, text="搜索联系人").pack(side="right", padx=(8, 0))
        ttk.Entry(list_header, textvariable=self.search, width=25).pack(side="right")
        self.select_visible_button = PillButton(list_header, "全选当前结果", self._select_visible, width=120, height=42, style="secondary", background=self.colors["background"])
        self.select_visible_button.pack(side="right", padx=(10, 0))
        self.clear_selection_button = PillButton(list_header, "清除选择", lambda: self.tree.selection_remove(self.tree.selection()), width=94, height=42, style="soft", background=self.colors["background"])
        self.clear_selection_button.pack(side="right", padx=(8, 0))

        list_card = ttk.Frame(outer, style="Card.TFrame", padding=8)
        list_card.pack(fill="both", expand=True)
        columns = ("contact", "wechat_id", "first", "last", "count")
        list_frame = ttk.Frame(list_card, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended", height=2, style="Chat.Treeview")
        self.tree.tag_configure("cjk", font=(CJK_FONT, 12))
        for key, label, width in (
            ("contact", "联系人", 360), ("wechat_id", "微信号 / ID", 275),
            ("first", "最早消息", 125), ("last", "最近消息", 125), ("count", "消息条数", 100),
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60, anchor="w" if key != "count" else "e")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", style="Dark.Vertical.TScrollbar", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        export = ttk.Frame(outer, style="Card.TFrame", padding=12)
        export.pack(side="bottom", fill="x", pady=(10, 8))
        ttk.Label(export, text="导出设置", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        date_row = ttk.Frame(export, style="Card.TFrame")
        date_row.pack(fill="x", pady=(0, 4))
        ttk.Label(date_row, text="日期范围", style="Muted.TLabel", width=10).pack(side="left")
        self.start_date_button = PillButton(date_row, "不限", lambda: self._open_date_picker(self.start_date, self.start_date_button, "选择开始日期"), width=122, style="secondary")
        self.start_date_button.pack(side="left", padx=(6, 12))
        ttk.Label(date_row, text="至", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.end_date_button = PillButton(date_row, "不限", lambda: self._open_date_picker(self.end_date, self.end_date_button, "选择结束日期"), width=122, style="secondary")
        self.end_date_button.pack(side="left", padx=(0, 12))
        ttk.Label(date_row, text="不限表示不筛选日期", style="Muted.TLabel").pack(side="left")

        format_row = ttk.Frame(export, style="Card.TFrame")
        format_row.pack(fill="x", pady=(0, 6))
        ttk.Label(format_row, text="格式与内容", style="Muted.TLabel", width=10).pack(side="left")
        for fmt, label, width in (("TXT", "TXT 纯文本", 142), ("PDF", "PDF 文档", 126)):
            button = PillButton(format_row, label, lambda name=fmt: self._toggle_export_format(name), width=width, height=54, style="secondary", background=self.colors["card"])
            button.set_selected(self.export_formats[fmt].get())
            button.pack(side="left", padx=(6, 6))
            self.format_buttons[fmt] = button
        self.images_button = PillButton(format_row, "PDF 图片位置标记", self._toggle_images, width=184, height=54, style="secondary", background=self.colors["card"])
        self.images_button.set_selected(self.include_images.get())
        self.images_button.pack(side="left", padx=(0, 10))
        ttk.Label(format_row, text="可多选同时导出，默认 TXT；图片标记仅用于 PDF", style="Muted.TLabel").pack(side="left")

        output_row = ttk.Frame(export, style="Card.TFrame")
        output_row.pack(fill="x")
        ttk.Label(output_row, text="保存位置", style="Muted.TLabel", width=10).pack(side="left")
        ttk.Entry(output_row, textvariable=self.export_folder).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.browse_output_button = PillButton(output_row, "浏览目录", self._browse_output, width=100, style="secondary")
        self.browse_output_button.pack(side="left", padx=(8, 0))
        self.export_button = PillButton(output_row, "导出所选联系人", self._export, width=174, height=54, style="primary")
        self.export_button.pack(side="left", padx=(10, 0))

        status_frame = ttk.Frame(outer, style="Status.TFrame", padding=(12, 8))
        status_frame.pack(side="bottom", fill="x")
        ttk.Label(status_frame, textvariable=self.status, style="Status.TLabel", wraplength=950).pack(anchor="w")
        self.root.update_idletasks()
        self.root.minsize(max(1040, self.root.winfo_reqwidth()), max(700, self.root.winfo_reqheight()))

    def _browse_db(self):
        path = filedialog.askdirectory(title="选择微信数据目录", initialdir=self.db_folder.get() or str(Path.home()))
        if path:
            self.db_folder.set(path)
            self.account = None
            self.all_chats = []
            self._render_chats()
            self.scan_enabled = True
            self._launch_scan()

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择导出目录", initialdir=self.export_folder.get() or str(Path.home()))
        if path:
            self.export_folder.set(path)

    def _toggle_export_format(self, fmt: str):
        selected = not self.export_formats[fmt].get()
        self.export_formats[fmt].set(selected)
        self.format_buttons[fmt].set_selected(selected)

    def _toggle_images(self):
        selected = not self.include_images.get()
        self.include_images.set(selected)
        self.images_button.set_selected(selected)

    def _open_date_picker(self, value: tk.StringVar, button: PillButton, title: str):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.transient(self.root)
        popup.resizable(False, False)
        popup.configure(background=self.colors["background"])
        selected = value.get().strip()
        selected_date = date.fromisoformat(selected) if selected else None
        shown = [selected_date.replace(day=1) if selected_date else date.today().replace(day=1)]

        header = ttk.Frame(popup, style="App.TFrame", padding=(10, 10, 10, 6))
        header.pack(fill="x")
        previous = PillButton(header, "上月", lambda: change_month(-1), width=74, height=40, style="soft", background=self.colors["background"])
        previous.pack(side="left")
        month_label = ttk.Label(header, width=14, anchor="center")
        month_label.pack(side="left", padx=8)
        following = PillButton(header, "下月", lambda: change_month(1), width=74, height=40, style="soft", background=self.colors["background"])
        following.pack(side="left")

        weekdays = ttk.Frame(popup, style="App.TFrame", padding=(10, 0, 10, 0))
        weekdays.pack(fill="x")
        for index, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            ttk.Label(weekdays, text=name, width=4, anchor="center", style="Subtitle.TLabel").grid(row=0, column=index, padx=1, pady=2)
        days = ttk.Frame(popup, style="App.TFrame", padding=(10, 0, 10, 6))
        days.pack()

        def render_month():
            month_label.configure(text=f"{shown[0].year}年 {shown[0].month}月")
            previous.set_enabled((shown[0].year, shown[0].month) != (1, 1))
            following.set_enabled((shown[0].year, shown[0].month) != (9999, 12))
            for child in days.winfo_children():
                child.destroy()
            for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(shown[0].year, shown[0].month)):
                for column, day in enumerate(week):
                    if day:
                        is_selected = selected_date == date(shown[0].year, shown[0].month, day)
                        day_button = PillButton(days, str(day), lambda d=day: choose_date(d), width=38, height=36, style="primary" if is_selected else "secondary")
                        day_button.grid(row=row, column=column, padx=1, pady=1)

        def change_month(delta: int):
            month_index = shown[0].year * 12 + shown[0].month - 1 + delta
            year, month_zero = divmod(month_index, 12)
            if 1 <= year <= 9999:
                shown[0] = date(year, month_zero + 1, 1)
                render_month()

        def choose_date(day: int):
            selected_day = shown[0].replace(day=day)
            value.set(selected_day.isoformat())
            button.set_text(value.get())
            popup.destroy()

        def clear_date():
            value.set("")
            button.set_text("不限")
            popup.destroy()

        render_month()
        actions = ttk.Frame(popup, style="App.TFrame", padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        PillButton(actions, "清除日期（不限）", clear_date, width=150, height=40, style="secondary", background=self.colors["background"]).pack(side="left")
        PillButton(actions, "取消", popup.destroy, width=78, height=40, style="soft", background=self.colors["background"]).pack(side="right")
        popup.grab_set()

    def _scan_cycle(self):
        if self.scan_enabled and not self.account:
            self._launch_scan()

    def _launch_scan(self):
        if self.worker_running or not self.scan_enabled or self.account:
            return
        self.worker_running = True
        self.db_entry.configure(state="disabled")
        self.browse_db_button.set_enabled(False)
        folder = self.db_folder.get().strip()

        def status(text):
            self.events.put(("status", text))

        def work():
            try:
                if not folder or not Path(folder).exists():
                    raise RuntimeError("请先选择微信数据目录。")
                self.events.put(("status", "正在只读扫描微信进程内存中的密钥配置……"))
                candidates = extract_candidates(status)
                self.events.put(("status", f"找到 {len(candidates)} 个候选密钥，正在校验联系人库和全部消息分片……"))
                account = scan_account(folder, candidates, status)
                self.events.put(("loaded", account))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("scan_done", None))

        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.set(value)
                elif kind == "error":
                    self.status.set(value)
                elif kind == "loaded":
                    self.account = value
                    self.all_chats = value.chats
                    self._render_chats()
                    self.scan_enabled = False
                    self.status.set(f"密钥已通过验证；已加载 {len(value.chats):,} 个有消息的会话。密钥不会写入磁盘。")
                elif kind == "scan_done":
                    self.worker_running = False
                    self.db_entry.configure(state="readonly")
                    self.browse_db_button.set_enabled(True)
                    if self.scan_enabled and not self.account:
                        self.root.after(8000, self._scan_cycle)
                elif kind == "export_status":
                    self.status.set(value)
                elif kind == "export_done":
                    self.busy = False
                    self.export_button.set_enabled(True)
                    paths, total = value
                    self.status.set(f"导出完成：{len(paths)} 个文件，共写入 {total:,} 条消息记录（多种格式分别计数）。")
                    messagebox.showinfo("导出完成", "已保存文件：\n" + "\n".join(str(path) for path in paths[:8]))
                elif kind == "export_error":
                    self.busy = False
                    self.export_button.set_enabled(True)
                    self.status.set(value)
                    messagebox.showerror("导出失败", value)
        except queue.Empty:
            pass
        self.root.after(150, self._drain_events)

    def _render_chats(self):
        if not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        needle = self.search.get().strip().casefold()
        visible = 0
        for index, chat in enumerate(self.all_chats):
            searchable = " ".join((chat.remark, chat.nickname, chat.alias, chat.username)).casefold()
            if needle and needle not in searchable:
                continue
            contact_name = self._contact_name(chat)
            tags = ("cjk",) if any("\u4e00" <= char <= "\u9fff" for char in contact_name) else ()
            self.tree.insert("", "end", iid=str(index), values=(
                contact_name, chat.alias or chat.username,
                _date(chat.first_ts), _date(chat.last_ts), f"{chat.count:,}",
            ), tags=tags)
            visible += 1
        self.chat_count.configure(text=f"显示 {visible:,} / {len(self.all_chats):,} 个会话")

    @staticmethod
    def _contact_name(chat: ChatSummary) -> str:
        remark = (chat.remark or "").strip()
        nickname = (chat.nickname or "").strip()
        return f"{remark}（{nickname}）" if remark and nickname else remark or nickname or "—"

    def _select_visible(self):
        self.tree.selection_set(self.tree.get_children())

    def _export(self):
        if self.busy:
            return
        if not self.account:
            messagebox.showwarning("尚未加载", "请先打开并登录微信，等待数据库验证完成。")
            return
        selected = []
        for iid in self.tree.selection():
            try:
                selected.append(self.all_chats[int(iid)])
            except (ValueError, IndexError):
                continue
        if not selected:
            messagebox.showwarning("未选择联系人", "请在列表中选择一个或多个联系人。")
            return
        formats = [fmt for fmt, variable in self.export_formats.items() if variable.get()]
        if not formats:
            messagebox.showwarning("未选择格式", "请至少选择 TXT 纯文本或 PDF 文档。")
            return
        try:
            date_bounds(self.start_date.get().strip(), self.end_date.get().strip())
        except ValueError as exc:
            messagebox.showerror("日期有误", str(exc))
            return
        account = self.account
        folder = Path(self.export_folder.get().strip() or Path.home() / "Documents" / "微信聊天记录导出")
        start = self.start_date.get().strip()
        end = self.end_date.get().strip()
        include_images = self.include_images.get()
        self.busy = True
        self.export_button.set_enabled(False)

        def work():
            try:
                paths, total = [], 0
                export_index = 0
                export_total = len(selected) * len(formats)
                for chat in selected:
                    for fmt in formats:
                        export_index += 1
                        self.events.put(("export_status", f"正在导出 {export_index}/{export_total}（{fmt}）：{chat.display_name}"))
                        path, count = export_chat(account, chat, folder, fmt, start, end, include_images and fmt == "PDF")
                        paths.append(path)
                        total += count
                self.events.put(("export_done", (paths, total)))
            except Exception as exc:
                self.events.put(("export_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

