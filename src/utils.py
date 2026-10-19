r"""
utils.py — вспомогательные функции программы «ШРЕДДЕР».

Здесь живут маленькие «инструменты», которыми пользуются
другие файлы программы:
  1. generate_temp_name()      — придумывает имя, похожее на временный файл Windows.
  2. build_path_for_io()       — готовит путь для работы с длинными и сетевыми путями.
  3. human_size()              — переводит байты в «человеческий» вид (КБ / МБ / ГБ).
  4. get_file_attributes()     — читает атрибуты файла через WinAPI.
  5. is_compressed_encrypted_sparse() — проверяет сжатие / шифрование / разреженность.
  6. get_drive_type()          — определяет тип диска (локальный / сетевой / съёмный).
"""

import os
import sys
import uuid
from ctypes import windll, c_uint32, c_wchar_p


# ============================================================
#  1. ГЕНЕРАТОР ВРЕМЕННЫХ ИМЁН
# ============================================================

def generate_temp_name() -> str:
    r"""
    Придумывает имя в стиле файлов из папки Windows Temp.

    Основной шаблон: GUID в нижнем регистре + .tmp
    Пример: 1ae11033-c780-4c2b-bcab-4c6097f8420c.tmp

    Возвращает: строку с именем файла (без пути).
    """
    # uuid.uuid4() — создаёт случайный уникальный номер (GUID).
    # str(...) превращает его в строку.
    # .lower() делает все буквы маленькими (как в реальных файлах Temp).
    # + ".tmp" дописывает расширение.
    return str(uuid.uuid4()).lower() + ".tmp"


# ============================================================
#  2. ПОДГОТОВКА ПУТИ ДЛЯ ДЛИННЫХ И СЕТЕВЫХ ПУТЕЙ
# ============================================================

MAX_PATH = 260
UNC_PREFIX = "\\\\?\\UNC\\"      # префикс для сетевых путей
LONG_PREFIX = "\\\\?\\"          # префикс для обычных длинных путей


def build_path_for_io(path: str) -> str:
    r"""
   Готовит путь для вызовов WinAPI, если путь длинный (>260 символов).

    Зачем это нужно:
    Windows по умолчанию не умеет работать с путями длиннее 260 символов.
    Если дописать в начало специальный префикс — лимит снимается.

    Для обычных путей (C:\...) префикс: \\?\
    Для сетевых путей (\\server\share\...) префикс: \\?\UNC\

    Возвращает: путь, пригодный для open() / os.rename() / os.remove().
    """
    # Всегда сначала делаем путь абсолютным.
    # Без этого относительный путь ("document.pdf") сломает
    # os.path.dirname в engine.py — вернёт пустую строку.
    abs_path = os.path.abspath(path)

    # Если путь короче или равен 250 символов — трогать не надо.
    if len(abs_path) <= 250:
        return abs_path

    # Если префикс уже стоит — не дублируем.
    if abs_path.startswith(LONG_PREFIX):
        return abs_path

    # Сетевой путь начинается с двойного обратного слэша.
    if abs_path.startswith("\\\\"):
        return UNC_PREFIX + abs_path[2:]

    # Обычный путь — приклеиваем префикс.
    return LONG_PREFIX + abs_path


# ============================================================
#  3. ЧЕЛОВЕЧЕСКИЙ РАЗМЕР ФАЙЛА
# ============================================================

def human_size(size_bytes: int) -> str:
    r"""
    Превращает размер в байтах в удобную строку.
    Единицы измерения локализованы через i18n.
    Пример (рус): 1610612736 → '1.50 ГБ'
    Пример (англ): 1610612736 → '1.50 GB'
    """
    # Импорт делаем внутри функции, чтобы избежать циклической зависимости.
    from src import i18n

    if size_bytes < 1024:
        return f"{size_bytes} {i18n.t('unit_b')}"

    unit_keys = ["unit_kb", "unit_mb", "unit_gb", "unit_tb", "unit_pb"]
    value = size_bytes / 1024.0
    unit_index = 0

    while value >= 1024.0 and unit_index < len(unit_keys) - 1:
        value /= 1024.0
        unit_index += 1

    return f"{value:.2f} {i18n.t(unit_keys[unit_index])}"


