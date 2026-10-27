"""
Автообновление yt-dlp без переустановки программы.

Официальный релиз yt-dlp содержит самодостаточный zip-архив «yt-dlp» с пакетом yt_dlp.
Мы скачиваем его в папку данных приложения и при следующем запуске подключаем раньше
встроенной копии (через мета-импортёр), поэтому это работает и в .exe, и при запуске из исходников.
Загруженный архив проверяется по SHA2-256SUMS из того же релиза и пробным импортом.
"""
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import json
import os
import re
import sys
import time
import zipfile
import zipimport
from dataclasses import dataclass

import requests

from src.utils.helpers import get_app_data_dir

RELEASES_LATEST_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/{name}"
RELEASE_ASSET = "yt-dlp"
CHECKSUMS_ASSET = "SHA2-256SUMS"

CHECK_INTERVAL_SECONDS = 12 * 60 * 60
REQUEST_TIMEOUT = (10, 60)

_TAG_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}(?:\.\d+)?$")

_active_finder: "_ZipOverrideFinder | None" = None


def update_dir() -> str:
    path = os.path.join(get_app_data_dir(), "yt-dlp")
    os.makedirs(path, exist_ok=True)
    return path


def override_path() -> str:
    return os.path.join(update_dir(), "yt-dlp.zip")


