r"""
dialogs.py — модальные диалоги программы «ШРЕДДЕР».

Все всплывающие окна (подтверждение, ошибка, отчёт) живут здесь,
чтобы gui.py не разрастался.

Каждая функция принимает parent — главное окно tkinter,
чтобы правильно центрироваться и брать иконку.
"""

import tkinter as tk
from tkinter import ttk

from src import i18n
from src.theme import (
    COLOR_PANEL, COLOR_TEXT, COLOR_TEXT_DIM,
    COLOR_ACCENT, COLOR_ACCENT_HOV,
    COLOR_BTN, COLOR_BTN_HOV,
    _seg,
)
from src.utils import resource_path, human_size


# ============================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def set_icon(window):
    """Ставит иконку Шреддера на окно. Молча, если файла нет."""
    try:
        window.iconbitmap(resource_path("assets/icon.ico"))
    except Exception:
        pass


def center_on_parent(parent, win, width, height):
    """
    Центрирует диалог win относительно главного окна parent.
    Надёжно работает даже из DnD-обработчика:
    ставит размер+позицию сейчас и повторяет через 50 мс.
    """
    win.geometry(f"{width}x{height}")

    def _apply():
        try:
            if not win.winfo_exists():
                return
            parent.update_idletasks()
            win.update_idletasks()

            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()

            # Если главное окно ещё не отрисовано — центрируем на экране.
            if pw < 100 or ph < 100:
                sw = win.winfo_screenwidth()
                sh = win.winfo_screenheight()
                x = (sw - width) // 2
                y = (sh - height) // 2
            else:
                x = px + (pw - width) // 2
                y = py + (ph - height) // 2

            win.geometry(f"{width}x{height}+{x}+{y}")
            win.deiconify()
            win.lift()
            win.focus_force()
        except tk.TclError:
            pass

    _apply()
    try:
        win.after(50, _apply)
    except tk.TclError:
        pass


def _dialog_button(parent, text, command,
                   primary=False, width=12, font_size=10):
    """Плоская кнопка для диалогов — с hover-эффектом."""
    bg = COLOR_ACCENT if primary else COLOR_BTN
    hov = COLOR_ACCENT_HOV if primary else COLOR_BTN_HOV

    btn = tk.Button(
        parent, text=text,
        font=_seg(font_size, "bold"),
        fg="#ffffff", bg=bg,
        activeforeground="#ffffff",
        activebackground=hov,
        relief="flat", bd=0,
        cursor="hand2",
        width=width, height=1,
        command=command
    )

    def on_enter(_):
        btn.config(bg=hov)

    def on_leave(_):
        btn.config(bg=bg)

    btn.bind('<Enter>', on_enter)
    btn.bind('<Leave>', on_leave)
    return btn


# ============================================================
#  ДИАЛОГ ПОДТВЕРЖДЕНИЯ (ДА/НЕТ)
# ============================================================

def show_confirm(parent, title, message, height=250, checkbox_text=None):
    """
    Кастомный диалог ДА/НЕТ.
    Возвращает (answer, dont_ask):
      answer   — True если нажали «Да».
      dont_ask — True если чекбокс был отмечен и нажали «Да».

    checkbox_text — если задано, показывает чекбокс с этим текстом.
    """
    result = {"answer": False, "dont_ask": False}

    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 460, height)

    tk.Label(
        win, text="⚠  " + title,
        font=_seg(13, "bold"),
        fg="#ffcc66", bg=COLOR_PANEL
    ).pack(pady=(20, 15))

    tk.Label(
        win, text=message,
        font=_seg(11),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        wraplength=400, justify="left"
    ).pack(padx=25, pady=(0, 15))

    check_var = None
    if checkbox_text:
        check_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            win, text=checkbox_text,
            variable=check_var,
            font=_seg(9),
            fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
            activeforeground=COLOR_TEXT,
            activebackground=COLOR_PANEL,
            selectcolor="#333333",
            bd=0, cursor="hand2",
            highlightthickness=0
        ).pack(padx=25, anchor="w", pady=(0, 10))

    btn_frame = tk.Frame(win, bg=COLOR_PANEL)
    btn_frame.pack(pady=(0, 20))

    def on_no():
        result["answer"] = False
        win.destroy()

    def on_yes():
        result["answer"] = True
        if check_var is not None:
            result["dont_ask"] = check_var.get()
        win.destroy()

    no_btn = _dialog_button(btn_frame, i18n.t("no"), on_no, primary=False)
    no_btn.pack(side="left", padx=8)

    yes_btn = _dialog_button(btn_frame, i18n.t("yes"), on_yes, primary=True)
    yes_btn.pack(side="left", padx=8)

    win.bind("<Escape>", lambda e: on_no())

    try:
        win.wait_window()
    except tk.TclError:
        pass

    return result["answer"], result["dont_ask"]


