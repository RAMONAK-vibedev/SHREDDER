r"""
engine.py — движок уничтожения файлов программы «ШРЕДДЕР».

Здесь живёт вся логика:
  1. Проверки файла (7 строгих + 1 предупреждающая).
  2. Переименование в GUID-имя.
  3. Перезапись данных (ПОЛНЫЙ или БЫСТРЫЙ режим).
  4. Обрезка до 32 байт.
  5. Удаление мимо корзины.

Движок НЕ знает про tkinter и окна. Он получает путь,
делает работу и возвращает отчёт. GUI сам решает,
как показать прогресс и что спросить у пользователя.
"""

import os
import stat
import time

from src import i18n
from src.utils import (
    generate_temp_name,
    build_path_for_io,
    is_compressed_encrypted_sparse,
    get_drive_type,
    DRIVE_REMOVABLE,
    DRIVE_REMOTE,
)

# ============================================================
#  КОНСТАНТЫ
# ============================================================

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024

SMALL_FILE_THRESHOLD = 1 * GB       # порог «маленький/большой» — 1 ГБ
HEAD_SIZE = 100 * MB                # голова в БЫСТРОМ режиме
TAIL_SIZE = 100 * MB                # хвост в БЫСТРОМ режиме
CHUNK_SIZE = 4 * MB                 # полоска в БЫСТРОМ режиме
TRUNCATE_TO = 32                    # обрезка до 32 байт

TOTAL_STEPS = 7                     # всего шагов в прогресс-баре

# ============================================================
#  ИСКЛЮЧЕНИЯ — свои «тревоги» для понятных сообщений
# ============================================================
#
# Зачем: чтобы GUI ловил не «Exception», а конкретные типы
# и показывал пользователю человеческое сообщение.

class ShredderError(Exception):
    """Базовое исключение ШРЕДДЕРА. Всё своё — наследуем отсюда."""
    pass


class FileRejectedError(ShredderError):
    """Файл отклонён по одной из строгих проверок.
    Текст исключения — готовое сообщение для пользователя."""
    pass

# ============================================================
#  ПРОВЕРКИ ФАЙЛА
# ============================================================

def check_file_strict(path_for_io: str) -> None:
    r"""
    Строгие проверки. Если файл не проходит — бросает FileRejectedError
    с готовым текстом для пользователя.

    Проверки идут по порядку (от грубых к тонким):
      1. Битый/обычный симлинк.
      2. Файл существует?
      3. Файл-заглушка (OneDrive, reparse point).
      4. Это вообще файл, а не папка?
      5. Ярлык .lnk.
      6. Hard links (жёсткие ссылки).
      7. Сжат / зашифрован / разрежен.
    """

    # 1. Симлинк — проверяем ДО lexists (см. ТЗ v1.5, 3.4).
    # ВНИМАНИЕ: os.path.islink на Windows НЕ ловит junction
    # (reparse point на папку). Их отловит проверка №3 ниже
    # (st_reparse_tag).
    if os.path.islink(path_for_io):
        raise FileRejectedError(
            i18n.t("error_is_symlink")
        )

    # 2. Файл существует? Используем lexists, не exists!
    # lexists не идёт «по ссылке» — важно для битых симлинков.
    if not os.path.lexists(path_for_io):
        raise FileRejectedError(i18n.t("error_not_found"))

    # 3. Reparse point (OneDrive-плейсхолдер, junction).
    # В Python 3.8+ есть st_reparse_tag.
    try:
        tag = os.lstat(path_for_io).st_reparse_tag
        if tag != 0:
            # ВНИМАНИЕ: FileRejectedError не ловится ниже — это другой
            # тип исключения, он пройдёт наверх, как и задумано.
            raise FileRejectedError(
                i18n.t("error_reparse")
            )
    except AttributeError:
        # На старых Python атрибута st_reparse_tag нет — пропускаем.
        pass
    except OSError:
        # На системных файлах или без прав lstat может упасть.
        # Пропускаем проверку — дальше сработают другие.
        pass

    # 4. Это файл, а не папка?
    if not os.path.isfile(path_for_io):
        raise FileRejectedError(
            i18n.t("error_not_file")
        )

    # 5. Hard links. st_nlink > 1 значит, у файла есть ещё имена.
    try:
        nlink = os.stat(path_for_io).st_nlink
        if nlink > 1:
            raise FileRejectedError(
                i18n.t("error_hardlinks", n=nlink)
            )
    except OSError:
        # На FAT32 st_nlink всегда 1 — эта ветка не сработает.
        pass

    # 6. Сжат / зашифрован / разрежен.
    if is_compressed_encrypted_sparse(path_for_io):
        raise FileRejectedError(
            i18n.t("error_compressed")
        )

