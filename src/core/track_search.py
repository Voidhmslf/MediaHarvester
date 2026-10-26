"""
«Треки по списку»: по строкам «Исполнитель — Название» ищет трек на YouTube (yt-dlp) и сохраняет лучшее
аудио в MP3. К VK не обращается: подходит, когда музыка VK недоступна через API.
"""
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable

import yt_dlp

from src.core.ytdlp_engine import AUDIO_CODECS, get_video_format_spec, needs_thumbnail
from src.utils.errors import explain_error
from src.utils.helpers import FFMPEG_PATH, DownloadCancelledError, sanitize_filename
from src.utils.logger import get_logger

log = get_logger("tracks")

FOLDER_NAME = "Треки_по_списку"
NOT_FOUND_REPORT = "_not_found.txt"
SEARCH_RESULTS = 8
MIN_TITLE_MATCH = 0.6   # доля слов названия, которые должны встретиться в найденном ролике
MIN_SCORE = 3.0

_SEPARATORS = (" - ", " – ", " — ", " | ", " – ", "—")
_NUMBERING = re.compile(r"^\s*(?:[-*•]\s*|\d+\s*[.)]\s*)")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NOISE = {"feat", "ft", "featuring", "official", "video", "audio", "lyrics", "lyric", "hd", "hq", "music", "клип"}
# Слова, по которым отсеиваем версии не из оригинала (если их нет в самом запросе)
_BAD_WORDS = {
    "live", "cover", "remix", "karaoke", "nightcore", "slowed", "reverb", "sped", "8d", "instrumental",
    "mashup", "reaction", "tutorial", "lesson", "parody", "fanmade", "minus", "минус", "кавер", "ремикс",
    "караоке", "концерт", "пародия", "hour", "hours", "часа", "часов", "mix",
}


@dataclass
class Track:
    query: str          # что искать
    artist: str = ""
    title: str = ""
    original: str = ""  # строка из списка как есть

    @property
    def file_stem(self) -> str:
        base = f"{self.artist} - {self.title}" if self.artist and self.title else self.query
        return sanitize_filename(base)[:150]


def parse_track_list(text: str) -> list[Track]:
    """Строки списка -> треки. Понимает нумерацию, маркеры, разделители « - », « – », « — », пропускает пустые и #-комментарии."""
    tracks: list[Track] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = _NUMBERING.sub("", raw).strip()
        if not line or line.startswith("#"):
            continue
        artist = title = ""
        for sep in _SEPARATORS:
            if sep in line:
                artist, title = (part.strip() for part in line.split(sep, 1))
                break
        query = f"{artist} {title}".strip() if artist and title else line
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        tracks.append(Track(query=query, artist=artist, title=title, original=raw.strip()))
    return tracks


def _tokens(text: str) -> list[str]:
    words = [w.lower().replace("ё", "е") for w in _WORD.findall(text or "")]
    return [w for w in words if w not in _NOISE and (len(w) > 1 or w.isdigit())]


def score_candidate(track: Track, entry: dict[str, Any]) -> tuple[float, float]:
    """Оценка ролика из выдачи: (баллы, доля совпавших слов названия). Чем больше, тем лучше."""
    title_tokens = set(_tokens(entry.get("title", "")))
    channel = entry.get("channel") or entry.get("uploader") or ""
    channel_tokens = set(_tokens(channel))
    haystack = title_tokens | channel_tokens

    wanted_title = _tokens(track.title if track.title else track.query)
    wanted_artist = _tokens(track.artist)
    title_hits = (sum(1 for w in wanted_title if w in title_tokens | channel_tokens) / len(wanted_title)
                  ) if wanted_title else 0.0
    artist_hits = (sum(1 for w in wanted_artist if w in haystack) / len(wanted_artist)) if wanted_artist else 1.0

    score = 4 * title_hits + 3 * artist_hits
    if channel.lower().endswith("- topic"):
        score += 1.5
    if "official" in (entry.get("title", "").lower()) or "vevo" in channel.lower():
        score += 0.8

    query_tokens = set(_tokens(track.query))
    penalty = sum(2.5 for w in _BAD_WORDS if w in title_tokens and w not in query_tokens)
    score -= min(penalty, 6.0)

    duration = entry.get("duration") or 0
    if duration > 900:
        score -= 4
    elif duration > 600:
        score -= 1.5
    elif 0 < duration < 45:
        score -= 3
    return score, title_hits