# ============================================================
#  ДИАЛОГ ОШИБКИ
# ============================================================

def show_error(parent, title, message):
    """Кастомный диалог ошибки с одной кнопкой OK."""
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 460, 250)

    tk.Label(
        win, text="❌  " + title,
        font=_seg(13, "bold"),
        fg="#ef5350", bg=COLOR_PANEL
    ).pack(pady=(20, 15))

    tk.Label(
        win, text=message,
        font=_seg(10),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        wraplength=400, justify="left"
    ).pack(padx=25, pady=(0, 25))

    ok_btn = _dialog_button(
        win, i18n.t("ok_button"), win.destroy,
        primary=False, width=15, font_size=11
    )
    ok_btn.pack(pady=(0, 20))

    win.bind("<Escape>", lambda e: win.destroy())

    try:
        win.wait_window()
    except tk.TclError:
        pass

# ============================================================
#  ОТЧЁТ ОБ УНИЧТОЖЕНИИ
# ============================================================

def show_success_report(parent, result, checkbox_text=None):
    """
    Показывает отчёт после успешного уничтожения.
    Возвращает True, если пользователь отметил «Не показывать снова».
    """
    answer = {"dont_show": False}

    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(i18n.t("report_window_title"))
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 540, 430)

    tk.Label(
        win, text=i18n.t("report_title"),
        font=_seg(14, "bold"),
        fg="#4caf50", bg=COLOR_PANEL
    ).pack(pady=(18, 12))

    mode_key = {
        "FULL": "report_mode_full",
        "FAST": "report_mode_fast",
        "EMPTY": "report_mode_empty",
    }.get(result['mode'], result['mode'])

    info = (
        f"{i18n.t('report_was')}           {result['original_name']}  "
        f"({human_size(result['original_size'])})\n"
        f"{i18n.t('report_final_name')}  {result['final_name']}  "
        f"({result['final_size']} {i18n.t('unit_b')})\n"
        f"{i18n.t('report_strategy')}      {i18n.t(mode_key)}"
    )
    tk.Label(
        win, text=info,
        font=("Consolas", 10),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        justify="left", anchor="w"
    ).pack(padx=20, pady=5, fill="x")

    tk.Label(
        win, text=result['status_message'],
        font=_seg(10),
        fg="#ffcc66", bg=COLOR_PANEL,
        wraplength=480, justify="left"
    ).pack(padx=20, pady=(12, 6), fill="x")

    tk.Label(
        win, text=i18n.t("report_limits_title"),
        font=_seg(10, "bold"),
        fg="#ef9a9a", bg=COLOR_PANEL
    ).pack(padx=20, pady=(8, 2), anchor="w")

    tk.Label(
        win, text=i18n.t("report_limits"),
        font=_seg(9),
        fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
        justify="left"
    ).pack(padx=30, pady=(0, 8), anchor="w")

    check_var = None
    if checkbox_text:
        check_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            win, text=checkbox_text,
            variable=check_var,
            font=_seg(9),
            fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
            activeforeground=COLOR_TEXT,
            activebackground=COLOR_PANEL,
            selectcolor="#333333",
            bd=0, cursor="hand2",
            highlightthickness=0
        ).pack(padx=30, anchor="w", pady=(0, 8))

    def on_close(_event=None):
        if check_var is not None:
            answer["dont_show"] = check_var.get()
        win.destroy()

    ok_btn = _dialog_button(
        win, i18n.t("ok_button"), on_close,
        primary=False, width=15, font_size=11
    )
    ok_btn.pack(pady=10, ipadx=40, ipady=6)

    win.bind("<Escape>", on_close)
    win.protocol("WM_DELETE_WINDOW", on_close)

    try:
        win.wait_window()
    except tk.TclError:
        pass

    return answer["dont_show"]

# ============================================================
#  ИНФОРМАЦИОННЫЙ ДИАЛОГ (успех / справка)
# ============================================================

def show_info(parent, title, message, height=280):
    """Информационный диалог с иконкой ✅ и одной кнопкой OK."""
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 460, height)

    tk.Label(
        win, text="✅  " + title,
        font=_seg(13, "bold"),
        fg="#4caf50", bg=COLOR_PANEL
    ).pack(pady=(20, 15))

    tk.Label(
        win, text=message,
        font=_seg(10),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        wraplength=400, justify="left"
    ).pack(padx=25, pady=(0, 25))

    ok_btn = _dialog_button(
        win, i18n.t("ok_button"), win.destroy,
        primary=False, width=15, font_size=11
    )
    ok_btn.pack(pady=(0, 20))

    win.bind("<Escape>", lambda e: win.destroy())

    try:
        win.wait_window()
    except tk.TclError:
        pass