def get_drive_warning(path: str):
    r"""
    Мягкая проверка: сетевой или съёмный диск.
    Не блокирует — возвращает текст предупреждения или None.

    path — КОРОТКИЙ (без \\?\ префикса)!
    """
    dtype = get_drive_type(path)

    if dtype == DRIVE_REMOTE:
        return i18n.t("drive_remote_warning")
    if dtype == DRIVE_REMOVABLE:
        return i18n.t("drive_removable_warning")
    return None

def overwrite_full(path_for_io: str, size: int, sub_progress) -> None:
    r"""
    ПОЛНЫЙ режим: весь файл нулями.
    sub_progress(fraction) — вызывается с числом от 0.0 до 1.0.
    """
    # Открываем 'r+b' — читать + писать БЕЗ усечения.
    # Именно 'r+b', не 'wb' — иначе Windows выделит новые кластеры.
    with open(path_for_io, 'r+b') as f:
        written = 0
        block = b'\x00' * (1 * MB)
        last_report = time.time()

        while written < size:
            to_write = min(len(block), size - written)
            f.write(block[:to_write])
            written += to_write

            # Обновляем прогресс не чаще раза в 0.3 секунды —
            # иначе очередь GUI захлебнётся.
            now = time.time()
            if now - last_report > 0.3:
                sub_progress(written / size)
                last_report = now

        # Финал: сбрасываем буферы ОС и диска.
        f.flush()
        os.fsync(f.fileno())
        sub_progress(1.0)

