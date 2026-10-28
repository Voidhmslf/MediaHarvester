"""
Чтобы ИИ-агент мог «посмотреть» видео: текст речи из субтитров и кадры через ffmpeg.
Используется командной строкой (transcript, frames) и MCP-сервером.
"""
import glob
import hashlib
import os
import re
import subprocess
import sys
from typing import Any

from src.utils.helpers import FFMPEG_PATH, get_app_data_dir
from src.utils.logger import get_logger

log = get_logger("media_tools")

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".3gp", ".ts")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic")
SUBTITLE_EXTENSIONS = (".srt", ".vtt")

_TIMING = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->")
_TAG = re.compile(r"<[^>]+>|\{\\[^}]*\}")


def is_url(source: str) -> bool:
    return bool(re.match(r"^(?:https?://|www\.)", source.strip(), re.IGNORECASE))


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def subtitles_to_text(raw: str, timestamps: bool = True) -> str:
    """
    SRT или WebVTT -> текст по строкам с временем начала «[мм:сс] текст».
    Автосубтитры YouTube повторяют предыдущую строку в каждой реплике — повторы убираются.
    """
    lines: list[str] = []
    recent: list[str] = []
    start = 0.0
    for block in re.split(r"\r?\n\s*\r?\n", raw):
        texts = []
        for line in block.splitlines():
            line = line.strip()
            m = _TIMING.search(line)
            if m:
                h, mnt, s, ms = m.groups()
                start = int(h or 0) * 3600 + int(mnt) * 60 + int(s) + int(ms) / 1000
                continue
            if not line or line.isdigit() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
                continue
            text = re.sub(r"\s+", " ", _TAG.sub("", line)).strip()
            text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            if text:
                texts.append(text)
        for text in texts:
            if text in recent:
                continue
            recent = (recent + [text])[-3:]
            lines.append(f"[{format_time(start)}] {text}" if timestamps else text)
    return "\n".join(lines)


def _lang_matches(code: str, wanted: str) -> bool:
    code, wanted = code.lower(), wanted.lower()
    return code == wanted or code.startswith(wanted + "-") or code == wanted + "-orig"


