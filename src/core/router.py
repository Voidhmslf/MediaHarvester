import re
from typing import Any


def detect_url_type(url: str) -> dict[str, Any]:
    """
    Анализирует URL и определяет платформу, тип контента и подходящий движок загрузки.

    Возвращает словарь:
    {
        "platform": "youtube" | "instagram" | "vk" | "generic" | "none",
        "media_type": "video" | "shorts" | "music" | "reel" | "post" | "stories" | "album" | "none",
        "engine": "ytdlp" | "insta" | "vk_photos" | "vk_music" | "none",
        "label": Человекочитаемая метка для интерфейса
    }
    """
    clean_url = url.strip()
    if not clean_url:
        return {
            "platform": "none",
            "media_type": "none",
            "engine": "none",
            "label": "Ожидание ссылки",
        }

    # ─────────────────────────────────────────────────────────────
    # 1. YouTube
    # ─────────────────────────────────────────────────────────────
    if "music.youtube.com" in clean_url:
        return {
            "platform": "youtube",
            "media_type": "music",
            "engine": "ytdlp",
            "label": "YouTube Music • Трек / Альбом",
        }

    if any(domain in clean_url for domain in ("youtube.com", "youtu.be")):
        if "/shorts/" in clean_url:
            return {
                "platform": "youtube",
                "media_type": "shorts",
                "engine": "ytdlp",
                "label": "YouTube • Shorts",
            }
        return {
            "platform": "youtube",
            "media_type": "video",
            "engine": "ytdlp",
            "label": "YouTube • Видео/Shorts",
        }

    # ─────────────────────────────────────────────────────────────
    # 2. Instagram
    # ─────────────────────────────────────────────────────────────
    if "instagram.com" in clean_url or "instagr.am" in clean_url:
        if "/reel/" in clean_url or "/reels/" in clean_url:
            return {
                "platform": "instagram",
                "media_type": "reel",
                "engine": "ytdlp",  # С авто-фоллбэком на insta_engine при необходимости
                "label": "Instagram • Reels",
            }
        if "/stories/" in clean_url:
            return {
                "platform": "instagram",
                "media_type": "stories",
                "engine": "insta",
                "label": "Instagram • Stories",
            }
        if "/p/" in clean_url:
            return {
                "platform": "instagram",
                "media_type": "post",
                "engine": "insta",
                "label": "Instagram • Пост / Карусель",
            }
        if "/tv/" in clean_url:
            return {
                "platform": "instagram",
                "media_type": "post",
                "engine": "insta",
                "label": "Instagram • IGTV / Видео",
            }
        # Профиль пользователя instagram.com/username
        if re.search(r"instagram\.com/[A-Za-z0-9_.]+(?:/)?$", clean_url):
            return {
                "platform": "instagram",
                "media_type": "post",
                "engine": "insta",
                "label": "Instagram • Профиль",
            }
        return {
            "platform": "instagram",
            "media_type": "post",
            "engine": "insta",
            "label": "Instagram • Пост / Карусель / Stories",
        }

    # ─────────────────────────────────────────────────────────────
    # 3. ВКонтакте (vk.com, vk.ru, vkvideo.ru)
    # ─────────────────────────────────────────────────────────────
    is_vk = any(d in clean_url for d in ("vk.com", "vk.ru", "vkvideo.ru")) or clean_url.startswith("vk.com")
    if is_vk:
        # Видео / Клипы
        if "vkvideo.ru" in clean_url or re.search(r"(?:video|clip)(-?\d+)_(\d+)", clean_url):
            return {
                "platform": "vk",
                "media_type": "video",
                "engine": "ytdlp",
                "label": "VK • Видео / Клип",
            }
        # Фотоальбомы
        if re.search(r"album(-?\d+)_([a-zA-Z0-9]+)", clean_url):
            return {
                "platform": "vk",
                "media_type": "album",
                "engine": "vk_photos",
                "label": "VK • Фотоальбом",
            }
        # Музыка
        if "music/playlist" in clean_url or "audio" in clean_url or re.search(r"vk\.com/id\d+", clean_url):
            return {
                "platform": "vk",
                "media_type": "music",
                "engine": "vk_music",
                "label": "VK • Музыка",
            }

    # ─────────────────────────────────────────────────────────────
    # 4. Неизвестная ссылка / Прямой URL видео-потока
    # ─────────────────────────────────────────────────────────────
    return {
        "platform": "generic",
        "media_type": "video",
        "engine": "ytdlp",
        "label": "Универсальный видео-загрузчик (yt-dlp)",
    }
