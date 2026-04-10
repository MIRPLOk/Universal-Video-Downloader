import os
import sys
import shutil
import argparse
import logging
from datetime import datetime
from urllib.parse import urlparse

# ─────────────────────────────────────────────
#  Проверка зависимостей
# ─────────────────────────────────────────────
try:
    import yt_dlp
except ImportError:
    print("❌ ОШИБКА: Библиотека 'yt-dlp' не установлена.")
    print("Выполните: pip install yt-dlp")
    input("\nНажмите Enter для выхода...")
    sys.exit(1)


# ─────────────────────────────────────────────
#  Проверка FFmpeg
# ─────────────────────────────────────────────
def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None

FFMPEG_AVAILABLE = check_ffmpeg()


# ─────────────────────────────────────────────
#  Логирование
# ─────────────────────────────────────────────
def setup_logger(log_dir: str) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"download_{datetime.now().strftime('%Y-%m-%d')}.log")

    logger = logging.getLogger("VideoDownloader")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ─────────────────────────────────────────────
#  Вспомогательные функции
# ─────────────────────────────────────────────
def is_url(text: str) -> bool:
    """Надёжная проверка: является ли строка ссылкой."""
    try:
        result = urlparse(text)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except ValueError:
        return False


def sanitize_input(text: str) -> str:
    """Убирает лишние пробелы и кавычки."""
    return text.strip().strip('"').strip("'")


def parse_items(raw: str) -> list[str]:
    """Разбивает ввод по запятой и/или переносам строк, убирает пустые."""
    items = []
    for part in raw.replace("\n", ",").split(","):
        item = sanitize_input(part)
        if item:
            items.append(item)
    return items


# ─────────────────────────────────────────────
#  Загрузчик
# ─────────────────────────────────────────────
def build_ydl_opts(download_path: str, quality: str, audio_only: bool) -> dict:
    """Формирует опции yt-dlp в зависимости от параметров и наличия FFmpeg."""
    postprocessors = []

    if audio_only:
        if FFMPEG_AVAILABLE:
            fmt = "bestaudio/best"
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        else:
            # Без FFmpeg — сразу берём аудио в готовом контейнере
            fmt = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio"
    else:
        if FFMPEG_AVAILABLE:
            # FFmpeg есть — можно раздельно скачать видео+аудио и склеить
            quality_map = {
                "best":  "bestvideo+bestaudio/best",
                "1080":  "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                "720":   "bestvideo[height<=720]+bestaudio/best[height<=720]",
                "480":   "bestvideo[height<=480]+bestaudio/best[height<=480]",
                "worst": "worstvideo+worstaudio/worst",
            }
        else:
            # FFmpeg нет — только форматы с видео И аудио в одном файле
            quality_map = {
                "best":  "best[ext=mp4]/best",
                "1080":  "best[height<=1080][ext=mp4]/best[height<=1080]",
                "720":   "best[height<=720][ext=mp4]/best[height<=720]",
                "480":   "best[height<=480][ext=mp4]/best[height<=480]",
                "worst": "worst[ext=mp4]/worst",
            }
        fmt = quality_map.get(quality, quality_map["best"])

    opts = {
        "format":             fmt,
        "outtmpl":            os.path.join(download_path, "%(title)s.%(ext)s"),
        "noplaylist":         False,
        "quiet":              True,
        "no_warnings":        True,
        "ignoreerrors":       True,
        "postprocessors":     postprocessors,
        "progress_hooks":     [],  # заполняется в download_item
    }

    # Если FFmpeg есть — объединяем в mp4
    if FFMPEG_AVAILABLE and not audio_only:
        opts["merge_output_format"] = "mp4"

    return opts


def download_item(
    input_data: str,
    download_path: str,
    quality: str,
    audio_only: bool,
    logger: logging.Logger,
) -> bool:
    """
    Скачивает одно видео/аудио или выполняет поиск по тексту.
    Возвращает True при успехе.
    """
    url_detected = is_url(input_data)
    opts = build_ydl_opts(download_path, quality, audio_only)

    if not url_detected:
        opts["default_search"] = "ytsearch1"
        opts["noplaylist"]     = True
        print(f"  🔍 Поиск: «{input_data}»")
        logger.info("Search: %s", input_data)
    else:
        print(f"  🚀 Загрузка: {input_data}")
        logger.info("Download URL: %s", input_data)

    # Прогресс-бар в терминале
    def _progress(d):
        if d["status"] == "downloading":
            pct  = d.get("_percent_str", "?").strip()
            spd  = d.get("_speed_str", "").strip()
            eta  = d.get("_eta_str", "").strip()
            print(f"\r     {pct}  {spd}  ETA {eta}   ", end="", flush=True)
        elif d["status"] == "finished":
            print(f"\r     ✅ Готово: {os.path.basename(d['filename'])}{' ' * 20}")
            logger.info("Finished: %s", d["filename"])
        elif d["status"] == "error":
            logger.error("Hook error for: %s", input_data)

    opts["progress_hooks"] = [_progress]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ret = ydl.download([input_data])
        return ret == 0
    except Exception as exc:
        print(f"\n  ❌ Ошибка: {exc}")
        logger.error("Exception for '%s': %s", input_data, exc)
        return False


