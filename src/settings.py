r"""
settings.py — сохранение настроек программы (например, выбранного языка).

Файл settings.json хранится в %APPDATA%\Shredder\settings.json
(стандартная скрытая папка Windows для настроек программ).

Пользователь её не видит и не замечает. Это чистый подход:
программа не засоряет рабочий стол и не пугает людей.
"""

import json
import os

# Язык по умолчанию (если файла нет).
DEFAULT_LANGUAGE = "en"

def _settings_dir() -> str:
    """
    Возвращает папку для settings.json:
    %APPDATA%\\Shredder\\
    Если %APPDATA% почему-то нет — используем папку пользователя.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        folder = os.path.join(appdata, "Shredder")
    else:
        # Резерв — папка пользователя.
        folder = os.path.join(os.path.expanduser("~"), ".shredder")

    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass
    return folder

SETTINGS_FILE = os.path.join(_settings_dir(), "settings.json")

def load_settings() -> dict:
    """
    Читает settings.json. Если файла нет или он битый —
    возвращает словарь со значениями по умолчанию.
    """
    if not os.path.isfile(SETTINGS_FILE):
        return {"language": DEFAULT_LANGUAGE}

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "language" not in data:
            data["language"] = DEFAULT_LANGUAGE
        return data
    except Exception:
        return {"language": DEFAULT_LANGUAGE}

def save_settings(data: dict) -> None:
    """
    Записывает настройки в settings.json.

    Автоматически удаляет устаревшие ключи skip_* — эти флаги
    теперь хранятся только в памяти (см. блок «ФЛАГИ» ниже).
    """
    clean = {k: v for k, v in data.items() if not k.startswith("skip_")}
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_language() -> str:
    """Возвращает текущий код языка (например, 'ru')."""
    return load_settings().get("language", DEFAULT_LANGUAGE)

def set_language(code: str) -> None:
    """Сохраняет выбранный язык."""
    data = load_settings()
    data["language"] = code
    save_settings(data)

# ============================================================
#  ФЛАГИ «НЕ СПРАШИВАТЬ / НЕ ПОКАЗЫВАТЬ»
# ============================================================
#
# ВАЖНО: это защитный барьер. Программа безвозвратно удаляет файлы,
# поэтому диалоги должны возвращаться при каждом перезапуске.
# Флаги живут ТОЛЬКО в памяти и сбрасываются при закрытии программы.
#
# Старые сохранённые значения (если были в settings.json) удаляются
# при первом сохранении настроек — см. save_settings().

# Словарь в памяти: {"skip_confirm": True, ...}
_session_flags: dict = {}

def get_flag(name: str) -> bool:
    """Возвращает True, если пользователь уже отключил этот диалог в текущей сессии."""
    return bool(_session_flags.get(name, False))

def set_flag(name: str, value: bool = True) -> None:
    """Устанавливает флаг ТОЛЬКО в памяти (не сохраняется на диск)."""
    _session_flags[name] = bool(value)

def reset_session_flags() -> None:
    """Сбрасывает все флаги текущей сессии (не используется автоматически)."""
    _session_flags.clear()

# ============================================================
#  НАСТРОЙКА ЗВУКА
# ============================================================

def get_sound_enabled() -> bool:
    """Возвращает True, если звук включён (по умолчанию — да)."""
    return bool(load_settings().get("sound_enabled", True))

def set_sound_enabled(value: bool) -> None:
    """Сохраняет настройку звука."""
    data = load_settings()
    data["sound_enabled"] = bool(value)
    save_settings(data)