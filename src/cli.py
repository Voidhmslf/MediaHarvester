"""
Командная строка MediaHarvester: `mediaharvester download|info|transcript|frames|update|mcp`.
Результат (пути к файлам, текст, JSON) пишется в stdout, ход работы и ошибки — в stderr,
поэтому вывод удобно передавать другим программам и ИИ-агентам.
"""
import argparse
import json
import os
import re
import sys
import threading

from src.version import __version__

COMMANDS = ("download", "info", "transcript", "frames", "update", "mcp")

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_CANCELLED = 0, 1, 2, 130

_EPILOG = """\
примеры:
  mediaharvester download https://youtu.be/jNQXAC9IVRw
  mediaharvester download -q 720 -o ~/Videos ССЫЛКА1 ССЫЛКА2
  mediaharvester download -q audio --audio-format m4a ССЫЛКА
  mediaharvester info ССЫЛКА --json
  mediaharvester transcript ССЫЛКА --lang ru,en
  mediaharvester frames видео.mp4 -n 8
  mediaharvester mcp            сервер MCP для ИИ-агентов (Claude, Cursor и др.)

Настройки cookies, браузера и вход ВКонтакте берутся из окна программы.
"""


def wants_cli(argv: list[str]) -> bool:
    """Запуск с подкомандой или справкой — командная строка; без аргументов или со ссылкой (%U ярлыка) — окно."""
    return len(argv) > 1 and (argv[1] in COMMANDS or argv[1] in ("-h", "--help", "-V", "--version"))


def parse_time(value: str) -> float:
    """'90', '1:30', '1:02:03.5' -> секунды."""
    parts = value.strip().split(":")
    if not parts or len(parts) > 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
        raise argparse.ArgumentTypeError(f"не понимаю время «{value}» (пример: 90, 1:30, 1:02:03)")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def _time_list(value: str) -> list[float]:
    return [parse_time(v) for v in value.split(",") if v.strip()]


def _lang_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediaharvester",
        description="MediaHarvester: видео, музыка и фото из YouTube, VK, Instagram, TikTok, X и других сайтов.",
        epilog=_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-V", "--version", action="version", version=f"MediaHarvester {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    p = sub.add_parser("download", help="скачать по ссылкам",
                       description="Скачивает по ссылкам и печатает пути к готовым файлам, по одному в строке.")
    p.add_argument("urls", nargs="+", metavar="ССЫЛКА", help="ссылки; «-» — читать ссылки из stdin")
    p.add_argument("-o", "--output", default="", metavar="ПАПКА", help="куда сохранять (по умолчанию текущая папка)")
    p.add_argument("-q", "--quality", default="best",
                   help="best, 2160, 1440, 1080, 720, 480, 360 или audio (по умолчанию best)")
    p.add_argument("--audio-format", choices=("mp3", "m4a", "opus"), default="mp3", help="формат для -q audio")
    p.add_argument("--cover", action="store_true", help="вшить обложку в аудиофайл")
    p.add_argument("--subs", type=_lang_list, default=[], metavar="ЯЗЫКИ",
                   help="субтитры .srt рядом с видео, например ru,en")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--playlist", dest="playlist", action="store_true", default=None,
                       help="скачать весь плейлист, если ссылка на него ведёт")
    group.add_argument("--no-playlist", dest="playlist", action="store_false", help="только одно видео")
    p.add_argument("--limit", type=int, default=0, metavar="N", help="только первые N видео плейлиста")
    p.add_argument("--engine", choices=("auto", "video", "insta", "gallery", "vk_photos", "vk_music"),
                   default="auto", help="движок вместо автоопределения")
    _add_cookie_args(p)
    _add_output_args(p)

    p = sub.add_parser("info", help="сведения о ссылке без скачивания")
    p.add_argument("url", metavar="ССЫЛКА")
    _add_cookie_args(p)
    p.add_argument("--json", action="store_true", help="вывод в JSON")

    p = sub.add_parser("transcript", help="текст речи из субтитров",
                       description="Печатает субтитры видео текстом с временем «[мм:сс]». Для ссылки берутся "
                                   "субтитры сайта (настоящие, иначе автоматические), для файла — .srt/.vtt рядом.")
    p.add_argument("source", metavar="ССЫЛКА|ФАЙЛ")
    p.add_argument("--lang", type=_lang_list, default=[], metavar="ЯЗЫКИ",
                   help="предпочтительные языки по порядку, например ru,en (по умолчанию язык видео)")
    p.add_argument("--no-times", action="store_true", help="без меток времени")
    _add_cookie_args(p)
    p.add_argument("--json", action="store_true", help="вывод в JSON")

    p = sub.add_parser("frames", help="кадры из видео в JPEG",
                       description="Сохраняет кадры видео в JPEG и печатает пути. Ссылка сначала скачивается "
                                   "в 480p в кэш программы.")
    p.add_argument("source", metavar="ФАЙЛ|ССЫЛКА")
    p.add_argument("-n", "--count", type=int, default=6, help="сколько кадров равномерно по длине (по умолчанию 6)")
    p.add_argument("--at", type=_time_list, default=None, metavar="ВРЕМЯ",
                   help="кадры в эти моменты: 15,1:30,2:05.5")
    p.add_argument("--width", type=int, default=640, help="ширина кадра в пикселях (по умолчанию 640)")
    p.add_argument("-o", "--output", default="", metavar="ПАПКА", help="куда сохранить кадры")
    _add_cookie_args(p)
    _add_output_args(p)

    sub.add_parser("update", help="обновить yt-dlp до свежей версии")
    sub.add_parser("mcp", help="запустить сервер MCP (stdio) для ИИ-агентов",
                   description="Сервер Model Context Protocol через stdin/stdout. Инструменты: download, "
                               "media_info, get_transcript, get_frames.")
    return parser