def overwrite_fast(path_for_io: str, size: int, sub_progress) -> None:
    r"""
    БЫСТРЫЙ режим: голова + хвост нулями, середина — полосками.

    Схема:
      [0..HEAD]                    — нули
      [HEAD..size-TAIL]            — цикл: [4 МБ нули][4 МБ пропуск]
      [size-TAIL..size]            — нули

    sub_progress — вызывается с долей ОТ ОБЪЁМА ЗАПИСИ (не от размера файла!).
    """
    # Если файл меньше головы + хвоста, полоски в середине не влезают.
    # Тогда просто пишем нули по всей голове и всему хвосту подряд.
    # (теоретически недостижимо: FAST только для >= 1 ГБ, а 1 ГБ > 200 МБ)
    if size <= HEAD_SIZE + TAIL_SIZE:
        # Защита от дурака: делаем полную перезапись.
        overwrite_full(path_for_io, size, sub_progress)
        return

    # Считаем РЕАЛЬНЫЙ объём записи для правильного прогресса.
    # ВНИМАНИЕ: формула может недооценить реальный объём
    # на 1 CHUNK. Финальный прогресс клампится в min(1.0, ...)
    # в _tick() ниже.
    middle_size = size - HEAD_SIZE - TAIL_SIZE
    # В середине записываем примерно половину (чередование 4/4).
    middle_writes = (middle_size // (2 * CHUNK_SIZE)) * CHUNK_SIZE
    # Плюс «хвостик» если middle_size не делится ровно.
    if middle_size % (2 * CHUNK_SIZE) > CHUNK_SIZE:
        middle_writes += CHUNK_SIZE
    total_writes = HEAD_SIZE + TAIL_SIZE + middle_writes

    written = 0
    last_report = time.time()
    zeros_1mb = b'\x00' * (1 * MB)
    zeros_chunk = b'\x00' * CHUNK_SIZE      # ← кешируем 4 МБ один раз

    def _tick():
        """Обновляет прогресс — не чаще 0.3 сек."""
        nonlocal last_report
        now = time.time()
        if now - last_report > 0.3:
            # Клампим в 1.0 — формула total_writes может
            # недооценить объём на 1 CHUNK.
            if total_writes > 0:
                sub_progress(min(1.0, written / total_writes))
            else:
                sub_progress(1.0)
            last_report = now

    with open(path_for_io, 'r+b') as f:
        # --- ГОЛОВА ---
        head_written = 0
        while head_written < HEAD_SIZE:
            to_write = min(len(zeros_1mb), HEAD_SIZE - head_written)
            f.write(zeros_1mb[:to_write])
            head_written += to_write
            written += to_write
            _tick()

        # --- СЕРЕДИНА ---
        # Ставим указатель на начало середины.
        f.seek(HEAD_SIZE, 0)
        middle_pos = HEAD_SIZE

        while middle_pos < size - TAIL_SIZE:
            # Пишем 4 МБ нулей (или меньше, если осталось чуть-чуть).
            to_write = min(CHUNK_SIZE, size - TAIL_SIZE - middle_pos)
            f.write(zeros_chunk[:to_write])
            middle_pos += to_write
            written += to_write
            _tick()

            # Пропускаем 4 МБ (не пишем — там остаётся «старое»).
            middle_pos += CHUNK_SIZE
            if middle_pos < size - TAIL_SIZE:
                f.seek(middle_pos, 0)

        # --- ХВОСТ ---
        # Прыгаем в начало хвоста.
        tail_start = size - TAIL_SIZE
        f.seek(tail_start, 0)
        tail_written = 0
        while tail_written < TAIL_SIZE:
            to_write = min(len(zeros_1mb), TAIL_SIZE - tail_written)
            f.write(zeros_1mb[:to_write])
            tail_written += to_write
            written += to_write
            _tick()

        # Финал: сбрасываем буферы.
        f.flush()
        os.fsync(f.fileno())
        sub_progress(1.0)

# ============================================================
#  ОБРЕЗКА
# ============================================================

def truncate_and_scramble(path_for_io: str) -> None:
    r"""
    Обрезает файл до 32 байт и заполняет их случайными байтами.
    """
    with open(path_for_io, 'r+b') as f:
        # truncate не двигает указатель — но мы всё равно делаем seek(0)
        # как страховку от будущих правок.
        f.truncate(TRUNCATE_TO)
        f.seek(0)
        f.write(os.urandom(TRUNCATE_TO))
        f.flush()
        os.fsync(f.fileno())

# ============================================================
#  ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def shred_file(path: str, mode: str, progress_callback=None) -> dict:
    r"""
    Уничтожает файл.

    Параметры:
      path              — короткий путь к файлу.
      mode              — 'FULL' или 'FAST'. Для файлов <1ГБ всё равно FULL.
      progress_callback — функция(step, message, sub_fraction), необязательно.

    Возвращает словарь с результатом:
      {
        'success': True/False,
        'original_name': str,
        'original_size': int,
        'final_name': str,
        'final_size': int,
        'mode': 'FULL'/'FAST'/'EMPTY',
        'status_message': str,
        'error': str или None,
      }
    """
    result = {
        'success': False,
        'original_name': os.path.basename(path),
        'original_size': 0,
        'final_name': '',
        'final_size': 0,
        'mode': mode,
        'status_message': '',
        'error': None,
    }

    def report(step: int, message: str, sub: float = 0.0):
        if progress_callback is not None:
            progress_callback(step, message, sub)

    # Служебные флаги для отката переименования при ошибке.
    renamed = False
    removed = False
    original_short_name = os.path.basename(path)

    def _restore_original_name():
        """
        Если файл был переименован, но не удалён — вернуть ему исходное имя.
        Вызывается ТОЛЬКО из обработчиков ошибок.
        """
        if not renamed or removed:
            return
        try:
            dir_path = os.path.dirname(current_path_for_io)
            restore_path = os.path.join(dir_path, original_short_name)
            os.rename(current_path_for_io, restore_path)
        except Exception:
            pass

    try:
        # ---------- ШАГ 0. ПОДГОТОВКА ----------
        path_for_io = build_path_for_io(path)
        current_path_for_io = path_for_io

        # Строгие проверки. Если что-то не так — бросит исключение.
        check_file_strict(path_for_io)

        # Снимаем атрибут "только для чтения" заранее.
        # Без этого open('r+b') в ШАГЕ 4 упадёт с PermissionError,
        # и мы не дойдём до ШАГА 6, где read-only тоже снимается.
        try:
            os.chmod(current_path_for_io, stat.S_IWRITE)
        except OSError:
            pass

        # Размер файла.
        original_size = os.path.getsize(current_path_for_io)
        result['original_size'] = original_size

        # ---------- ШАГ 1. СТРАТЕГИЯ ----------
        report(1, i18n.t("step_strategy"))
        # Маленькие файлы (<1 ГБ) — всегда ПОЛНЫЙ, независимо от выбора.
        if original_size < SMALL_FILE_THRESHOLD:
            mode = 'FULL'
        result['mode'] = mode
        # Пустой файл — отмечаем отдельно.
        if original_size == 0:
            result['mode'] = 'EMPTY'

        # ---------- ШАГ 2. ПОДТВЕРЖДЕНИЕ ----------
        # (диалог ДА/НЕТ делает GUI; сюда мы попадаем уже после согласия)
        report(2, i18n.t("step_confirm"))

        # ---------- ШАГ 3. ПЕРЕИМЕНОВАНИЕ ----------
        # ВАЖНО: переименование идёт ПЕРЕД перезаписью осознанно.
        # Причины (см. ревью сеньоров от 15.10.2026):
        # 1. Отвязка от блокировок: OneDrive, превью-генераторы,
        #    плееры могут держать файл по оригинальному пути.
        #    Переименование "отпускает" старую ссылку — и open('r+b')
        #    в ШАГЕ 4 проходит без PermissionError.
        # 2. Мимикрия: пока идёт долгая перезапись (до 2 минут для
        #    20 ГБ), файл уже называется uuid.tmp — неотличим от
        #    обычной активности temp.
        # Минус: при падении питания во время перезаписи пользователь
        # увидит uuid.tmp вместо имени файла. Это осознанный компромисс.
        report(3, i18n.t("step_rename"))
        new_name = generate_temp_name()
        new_path_for_io = os.path.join(
            os.path.dirname(current_path_for_io),
            new_name
        )
        os.rename(current_path_for_io, new_path_for_io)
        current_path_for_io = new_path_for_io
        renamed = True        # ← отметили, что переименование прошло

        # ---------- ШАГ 4. ПЕРЕЗАПИСЬ ----------
        report(4, i18n.t("step_overwrite"), 0.0)
        if original_size == 0:
            # Пустой файл — перезаписывать нечего.
            pass
        elif mode == 'FULL':
            overwrite_full(
                current_path_for_io,
                original_size,
                lambda frac: report(4, i18n.t("step_overwrite_full"), frac)
            )
        else:  # 'FAST'
            overwrite_fast(
                current_path_for_io,
                original_size,
                lambda frac: report(4, i18n.t("step_overwrite_fast"), frac)
            )

        # ---------- ШАГ 5. ОБРЕЗКА ----------
        if original_size > 0:
            report(5, i18n.t("step_truncate"))
            truncate_and_scramble(current_path_for_io)

        # ---------- ШАГ 6. УДАЛЕНИЕ ----------
        report(6, i18n.t("step_delete"))
        try:
            os.chmod(current_path_for_io, stat.S_IWRITE)
        except OSError:
            pass
        os.remove(current_path_for_io)
        removed = True        # ← отметили, что файл удалён (откатывать нечего)

        # ---------- ШАГ 7. ОТЧЁТ ----------
        report(7, i18n.t("step_done"), sub=1.0)

        # Заполняем результат.
        result['success'] = True
        result['final_name'] = new_name
        result['final_size'] = TRUNCATE_TO if original_size > 0 else 0

        # Формируем сообщение о статусе.
        if original_size == 0:
            result['status_message'] = (
                i18n.t("status_empty")
            )
        elif mode == 'FULL':
            result['status_message'] = (
                i18n.t("status_full")
            )
        else:
            result['status_message'] = (
                i18n.t("status_fast")
            )

    except PermissionError:
        _restore_original_name()
        result['error'] = i18n.t("error_permission")
    except FileNotFoundError:
        _restore_original_name()
        result['error'] = i18n.t("error_not_found")
    except FileRejectedError as e:
        _restore_original_name()
        result['error'] = str(e)
    except Exception as e:
        _restore_original_name()
        result['error'] = i18n.t("error_unknown", err=f"{type(e).__name__}: {e}")

    return result