# ============================================================
#  ДИАЛОГ ВЫБОРА ЯЗЫКА
# ============================================================

# Топ языков по мировой значимости.
POPULAR_LANGS = ["en", "de", "fr", "it", "es", "es-419", "pt-PT", "pt-BR", "ru", "uk", "pl", "tr", "ar", "ko", "zh-Hans", "ja", "hi"]

# Ссылка на текущее открытое окно выбора языка (или None).
_lang_picker_win = None


def show_language_picker(parent, current_lang, on_apply):
    """
    Показывает окно выбора языка.

    Защита от двойного открытия: если окно уже открыто — поднимаем его
    и выходим. Ссылка хранится на уровне модуля, потому что внутри
    функции управление блокируется на wait_window.
    """
    global _lang_picker_win

    # Уже открыто — поднимаем и выходим.
    if _lang_picker_win is not None:
        try:
            if _lang_picker_win.winfo_exists():
                _lang_picker_win.lift()
                _lang_picker_win.focus_force()
                return
        except Exception:
            pass

    from src import i18n as _i18n

    langs = _i18n.available_languages()   # {"ru": "Русский", ...}
    if not langs:
        return

    win = tk.Toplevel(parent)
    # Скрываем, пока настраиваем — иначе мелькнёт в углу.
    win.withdraw()
    _lang_picker_win = win
    win.title(_i18n.t("lang_dialog_title"))
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 460, 600)

    tk.Label(
        win, text=_i18n.t("lang_dialog_title"),
        font=_seg(13, "bold"),
        fg=COLOR_TEXT, bg=COLOR_PANEL
    ).pack(pady=(15, 10))

    # Поле поиска.
    search_frame = tk.Frame(win, bg=COLOR_PANEL)
    search_frame.pack(fill="x", padx=20, pady=(0, 8))

    search_var = tk.StringVar()
    search_entry = tk.Entry(
        search_frame, textvariable=search_var,
        font=_seg(11),
        bg="#1a1a1a", fg=COLOR_TEXT,
        insertbackground=COLOR_TEXT,
        relief="flat", bd=0,
        highlightthickness=1,
        highlightbackground="#333333",
        highlightcolor=COLOR_ACCENT
    )
    search_entry.pack(fill="x", ipady=6, ipadx=8)

    # Placeholder (подсказка) в поле поиска.
    placeholder = _i18n.t("search_placeholder")
    PLACEHOLDER_FG = "#666666"
    NORMAL_FG = COLOR_TEXT

    def _on_focus_in(_event):
        if search_entry.get() == placeholder:
            search_entry.delete(0, "end")
            search_entry.config(fg=NORMAL_FG)

    def _on_focus_out(_event):
        if not search_entry.get().strip():
            search_entry.delete(0, "end")
            search_entry.insert(0, placeholder)
            search_entry.config(fg=PLACEHOLDER_FG)

    search_entry.insert(0, placeholder)
    search_entry.config(fg=PLACEHOLDER_FG)
    search_entry.bind("<FocusIn>", _on_focus_in)
    search_entry.bind("<FocusOut>", _on_focus_out)
    # focus_set() НЕ вызываем — иначе <FocusIn> сработает сразу
    # и placeholder исчезнет. Пользователь кликнет сам.

    # Список.
    list_frame = tk.Frame(win, bg=COLOR_PANEL)
    list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    listbox = tk.Listbox(
        list_frame,
        font=_seg(11),
        bg="#1a1a1a", fg=COLOR_TEXT,
        selectbackground=COLOR_ACCENT,
        selectforeground="#ffffff",
        relief="flat", bd=0,
        highlightthickness=0,
        activestyle="none"
    )
    listbox.pack(side="left", fill="both", expand=True)

    scrollbar = tk.Scrollbar(list_frame, command=listbox.yview)
    scrollbar.pack(side="right", fill="y")
    listbox.config(yscrollcommand=scrollbar.set)

    current_data = []   # индекс строки → код языка (или None для разделителя)

    def build_list(query=""):
        nonlocal current_data
        listbox.delete(0, "end")
        current_data = []

        q = query.lower().strip()
        popular_set = set(POPULAR_LANGS)

        popular = [(c, langs[c]) for c in POPULAR_LANGS if c in langs]
        others = [(c, n) for c, n in langs.items() if c not in popular_set]
        others.sort(key=lambda x: x[1].lower())

        if q:
            popular = [p for p in popular
                       if q in p[1].lower() or q in p[0].lower()]
            others = [o for o in others
                      if q in o[1].lower() or q in o[0].lower()]

        for code, name in popular:
            listbox.insert("end", f"  {name}  ({code})")
            current_data.append(code)

        if popular and others:
            listbox.insert("end", "")
            current_data.append(None)

        for code, name in others:
            listbox.insert("end", f"  {name}  ({code})")
            current_data.append(code)

        try:
            idx = current_data.index(current_lang)
            listbox.selection_set(idx)
            listbox.see(idx)
        except ValueError:
            pass

    build_list()

    def on_search_change(*_):
        text = search_var.get()
        # Игнорируем placeholder — это не запрос пользователя.
        if text == placeholder:
            return
        build_list(text)

    search_var.trace_add("write", on_search_change)

    def on_select(_event=None):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(current_data) and current_data[idx] is None:
            listbox.selection_clear(0, "end")

    listbox.bind("<<ListboxSelect>>", on_select)

    result = {"code": None}

    def on_ok(_event=None):
        sel = listbox.curselection()
        if sel:
            idx = sel[0]
            if idx < len(current_data) and current_data[idx] is not None:
                result["code"] = current_data[idx]
        win.destroy()

    def on_cancel(_event=None):
        win.destroy()

    listbox.bind("<Double-Button-1>", on_ok)
    search_entry.bind("<Return>", on_ok)
    win.bind("<Escape>", on_cancel)

    # Кнопки.
    btn_frame = tk.Frame(win, bg=COLOR_PANEL)
    btn_frame.pack(pady=(0, 15))

    cancel_btn = _dialog_button(
        btn_frame, _i18n.t("lang_dialog_cancel"),
        on_cancel, primary=False, width=10
    )
    cancel_btn.pack(side="left", padx=5)

    ok_btn = _dialog_button(
        btn_frame, _i18n.t("lang_dialog_ok"),
        on_ok, primary=True, width=10
    )
    ok_btn.pack(side="left", padx=5)

    try:
        win.wait_window()
    except tk.TclError:
        pass

    # Окно закрыто — сбрасываем глобальную ссылку.
    _lang_picker_win = None

    # Применяем выбор — вызываем колбэк.
    new_code = result["code"]
    if new_code and new_code != current_lang:
        on_apply(new_code)