def _add_cookie_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cookies", default=None, metavar="ФАЙЛ", help="cookies.txt (по умолчанию из настроек программы)")
    p.add_argument("--browser", default=None, metavar="БРАУЗЕР",
                   help="брать cookies из браузера: firefox, chrome, edge, chromium… (по умолчанию из настроек)")


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="вывод в JSON")
    p.add_argument("--quiet", action="store_true", help="не показывать ход работы")


class _Progress:
    """Ход работы в stderr: в терминале одной обновляемой строкой, в журнал — только смена этапов."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.tty = sys.stderr.isatty()
        self.prefix = ""
        self._last = ""
        self._width = 0

    def __call__(self, text: str, state: str = "working", progress=None, percent: str = "") -> None:
        if self.quiet or not text:
            return
        line = self.prefix + text
        if self.tty:
            pad = max(0, self._width - len(line))
            sys.stderr.write("\r" + line[:150] + " " * pad)
            sys.stderr.flush()
            self._width = len(line[:150])
            return
        stage = re.sub(r"[\d.,:%]+", "", line)
        if stage != self._last:
            self._last = stage
            print(line, file=sys.stderr, flush=True)

    def done(self) -> None:
        if self.tty and self._width and not self.quiet:
            sys.stderr.write("\r" + " " * self._width + "\r")
            sys.stderr.flush()
        self._width = 0


def _settings():
    from src.config import SettingsManager
    from src.utils.logger import register_secret
    settings = SettingsManager()
    for kind in ("photos", "music", "music_android"):
        register_secret(settings.get_vk_token(kind))
    return settings


def _cookie_options(args, settings) -> tuple[str, str]:
    from src.utils import browser_cookies
    cookies = settings.cookies_path if args.cookies is None else args.cookies
    browser = settings.get("cookies_browser", "") if args.browser is None else args.browser
    if browser.lower() in ("none", "no", "off", browser_cookies.NONE_CHOICE.lower()):
        browser = ""
    if browser:
        # В настройках окна браузер записан названием из списка («Firefox»), в командной строке — как удобно
        for choice in browser_cookies.BROWSER_CHOICES:
            if choice.lower().replace(" ", "") == browser.lower().replace(" ", ""):
                browser = choice
                break
        else:
            if browser_cookies.resolve(browser) is None:
                raise ValueError(f"Неизвестный браузер «{browser}». Можно: "
                                 + ", ".join(c for c in browser_cookies.BROWSER_CHOICES
                                             if c != browser_cookies.NONE_CHOICE))
    if cookies and not os.path.isfile(cookies):
        raise ValueError(f"Файл cookies не найден: {cookies}")
    return cookies or "", browser or ""


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_download(args) -> int:
    from src.core.download_queue import parse_urls
    from src.core.headless import DownloadOptions, download_url, quality_choice

    urls: list[str] = []
    for item in args.urls:
        urls += parse_urls(sys.stdin.read()) if item == "-" else [item]
    if not urls:
        print("Нет ссылок", file=sys.stderr)
        return EXIT_USAGE
    quality_choice(args.quality)  # проверка до начала загрузки

    settings = _settings()
    cookies, browser = _cookie_options(args, settings)
    opts = DownloadOptions(
        output_dir=args.output or os.getcwd(), quality=args.quality, audio_format=args.audio_format,
        embed_cover=args.cover, playlist=args.playlist, playlist_limit=max(0, args.limit),
        subtitles=args.subs, cookies_path=cookies, cookies_browser=browser, engine=args.engine)

    progress = _Progress(args.quiet)
    cancel = threading.Event()
    results = []
    try:
        for number, url in enumerate(urls, 1):
            progress.prefix = f"[{number}/{len(urls)}] " if len(urls) > 1 else ""
            result = download_url(url, opts, settings, progress, cancel)
            progress.done()
            results.append(result)
            if not args.json:
                for path in result.files:
                    print(path, flush=True)
                if not result.ok:
                    hint = f" ({result.hint})" if result.hint else ""
                    print(f"Ошибка: {url}: {result.error}{hint}", file=sys.stderr)
                elif not result.files:
                    print(f"{url}: новых файлов нет (возможно, уже скачано)", file=sys.stderr)
            if result.cancelled:
                break
    except KeyboardInterrupt:
        cancel.set()
        progress.done()
        print("Отменено", file=sys.stderr)
        if args.json:
            _print_json([r.as_dict() for r in results])
        return EXIT_CANCELLED
    if args.json:
        _print_json([r.as_dict() for r in results])
    if any(r.cancelled for r in results):
        return EXIT_CANCELLED
    return EXIT_OK if all(r.ok for r in results) else EXIT_FAILED


def media_info(url: str, cookies: str = "", browser: str = "") -> dict:
    from src.core.router import detect_url_type
    from src.core.ytdlp_engine import probe_media

    detected = detect_url_type(url)
    data = {"url": url, "platform": detected["platform"], "type": detected["media_type"],
            "engine": detected["engine"], "label": detected["label"]}
    if detected["engine"] == "ytdlp":
        data.update(probe_media(url, cookies, browser))
    return data


def cmd_info(args) -> int:
    settings = _settings()
    cookies, browser = _cookie_options(args, settings)
    data = media_info(args.url, cookies, browser)
    if args.json:
        _print_json(data)
        return EXIT_OK
    from src.core.media_tools import format_time
    rows = [("Источник", data["label"]), ("Название", data.get("title", "")),
            ("Автор", data.get("uploader", "")),
            ("Длительность", format_time(data["duration"]) if data.get("duration") else ""),
            ("Качество", ", ".join(f"{h}p" for h in data.get("heights", []))),
            ("Плейлист", f"да, {data['playlist_count']} шт." if data.get("playlist") else "")]
    for name, value in rows:
        if value:
            print(f"{name + ':':<14}{value}")
    return EXIT_OK


def cmd_transcript(args) -> int:
    from src.core.media_tools import fetch_transcript
    settings = _settings()
    cookies, browser = _cookie_options(args, settings)
    data = fetch_transcript(args.source, args.lang, cookies, browser, timestamps=not args.no_times)
    if args.json:
        _print_json(data)
    else:
        print(data["text"])
    return EXIT_OK


def cmd_frames(args) -> int:
    from src.core.headless import local_media
    from src.core.media_tools import extract_frames
    settings = _settings()
    cookies, browser = _cookie_options(args, settings)
    settings._data.update(cookies_path=cookies, cookies_browser=browser)  # только для этого запуска
    progress = _Progress(args.quiet)
    try:
        path = local_media(args.source, settings, progress)
    finally:
        progress.done()
    data = extract_frames(path, args.count, args.at, args.width, args.output)
    if args.json:
        _print_json(data)
    else:
        for frame in data["frames"]:
            print(frame["path"])
    return EXIT_OK


def cmd_update(_args) -> int:
    from src.utils.helpers import self_update_disabled
    from src.utils.ytdlp_updater import check_for_update
    if self_update_disabled():
        print("yt-dlp обновляется вместе с системным пакетом (например, nix flake update)", file=sys.stderr)
        return EXIT_OK
    result = check_for_update(force=True)
    if result.status == "error":
        print(f"Не удалось обновить yt-dlp: {result.message}", file=sys.stderr)
        return EXIT_FAILED
    if result.status == "updated":
        print(f"yt-dlp {result.current} -> {result.latest}. Новая версия подключится при следующем запуске")
    else:
        print(f"yt-dlp {result.current}: свежая версия")
    return EXIT_OK


def _utf8_streams() -> None:
    # Агенты и другие программы читают вывод как UTF-8, даже на Windows с русской кодовой страницей
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    from src.utils.logger import setup_logging

    _utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    setup_logging()
    if args.command == "mcp":
        from src.mcp_server import serve
        return serve()

    handlers = {"download": cmd_download, "info": cmd_info, "transcript": cmd_transcript,
                "frames": cmd_frames, "update": cmd_update}
    from src.core.headless import explain
    from src.utils.helpers import DownloadCancelledError
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        print("\nОтменено", file=sys.stderr)
        return EXIT_CANCELLED
    except DownloadCancelledError:
        return EXIT_CANCELLED
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as e:
        message, hint = explain(e)
        print(f"Ошибка: {message}" + (f"\n{hint}" if hint else ""), file=sys.stderr)
        return EXIT_FAILED
