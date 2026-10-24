"""Текстовый отчёт об ошибках загрузки: для окна «Подробнее» и кнопки «Скопировать отчёт»."""
import platform
import sys
from datetime import datetime
from typing import Any, Iterable

from src.utils.logger import read_log_tail, redact


def format_failures(items: Iterable[Any]) -> str:
    """Понятное описание каждой неудачи: ссылка, что случилось, что делать, исходная ошибка."""
    blocks: list[str] = []
    for item in items:
        lines = [redact(item.url)]
        lines.append(f"  Что случилось: {item.message or 'неизвестная ошибка'}")
        if item.hint:
            lines.append(f"  Что делать: {item.hint}")
        if item.technical:
            lines.append(f"  Техническая причина: {item.technical}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_report(items: Iterable[Any], engine_state: dict[str, Any], log_lines: int = 60) -> str:
    """Полный отчёт для разработчика: окружение, ошибки и хвост лога. Секреты маскируются."""
    ffmpeg = engine_state.get("ffmpeg")
    ffmpeg_text = "не проверен" if ffmpeg is None else (
        f"OK {ffmpeg[1]}" if ffmpeg[0] else f"проблема: {ffmpeg[1]}")
    parts = [
        "MediaHarvester — отчёт об ошибке",
        f"Время: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Система: {platform.platform()} | Python {platform.python_version()} | "
        f"exe={getattr(sys, 'frozen', False)}",
        f"yt-dlp: {engine_state.get('ytdlp') or '?'} | ffmpeg: {ffmpeg_text}",
        "",
        "=== Ошибки ===",
        format_failures(items) or "(нет)",
        "",
        f"=== Последние строки лога ({log_lines}) ===",
        read_log_tail(log_lines) or "(лог пуст)",
    ]
    return "\n".join(parts)
