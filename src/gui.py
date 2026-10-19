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

from src.utils import (human_size, build_path_for_io, resource_path,
                       is_compressed_encrypted_sparse)
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
    FONT_FAMILY, _seg,
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
        self.bg_single = None   # Фон одиночного режима
        self.bg_queue = None    # Фон очереди
        # Счётчики текста — отдельные для каждого canvas.
        # Ключ — имя режима, значение — текущий номер.
        self._text_counters = {"single": 0, "queue": 0}
        # Активный режим. Пока всегда "single", в v1.1 добавится "queue".
        self._active_mode = "single"
        # Ссылки на логотипы — отдельно от canvas, иначе вторая
        # отрисовка удалит старую и картинка исчезнет с первого canvas.
        self._my_logo_img = None
        self._ds_logo_img = None
        # Настройка звука.
        self.sound_enabled = app_settings.get_sound_enabled()
        # Состояние очереди.
        self._queue_paths = []           # список путей в порядке добавления
        self._queue_tree_ids = {}        # {tree_item_id: path}
        self._queue_sizes = {}           # {path: size}
        self._queue_canonical = set()    # нормализованные пути (для дубликатов)
        self._queue_warnings = {}        # {path: True/False} — есть ли проблемы

        # Состояние обработки очереди.
        self._queue_running = False      # очередь сейчас обрабатывается
        self._queue_current_index = 0    # номер текущего файла (0-based)
        self._queue_results = []         # [{path, status, reason}, ...]
        self._queue_total_bytes = 0      # общий размер всех файлов
        self._queue_done_bytes = 0       # сколько уже обработано
        # Для ETA.
        self._queue_start_time = 0.0     # время старта обработки (time.time())
        self._queue_file_times = []      # времена обработки каждого файла
        # Event: установлен = поток может работать, снят = пауза.
        self._pause_event = threading.Event()
        self._pause_event.set()
        # Состояние hard links.
        # Решения по конкретным inode: {inode_key: "yes"/"no"}
        self._hardlink_inode_decisions = {}
        # Галочка «применять ко всем» для всей очереди: None/"yes"/"no"
        self._hardlink_apply_to_all = None
        # Event для синхронизации диалога: поток ждёт ответа GUI.
        self._hardlink_event = threading.Event()
        self._hardlink_answer = None     # сюда GUI кладёт ответ
        self._hardlink_dont_ask = False  # вернулась ли галочка

        # Настраиваем тёмную тему для Treeview.
        self._setup_treeview_style()
        self._strategy_trace_id = None
        self._pending_report_id = None

        # Список виджетов для уничтожения при перерисовке.
        self._widgets = []

        # Два холста — одиночный режим и очередь.
        # Активный указывается в self.canvas (псевдоним).
        self.canvas_single = tk.Canvas(
            root, width=WIN_W, height=WIN_H,
            bg=COLOR_BG, highlightthickness=0, bd=0
        )
        self.canvas_queue = tk.Canvas(
            root, width=WIN_W, height=WIN_H,
            bg=COLOR_BG, highlightthickness=0, bd=0
        )
        self.canvas = self.canvas_single
        self.canvas_single.pack(fill="both", expand=True)

        # Собираем интерфейс.
        self._build_ui()
        self._setup_dnd()
        self._pump_queue()

        # Кнопки в root — поверх canvas.
        self._create_lang_button()
        self._create_sound_button()
        self._create_toggle_button()

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
    #  КНОПКИ В ROOT (поверх canvas)
    # ========================================================

    def _create_lang_button(self):
        """Кнопка выбора языка — в root, поверх обоих canvas."""
        self.lang_button = tk.Button(
            self.root,
            text=f"{i18n.get_language().upper()} ▾",
            font=_seg(10, "bold"),
            fg="#ffffff", bg="#333333",
            activeforeground="#ffffff",
            activebackground="#555555",
            relief="flat", bd=0,
            cursor="hand2", width=6, height=1,
            command=self._open_language_dialog
        )
        self.lang_button.place(x=20, y=32, width=58, height=32)

    def _create_sound_button(self):
        """Кнопка вкл/выкл звука — в root, рядом с кнопкой языка."""
        text = "🔊" if self.sound_enabled else "🔇"
        self.sound_button = tk.Button(
            self.root, text=text,
            font=_seg(12, "bold"),
            fg="#ffffff", bg="#333333",
            activeforeground="#ffffff",
            activebackground="#555555",
            relief="flat", bd=0,
            cursor="hand2", width=3,
            command=self._toggle_sound
        )
        self.sound_button.place(x=86, y=32, width=32, height=32)

    def _toggle_sound(self):
        """Переключает звук вкл/выкл и сохраняет в настройки."""
        self.sound_enabled = not self.sound_enabled
        app_settings.set_sound_enabled(self.sound_enabled)

        self.sound_button.config(
            text="🔊" if self.sound_enabled else "🔇"
        )

        if not self.sound_enabled:
            # Выключили — останавливаем.
            stop_all()
        else:
            # Включили — если прямо сейчас идёт одиночное уничтожение,
            # запускаем звук заново. (В очереди звук не играет никогда.)
            if self.engine_running:
                play_looping("shredding.wav")

    def _create_toggle_button(self):
        """Кнопка переключения режимов — в root, поверх обоих canvas."""
        text = i18n.t("queue_toggle_to_queue") if self._active_mode == "single" else i18n.t("queue_toggle_to_single")
        self.toggle_button = tk.Button(
            self.root, text=text,
            font=_seg(10, "bold"),
            fg="#ffffff", bg="#333333",
            activeforeground="#ffffff",
            activebackground="#555555",
            relief="flat", bd=0,
            cursor="hand2",
            command=self._toggle_mode
        )
        self.toggle_button.place(
            x=WIN_W - 130, y=32, width=110, height=32
        )

    def _toggle_mode(self):
        """Переключает между одиночным режимом и очередью."""
        # Блокировка при работе движка.
        if self.engine_running:
            return

        # Отменяем отложенный отчёт — он относится к другому режиму.
        if self._pending_report_id is not None:
            try:
                self.root.after_cancel(self._pending_report_id)
            except Exception:
                pass
            self._pending_report_id = None

        if self._active_mode == "single":
            self.canvas_single.pack_forget()
            self.canvas = self.canvas_queue
            self.canvas.pack(fill="both", expand=True)
            self._active_mode = "queue"
            self.toggle_button.config(text=i18n.t("queue_toggle_to_single"))
        else:
            self.canvas_queue.pack_forget()
            self.canvas = self.canvas_single
            self.canvas.pack(fill="both", expand=True)
            self._active_mode = "single"
            self.toggle_button.config(text=i18n.t("queue_toggle_to_queue"))

        # Кнопки — всегда поверх.
        self.toggle_button.lift()
        self.lang_button.lift()
        if hasattr(self, "sound_button"):
            self.sound_button.lift()

    # ========================================================
    #  ФОН
    # ========================================================

    def _setup_treeview_style(self):
        """Тёмная тема для Treeview. На Windows нужна тема 'clam' —
        'vista' игнорирует настройки цвета."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Queue.Treeview",
            background="#1a1a1a",
            foreground="#ffffff",
            fieldbackground="#1a1a1a",
            bordercolor="#333333",
            lightcolor="#333333",
            darkcolor="#333333",
            borderwidth=1,
            font=(FONT_FAMILY, 10),
            rowheight=24,
        )
        style.map(
            "Queue.Treeview",
            background=[("selected", COLOR_ACCENT)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Queue.Treeview.Heading",
            background="#2a2a2a",
            foreground="#ffffff",
            font=(FONT_FAMILY, 10, "bold"),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Queue.Treeview.Heading",
            background=[("active", "#3a3a3a")],
        )
        # Тёмный стиль для прогресс-баров
        style.configure(
            "Red.Horizontal.TProgressbar",
            troughcolor="#181818",     # Тёмная подложка
            background=COLOR_ACCENT,   # Красный цвет заполнения
            bordercolor="#333333",
            lightcolor=COLOR_ACCENT,
            darkcolor=COLOR_ACCENT,
            borderwidth=1,
        )

    def _load_background(self):
        """Загружает фоны для обоих режимов."""
        if PIL_AVAILABLE:
            # 1. Фон для одиночного режима (Шреддер)
            bg1_path = resource_path("assets/shredder_bg.png")
            if os.path.isfile(bg1_path):
                try:
                    img1 = Image.open(bg1_path)
                    img1 = img1.resize((WIN_W, WIN_H), Image.LANCZOS)
                    self.bg_single = ImageTk.PhotoImage(img1)
                    self.canvas_single.create_image(
                        0, 0, image=self.bg_single, anchor="nw"
                    )
                except Exception:
                    self.canvas_single.configure(bg=COLOR_BG)
            else:
                self.canvas_single.configure(bg=COLOR_BG)

            # 2. Фон для режима очереди (Банда на крыше)
            bg2_path = resource_path("assets/shredder_bg2.png")
            if os.path.isfile(bg2_path):
                try:
                    img2 = Image.open(bg2_path)
                    img2 = img2.resize((WIN_W, WIN_H), Image.LANCZOS)
                    self.bg_queue = ImageTk.PhotoImage(img2)
                    self.canvas_queue.create_image(
                        0, 0, image=self.bg_queue, anchor="nw"
                    )
                except Exception:
                    self.canvas_queue.configure(bg=COLOR_BG)
            else:
                self.canvas_queue.configure(bg=COLOR_BG)
        else:
            self.canvas_single.configure(bg=COLOR_BG)
            self.canvas_queue.configure(bg=COLOR_BG)

    # ========================================================
    #  ТЕКСТ С ТЕНЬЮ
    # ========================================================

    def _shadow_text(self, canvas, x, y, text, font, fill,
                     anchor="w", width=None):
        """
        Рисует текст с тенью на указанном canvas.
        Теги уникальны для каждого canvas (по счётчику режима).
        """
        self._text_counters[self._active_mode] += 1
        counter = self._text_counters[self._active_mode]
        tag = f"txt_{self._active_mode}_{counter}"

        kwargs_shadow = dict(text=text, font=font, fill=COLOR_SHADOW,
                             anchor=anchor, tags=tag)
        kwargs_main = dict(text=text, font=font, fill=fill,
                           anchor=anchor, tags=tag)
        if width is not None:
            kwargs_shadow["width"] = width
            kwargs_main["width"] = width

        canvas.create_text(x + 1, y + 1, **kwargs_shadow)
        canvas.create_text(x, y, **kwargs_main)
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
        """Собирает интерфейс: общая часть на оба canvas + специфика."""
        self._load_background()
        # Общая часть — на оба canvas.
        self._build_common_ui(self.canvas_single)
        self._build_common_ui(self.canvas_queue)
        # Специфика.
        self._build_single_ui(self.canvas_single)
        self._build_queue_ui(self.canvas_queue)
        # Логотипы — один вызов, рисует на обоих canvas сразу.
        self._draw_two_logos(
            WIN_W // 2 - 5, WIN_H - 40, gap=22,
            my_height=44, ds_height=29
        )

    def _build_common_ui(self, canvas):
        """Общая часть интерфейса — на обоих экранах (одиночный + очередь)."""
        cx = WIN_W // 2

        # --- ЗАГОЛОВОК ---
        self._shadow_text(
            canvas, cx, 40, i18n.t("brand"),
            _seg(26, "bold"), COLOR_ACCENT, anchor="center"
        )
        self._shadow_text(
            canvas, cx, 72, i18n.t("subtitle"),
            _seg(10, "italic"), COLOR_TEXT_DIM, anchor="center"
        )

        # --- ПРЕДУПРЕЖДЕНИЕ ВНИЗУ ---
        self._shadow_text(
            canvas, cx, WIN_H - 95, i18n.t("ssd_warning"),
            _seg(8, "italic"), COLOR_TEXT_TINY, anchor="center",
            width=WIN_W - 30
        )

    def _build_queue_ui(self, canvas):
        """UI очереди: список файлов, кнопки управления, прогресс."""
        cx = WIN_W // 2

        # --- ЗАГОЛОВОК БЛОКА ---
        self._shadow_text(
            canvas, 40, 100, i18n.t("queue_title"),
            _seg(11), COLOR_TEXT_TINY, anchor="w"
        )
        canvas.create_line(
            40, 118, WIN_W - 40, 118,
            fill=COLOR_DIVIDER, width=1
        )

        # --- КНОПКИ ДОБАВЛЕНИЯ / ОЧИСТКИ ---
        self.queue_add_button = self._make_button(
            canvas, i18n.t("queue_btn_add"), self._on_queue_add_files
        )
        canvas.create_window(
            cx - 75, 145, window=self.queue_add_button,
            width=170, height=32
        )

        self.queue_clear_button = self._make_button(
            canvas, i18n.t("queue_btn_clear"), self._on_queue_clear
        )
        canvas.create_window(
            cx + 90, 145, window=self.queue_clear_button,
            width=110, height=32
        )

        # Подсказка.
        self.queue_hint_tag = self._shadow_text(
            canvas, cx, 175, i18n.t("queue_hint"),
            _seg(9, "italic"), COLOR_TEXT_DIM, anchor="center"
        )

        # --- TREEVIEW СО СПИСКОМ ---
        tree_frame = tk.Frame(canvas, bg=COLOR_BG)
        self._widgets.append(tree_frame)

        self.queue_tree = ttk.Treeview(
            tree_frame,
            columns=("num", "warn", "name", "size"),
            show="headings",
            height=1,
            selectmode="extended",
            style="Queue.Treeview",
        )
        self.queue_tree.heading("num", text="#")
        self.queue_tree.heading("warn", text="")
        self.queue_tree.heading("name", text=i18n.t("queue_col_name"))
        self.queue_tree.heading("size", text=i18n.t("queue_col_size"))
        self.queue_tree.column("num", width=40, anchor="center", stretch=False)
        self.queue_tree.column("warn", width=26, anchor="center", stretch=False)
        self.queue_tree.column("name", width=300, anchor="w")
        self.queue_tree.column("size", width=90, anchor="e", stretch=False)
        self._widgets.append(self.queue_tree)

        tree_scroll = ttk.Scrollbar(
            tree_frame, orient="vertical",
            command=self.queue_tree.yview
        )
        self.queue_tree.configure(yscrollcommand=tree_scroll.set)
        self._widgets.append(tree_scroll)

        self.queue_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Привязываемся к верхнему краю, чтобы список рос вниз.
        canvas.create_window(
            cx, 190, window=tree_frame,
            width=WIN_W - 60, anchor="n"
        )

        # Hotkey для удаления выделенных.
        self.queue_tree.bind("<Delete>", self._on_queue_delete_selected)
        self.queue_tree.bind("<BackSpace>", self._on_queue_delete_selected)

        # --- СЧЁТЧИК ФАЙЛОВ / ОБЩИЙ РАЗМЕР (сдвинули вниз) ---
        self.queue_stats_tag = self._shadow_text(
            canvas, cx, 510,
            i18n.t("queue_stat_files", n=0) + "      " + i18n.t("queue_stat_size", size=human_size(0)),
            _seg(10), COLOR_TEXT_DIM, anchor="center"
        )

        # --- ОБЩИЙ ПРОГРЕСС ---
        self.queue_progress_total = ttk.Progressbar(
            canvas, mode="determinate",
            style="Red.Horizontal.TProgressbar",
            maximum=100, length=WIN_W - 80
        )
        self._widgets.append(self.queue_progress_total)
        canvas.create_window(
            cx, 545, window=self.queue_progress_total,
            width=WIN_W - 80, height=16
        )
        self.queue_progress_total_tag = self._shadow_text(
            canvas, cx, 565,
            i18n.t("queue_progress_total", current=0, total=0),
            _seg(9), COLOR_TEXT_DIM, anchor="center"
        )

        # --- ПРОГРЕСС ТЕКУЩЕГО ФАЙЛА ---
        self.queue_progress_current = ttk.Progressbar(
            canvas, mode="determinate",
            style="Red.Horizontal.TProgressbar",
            maximum=100, length=WIN_W - 80
        )
        self._widgets.append(self.queue_progress_current)
        canvas.create_window(
            cx, 590, window=self.queue_progress_current,
            width=WIN_W - 80, height=16
        )
        self.queue_progress_current_tag = self._shadow_text(
            canvas, cx, 610,
            "",
            _seg(9), COLOR_TEXT_DIM, anchor="center"
        )

        # --- КНОПКИ УПРАВЛЕНИЯ ---
        self.queue_start_button = self._make_button(
            canvas, i18n.t("queue_btn_start"), self._on_queue_start,
            primary=True, font_size=12
        )
        self.queue_start_button.config(
            state="disabled", bg=COLOR_ACCENT_OFF
        )
        canvas.create_window(
            cx - 120, 660, window=self.queue_start_button,
            width=110, height=44
        )

        self.queue_pause_button = self._make_button(
            canvas, i18n.t("queue_btn_pause"), self._on_queue_pause,
            font_size=12
        )
        self.queue_pause_button.config(state="disabled")
        canvas.create_window(
            cx, 660, window=self.queue_pause_button,
            width=110, height=44
        )

        self.queue_stop_button = self._make_button(
            canvas, i18n.t("queue_btn_stop"), self._on_queue_stop,
            font_size=12
        )
        self.queue_stop_button.config(state="disabled")
        canvas.create_window(
            cx + 120, 660, window=self.queue_stop_button,
            width=110, height=44
        )

        # Инициализируем состояние кнопок.
        self._refresh_queue_buttons()

        # ВАЖНО: восстанавливаем список файлов и статистику,
        # если они уже были в памяти (например, при смене языка).
        self._refresh_queue_list()
        self._update_queue_stats()

    # ========================================================
    #  ОЧЕРЕДЬ — ДОБАВЛЕНИЕ ФАЙЛОВ
    # ========================================================

    def _on_queue_add_files(self):
        """Кнопка «ВЫБРАТЬ ФАЙЛЫ» — открывает диалог, добавляет в очередь."""
        if self.engine_running or self._queue_running:
            return

        paths = filedialog.askopenfilenames(
            title=i18n.t("choose_dialog_title"),
            filetypes=[(i18n.t("choose_dialog_all_files"), "*.*")]
        )
        if not paths:
            return

        paths = [os.path.normpath(p) for p in paths]
        self._add_to_queue(paths)

    def _add_to_queue(self, paths):
        """
        Добавляет список путей в очередь.
        Быстрая валидация: exists, не папка, не симлинк, не .lnk (диалог),
        не дубликат. Плюс пометка ⚠ для hard links / EFS / reparse.
        Возвращает (added, skipped).
        """
        if self._queue_running:
            return 0, 0

        added = 0
        skipped = 0

        for path in paths:
            # Нормализуем.
            try:
                path = os.path.normpath(path)
            except Exception:
                skipped += 1
                continue

            # Дубликат? Сравниваем по нормализованному абсолютному пути.
            try:
                canonical = os.path.normcase(os.path.abspath(path))
            except Exception:
                skipped += 1
                continue

            if canonical in self._queue_canonical:
                skipped += 1
                continue

            # Существует?
            if not os.path.exists(path):
                skipped += 1
                continue

            # Папка?
            if os.path.isdir(path):
                skipped += 1
                continue

            # Симлинк?
            if os.path.islink(path):
                skipped += 1
                continue

            # .lnk — предупреждение.
            if path.lower().endswith(".lnk"):
                if not app_settings.get_flag("skip_lnk_confirm"):
                    answer, dont_ask = dialogs.show_confirm(
                        self.root,
                        i18n.t("confirm_lnk_title"),
                        i18n.t("confirm_lnk_text"),
                        height=310,
                        checkbox_text=i18n.t("dont_ask_again"),
                    )
                    if not answer:
                        skipped += 1
                        continue
                    if dont_ask:
                        app_settings.set_flag("skip_lnk_confirm", True)

            # Быстрая проверка на проблемы — пометка ⚠, НЕ блокировка.
            warn = False
            try:
                st = os.stat(path)
                if st.st_nlink > 1:
                    warn = True   # hard link
            except Exception:
                pass

            try:
                tag = os.lstat(path).st_reparse_tag
                if tag != 0:
                    warn = True       # OneDrive / reparse
            except (AttributeError, OSError):
                pass

            try:
                path_for_io = build_path_for_io(path)
                if is_compressed_encrypted_sparse(path_for_io):
                    warn = True       # сжат / EFS / sparse
            except Exception:
                pass

            # Запоминаем размер (чтобы потом не читать с диска в GUI).
            try:
                self._queue_sizes[path] = os.path.getsize(path)
            except Exception:
                self._queue_sizes[path] = 0

            # Добавляем в очередь.
            self._queue_paths.append(path)
            self._queue_canonical.add(canonical)
            self._queue_warnings[path] = warn
            added += 1

        # Обновляем UI.
        self._refresh_queue_list()
        self._update_queue_stats()
        self._refresh_queue_buttons()

        return added, skipped

    def _refresh_queue_list(self):
        """Перерисовывает список файлов в Treeview."""
        # Очищаем.
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        self._queue_tree_ids = {}

        # Динамическая высота: минимум 1, максимум 8 строк.
        # Уменьшили с 10 до 8, чтобы не закрывать фон.
        count = len(self._queue_paths)
        new_height = max(1, min(8, count))
        self.queue_tree.config(height=new_height)

        for idx, path in enumerate(self._queue_paths, start=1):
            name = _shorten_middle(os.path.basename(path), 40)
            size = self._queue_sizes.get(path, 0)
            # Если файла нет в словаре — значит, прочитать не удалось (ошибка).
            # Если файл там есть, но size == 0 — это валидный пустой файл.
            size_str = human_size(size) if path in self._queue_sizes else "—"

            warn_char = "⚠" if self._queue_warnings.get(path) else ""

            item_id = self.queue_tree.insert(
                "", "end",
                values=(idx, warn_char, name, size_str)
            )
            self._queue_tree_ids[item_id] = path

    def _update_queue_stats(self):
        """Обновляет счётчик файлов и общий размер."""
        count = len(self._queue_paths)
        total = 0
        for path in self._queue_paths:
            total += self._queue_sizes.get(path, 0)

        text = (i18n.t("queue_stat_files", n=count) + "      " +
                i18n.t("queue_stat_size", size=human_size(total)))
        self.canvas_queue.itemconfig(self.queue_stats_tag, text=text)

    def _refresh_queue_buttons(self):
        """Включает/выключает кнопки в зависимости от состояния очереди."""
        has_files = len(self._queue_paths) > 0

        # Кнопка добавления — активна всегда (кроме работы движка).
        if self.engine_running:
            self.queue_add_button.config(state="disabled")
        else:
            self.queue_add_button.config(state="normal")

        # Кнопка очистки — только если есть что очищать.
        if has_files and not self.engine_running:
            self.queue_clear_button.config(state="normal")
        else:
            self.queue_clear_button.config(state="disabled")

        # Кнопка СТАРТ — только если есть файлы и движок не работает.
        if has_files and not self.engine_running:
            self.queue_start_button.config(state="normal", bg=COLOR_ACCENT)
        else:
            self.queue_start_button.config(
                state="disabled", bg=COLOR_ACCENT_OFF
            )

    def _on_queue_clear(self):
        """Очищает очередь полностью."""
        if self.engine_running:
            return

        # Подтверждение, если очередь не пуста.
        if self._queue_paths:
            answer, _ = dialogs.show_confirm(
                self.root,
                i18n.t("queue_clear_confirm_title"),
                i18n.t("queue_clear_confirm_text", count=len(self._queue_paths)),
                height=200,
            )
            if not answer:
                return

        self._queue_paths = []
        self._queue_canonical = set()
        self._queue_warnings = {}
        self._queue_sizes = {}

        self._refresh_queue_list()
        self._update_queue_stats()
        self._refresh_queue_buttons()

    def _on_queue_delete_selected(self, event=None):
        """Удаляет выделенные в Treeview файлы из очереди."""
        if self.engine_running or self._queue_running:
            return

        selected = self.queue_tree.selection()
        if not selected:
            return

        # Собираем пути для удаления.
        to_remove = set()
        for item_id in selected:
            path = self._queue_tree_ids.get(item_id)
            if path:
                to_remove.add(path)

        # Фильтруем.
        new_paths = [p for p in self._queue_paths if p not in to_remove]
        self._queue_paths = new_paths

        # Пересобираем canonical и warnings.
        self._queue_canonical = set()
        for p in new_paths:
            try:
                self._queue_canonical.add(
                    os.path.normcase(os.path.abspath(p))
                )
            except Exception:
                pass

        self._queue_warnings = {
            p: w for p, w in self._queue_warnings.items() if p in new_paths
        }
        self._queue_sizes = {
            p: s for p, s in self._queue_sizes.items() if p in new_paths
        }

        self._refresh_queue_list()
        self._update_queue_stats()
        self._refresh_queue_buttons()

    # ========================================================
    #  ЗАГЛУШКИ ОБРАБОТКИ (шаги 6-9)
    # ========================================================

    def _on_queue_start(self):
        """Запускает обработку очереди."""
        if self._queue_running or not self._queue_paths:
            return

        # Общий диалог перед запуском.
        count = len(self._queue_paths)
        total_size = 0
        for path in self._queue_paths:
            try:
                total_size += os.path.getsize(path)
            except Exception:
                pass

        if not app_settings.get_flag("skip_confirm"):
            answer, dont_ask = dialogs.show_confirm(
                self.root,
                i18n.t("queue_confirm_title"),
                i18n.t("queue_confirm_text", count=count, size=human_size(total_size)),
                height=290,
                checkbox_text=i18n.t("dont_ask_again"),
            )
            if not answer:
                return
            if dont_ask:
                app_settings.set_flag("skip_confirm", True)

        # Подготовка состояния.
        self.engine_running = True   # ← блокируем весь UI
        self._queue_running = True
        self._queue_current_index = 0
        self._queue_results = []
        self._queue_total_bytes = total_size
        self._queue_done_bytes = 0
        self._queue_paused = False
        self._queue_stopped = False
        self._pause_event.set()

        # Для ETA.
        import time as _t
        self._queue_start_time = _t.time()
        self._queue_file_times = []

        # Сброс состояния hard links для новой очереди.
        self._hardlink_inode_decisions = {}
        self._hardlink_apply_to_all = None
        self._hardlink_event.clear()
        self._hardlink_answer = None
        self._hardlink_dont_ask = False

        # Блокируем кнопки.
        self._block_queue_buttons(True)

        # Сбрасываем прогрессы.
        self.queue_progress_total['value'] = 0
        self.queue_progress_current['value'] = 0
        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag, text=""
        )
        self._update_queue_total_progress(0)

        # Запускаем поток.
        threading.Thread(
            target=self._run_queue_engine,
            daemon=True
        ).start()

    def _block_queue_buttons(self, blocked):
        """Блокирует/разблокирует кнопки на время обработки."""
        if blocked:
            # Во время работы — добавлять/чистить/стартовать нельзя.
            self.queue_add_button.config(state="disabled")
            self.queue_clear_button.config(state="disabled")
            self.queue_start_button.config(
                state="disabled", bg=COLOR_ACCENT_OFF
            )
            # Пауза и стоп — доступны.
            self.queue_pause_button.config(
                state="normal", text=i18n.t("queue_btn_pause")
            )
            self.queue_stop_button.config(state="normal")
        else:
            # Обработка завершена — всё вернулось в норму.
            self._refresh_queue_buttons()
            self.queue_pause_button.config(
                state="disabled", text=i18n.t("queue_btn_pause")
            )
            self.queue_stop_button.config(state="disabled")

    def _update_queue_total_progress(self, current_index):
        """Обновляет общий прогресс по файлам + ETA."""
        import time as _t

        total = len(self._queue_paths)
        if total == 0:
            percent = 0
        else:
            percent = (current_index / total) * 100
        self.queue_progress_total['value'] = percent

        # Базовый текст.
        text = (i18n.t("queue_progress_total", current=current_index, total=total) +
                f"  ({human_size(self._queue_done_bytes)} / "
                f"{human_size(self._queue_total_bytes)})")

        # ETA — только если есть обработанные файлы и время старта.
        if (current_index > 0 and self._queue_file_times
                and self._queue_start_time > 0):
            elapsed = _t.time() - self._queue_start_time
            avg_per_file = sum(self._queue_file_times) / len(self._queue_file_times)
            remaining_files = total - current_index
            eta_seconds = int(avg_per_file * remaining_files)

            text += ("    " + i18n.t("queue_eta_elapsed", time=_format_duration(int(elapsed))) +
                     "    " + i18n.t("queue_eta_remaining", time=_format_duration(eta_seconds)))

        self.canvas_queue.itemconfig(
            self.queue_progress_total_tag, text=text
        )

    def _run_queue_engine(self):
        """
        Обрабатывает очередь файл за файлом. Работает в отдельном потоке.
        Не трогает tkinter напрямую — только кладёт события в queue.
        """
        import time
        total = len(self._queue_paths)

        processed_idx = -1
        try:
            for idx, path in enumerate(self._queue_paths):
                # Ждём, пока пользователь снимет паузу (или нажмёт стоп).
                while not self._pause_event.is_set():
                    time.sleep(0.1)

                if self._queue_stopped:
                    break

                processed_idx = idx
                self.queue.put(("queue_file_start", idx, path))

                # Проверка существования.
                if not os.path.exists(path):
                    self.queue.put(("queue_file_done", idx, path,
                                    "skipped", i18n.t("queue_reason_not_found"), 0))
                    continue

                # Получаем размер ДО любых проверок (файл скоро исчезнет).
                try:
                    size = os.path.getsize(path)
                except Exception:
                    size = 0

                # === Проверка hard links ===
                allow_hardlinks = False
                try:
                    st = os.stat(path)
                    nlink = st.st_nlink
                    inode_key = (st.st_dev, st.st_ino)
                except OSError:
                    nlink = 1
                    inode_key = None

                if nlink > 1 and inode_key is not None:
                    # Галочка «применять ко всем»?
                    if self._hardlink_apply_to_all is not None:
                        allow_hardlinks = (self._hardlink_apply_to_all == "yes")
                        if not allow_hardlinks:
                            self.queue.put(("queue_file_done", idx, path,
                                            "skipped",
                                            i18n.t("queue_reason_hardlink"), size))
                            continue
                    # Решение по конкретному inode?
                    elif inode_key in self._hardlink_inode_decisions:
                        decision = self._hardlink_inode_decisions[inode_key]
                        if decision == "no":
                            self.queue.put(("queue_file_done", idx, path,
                                            "skipped",
                                            i18n.t("queue_reason_hardlink_dup"), size))
                            continue
                        allow_hardlinks = True
                    else:
                        # Первый раз видим этот inode — спрашиваем.
                        answer, dont_ask = self._ask_hardlink_in_queue(
                            idx, path, nlink
                        )
                        if dont_ask:
                            self._hardlink_apply_to_all = "yes" if answer else "no"
                        if not answer:
                            self._hardlink_inode_decisions[inode_key] = "no"
                            self.queue.put(("queue_file_done", idx, path,
                                            "skipped",
                                            i18n.t("queue_reason_hardlink"), size))
                            continue
                        self._hardlink_inode_decisions[inode_key] = "yes"
                        allow_hardlinks = True

                # Полная валидация через check_file_strict.
                path_for_io = build_path_for_io(path)
                try:
                    check_file_strict(path_for_io,
                                      allow_hardlinks=allow_hardlinks)
                except FileRejectedError as e:
                    self.queue.put(("queue_file_done", idx, path,
                                    "skipped", str(e), size))
                    continue
                except Exception as e:
                    self.queue.put(("queue_file_done", idx, path,
                                    "skipped",
                                    f"{type(e).__name__}: {e}", size))
                    continue

                mode = "FULL"

                def sub_cb(step, message, sub, _idx=idx):
                    self.queue.put(("queue_file_progress", _idx, step,
                                    message, sub))

                result = shred_file(path, mode, progress_callback=sub_cb,
                                    allow_hardlinks=allow_hardlinks)

                if result.get("success"):
                    self.queue.put(("queue_file_done", idx, path,
                                    "done", "", size))
                else:
                    self.queue.put(("queue_file_done", idx, path,
                                    "failed",
                                    result.get("error") or i18n.t("error_unknown", err="unknown"),
                                    size))

            if self._queue_stopped:
                for i in range(processed_idx + 1, len(self._queue_paths)):
                    self.queue.put(("queue_file_done", i,
                                    self._queue_paths[i],
                                    "cancelled",
                                    i18n.t("queue_reason_cancelled"), 0))
        except Exception as e:
            # Страховка: если что-то фатально упало — отправляем ошибку.
            # Проверяем processed_idx, чтобы не отправить -1, если упало до цикла.
            if processed_idx >= 0:
                self.queue.put(("queue_file_done", processed_idx, "unknown", "failed", str(e), 0))
            
            # ВАЖНО: помечаем все оставшиеся файлы как отменённые,
            # чтобы _show_queue_summary не стёрла их из списка.
            for i in range(processed_idx + 1, len(self._queue_paths)):
                self.queue.put(("queue_file_done", i, self._queue_paths[i],
                                "cancelled", str(e), 0))
            
            # Принудительно включаем режим «остановлено»,
            # чтобы UI корректно обработал оставшиеся файлы.
            self._queue_stopped = True
        finally:
            # ГАРАНТИРОВАННЫЙ ФИНАЛ: UI всегда разблокируется.
            self.queue.put(("queue_all_done",))

    def _on_queue_pause(self):
        """Пауза / продолжение обработки очереди."""
        if not self._queue_running:
            return

        if not self._queue_paused:
            # Ставим на паузу.
            self._queue_paused = True
            self._pause_event.clear()
            self.queue_pause_button.config(text=i18n.t("queue_btn_resume"))
            self.canvas_queue.itemconfig(
                self.queue_progress_current_tag,
                text=i18n.t("queue_paused")
            )
        else:
            # Снимаем с паузы.
            self._queue_paused = False
            self._pause_event.set()
            self.queue_pause_button.config(text=i18n.t("queue_btn_pause"))

    def _on_queue_stop(self):
        """Останавливает очередь после текущего файла."""
        if not self._queue_running:
            return

        self._queue_stopped = True
        self._queue_paused = False
        self._pause_event.set()   # разблокировать поток

        # Кнопки паузы/стопа — недоступны.
        self.queue_pause_button.config(state="disabled", text=i18n.t("queue_btn_pause"))
        self.queue_stop_button.config(state="disabled")

        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag,
            text=i18n.t("queue_stopping")
        )

    def _build_single_ui(self, canvas):
        """Специфичная часть — только для одиночного режима."""
        cx = WIN_W // 2

        # --- СТРОКА ФАЙЛА ---
        self.file_text_tag = self._shadow_text(
            canvas, 40, 108, i18n.t("no_file"),
            _seg(11), COLOR_TEXT, anchor="w",
            width=WIN_W - 100
        )

        # Кнопка отмены.
        self.cancel_button = tk.Button(
            canvas, text="✕",
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
            canvas, i18n.t("choose_file"), self._on_choose_file
        )
        canvas.create_window(
            cx, 148, window=self.choose_button,
            width=180, height=34
        )

        # Подсказка.
        self.hint_tag = self._shadow_text(
            canvas, cx, 180, i18n.t("dnd_hint"),
            _seg(9, "italic"), COLOR_TEXT_DIM, anchor="center"
        )

        if not DND_AVAILABLE:
            canvas.itemconfig(self.hint_tag, text=i18n.t("dnd_unavailable"))

        # --- БЛОК «ИНФОРМАЦИЯ» ---
        info_left = 40
        self._shadow_text(
            canvas, info_left, 215, i18n.t("info_title"),
            _seg(11), COLOR_TEXT_TINY, anchor="w"
        )
        canvas.create_line(
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
            self._shadow_text(
                canvas, info_left, y, i18n.t(title_key),
                _seg(11), COLOR_TEXT_DIM, anchor="w"
            )
            self.info_tags[key] = self._shadow_text(
                canvas, info_left + 105, y, "—",
                _seg(11), COLOR_TEXT, anchor="w",
                width=WIN_W - 40 - (info_left + 105)
            )
            y += row_step

        self.strategy_y = y + 8
        self.strategy_left = info_left

        # --- КНОПКА УНИЧТОЖИТЬ ---
        self.shred_button = self._make_button(
            canvas, i18n.t("shred_button"),
            self._on_shred_click, primary=True, font_size=20
        )
        self.shred_button.config(state="disabled", bg=COLOR_ACCENT_OFF)
        canvas.create_window(
            cx, WIN_H - 220, window=self.shred_button,
            width=WIN_W - 80, height=64
        )

        # --- ПРОГРЕСС ---
        self.progress_bar = ttk.Progressbar(
            canvas, mode="determinate",
            maximum=100, length=WIN_W - 80
        )
        self._widgets.append(self.progress_bar)
        canvas.create_window(
            cx, WIN_H - 160, window=self.progress_bar,
            width=WIN_W - 80, height=18
        )

        self.progress_tag = self._shadow_text(
            canvas, cx, WIN_H - 133, "",
            _seg(9), COLOR_TEXT_DIM, anchor="center"
        )

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
        """
        Рисует логотипы RAMONAK + DeepSeek сразу на ОБОИХ canvas.
        Картинки загружаются один раз и переиспользуются —
        иначе вторая отрисовка удалит ссылку на первую.
        """
        if not PIL_AVAILABLE:
            return

        # Загружаем логотипы один раз, сохраняем ссылки.
        if self._my_logo_img is None:
            self._my_logo_img = self._load_logo(
                "my_logo.png", height=my_height
            )
        if self._ds_logo_img is None:
            self._ds_logo_img = self._load_logo(
                "deepseek_logo.png", height=ds_height
            )

        my_img = self._my_logo_img
        ds_img = self._ds_logo_img
        w1 = my_img.width() if my_img else 0
        w2 = ds_img.width() if ds_img else 0
        if w1 == 0 and w2 == 0:
            return

        total_w = w1 + w2 + (gap if (w1 and w2) else 0)
        start_x = cx - total_w // 2

        # Рисуем на обоих canvas сразу.
        for canvas in (self.canvas_single, self.canvas_queue):
            x = start_x
            if my_img:
                canvas.create_image(x, y, image=my_img, anchor="w")
                x += w1 + gap
            if ds_img:
                canvas.create_image(x, y, image=ds_img, anchor="w")

    # ========================================================
    #  ПЕРЕРИСОВКА ПРИ СМЕНЕ ЯЗЫКА
    # ========================================================

    def _rebuild_ui(self):
        """Полностью перерисовывает интерфейс. Вызывается после смены языка."""
        for w in self._widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._widgets = []

        # Очищаем оба canvas.
        self.canvas_single.delete("all")
        self.canvas_queue.delete("all")

        # Сбрасываем счётчики текста.
        self._text_counters = {"single": 0, "queue": 0}

        # Сбрасываем ссылки на логотипы и фоны — будут перезагружены.
        self._my_logo_img = None
        self._ds_logo_img = None
        self.bg_single = None
        self.bg_queue = None

        self.root.title(i18n.t("window_title"))

        # Пересобираем оба canvas.
        self._build_ui()

        # Обновляем текст кнопки языка.
        if hasattr(self, "lang_button"):
            self.lang_button.config(text=f"{i18n.get_language().upper()} ▾")

        # Кнопки — поверх и с обновлённым текстом.
        if hasattr(self, "toggle_button"):
            # ВАЖНО: обновляем текст кнопки переключения режимов,
            # иначе при смене языка он останется старым до первого клика.
            toggle_text = (
                i18n.t("queue_toggle_to_queue")
                if self._active_mode == "single"
                else i18n.t("queue_toggle_to_single")
            )
            self.toggle_button.config(text=toggle_text)
            self.toggle_button.lift()
        if hasattr(self, "lang_button"):
            self.lang_button.lift()
        if hasattr(self, "sound_button"):
            self.sound_button.config(
                text="🔊" if self.sound_enabled else "🔇"
            )
            self.sound_button.lift()

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
            if self.engine_running or self._queue_running:
                return
            try:
                paths = self.root.tk.splitlist(event.data)
            except Exception:
                return
            if not paths:
                return
            paths = [os.path.normpath(p) for p in paths]

            if self._active_mode == "single":
                if len(paths) == 1:
                    self._set_selected_file(paths[0])
                else:
                    # 2+ файлов → автопереключение в очередь.
                    self._toggle_mode()
                    self._add_to_queue(paths)
            else:
                # Уже в очереди — просто добавляем.
                self._add_to_queue(paths)

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

        # Играем звук, только если он включён.
        if self.sound_enabled:
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

                # --- Очередь ---
                elif msg[0] == "queue_file_start":
                    _, idx, path = msg
                    self._on_queue_file_start(idx, path)

                elif msg[0] == "queue_file_progress":
                    _, idx, step, message, sub = msg
                    self._on_queue_file_progress(idx, step, message, sub)

                elif msg[0] == "queue_file_done":
                    _, idx, path, status, reason, size = msg
                    self._on_queue_file_done(idx, path, status, reason, size)

                elif msg[0] == "queue_all_done":
                    self._on_queue_all_done()

                elif msg[0] == "queue_ask_hardlink":
                    _, idx, path, nlink = msg
                    self._on_queue_ask_hardlink(idx, path, nlink)

        except queue.Empty:
            pass

        try:
            self.root.after(100, self._pump_queue)
        except tk.TclError:
            pass

    def _on_queue_ask_hardlink(self, idx, path, nlink):
        """
        Показывает диалог hard link. Вызывается из главного потока.
        Записывает ответ в атрибуты и разблокирует фоновый поток.
        """
        name = _shorten_middle(os.path.basename(path), 40)
        answer, dont_ask = dialogs.show_hardlink_dialog(
            self.root, name, nlink
        )
        self._hardlink_answer = answer
        self._hardlink_dont_ask = dont_ask
        # Разблокируем фоновый поток.
        self._hardlink_event.set()

    def _on_queue_file_start(self, idx, path):
        """Началась обработка файла №idx."""
        import time as _t
        self._queue_current_index = idx
        self._queue_file_start_time = _t.time()

        # Обновляем подсветку в Treeview.
        item_ids = self.queue_tree.get_children()
        if idx < len(item_ids):
            self.queue_tree.selection_remove(self.queue_tree.selection())
            self.queue_tree.selection_set(item_ids[idx])
            self.queue_tree.see(item_ids[idx])

        name = _shorten_middle(os.path.basename(path), 50)
        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag,
            text=i18n.t("queue_working", name=name)
        )

    def _ask_hardlink_in_queue(self, idx, path, nlink):
        """
        Спрашивает пользователя про hard link из фонового потока.
        Через queue.Queue и threading.Event — tkinter нельзя
        трогать из не-главного потока.

        Возвращает (answer, dont_ask):
          answer   — True = уничтожить, False = пропустить.
          dont_ask — True = применить ко всем.
        """
        # Сбрасываем состояние.
        self._hardlink_event.clear()
        self._hardlink_answer = None
        self._hardlink_dont_ask = False

        # Кладём событие в очередь для главного потока.
        self.queue.put(("queue_ask_hardlink", idx, path, nlink))

        # Ждём ответа (главный поток выставит Event).
        self._hardlink_event.wait()

        return self._hardlink_answer, self._hardlink_dont_ask

    def _on_queue_file_progress(self, idx, step, message, sub):
        """Прогресс по текущему файлу."""
        overall = ((step - 1) + sub) / TOTAL_STEPS * 100
        self.queue_progress_current['value'] = overall

        name = _shorten_middle(
            os.path.basename(self._queue_paths[idx]), 40
        )
        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag,
            text=i18n.t("queue_progress_current", name=name, step=step, total=TOTAL_STEPS, pct=int(sub*100))
        )

    def _on_queue_file_done(self, idx, path, status, reason, size):
        """Обработка файла завершена."""
        import time as _t

        # Время обработки этого файла.
        if hasattr(self, "_queue_file_start_time"):
            elapsed = _t.time() - self._queue_file_start_time
            self._queue_file_times.append(elapsed)

        self._queue_results.append({
            "path": path,
            "status": status,
            "reason": reason,
        })

        # Считаем обработанные байты по переданному size.
        if status == "done":
            self._queue_done_bytes += size

        self._queue_current_index = idx + 1
        self._update_queue_total_progress(idx + 1)

    def _on_queue_all_done(self):
        """Вся очередь обработана (или остановлена пользователем)."""
        was_stopped = self._queue_stopped

        self._queue_running = False
        self.engine_running = False  # ← разблокируем UI
        self._queue_paused = False
        self._queue_stopped = False
        self._pause_event.set()

        # Прогресс — 100%, если всё завершено. Иначе оставляем как есть.
        if not was_stopped:
            self.queue_progress_total['value'] = 100
        self.queue_progress_current['value'] = 0
        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag, text=""
        )

        # Разблокируем кнопки.
        self._block_queue_buttons(False)

        # Показываем сводку (с флагом «остановлено»).
        self._show_queue_summary(was_stopped=was_stopped)

        # Сбрасываем состояние.
        self._queue_current_index = 0

    def _show_queue_summary(self, was_stopped=False):
        """Сводный отчёт по завершении очереди + очистка списка."""
        done = sum(1 for r in self._queue_results if r["status"] == "done")
        skipped = sum(1 for r in self._queue_results
                      if r["status"] == "skipped")
        failed = sum(1 for r in self._queue_results
                     if r["status"] == "failed")
        cancelled = sum(1 for r in self._queue_results
                        if r["status"] == "cancelled")
        total = len(self._queue_results)

        # Сколько было всего в очереди на момент старта.
        original_total = len(self._queue_paths)
        cancelled = 0
        if was_stopped:
            cancelled = original_total - total

        # Собираем уникальные причины пропусков.
        reasons = {}
        for r in self._queue_results:
            if r["status"] == "skipped" and r["reason"]:
                reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1

        # Формируем короткую сводку.
        lines = []
        if was_stopped:
            lines.append(i18n.t("queue_report_done_of", done=done, total=original_total))
            lines.append(i18n.t("queue_report_cancelled_by_user"))
            if cancelled:
                lines.append(i18n.t("queue_report_cancelled", n=cancelled))
        else:
            lines.append(i18n.t("queue_report_total", n=total))
            lines.append("")
            lines.append(i18n.t("queue_report_done", n=done))
            if skipped:
                lines.append(i18n.t("queue_report_skipped", n=skipped))
                for reason, count in list(reasons.items())[:5]:
                    lines.append(f"  • {reason[:60]}: {count}")
            if failed:
                lines.append(i18n.t("queue_report_failed", n=failed))

        summary = "\n".join(lines)

        # Готовим детальные строки для кнопки «ПОКАЗАТЬ ДЕТАЛИ».
        details_rows = []
        for r in self._queue_results:
            details_rows.append({
                "name": _shorten_middle(
                    os.path.basename(r["path"]), 40
                ),
                "status": r["status"],
                "reason": r.get("reason", "") or "",
            })

        # Показываем расширенный отчёт.
        dialogs.show_queue_report(
            self.root,
            summary,
            details_rows,
            was_stopped=was_stopped,
            has_errors=(failed > 0),  # ← ошибка только если был failed
        )

        # Формируем новый список файлов.
        if was_stopped:
            # При СТОП — оставляем в очереди файлы, которые НЕ были
            # реально обработаны (done/skipped/failed).
            # Отменённые (cancelled) тоже остаются в списке!
            processed = {r["path"] for r in self._queue_results
                         if r["status"] != "cancelled"}
            remaining = [p for p in self._queue_paths
                         if p not in processed]
            self._queue_paths = remaining
            self._queue_sizes = {p: s for p, s in self._queue_sizes.items() if p in remaining}

            # Пересобираем canonical.
            self._queue_canonical = set()
            for p in remaining:
                try:
                    self._queue_canonical.add(
                        os.path.normcase(os.path.abspath(p))
                    )
                except Exception:
                    pass

            # Пересобираем warnings — только для оставшихся.
            self._queue_warnings = {
                p: w for p, w in self._queue_warnings.items()
                if p in remaining
            }
        else:
            # Всё обработано — очередь пуста.
            self._queue_paths = []
            self._queue_canonical = set()
            self._queue_warnings = {}
            self._queue_sizes = {}

        # Результаты текущей сессии — сбрасываем в любом случае.
        self._queue_results = []
        self._queue_done_bytes = 0
        self._queue_total_bytes = 0

        self._refresh_queue_list()
        self._update_queue_stats()
        self._refresh_queue_buttons()

        # Прогресс-бары — в ноль (следующая обработка начнётся заново).
        self.queue_progress_total['value'] = 0
        self.queue_progress_current['value'] = 0
        self.canvas_queue.itemconfig(
            self.queue_progress_total_tag,
            text=i18n.t("queue_progress_total", current=0, total=0)
        )
        self.canvas_queue.itemconfig(
            self.queue_progress_current_tag, text=""
        )

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

def _format_duration(seconds: int) -> str:
    """
    Форматирует секунды в «M:SS» или «H:MM:SS».
    Примеры: 45 → «0:45», 125 → «2:05», 3725 → «1:02:05».
    """
    if seconds < 0:
        return "—"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

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