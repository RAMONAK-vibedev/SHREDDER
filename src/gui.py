r"""
gui.py — визуальная часть программы «ШРЕДДЕР».

Локализованная версия: все тексты берутся из i18n (t()).
Кнопка 🌐 в левом верхнем углу — переключение языка.
При смене языка интерфейс перерисовывается.
"""

import os
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog
from datetime import datetime

try:
    from tkinterdnd2 import DND_FILES
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False
    DND_FILES = None

from src.utils import human_size, build_path_for_io, resource_path
from src.engine import (shred_file, TOTAL_STEPS, check_file_strict,
                        FileRejectedError, get_drive_warning)
from src.sounds import play_looping, stop_all
from src import i18n
from src import dialogs
from src import settings as app_settings
from src.theme import (
    WIN_W, WIN_H, NAME_MAX_LEN,
    COLOR_BG,
    COLOR_TEXT, COLOR_TEXT_DIM, COLOR_TEXT_TINY,
    COLOR_ACCENT, COLOR_ACCENT_HOV, COLOR_ACCENT_OFF,
    COLOR_BTN, COLOR_BTN_HOV, COLOR_GOLD,
    COLOR_SHADOW, COLOR_DIVIDER,
    _seg,
)

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

class ShredderApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - WIN_W) // 2
        y = (screen_h - WIN_H) // 2
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
        self.root.resizable(False, False)
        self.root.configure(bg=COLOR_BG)

        # Загружаем локали и текущий язык из настроек.
        i18n.load_all_locales()
        i18n.set_language(app_settings.get_language())

        self.root.title(i18n.t("window_title"))
        self._set_icon(self.root)

        # Состояние программы.
        self.selected_path = None
        self.selected_path_for_io = None
        self.strategy_var = tk.StringVar(value="FAST")
        self.engine_running = False
        self.queue = queue.Queue()
        self.bg_image = None
        self._text_counter = 0
        self._strategy_trace_id = None
        self._pending_report_id = None

        # Список виджетов для уничтожения при перерисовке.
        self._widgets = []

        # Холст.
        self.canvas = tk.Canvas(
            root, width=WIN_W, height=WIN_H,
            bg=COLOR_BG, highlightthickness=0, bd=0
        )
        self.canvas.pack(fill="both", expand=True)

        # Собираем интерфейс.
        self._build_ui()
        self._setup_dnd()
        self._pump_queue()

    # ========================================================
    #  ИКОНКА
    # ========================================================

    def _set_icon(self, window):
        """
        Устанавливает иконку окна.
        ВАЖНО: iconbitmap работает ТОЛЬКО с .ico, не с .png.
        Файл icon.ico содержит несколько размеров (16/32/48/256).
        """
        try:
            window.iconbitmap(resource_path("assets/icon.ico"))
        except Exception:
            pass

    # ========================================================
    #  ФОН
    # ========================================================

    def _load_background(self):
        if PIL_AVAILABLE:
            bg_path = resource_path("assets/shredder_bg.png")
            if os.path.isfile(bg_path):
                try:
                    img = Image.open(bg_path)
                    img = img.resize((WIN_W, WIN_H), Image.LANCZOS)
                    self.bg_image = ImageTk.PhotoImage(img)
                    self.canvas.create_image(0, 0, image=self.bg_image, anchor="nw")
                    return
                except Exception:
                    pass
        self.canvas.configure(bg=COLOR_BG)

    # ========================================================
    #  ТЕКСТ С ТЕНЬЮ
    # ========================================================

    def _shadow_text(self, x, y, text, font, fill, anchor="w", width=None):
        self._text_counter += 1
        tag = f"txt_{self._text_counter}"

        kwargs_shadow = dict(text=text, font=font, fill=COLOR_SHADOW,
                             anchor=anchor, tags=tag)
        kwargs_main = dict(text=text, font=font, fill=fill,
                           anchor=anchor, tags=tag)
        if width is not None:
            kwargs_shadow["width"] = width
            kwargs_main["width"] = width

        self.canvas.create_text(x + 1, y + 1, **kwargs_shadow)
        self.canvas.create_text(x, y, **kwargs_main)
        return tag

    # ========================================================
    #  КНОПКИ
    # ========================================================

    def _make_button(self, parent, text, command,
                     primary=False, font_size=12, small=False):
        bg = COLOR_ACCENT if primary else COLOR_BTN
        hov = COLOR_ACCENT_HOV if primary else COLOR_BTN_HOV

        if small:
            btn = tk.Button(
                parent, text=text,
                font=_seg(font_size, "bold"),
                fg="#ffffff", bg="#333333",
                activeforeground="#ffffff",
                activebackground="#555555",
                relief="flat", bd=0,
                cursor="hand2", width=6,
                command=command
            )
        else:
            btn = tk.Button(
                parent, text=text,
                font=_seg(font_size, "bold"),
                fg="#ffffff", bg=bg,
                activeforeground="#ffffff",
                activebackground=hov,
                disabledforeground="#b0b0b0",
                relief="flat", bd=0,
                cursor="hand2",
                command=command
            )

            def on_enter(_):
                if str(btn['state']) != 'disabled':
                    btn.config(bg=hov)

            def on_leave(_):
                if str(btn['state']) != 'disabled':
                    btn.config(bg=bg)

            btn.bind('<Enter>', on_enter)
            btn.bind('<Leave>', on_leave)

        btn._normal_bg = bg
        self._widgets.append(btn)
        return btn

    # ========================================================
    #  СБОРКА ИНТЕРФЕЙСА
    # ========================================================

    def _build_ui(self):
        cx = WIN_W // 2

        self._load_background()

        # --- КНОПКА ВЫБОРА ЯЗЫКА (левый верхний угол) ---
        self.lang_button = self._make_button(
            self.canvas,
            f"{i18n.get_language().upper()} ▾",
            self._open_language_dialog,
            small=True, font_size=10
        )
        self.canvas.create_window(
            50, 40, window=self.lang_button,
            width=58, height=26
        )

        # --- ЗАГОЛОВОК ---
        self._shadow_text(cx, 40, i18n.t("brand"),
                          _seg(26, "bold"), COLOR_ACCENT, anchor="center")
        self._shadow_text(cx, 72, i18n.t("subtitle"),
                          _seg(10, "italic"), COLOR_TEXT_DIM, anchor="center")

        # --- СТРОКА ФАЙЛА ---
        self.file_text_tag = self._shadow_text(
            40, 108, i18n.t("no_file"),
            _seg(11), COLOR_TEXT, anchor="w",
            width=WIN_W - 100
        )

        # Кнопка отмены.
        self.cancel_button = tk.Button(
            self.canvas, text="✕",
            font=_seg(9, "bold"),
            fg="#ffffff", bg="#5a1818",
            activeforeground="#ffffff",
            activebackground=COLOR_ACCENT_HOV,
            relief="flat", bd=0,
            cursor="hand2", width=2, height=1,
            command=self._reset_selection
        )
        self._widgets.append(self.cancel_button)

        # Кнопка «ВЫБРАТЬ ФАЙЛ».
        self.choose_button = self._make_button(
            self.canvas, i18n.t("choose_file"), self._on_choose_file
        )
        self.canvas.create_window(cx, 148, window=self.choose_button,
                                  width=180, height=34)

        self.hint_tag = self._shadow_text(
            cx, 180, i18n.t("dnd_hint"),
            _seg(9, "italic"), COLOR_TEXT_DIM, anchor="center"
        )

        if not DND_AVAILABLE:
            self.canvas.itemconfig(self.hint_tag, text=i18n.t("dnd_unavailable"))

        # --- БЛОК «ИНФОРМАЦИЯ» ---
        info_left = 40
        self._shadow_text(
            info_left, 215, i18n.t("info_title"),
            _seg(11), COLOR_TEXT_TINY, anchor="w"
        )
        self.canvas.create_line(
            info_left, 234, WIN_W - 40, 234,
            fill=COLOR_DIVIDER, width=1
        )

        self.info_tags = {}
        info_rows = [
            ("name", "info_name"),
            ("size", "info_size"),
            ("type", "info_type"),
            ("path", "info_path"),
            ("created", "info_created"),
            ("modified", "info_modified"),
            ("strategy", "info_strategy"),
        ]
        y = 254
        row_step = 26
        for key, title_key in info_rows:
            self._shadow_text(info_left, y, i18n.t(title_key),
                              _seg(11), COLOR_TEXT_DIM, anchor="w")
            self.info_tags[key] = self._shadow_text(
                info_left + 105, y, "—",
                _seg(11), COLOR_TEXT, anchor="w",
                width=WIN_W - 40 - (info_left + 105)
            )
            y += row_step

        self.strategy_y = y + 8
        self.strategy_left = info_left

        # --- КНОПКА УНИЧТОЖИТЬ ---
        self.shred_button = self._make_button(
            self.canvas, i18n.t("shred_button"),
            self._on_shred_click, primary=True, font_size=20
        )
        self.shred_button.config(state="disabled", bg=COLOR_ACCENT_OFF)
        self.canvas.create_window(cx, WIN_H - 220, window=self.shred_button,
                                  width=WIN_W - 80, height=64)

        # --- ПРОГРЕСС ---
        self.progress_bar = ttk.Progressbar(
            self.canvas, mode="determinate",
            maximum=100, length=WIN_W - 80
        )
        self.canvas.create_window(cx, WIN_H - 160, window=self.progress_bar,
                                  width=WIN_W - 80, height=18)

        self.progress_tag = self._shadow_text(
            cx, WIN_H - 133, "",
            _seg(9), COLOR_TEXT_DIM, anchor="center"
        )

        # --- ПРЕДУПРЕЖДЕНИЕ ---
        self._shadow_text(
            cx, WIN_H - 95, i18n.t("ssd_warning"),
            _seg(8, "italic"), COLOR_TEXT_TINY, anchor="center",
            width=WIN_W - 30
        )

        # --- ЛОГОТИПЫ ---
        self._draw_two_logos(cx - 5, WIN_H - 40, gap=22,
                             my_height=44, ds_height=29)

        # Если был выбран файл — восстановим его.
        if self.selected_path:
            self._set_selected_file(self.selected_path, restore=True)

    # ========================================================
    #  ЛОГОТИПЫ
    # ========================================================

    def _load_logo(self, filename, height=22):
        path = resource_path(os.path.join("assets", filename))
        if not os.path.isfile(path):
            return None
        try:
            img = Image.open(path).convert("RGBA")
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            w = int(img.width * (height / img.height))
            img = img.resize((w, height), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _draw_two_logos(self, cx, y, gap=20,
                        my_height=28, ds_height=28):
        if not PIL_AVAILABLE:
            return
        my_img = self._load_logo("my_logo.png", height=my_height)
        ds_img = self._load_logo("deepseek_logo.png", height=ds_height)
        w1 = my_img.width() if my_img else 0
        w2 = ds_img.width() if ds_img else 0
        if w1 == 0 and w2 == 0:
            return
        total_w = w1 + w2 + (gap if (w1 and w2) else 0)
        start_x = cx - total_w // 2
        if my_img:
            self.my_logo_image = my_img
            self.canvas.create_image(start_x, y, image=my_img, anchor="w")
            start_x += w1 + gap
        if ds_img:
            self.ds_logo_image = ds_img
            self.canvas.create_image(start_x, y, image=ds_img, anchor="w")

    # ========================================================
    #  ПЕРЕРИСОВКА ПРИ СМЕНЕ ЯЗЫКА
    # ========================================================

    def _rebuild_ui(self):
        """Полностью перерисовывает интерфейс. Вызывается после смены языка."""
        # Уничтожаем все виджеты (Button, Progressbar и т.п.).
        for w in self._widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._widgets = []

        # Очищаем канвас (тексты, фигуры).
        self.canvas.delete("all")

        # Сбрасываем счётчик тегов, чтобы не накапливались.
        self._text_counter = 0

        # Обновляем заголовок окна.
        self.root.title(i18n.t("window_title"))

        # Строим интерфейс заново.
        self._build_ui()

    # ========================================================
    #  ДИАЛОГ ВЫБОРА ЯЗЫКА
    # ========================================================

    def _open_language_dialog(self):
        """Обёртка вокруг dialogs.show_language_picker."""
        def on_apply(new_code):
            i18n.set_language(new_code)
            app_settings.set_language(new_code)
            self._rebuild_ui()

        dialogs.show_language_picker(
            self.root,
            i18n.get_language(),
            on_apply
        )

    # ========================================================
    #  КАСТОМНЫЕ ДИАЛОГИ
    # ========================================================

    def _error_dialog(self, title: str, message: str) -> None:
        """Обёртка вокруг dialogs.show_error — сохраняет все вызовы."""
        dialogs.show_error(self.root, title, message)

    # ========================================================
    #  DRAG-AND-DROP
    # ========================================================

    def _setup_dnd(self):
        if not DND_AVAILABLE:
            return

        def on_drop(event):
            if self.engine_running:
                return
            try:
                paths = self.root.tk.splitlist(event.data)
            except Exception:
                return
            if not paths:
                return
            self._set_selected_file(os.path.normpath(paths[0]))

        def register_recursive(widget):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>', on_drop)
            except Exception:
                pass
            for child in widget.winfo_children():
                register_recursive(child)

        register_recursive(self.root)

    # ========================================================
    #  ВЫБОР ФАЙЛА
    # ========================================================

    def _on_choose_file(self):
        if self.engine_running:
            return
        path = filedialog.askopenfilename(
            title=i18n.t("choose_dialog_title"),
            filetypes=[(i18n.t("choose_dialog_all_files"), "*.*")]
        )
        if path:
            self._set_selected_file(os.path.normpath(path))

    def _set_selected_file(self, path: str, restore=False):
        # Отменяем отложенный отчёт — пользователь уже работает с новым файлом.
        if self._pending_report_id is not None:
            try:
                self.root.after_cancel(self._pending_report_id)
            except Exception:
                pass
            self._pending_report_id = None

        if not os.path.exists(path):
            self._error_dialog(i18n.t("error_title"),
                               i18n.t("error_file_not_found"))
            return

        # .lnk — особый случай: спрашиваем пользователя (Вариант В).
        if not restore and path.lower().endswith(".lnk"):
            if not app_settings.get_flag("skip_lnk_confirm"):
                answer, dont_ask = dialogs.show_confirm(
                    self.root,
                    i18n.t("confirm_lnk_title"),
                    i18n.t("confirm_lnk_text"),
                    height=310,
                    checkbox_text=i18n.t("dont_ask_again"),
                )
                if not answer:
                    return
                if dont_ask:
                    app_settings.set_flag("skip_lnk_confirm", True)

        # Строгие проверки — сразу при выборе, а не при уничтожении.
        if not restore:
            path_for_io = build_path_for_io(path)
            try:
                check_file_strict(path_for_io)
            except FileRejectedError as e:
                self._error_dialog(i18n.t("error_title"), str(e))
                return
            except Exception as e:
                self._error_dialog(
                    i18n.t("error_title"),
                    i18n.t("error_unknown", err=f"{type(e).__name__}: {e}")
                )
                return

        # Мягкое предупреждение — сетевой или съёмный диск.
        if not restore:
            try:
                warning = get_drive_warning(path)
                if warning:
                    answer, _ = dialogs.show_confirm(
                        self.root,
                        i18n.t("confirm_title"),
                        warning,
                        height=270,
                    )
                    if not answer:
                        return
            except Exception:
                pass

        self.selected_path = path
        self.selected_path_for_io = build_path_for_io(path)

        try:
            st = os.stat(self.selected_path_for_io)
            size = st.st_size
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].lower()
            file_type = _detect_file_type(ext)

            created = datetime.fromtimestamp(st.st_ctime).strftime("%d.%m.%Y %H:%M")
            modified = datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")

            self.canvas.itemconfig(self.info_tags["name"],
                                   text=_shorten_middle(name, 44))
            self.canvas.itemconfig(self.info_tags["size"],
                                   text=f"{human_size(size)} ({size} {i18n.t('unit_b')})")
            self.canvas.itemconfig(self.info_tags["type"], text=file_type)
            folder = os.path.dirname(path)
            if folder:
                folder = folder + "\\"
            if len(folder) > 42:
                folder = "..." + folder[-39:]
            self.canvas.itemconfig(self.info_tags["path"], text=folder)
            self.canvas.itemconfig(self.info_tags["created"], text=created)
            self.canvas.itemconfig(self.info_tags["modified"], text=modified)
        except Exception as e:
            self._error_dialog(i18n.t("error_title"),
                               i18n.t("error_cannot_read", err=e))
            self._reset_selection()
            return

        self._update_strategy_ui(size)

        short_name = os.path.basename(path)
        if len(short_name) > 48:
            short_name = short_name[:45] + "..."
        self.canvas.itemconfig(
            self.file_text_tag,
            text=f"{i18n.t('selected_prefix')} {short_name}"
        )

        self.shred_button.config(state="normal", bg=COLOR_ACCENT)

        if not restore:
            try:
                self.canvas.delete(self.cancel_window_id)
            except Exception:
                pass
        self.cancel_window_id = self.canvas.create_window(
            WIN_W - 30, 108, window=self.cancel_button,
            width=22, height=22
        )
        self.cancel_button.config(state="normal")

    def _reset_selection(self):
        # Отменяем отложенный отчёт (если был).
        if self._pending_report_id is not None:
            try:
                self.root.after_cancel(self._pending_report_id)
            except Exception:
                pass
            self._pending_report_id = None

        self.selected_path = None
        self.selected_path_for_io = None
        self.strategy_var.set("FAST")
        self.canvas.itemconfig(self.file_text_tag, text=i18n.t("no_file"))
        for key in self.info_tags:
            self.canvas.itemconfig(self.info_tags[key], text="—")
        self.shred_button.config(
            state="disabled",
            bg=COLOR_ACCENT_OFF,
            text=i18n.t("shred_button")
        )

        self.canvas.delete("strategy_ui")
        self.progress_bar['value'] = 0
        self.canvas.itemconfig(self.progress_tag, text="")

        try:
            self.canvas.delete(self.cancel_window_id)
        except Exception:
            pass

        # Убираем активный trace — он больше не нужен без файла.
        if self._strategy_trace_id is not None:
            try:
                self.strategy_var.trace_remove("write", self._strategy_trace_id)
            except Exception:
                pass
            self._strategy_trace_id = None

    # ========================================================
    #  СТРАТЕГИЯ
    # ========================================================

    def _update_strategy_ui(self, size: int):
        self.canvas.delete("strategy_ui")

        # Всегда удаляем старый trace в самом начале —
        # иначе при переключении с большого файла на маленький
        # он останется висеть (эта ветка в else ниже).
        if self._strategy_trace_id is not None:
            try:
                self.strategy_var.trace_remove("write", self._strategy_trace_id)
            except Exception:
                pass
            self._strategy_trace_id = None

        GB = 1024 * 1024 * 1024
        y = self.strategy_y
        left = self.strategy_left
        right = WIN_W - 40
        ...

        self.canvas.create_text(
            left + 1, y + 1, text=i18n.t("strategy_title"),
            font=_seg(11), fill=COLOR_SHADOW, anchor="w", tags="strategy_ui"
        )
        self.canvas.create_text(
            left, y, text=i18n.t("strategy_title"),
            font=_seg(11), fill=COLOR_TEXT_TINY, anchor="w", tags="strategy_ui"
        )
        self.canvas.create_line(
            left, y + 16, right, y + 16,
            fill=COLOR_DIVIDER, width=1, tags="strategy_ui"
        )

        if size < GB:
            self.strategy_var.set("FULL")
            text = i18n.t("strategy_full_small")
            self.canvas.create_text(
                left + 1, y + 38, text=text,
                font=_seg(11, "bold"), fill=COLOR_SHADOW,
                anchor="w", tags="strategy_ui"
            )
            self.canvas.create_text(
                left, y + 37, text=text,
                font=_seg(11, "bold"), fill=COLOR_GOLD,
                anchor="w", tags="strategy_ui"
            )
            self.canvas.itemconfig(
                self.info_tags["strategy"],
                text=i18n.t("strategy_full_small_short")
            )
        else:
            self._draw_radio_row(
                left, right, y + 42, i18n.t("strategy_fast"), "FAST"
            )
            self._draw_radio_row(
                left, right, y + 74, i18n.t("strategy_full"), "FULL"
            )

            def update_label(*_):
                mode = self.strategy_var.get()
                text = (i18n.t("strategy_fast_short") if mode == "FAST"
                        else i18n.t("strategy_full_short"))
                self.canvas.itemconfig(self.info_tags["strategy"], text=text)

            # (старый trace уже удалён в начале метода)

            self._strategy_trace_id = self.strategy_var.trace_add(
                "write", update_label
            )
            update_label()
            self._refresh_radios()

    def _draw_radio_row(self, left, right, y, text, value):
        self.canvas.create_oval(
            left + 2, y - 7, left + 16, y + 7,
            outline=COLOR_TEXT_DIM, width=1, fill="",
            tags=("strategy_ui", f"radio_bg_{value}")
        )
        self.canvas.create_oval(
            left + 6, y - 3, left + 12, y + 3,
            outline="", fill=COLOR_ACCENT,
            tags=("strategy_ui", f"radio_dot_{value}")
        )
        self.canvas.create_text(
            left + 27 + 1, y + 1, text=text,
            font=_seg(11), fill=COLOR_SHADOW,
            anchor="w", tags=("strategy_ui", f"radio_lbl_{value}")
        )
        self.canvas.create_text(
            left + 27, y, text=text,
            font=_seg(11), fill=COLOR_TEXT,
            anchor="w", tags=("strategy_ui", f"radio_lbl_{value}")
        )
        hit = self.canvas.create_rectangle(
            left, y - 12, right, y + 12,
            fill="", outline="",
            tags=("strategy_ui", f"radio_hit_{value}")
        )

        def on_click(_):
            self.strategy_var.set(value)
            self._refresh_radios()

        def on_enter(_):
            self.canvas.config(cursor="hand2")

        def on_leave(_):
            self.canvas.config(cursor="")

        self.canvas.tag_bind(hit, "<Button-1>", on_click)
        self.canvas.tag_bind(hit, "<Enter>", on_enter)
        self.canvas.tag_bind(hit, "<Leave>", on_leave)

    def _refresh_radios(self):
        current = self.strategy_var.get()
        for value in ("FAST", "FULL"):
            state = "normal" if value == current else "hidden"
            self.canvas.itemconfig(f"radio_dot_{value}", state=state)

    # ========================================================
    #  УНИЧТОЖЕНИЕ
    # ========================================================

    def _on_shred_click(self):
        if self.engine_running or not self.selected_path:
            return

        # Проверяем «не спрашивать»
        if not app_settings.get_flag("skip_confirm"):
            name = _shorten_middle(os.path.basename(self.selected_path), 44)
            answer, dont_ask = dialogs.show_confirm(
                self.root,
                i18n.t("confirm_title"),
                i18n.t("confirm_text", name=name),
                height=270,
                checkbox_text=i18n.t("dont_ask_again"),
            )
            if not answer:
                return
            if dont_ask:
                app_settings.set_flag("skip_confirm", True)

        play_looping("shredding.wav")

        self.engine_running = True
        self.shred_button.config(
            state="disabled", bg=COLOR_ACCENT_OFF, text=i18n.t("working")
        )
        self.cancel_button.config(state="disabled")
        self.lang_button.config(state="disabled")

        self.progress_bar['value'] = 0
        self.canvas.itemconfig(self.progress_tag, text=i18n.t("preparing"))

        mode = self.strategy_var.get()
        threading.Thread(
            target=self._run_engine,
            args=(self.selected_path, mode),
            daemon=True
        ).start()

    def _run_engine(self, path: str, mode: str):
        def callback(step, message, sub):
            self.queue.put(("progress", step, message, sub))

        result = shred_file(path, mode, progress_callback=callback)
        self.queue.put(("done", result))

    def _pump_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()

                if msg[0] == "progress":
                    _, step, message, sub = msg
                    overall = ((step - 1) + sub) / TOTAL_STEPS * 100
                    self.progress_bar['value'] = overall
                    self.canvas.itemconfig(
                        self.progress_tag,
                        text=i18n.t("step_progress",
                                    n=step, total=TOTAL_STEPS,
                                    msg=message, pct=int(sub * 100))
                    )

                elif msg[0] == "done":
                    self._on_engine_done(msg[1])
        except queue.Empty:
            pass

        try:
            self.root.after(100, self._pump_queue)
        except tk.TclError:
            pass

    def _on_engine_done(self, result):
        stop_all()

        self.engine_running = False
        # Кнопку пока НЕ включаем — сделаем это в _reset_selection.
        self.cancel_button.config(state="normal")
        self.lang_button.config(state="normal")

        if not result['success']:
            self._error_dialog(i18n.t("error_title"), result['error'] or "?")
            self._reset_selection()
            return

        # Даём пользователю увидеть заполненную полоску — 500 мс.
        # Сохраняем ID, чтобы можно было отменить при сбросе.
        self._pending_report_id = self.root.after(
            500, lambda: self._show_report_and_reset(result)
        )

    def _show_report_and_reset(self, result):
        """Показывает отчёт (если не отключён), затем сбрасывает панель."""
        self._pending_report_id = None
        if not app_settings.get_flag("skip_report"):
            dont_show = dialogs.show_success_report(
                self.root, result,
                checkbox_text=i18n.t("dont_show_again"),
            )
            if dont_show:
                app_settings.set_flag("skip_report", True)
        self._reset_selection()

# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ
# ============================================================

def _shorten_middle(name: str, max_len: int = NAME_MAX_LEN) -> str:
    if len(name) <= max_len:
        return name
    head = (max_len - 3) // 2
    tail = max_len - 3 - head
    return name[:head] + "..." + name[-tail:]

def _detect_file_type(ext: str) -> str:
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm'):
        return i18n.t("ft_video")
    if ext in ('.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'):
        return i18n.t("ft_audio")
    if ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'):
        return i18n.t("ft_image")
    if ext in ('.zip', '.rar', '.7z', '.tar', '.gz'):
        return i18n.t("ft_archive")
    if ext in ('.doc', '.docx', '.pdf', '.txt', '.rtf', '.odt'):
        return i18n.t("ft_document")
    if ext in ('.exe', '.msi', '.bat', '.cmd'):
        return i18n.t("ft_program")
    if ext == '.lnk':
        return i18n.t("ft_lnk")
    return i18n.t("ft_other")

# ============================================================
#  ЗАПУСК
# ============================================================

def run():
    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()

    # Сохраняем ссылку на root — иначе сборщик мусора удалит
    # приложение и оно зависнет.
    root.app = ShredderApp(root)
    root.mainloop()