def pick_best(track: Track, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Лучший ролик из выдачи или None, если ничего достаточно похожего нет."""
    best, best_score = None, MIN_SCORE
    for entry in entries:
        if not entry or not (entry.get("url") or entry.get("id")):
            continue
        score, title_hits = score_candidate(track, entry)
        if title_hits >= MIN_TITLE_MATCH and score > best_score:
            best, best_score = entry, score
    return best


def _tag_mp3(path: str, track: Track) -> None:
    """Записывает исполнителя и название из списка в теги (если есть mutagen)."""
    if not (track.artist and track.title and path.lower().endswith(".mp3")):
        return
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3NoHeaderError
        try:
            tags = EasyID3(path)
        except ID3NoHeaderError:
            tags = EasyID3()
        tags["artist"], tags["title"] = track.artist, track.title
        tags.save(path)
    except Exception as e:
        log.debug("Теги не записаны (%s): %s", path, e)


def _existing_file(folder: str, stem: str) -> str | None:
    for ext in ("mp3", "m4a", "opus", "webm", "ogg"):
        candidate = os.path.join(folder, f"{stem}.{ext}")
        if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


def download_track_list(
    text: str,
    download_path: str,
    progress_callback: Callable[[str, str, float | None, str], None],
    cookies_path: str = "",
    cancel_event: threading.Event | None = None,
    audio_codec: str = "mp3",
    embed_cover: bool = False,
) -> str:
    """
    Ищет и скачивает треки из списка. Уже скачанные пропускает (повторный запуск докачивает только недостающее),
    ненайденные и упавшие записывает в _not_found.txt. Возвращает папку с треками.
    """
    tracks = parse_track_list(text)
    if not tracks:
        raise ValueError("Список пуст: вставьте строки вида «Исполнитель — Название»")

    folder = os.path.join(download_path, FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    total = len(tracks)
    downloaded = skipped = 0
    problems: list[tuple[Track, str]] = []
    log.info("Список треков: %s, папка %s", total, folder)

    def cancelled() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    base_opts: dict[str, Any] = {"quiet": True, "no_warnings": True}
    if FFMPEG_PATH:
        base_opts["ffmpeg_location"] = FFMPEG_PATH
    if cookies_path and os.path.isfile(cookies_path):
        base_opts["cookiefile"] = cookies_path
    _, postprocessors = get_video_format_spec("Только аудио (MP3)", audio_codec, embed_cover)
    codec_name = audio_codec.upper() if audio_codec in AUDIO_CODECS else "MP3"

    for index, track in enumerate(tracks, 1):
        if cancelled():
            progress_callback(f"Загрузка отменена (скачано {downloaded} из {total})", "warning", None, "")
            raise DownloadCancelledError("Загрузка отменена пользователем")

        stem = track.file_stem
        label = f"Трек {index} из {total}: {stem[:34]}"

        def report(fraction: float, text_: str = label) -> None:
            overall = (index - 1 + max(0.0, min(1.0, fraction))) / total
            progress_callback(text_, "working", overall, f"{int(overall * 100)}%")

        if _existing_file(folder, stem):
            skipped += 1
            report(1.0)
            continue

        report(0.0, f"Ищу: {stem[:40]}")
        try:
            with yt_dlp.YoutubeDL({**base_opts, "extract_flat": True, "skip_download": True}) as ydl:
                found = ydl.extract_info(f"ytsearch{SEARCH_RESULTS}:{track.query}", download=False)
            entry = pick_best(track, list((found or {}).get("entries") or []))
            if entry is None:
                problems.append((track, "не найден подходящий ролик"))
                log.info("Не найден: %s", track.query)
                report(1.0)
                continue

            url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"

            def hook(d: dict[str, Any]) -> None:
                if cancelled():
                    raise DownloadCancelledError("Загрузка отменена пользователем")
                if d.get("status") == "downloading":
                    total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    if total_bytes:
                        report(0.1 + 0.8 * d.get("downloaded_bytes", 0) / total_bytes)
                elif d.get("status") == "finished":
                    report(0.95, f"Конвертация в {codec_name}: {stem[:30]}")

            opts = {
                **base_opts,
                "format": "bestaudio/best",
                "outtmpl": os.path.join(folder, f"{stem}.%(ext)s"),
                "noplaylist": True,
                "windowsfilenames": True,
                "progress_hooks": [hook],
            }
            if postprocessors:
                opts["postprocessors"] = postprocessors
            if needs_thumbnail(postprocessors):
                opts["writethumbnail"] = True
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            saved = _existing_file(folder, stem)
            if saved:
                _tag_mp3(saved, track)
                downloaded += 1
                log.info("Скачан: %s <- %s", stem, url)
            else:
                problems.append((track, "файл не появился после скачивания"))
            report(1.0)
        except DownloadCancelledError:
            progress_callback(f"Загрузка отменена (скачано {downloaded} из {total})", "warning", None, "")
            raise
        except Exception as e:
            info = explain_error(e)
            problems.append((track, info.message))
            log.warning("Трек '%s' не скачан: %s | %s", track.query, info.message, info.technical)
            report(1.0)

    report_path = os.path.join(folder, NOT_FOUND_REPORT)
    if problems:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("Не удалось скачать (запустите тот же список ещё раз — докачается только это):\n")
            for track, reason in problems:
                f.write(f"{track.original or track.query}\n    причина: {reason}\n")
    elif os.path.exists(report_path):
        os.remove(report_path)

    if downloaded == 0 and skipped == 0:
        raise RuntimeError("Не удалось скачать ни одного трека: " + (problems[0][1] if problems else "нет результатов"))

    parts = [f"скачано {downloaded}"]
    if skipped:
        parts.append(f"уже было {skipped}")
    if problems:
        parts.append(f"не найдено/ошибок {len(problems)}, см. {NOT_FOUND_REPORT}")
    progress_callback(f"Готово: {total} треков ({', '.join(parts)})",
                      "warning" if problems else "success", 1.0, "100%")
    return folder