def _pick_track(info: dict[str, Any], languages: list[str]) -> tuple[str, bool, dict] | None:
    """Выбирает дорожку субтитров: (язык, автоматические ли, формат с url)."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    manual = {k: v for k, v in manual.items() if k != "live_chat"}

    def best_format(formats: list[dict]) -> dict | None:
        for ext in ("vtt", "srt"):
            for f in formats:
                if f.get("ext") == ext and f.get("url"):
                    return f
        return None

    candidates: list[tuple[str, bool]] = []
    for wanted in languages:
        candidates += [(k, False) for k in manual if _lang_matches(k, wanted)]
        # «en-orig» — исходная дорожка, остальные автоматические — машинный перевод
        candidates += sorted(((k, True) for k in auto if _lang_matches(k, wanted)),
                             key=lambda c: not c[0].endswith("-orig"))
    if not languages:
        original = (info.get("language") or "").lower()
        if original:
            candidates += [(k, False) for k in manual if _lang_matches(k, original)]
        candidates += [(k, False) for k in manual]
        candidates += [(k, True) for k in auto if k.endswith("-orig")]
        if original:
            candidates += [(k, True) for k in auto if _lang_matches(k, original)]
        candidates += [(k, True) for k in auto if _lang_matches(k, "en")]
    for code, is_auto in candidates:
        fmt = best_format((auto if is_auto else manual).get(code) or [])
        if fmt:
            return code, is_auto, fmt
    return None


def fetch_transcript(source: str, languages: list[str] | None = None, cookies_path: str = "",
                     cookies_browser: str = "", timestamps: bool = True) -> dict[str, Any]:
    """
    Текст речи видео. Для ссылки берутся субтитры с сайта (настоящие, иначе автоматические),
    для файла — лежащие рядом .srt/.vtt с тем же началом имени. Распознавания речи нет.
    """
    languages = [lang.strip() for lang in (languages or []) if lang.strip()]
    if not is_url(source):
        return _local_transcript(source, languages, timestamps)

    import yt_dlp
    from src.core.ytdlp_engine import _apply_cookies

    opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "noplaylist": True,
                            "skip_download": True, "socket_timeout": 20}
    _apply_cookies(opts, cookies_path, cookies_browser)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source, download=False) or {}
        picked = _pick_track(info, languages)
        if not picked:
            have = sorted(set(info.get("subtitles") or {}) | {
                k for k in (info.get("automatic_captions") or {}) if k.endswith("-orig")})
            wanted = f" на языках {', '.join(languages)}" if languages else ""
            extra = f" Есть: {', '.join(have)}." if have else ""
            raise RuntimeError(f"У этого видео нет субтитров{wanted}.{extra}")
        code, is_auto, fmt = picked
        raw = ydl.urlopen(fmt["url"]).read().decode("utf-8", "replace")
    text = subtitles_to_text(raw, timestamps)
    log.info("transcript: %s, язык %s, авто=%s, строк %s", info.get("id"), code, is_auto, text.count("\n") + 1)
    return {
        "title": info.get("title") or "",
        "duration": info.get("duration") or 0,
        "language": code.removesuffix("-orig"),
        "automatic": is_auto,
        "text": text,
    }


def _local_transcript(path: str, languages: list[str], timestamps: bool) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise RuntimeError(f"Файл не найден: {path}")
    if path.lower().endswith(SUBTITLE_EXTENSIONS):
        found = [path]
    else:
        stem = os.path.splitext(path)[0]
        found = sorted(p for p in glob.glob(glob.escape(stem) + ".*")
                       if p.lower().endswith(SUBTITLE_EXTENSIONS))
    if languages:
        preferred = [p for lang in languages for p in found
                     if f".{lang.lower()}." in os.path.basename(p).lower()]
        found = preferred or found
    if not found:
        raise RuntimeError("Рядом с файлом нет субтитров (.srt/.vtt). Передайте ссылку на видео "
                           "или скачайте его с субтитрами (--subs ru,en)")
    with open(found[0], encoding="utf-8", errors="replace") as f:
        raw = f.read()
    parts = os.path.basename(found[0]).split(".")
    return {
        "title": os.path.basename(os.path.splitext(path)[0]),
        "language": parts[-2] if len(parts) >= 3 else "",
        "automatic": False,
        "file": os.path.abspath(found[0]),
        "text": subtitles_to_text(raw, timestamps),
    }


def _run_ffmpeg(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    if not FFMPEG_PATH:
        raise RuntimeError("ffmpeg не найден, кадры извлечь нельзя")
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run([FFMPEG_PATH, "-hide_banner", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, **kwargs)


def media_duration(path: str) -> float | None:
    """Длительность в секундах по выводу `ffmpeg -i` (ffprobe есть не во всех сборках)."""
    out = _run_ffmpeg(["-i", path], timeout=60)
    m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", out.stderr)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def frames_dir_for(path: str) -> str:
    """Папка для кадров файла: в данных программы, своя для каждого файла."""
    digest = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:10]
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(path))[0])[:40]
    return os.path.join(get_app_data_dir(), "frames", f"{stem}-{digest}")


def extract_frames(path: str, count: int = 6, timestamps: list[float] | None = None,
                   width: int = 640, out_dir: str = "") -> dict[str, Any]:
    """
    Кадры видео в JPEG. Без timestamps — count кадров равномерно по всей длине (середины отрезков),
    с timestamps — ровно в указанные секунды. Картинка (фото из галереи) отдаётся одним кадром.
    """
    if not os.path.isfile(path):
        raise RuntimeError(f"Файл не найден: {path}")
    count = max(1, min(int(count), 60))
    width = max(64, min(int(width), 1920))
    duration = media_duration(path)
    if timestamps:
        times = [max(0.0, float(t)) for t in timestamps][:60]
        if duration:
            times = [min(t, max(duration - 0.1, 0.0)) for t in times]
    elif duration and duration > 0.2:
        times = [duration * (i + 0.5) / count for i in range(count)]
    else:
        times = [0.0]

    out_dir = out_dir or frames_dir_for(path)
    os.makedirs(out_dir, exist_ok=True)
    frames = []
    for t in times:
        out = os.path.join(out_dir, f"frame_{t:09.2f}.jpg".replace(":", "-"))
        # -ss до -i: быстрый переход к ключевому кадру, затем точная докрутка
        result = _run_ffmpeg(["-loglevel", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                              "-vf", f"scale='min({width},iw)':-2", "-q:v", "4", "-y", out])
        if result.returncode != 0 or not os.path.isfile(out):
            log.warning("frames: кадр %.2f не получился: %s", t, result.stderr.strip()[-300:])
            continue
        frames.append({"time": round(t, 2), "label": format_time(t), "path": out})
    if not frames:
        raise RuntimeError("Не удалось извлечь ни одного кадра: ffmpeg не смог открыть файл")
    return {"file": os.path.abspath(path), "duration": round(duration, 2) if duration else None,
            "frames": frames}


def pick_media_file(files: list[str]) -> str | None:
    """Из скачанного выбирает файл для кадров: видео, иначе картинку."""
    for exts in (VIDEO_EXTENSIONS, IMAGE_EXTENSIONS):
        for path in files:
            if path.lower().endswith(exts):
                return path
    return None