# ─────────────────────────────────────────────
#  Основной интерфейс
# ─────────────────────────────────────────────
QUALITY_CHOICES = ["best", "1080", "720", "480", "worst"]
EXIT_WORDS      = {"выход", "exit", "quit", "q", "stop"}

BANNER = """
╔══════════════════════════════════════════════╗
║       UNIVERSAL VIDEO DOWNLOADER PRO         ║
║          yt-dlp · by you · v2.1              ║
╠══════════════════════════════════════════════╣
║  Введите ссылку(и) через запятую или поиск   ║
║  Для выхода: выход / exit / q                ║
╚══════════════════════════════════════════════╝
"""


def run_interactive(download_path: str, quality: str, audio_only: bool, logger: logging.Logger):
    print(BANNER)
    print(f"  📁 Папка: {os.path.abspath(download_path)}")
    print(f"  🎬 Качество: {'аудио (mp3)' if audio_only else quality}")
    ffmpeg_status = "✅ найден (высокое качество)" if FFMPEG_AVAILABLE else "❌ не найден (скачивается ready-made mp4)"
    print(f"  🔧 FFmpeg: {ffmpeg_status}")
    if not FFMPEG_AVAILABLE:
        print("     → Установите FFmpeg для максимального качества: https://ffmpeg.org/download.html")
    print()

    session_ok   = 0
    session_fail = 0

    try:
        while True:
            try:
                raw = input("👉 Ссылка / поиск / несколько через запятую: ").strip()
            except EOFError:
                break

            if not raw:
                continue

            if raw.lower() in EXIT_WORDS:
                break

            # Inline команды
            if raw.startswith(":quality "):
                q = raw.split()[1]
                if q in QUALITY_CHOICES:
                    quality = q
                    print(f"  ✅ Качество изменено на: {quality}")
                else:
                    print(f"  ⚠️  Доступные значения: {', '.join(QUALITY_CHOICES)}")
                continue

            if raw == ":audio":
                audio_only = not audio_only
                print(f"  🎵 Режим аудио: {'вкл' if audio_only else 'выкл'}")
                continue

            if raw == ":ffmpeg":
                status = "✅ найден" if FFMPEG_AVAILABLE else "❌ не найден — https://ffmpeg.org/download.html"
                print(f"  🔧 FFmpeg: {status}")
                continue

            if raw == ":path":
                print(f"  📁 {os.path.abspath(download_path)}")
                continue

            if raw == ":stats":
                print(f"  ✅ Успешно: {session_ok}  ❌ Ошибок: {session_fail}")
                continue

            if raw == ":help":
                print(
                    "  Команды:\n"
                    "    :quality <best|1080|720|480|worst>  — сменить качество\n"
                    "    :audio                              — переключить режим аудио\n"
                    "    :ffmpeg                             — статус FFmpeg\n"
                    "    :path                               — показать папку загрузки\n"
                    "    :stats                              — счётчик сессии\n"
                    "    :help                               — эта справка\n"
                    "    выход / exit / q                    — завершить\n"
                )
                continue

            items = parse_items(raw)
            total = len(items)

            if total == 0:
                continue

            if total > 1:
                print(f"\n  📦 Пачка из {total} элементов\n")

            for idx, item in enumerate(items, 1):
                if total > 1:
                    print(f"  [{idx}/{total}] ", end="")
                ok = download_item(item, download_path, quality, audio_only, logger)
                if ok:
                    session_ok += 1
                else:
                    session_fail += 1

            print(f"\n  ─ Итог сессии: ✅ {session_ok}  ❌ {session_fail}\n")

    except KeyboardInterrupt:
        print("\n\n  Прервано (Ctrl+C).")

    print(f"\n  Завершено. Всего за сессию: ✅ {session_ok}  ❌ {session_fail}")
    logger.info("Session ended. OK=%d FAIL=%d", session_ok, session_fail)


# ─────────────────────────────────────────────
#  Точка входа
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Universal Video Downloader Pro — интерактивный или пакетный режим",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Ссылки или поисковые запросы (необязательно — без них запускается интерактивный режим)",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloads",
        help="Папка для сохранения (по умолчанию: downloads)",
    )
    parser.add_argument(
        "-q", "--quality",
        choices=QUALITY_CHOICES,
        default="best",
        help="Качество видео: best | 1080 | 720 | 480 | worst (по умолчанию: best)",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Скачать только аудио (mp3)",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Папка для лог-файлов (по умолчанию: logs)",
    )

    args   = parser.parse_args()
    logger = setup_logger(args.log_dir)
    os.makedirs(args.output, exist_ok=True)

    # Пакетный режим: ссылки переданы сразу через CLI
    if args.urls:
        items = []
        for u in args.urls:
            items.extend(parse_items(u))

        ok = fail = 0
        for idx, item in enumerate(items, 1):
            print(f"[{idx}/{len(items)}] ", end="")
            if download_item(item, args.output, args.quality, args.audio, logger):
                ok += 1
            else:
                fail += 1

        print(f"\n✅ {ok}  ❌ {fail}")
        sys.exit(0 if fail == 0 else 1)

    # Интерактивный режим
    run_interactive(args.output, args.quality, args.audio, logger)
    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