# ============================================================
#  ДИАЛОГ HARD LINK (для очереди)
# ============================================================

def show_hardlink_dialog(parent, filename, nlink, height=310):
    """
    Диалог для hard link с галочкой «применять ко всем».
    Возвращает (answer, dont_ask):
      answer   — True = уничтожить, False = пропустить.
      dont_ask — True = применить ко всем hard links в очереди.
    """
    result = {"answer": False, "dont_ask": False}

    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(i18n.t("hardlink_title"))
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 480, height)

    tk.Label(
        win, text="⚠  " + i18n.t("hardlink_title"),
        font=_seg(13, "bold"),
        fg="#ffcc66", bg=COLOR_PANEL
    ).pack(pady=(20, 15))

    msg = i18n.t("hardlink_text", name=filename, nlink=nlink)
    tk.Label(
        win, text=msg,
        font=_seg(10),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        wraplength=430, justify="left"
    ).pack(padx=25, pady=(0, 12))

    check_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        win, text=i18n.t("hardlink_apply_all"),
        variable=check_var,
        font=_seg(9),
        fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
        activeforeground=COLOR_TEXT,
        activebackground=COLOR_PANEL,
        selectcolor="#333333",
        bd=0, cursor="hand2",
        highlightthickness=0
    ).pack(padx=25, anchor="w", pady=(0, 12))

    btn_frame = tk.Frame(win, bg=COLOR_PANEL)
    btn_frame.pack(pady=(0, 20))

    def on_skip():
        result["answer"] = False
        result["dont_ask"] = check_var.get()
        win.destroy()

    def on_destroy():
        result["answer"] = True
        result["dont_ask"] = check_var.get()
        win.destroy()

    skip_btn = _dialog_button(
        btn_frame, i18n.t("hardlink_skip"), on_skip,
        primary=False, width=13
    )
    skip_btn.pack(side="left", padx=8)

    destroy_btn = _dialog_button(
        btn_frame, i18n.t("hardlink_destroy"), on_destroy,
        primary=True, width=13
    )
    destroy_btn.pack(side="left", padx=8)

    win.bind("<Escape>", lambda e: on_skip())

    try:
        win.wait_window()
    except tk.TclError:
        pass

    return result["answer"], result["dont_ask"]

