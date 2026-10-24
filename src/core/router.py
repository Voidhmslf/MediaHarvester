import re
from typing import Any
from urllib.parse import urlparse

# Домены (хост равен или оканчивается на ".домен") -> имя платформы, для которой возможен
# запасной движок gallery-dl (фото, галереи, карусели)
GALLERY_HOSTS: dict[str, str] = {
    "instagram.com": "Instagram",
    "instagr.am": "Instagram",
    "x.com": "X",
    "twitter.com": "X",
    "tiktok.com": "TikTok",
    "pinterest.com": "Pinterest",
    "pinterest.ru": "Pinterest",
    "pin.it": "Pinterest",
    "reddit.com": "Reddit",
    "redd.it": "Reddit",
}

SOUNDCLOUD_HOSTS = ("soundcloud.com", "snd.sc")


def _host(url: str) -> str:
    """Хост из ссылки (с учётом ссылок без схемы), в нижнем регистре и без www."""
    raw = url.strip()
    if "://" not in raw:
        raw = "//" + raw
    host = (urlparse(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def gallery_platform_name(url: str) -> str | None:
    """Имя платформы, если для неё есть запасной/основной движок gallery-dl, иначе None."""
    host = _host(url)
    for domain, name in GALLERY_HOSTS.items():
        if _host_matches(host, (domain,)):
            return name
    return None


def _path(url: str) -> str:
    raw = url.strip()
    if "://" not in raw:
        raw = "//" + raw
    return urlparse(raw).path


def _detect_other_platform(url: str) -> dict[str, Any] | None:
    host = _host(url)
    path = _path(url)

    # TikTok
    if _host_matches(host, ("tiktok.com",)):
        if "/photo/" in path:
            return {"platform": "tiktok", "media_type": "post", "engine": "gallery",
                    "label": "TikTok • Фотопост / слайдшоу"}
        if re.fullmatch(r"/@[^/]+/?", path):
            return {"platform": "tiktok", "media_type": "video", "engine": "ytdlp",
                    "playlist": True, "label": "TikTok • Профиль (все видео)"}
        return {"platform": "tiktok", "media_type": "video", "engine": "ytdlp",
                "label": "TikTok • Видео"}

    # X / Twitter
    if _host_matches(host, ("x.com", "twitter.com")):
        if "/status/" in path:
            return {"platform": "x", "media_type": "post", "engine": "ytdlp",
                    "label": "X • Пост (видео / фото)"}
        return {"platform": "x", "media_type": "post", "engine": "gallery",
                "listing": True, "label": "X • Профиль (медиа)"}

    # Pinterest
    if _host_matches(host, ("pinterest.com", "pinterest.ru", "pin.it")):
        if host == "pin.it" or "/pin/" in path:
            return {"platform": "pinterest", "media_type": "post", "engine": "gallery",
                    "label": "Pinterest • Пин"}
        return {"platform": "pinterest", "media_type": "album", "engine": "gallery",
                "listing": True, "label": "Pinterest • Доска / профиль"}

    # Reddit
    if _host_matches(host, ("reddit.com", "redd.it")):
        if host.endswith("redd.it") or "/comments/" in path:
            return {"platform": "reddit", "media_type": "post", "engine": "ytdlp",
                    "label": "Reddit • Пост"}
        return {"platform": "reddit", "media_type": "album", "engine": "gallery",
                "listing": True, "label": "Reddit • Сабреддит / профиль"}

    # SoundCloud
    if _host_matches(host, SOUNDCLOUD_HOSTS):
        segments = [s for s in path.split("/") if s]
        if "sets" in segments:
            return {"platform": "soundcloud", "media_type": "music", "engine": "ytdlp",
                    "playlist": True, "label": "SoundCloud • Плейлист / альбом"}
        if len(segments) == 1:
            return {"platform": "soundcloud", "media_type": "music", "engine": "ytdlp",
                    "playlist": True, "label": "SoundCloud • Профиль (все треки)"}
        return {"platform": "soundcloud", "media_type": "music", "engine": "ytdlp",
                "label": "SoundCloud • Трек"}

    return None


def detect_url_type(url: str) -> dict[str, Any]:
    """
    Анализирует URL и определяет платформу, тип контента и подходящий движок загрузки.

    Возвращает словарь:
    {
        "platform": "youtube" | "instagram" | "vk" | "tiktok" | "x" | "pinterest" | "reddit"
                    | "soundcloud" | "generic" | "none",
        "media_type": "video" | "shorts" | "music" | "reel" | "post" | "stories" | "album" | "none",
        "engine": "ytdlp" | "insta" | "gallery" | "vk_photos" | "vk_music" | "none",
        "label": Человекочитаемая метка для интерфейса,
        "playlist": (необязательно) True — ссылка ведёт на список, нужно качать целиком,
        "listing": (необязательно) True — страница-лента (доска, профиль), число файлов ограничивается
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
    # 4. TikTok, X, Pinterest, Reddit, SoundCloud
    # ─────────────────────────────────────────────────────────────
    other = _detect_other_platform(clean_url)
    if other:
        return other

    # ─────────────────────────────────────────────────────────────
    # 5. Неизвестная ссылка / Прямой URL видео-потока
    # ─────────────────────────────────────────────────────────────
    return {
        "platform": "generic",
        "media_type": "video",
        "engine": "ytdlp",
        "label": "Универсальный видео-загрузчик (yt-dlp)",
    }