# ============================================================
#  4. WinAPI — ОБЪЯВЛЕНИЕ СИГНАТУР (ctypes)
# ============================================================
#
# ВАЖНО: без явного argtypes / restype ctypes может усечь 64-битные
# указатели на 64-битном Python. Это лотерея, поэтому объявляем типы.

# GetFileAttributesW — читает атрибуты файла.
_GetFileAttributesW = windll.kernel32.GetFileAttributesW
_GetFileAttributesW.argtypes = [c_wchar_p]      # аргумент: широкая строка
_GetFileAttributesW.restype = c_uint32          # возврат: 32-битное число

# GetDriveTypeW — определяет тип диска (fixed / remote / removable).
_GetDriveTypeW = windll.kernel32.GetDriveTypeW
_GetDriveTypeW.argtypes = [c_wchar_p]           # аргумент: широкая строка
_GetDriveTypeW.restype = c_uint32               # возврат: 32-битное число

# Константы возврата GetFileAttributesW.
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

# Битовые флаги атрибутов.
FILE_ATTRIBUTE_COMPRESSED = 0x800
FILE_ATTRIBUTE_ENCRYPTED = 0x4000
FILE_ATTRIBUTE_SPARSE_FILE = 0x200

# Типы дисков (возврат GetDriveTypeW).
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_NO_ROOT_DIR = 1


# ============================================================
#  5. ОБЁРТКИ НАД WinAPI
# ============================================================

def get_file_attributes(path_for_io: str) -> int:
    r"""
    Читает атрибуты файла через WinAPI.
    Возвращает целое число (битовая маска) или INVALID_FILE_ATTRIBUTES при ошибке.

    ВАЖНО: path_for_io должен быть уже с префиксом для длинных путей.
    """
    return _GetFileAttributesW(path_for_io)


def is_compressed_encrypted_sparse(path_for_io: str) -> bool:
    r"""
    Проверяет, есть ли у файла атрибуты «сжат / зашифрован / разрежен».

    Если да — такой файл нельзя надёжно уничтожить перезаписью нулями,
    потому что NTFS хранит содержимое в другом виде.
    """
    attrs = get_file_attributes(path_for_io)

    # Если WinAPI вернул ошибку — не блокируем файл, пропускаем проверку.
    if attrs == INVALID_FILE_ATTRIBUTES:
        return False

    # Проверяем биты. Если хотя бы один установлен — возвращаем True.
    mask = FILE_ATTRIBUTE_COMPRESSED | FILE_ATTRIBUTE_ENCRYPTED | FILE_ATTRIBUTE_SPARSE_FILE
    return bool(attrs & mask)


def get_drive_type(path: str) -> int:
    r"""
    Определяет тип диска, на котором лежит файл.

    ВАЖНО: здесь используется КОРОТКИЙ path (без длинного префикса),
    потому что os.path.splitdrive не понимает префиксный путь.

    Возвращает одно из:
      2 — съёмный (флешка, внешний USB)
      3 — локальный (HDD / SSD)
      4 — сетевой (\\server\share)
      1 — некорректный путь (ошибка)
    """
def get_drive_type(path: str) -> int:
    # Приводим к абсолютному пути (защита от "file.txt").
    abs_path = os.path.abspath(path)
    # Отделяем букву диска: 'C:\file.txt' → 'C:'
    drive = os.path.splitdrive(abs_path)[0]

    # Приклеиваем хвостовой слэш.
    # MSDN требует, чтобы UNC-путь был с завершающим \,
    # а обычная буква диска — как 'C:\'.
    if drive.startswith("\\\\"):
        drive_for_api = drive + "\\"      # \\server\share → \\server\share\
    else:
        drive_for_api = drive + "\\"      # C: → C:\

    return _GetDriveTypeW(drive_for_api)

# ============================================================
#  6. ПУТИ К РЕСУРСАМ (assets, locales, sounds)
# ============================================================

def resource_path(rel: str) -> str:
    """
    Возвращает абсолютный путь к ресурсу (assets, locales, sounds).
    Работает и в режиме разработки, и в собранном .exe (PyInstaller).

    В .exe PyInstaller распаковывает все data-файлы во временную
    папку и сообщает её путь через sys._MEIPASS. В обычном режиме
    возвращаем корень проекта.
    """
    # В .exe — PyInstaller выставляет sys.frozen = True
    # и кладёт путь распаковки в sys._MEIPASS.
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # В режиме разработки: utils.py лежит в src/,
        # значит корень проекта — на два уровня выше.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)