def _state_path() -> str:
    return os.path.join(update_dir(), "state.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass


def version_key(version: str) -> tuple[int, ...]:
    """'2026.10.01' -> (2026, 10, 1); ночные сборки '2026.10.01.123456' считаются новее."""
    return tuple(int(p) for p in re.findall(r"\d+", version))


def read_zip_version(zip_path: str) -> str | None:
    """Версия yt-dlp из архива без его импорта."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            text = zf.read("yt_dlp/version.py").decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


class _ZipOverrideFinder(importlib.abc.MetaPathFinder):
    """Отдаёт пакет yt_dlp из zip-архива раньше любых других источников (в том числе из .exe)."""

    def __init__(self, zip_path: str):
        self.zip_path = zip_path
        self._importer = zipimport.zipimporter(zip_path)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yt_dlp" or fullname.startswith("yt_dlp."):
            return self._importer.find_spec(fullname, target)
        return None


def _purge_ytdlp_modules() -> None:
    for name in [n for n in sys.modules if n == "yt_dlp" or n.startswith("yt_dlp.")]:
        del sys.modules[name]


def _bundled_version() -> str | None:
    """Версия yt-dlp, поставляемая с программой (None, если определить дёшево нельзя)."""
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return None


def _override_is_stale(zip_path: str, zip_version: str | None) -> bool:
    """Загруженная копия не нужна, если встроенная новее (программу переустановили/обновили)."""
    bundled = _bundled_version()
    if bundled and zip_version:
        try:
            return version_key(bundled) >= version_key(zip_version)
        except Exception:
            return False
    if getattr(sys, "frozen", False):
        try:
            return os.path.getmtime(sys.executable) > os.path.getmtime(zip_path)
        except OSError:
            return False
    return False


def activate_override() -> str | None:
    """
    Подключает загруженную версию yt-dlp, если она есть и валидна. Вызывать ДО импорта yt_dlp.
    Возвращает версию подключённой копии или None (используется встроенная).
    """
    global _active_finder
    if _active_finder is not None:
        return read_zip_version(_active_finder.zip_path)
    from src.utils.helpers import self_update_disabled
    if self_update_disabled():
        return None  # системный пакет: только yt-dlp из пакета, даже если скачанная копия осталась от другой сборки

    zip_path = override_path()
    if not os.path.isfile(zip_path):
        return None

    zip_version = read_zip_version(zip_path)
    if zip_version is None or _override_is_stale(zip_path, zip_version):
        _discard_override(zip_path)
        return None

    if "yt_dlp" in sys.modules:
        return None  # слишком поздно: встроенная версия уже импортирована

    finder = None
    try:
        finder = _ZipOverrideFinder(zip_path)
        sys.meta_path.insert(0, finder)
        importlib.import_module("yt_dlp.version")
        _active_finder = finder
        return zip_version
    except Exception:
        # Битый архив не должен ломать запуск: откатываемся на встроенную копию
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)
        _purge_ytdlp_modules()
        _discard_override(zip_path)
        return None


def _discard_override(zip_path: str) -> None:
    try:
        os.remove(zip_path)
    except OSError:
        pass
    state = _load_state()
    state.pop("version", None)
    _save_state(state)


def current_version() -> str:
    """Версия yt-dlp, которая реально используется сейчас."""
    import yt_dlp.version
    return yt_dlp.version.__version__


@dataclass
class UpdateResult:
    status: str          # "current" | "updated" | "skipped" | "error"
    current: str = ""
    latest: str = ""
    message: str = ""


def fetch_latest_tag() -> str:
    """Тег последнего релиза: GitHub перенаправляет /releases/latest на /releases/tag/<тег>."""
    r = requests.get(RELEASES_LATEST_URL, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                     headers={"User-Agent": "MediaHarvester"}, stream=True)
    try:
        r.raise_for_status()
        tag = r.url.rstrip("/").rsplit("/", 1)[-1]
    finally:
        r.close()
    if not _TAG_RE.match(tag):
        raise RuntimeError(f"Неожиданный тег релиза: {tag!r}")
    return tag


def _download(url: str, dest: str) -> None:
    with requests.get(url, timeout=REQUEST_TIMEOUT, stream=True,
                      headers={"User-Agent": "MediaHarvester"}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                f.write(chunk)


def _expected_sha256(tag: str) -> str:
    r = requests.get(DOWNLOAD_URL_TEMPLATE.format(tag=tag, name=CHECKSUMS_ASSET),
                     timeout=REQUEST_TIMEOUT, headers={"User-Agent": "MediaHarvester"})
    r.raise_for_status()
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == RELEASE_ASSET:
            return parts[0].lower()
    raise RuntimeError("В SHA2-256SUMS нет записи для yt-dlp")


def install_release(tag: str) -> str:
    """Скачивает релиз, проверяет контрольную сумму и версию, подменяет файл. Возвращает версию."""
    dest = override_path()
    tmp = dest + ".download"
    try:
        expected = _expected_sha256(tag)
        _download(DOWNLOAD_URL_TEMPLATE.format(tag=tag, name=RELEASE_ASSET), tmp)

        sha = hashlib.sha256()
        with open(tmp, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(block)
        if sha.hexdigest() != expected:
            raise RuntimeError("Контрольная сумма скачанного yt-dlp не совпала")

        version = read_zip_version(tmp)
        if version != tag:
            raise RuntimeError(f"Версия в архиве ({version}) не совпала с релизом ({tag})")

        os.replace(tmp, dest)
        return version
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def check_for_update(force: bool = False) -> UpdateResult:
    """
    Проверяет новую версию yt-dlp (не чаще раза в 12 часов, если не force) и скачивает её.
    Новая версия начнёт использоваться после перезапуска программы. Ошибки сети не бросаются.
    """
    try:
        current = current_version()
    except Exception as e:
        return UpdateResult("error", message=f"yt-dlp не загружен: {e}")

    state = _load_state()
    if not force and time.time() - float(state.get("last_check", 0) or 0) < CHECK_INTERVAL_SECONDS:
        return UpdateResult("skipped", current=current)

    try:
        latest = fetch_latest_tag()

        if version_key(latest) <= version_key(current):
            state["last_check"] = time.time()
            _save_state(state)
            return UpdateResult("current", current=current, latest=latest)

        pending = read_zip_version(override_path())
        if pending and version_key(pending) >= version_key(latest):
            return UpdateResult("updated", current=current, latest=pending,
                                message="Уже скачано, вступит в силу после перезапуска")

        version = install_release(latest)
        state = _load_state()
        state["version"] = version
        state["last_check"] = time.time()
        _save_state(state)
        return UpdateResult("updated", current=current, latest=version)
    except Exception as e:
        return UpdateResult("error", current=current, message=str(e)[:120])