# ============================================================
#  СВОДНЫЙ ОТЧЁТ ПО ОЧЕРЕДИ (с деталями)
# ============================================================

def show_queue_report(parent, summary_text, details_rows,
                      was_stopped=False, has_errors=False):
    """
    Сводный отчёт по завершении очереди.
    С кнопкой «ПОКАЗАТЬ ДЕТАЛИ» — открывает список с причинами.

    Параметры:
      summary_text  — текст сводки (общая часть).
      details_rows  — список словарей:
                        [{"name": str, "status": str, "reason": str}, ...]
      was_stopped   — True если очередь была прервана.
      has_errors    — True если были ошибки/пропуски (красная иконка).
    """
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(i18n.t("queue_report_title"))
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 520, 400)

    icon = "❌" if has_errors else "✅"
    color = "#ef5350" if has_errors else "#4caf50"

    tk.Label(
        win, text=f"{icon}  {i18n.t('queue_report_title')}",
        font=_seg(14, "bold"),
        fg=color, bg=COLOR_PANEL
    ).pack(pady=(18, 12))

    tk.Label(
        win, text=summary_text,
        font=_seg(10),
        fg=COLOR_TEXT, bg=COLOR_PANEL,
        justify="left", wraplength=460
    ).pack(padx=25, pady=(0, 15), fill="x")

    btn_frame = tk.Frame(win, bg=COLOR_PANEL)
    btn_frame.pack(pady=(0, 20))

    def on_details():
        win.destroy()
        _show_queue_details(parent, details_rows)

    details_btn = _dialog_button(
        btn_frame, i18n.t("queue_report_details_btn"), on_details,
        primary=False, width=18, font_size=10
    )
    details_btn.pack(side="left", padx=8)

    ok_btn = _dialog_button(
        btn_frame, i18n.t("ok_button"), win.destroy,
        primary=True, width=12, font_size=10
    )
    ok_btn.pack(side="left", padx=8)

    win.bind("<Escape>", lambda e: win.destroy())

    try:
        win.wait_window()
    except tk.TclError:
        pass


def _show_queue_details(parent, details_rows):
    """Отдельное окно со списком результатов по каждому файлу."""
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(i18n.t("queue_details_title"))
    set_icon(win)
    win.configure(bg=COLOR_PANEL)
    win.resizable(False, False)
    win.transient(parent)
    center_on_parent(parent, win, 650, 580)

    tk.Label(
        win, text=i18n.t("queue_details_title"),
        font=_seg(13, "bold"),
        fg=COLOR_TEXT, bg=COLOR_PANEL
    ).pack(pady=(15, 10))

    # Treeview с результатами.
    tree_frame = tk.Frame(win, bg=COLOR_PANEL)
    tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    tree = ttk.Treeview(
        tree_frame,
        columns=("name", "status", "reason"),
        show="headings",
        height=15,
        selectmode="browse",
        style="Queue.Treeview",
    )
    tree.heading("name", text=i18n.t("queue_details_file"))
    tree.heading("status", text=i18n.t("queue_details_status"))
    tree.heading("reason", text=i18n.t("queue_details_reason"))
    tree.column("name", width=220, anchor="w")
    tree.column("status", width=90, anchor="center", stretch=False)
    tree.column("reason", width=260, anchor="w")

    scroll = ttk.Scrollbar(
        tree_frame, orient="vertical", command=tree.yview
    )
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    status_map = {
        "done":      (i18n.t("queue_status_done"), "#4caf50"),
        "skipped":   (i18n.t("queue_status_skipped"), "#ffcc66"),
        "failed":    (i18n.t("queue_status_failed"), "#ef5350"),
        "cancelled": (i18n.t("queue_status_cancelled"), "#aaaaaa"),
    }

    for row in details_rows:
        name = row.get("name", "—")
        status = row.get("status", "—")
        reason = row.get("reason", "") or ""

        status_label = status_map.get(status, (status, "#ffffff"))[0]
        tree.insert(
            "", "end",
            values=(name, status_label, reason)
        )

    ok_btn = _dialog_button(
        win, i18n.t("ok_button"), win.destroy,
        primary=False, width=15, font_size=11
    )
    ok_btn.pack(pady=(0, 20))

    win.bind("<Escape>", lambda e: win.destroy())

    try:
        win.wait_window()
    except tk.TclError:
        pass