"""
Сервер MCP (Model Context Protocol) через stdin/stdout: `mediaharvester mcp`.
ИИ-агент (Claude Desktop, Claude Code, Cursor и другие) получает инструменты: скачать по ссылке,
узнать сведения о ссылке, прочитать речь из субтитров и посмотреть кадры видео картинками.
Сообщения — JSON-RPC 2.0, по одному в строке. Зависимостей, кроме самой программы, нет.
"""
import base64
import json
import os
import queue
import sys
import threading
import time
from typing import Any, Callable

from src.version import __version__
from src.utils.logger import get_logger

log = get_logger("mcp")

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "MediaHarvester downloads video, audio and photos from YouTube, VK, Instagram, TikTok, X, Reddit, "
    "Pinterest, SoundCloud and most other sites (yt-dlp + gallery-dl). "
    "To understand a video without a human: call get_transcript for what is said (timestamped lines) "
    "and get_frames for what is shown; ask get_frames for specific timestamps to look closer at a moment. "
    "Use download to save files for the user; it returns absolute paths of the saved files."
)

_SOURCE = {"type": "string", "description": "Video URL, or an absolute path to a downloaded file"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "download",
        "title": "Download media",
        "description": ("Download video, audio or photos from one or more links and return the saved file "
                        "paths. Playlists, channels and profiles are detected automatically."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                         "description": "Links to download"},
                "output_dir": {"type": "string",
                               "description": "Folder to save to (default: the folder chosen in the app, "
                                              "usually ~/Downloads)"},
                "quality": {"type": "string",
                            "enum": ["best", "2160", "1440", "1080", "720", "480", "360", "audio"],
                            "description": "Max video height, or 'audio' for audio only (default best)"},
                "audio_format": {"type": "string", "enum": ["mp3", "m4a", "opus"],
                                 "description": "Format when quality is 'audio' (default mp3)"},
                "playlist": {"type": "boolean",
                             "description": "Download the whole playlist if the link points to one"},
                "playlist_limit": {"type": "integer", "minimum": 0,
                                   "description": "Only the first N playlist items (0 = all)"},
                "subtitles": {"type": "array", "items": {"type": "string"},
                              "description": "Save .srt subtitles in these languages, e.g. ['en', 'ru']"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "media_info",
        "title": "Link info",
        "description": "Title, author, duration, available qualities and platform of a link, without downloading.",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_transcript",
        "title": "Transcript",
        "description": ("Spoken text of a video as '[mm:ss] text' lines, from the site's subtitles (manual, "
                        "otherwise automatic) or from .srt/.vtt files next to a downloaded file. "
                        "No speech recognition: fails if the video has no subtitles."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": _SOURCE,
                "languages": {"type": "array", "items": {"type": "string"},
                              "description": "Preferred languages in order, e.g. ['ru', 'en'] "
                                             "(default: the video's own language)"},
            },
            "required": ["source"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_frames",
        "title": "Video frames",
        "description": ("Look at a video: returns JPEG frames as images. Without timestamps, frames are spread "
                        "evenly over the whole video; pass timestamps (seconds) to inspect particular moments. "
                        "A link is first downloaded in 480p to the app cache."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": _SOURCE,
                "count": {"type": "integer", "minimum": 1, "maximum": 24,
                          "description": "Number of evenly spaced frames (default 6)"},
                "timestamps": {"type": "array", "items": {"type": "number", "minimum": 0},
                               "maxItems": 24, "description": "Exact moments in seconds"},
                "width": {"type": "integer", "minimum": 160, "maximum": 1280,
                          "description": "Frame width in pixels (default 640)"},
            },
            "required": ["source"],
        },
        "annotations": {"readOnlyHint": True},
    },
]


class ToolError(Exception):
    """Ошибка, которую агент должен увидеть как результат инструмента (isError), а не как сбой протокола."""


class Server:
    def __init__(self, write: Callable[[dict], None]):
        self._write = write
        self._settings = None
        self.cancel_event = threading.Event()
        self.current_id: Any = None

    @property
    def settings(self):
        if self._settings is None:
            from src.config import SettingsManager
            from src.utils.logger import register_secret
            self._settings = SettingsManager()
            for kind in ("photos", "music", "music_android"):
                register_secret(self._settings.get_vk_token(kind))
        return self._settings

    # ── протокол ──────────────────────────────────────────────

    def handle(self, message: dict) -> dict | None:
        """Обрабатывает одно сообщение; возвращает ответ или None для уведомлений."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if msg_id is None:
            return None  # уведомления (initialized, cancelled) ответа не требуют
        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params, msg_id)
            elif method in ("resources/list", "prompts/list"):
                result = {method.split("/")[0]: []}
            else:
                return _error(msg_id, -32601, f"Method not found: {method}")
        except _ProtocolError as e:
            return _error(msg_id, e.code, str(e))
        except Exception as e:
            log.error("mcp: сбой %s", method, exc_info=True)
            return _error(msg_id, -32603, f"Internal error: {e}")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        client = (params.get("clientInfo") or {}).get("name", "?")
        log.info("mcp: клиент %s, протокол %s", client, version)
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mediaharvester", "title": "MediaHarvester", "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _call_tool(self, params: dict, msg_id: Any) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = {"download": self.tool_download, "media_info": self.tool_media_info,
                   "get_transcript": self.tool_transcript, "get_frames": self.tool_frames}.get(name)
        if handler is None:
            raise _ProtocolError(-32602, f"Unknown tool: {name}")
        token = (params.get("_meta") or {}).get("progressToken")
        self.cancel_event.clear()
        self.current_id = msg_id
        started = time.time()
        log.info("mcp: %s %s", name, json.dumps(args, ensure_ascii=False)[:300])
        try:
            content = handler(args, self._progress(token))
            return {"content": content, "isError": False}
        except ToolError as e:
            return {"content": [_text(str(e))], "isError": True}
        except Exception as e:
            from src.core.headless import explain
            from src.utils.helpers import DownloadCancelledError
            if isinstance(e, DownloadCancelledError):
                return {"content": [_text("Cancelled")], "isError": True}
            message, hint = explain(e)
            log.error("mcp: %s: %s", name, message, exc_info=True)
            return {"content": [_text(message + (f" ({hint})" if hint else ""))], "isError": True}
        finally:
            self.current_id = None
            log.info("mcp: %s за %.1f с", name, time.time() - started)

    def _progress(self, token: Any):
        """Ход загрузки уведомлениями notifications/progress, если клиент передал progressToken."""
        state = {"n": 0, "last": 0.0}

        def report(text: str, _state: str = "working", fraction=None, _percent: str = "") -> None:
            now = time.time()
            if token is None or not text or now - state["last"] < 0.5:
                return
            state["n"] += 1
            state["last"] = now
            self._write({"jsonrpc": "2.0", "method": "notifications/progress",
                         "params": {"progressToken": token, "progress": state["n"], "message": text}})
        return report

    # ── инструменты ───────────────────────────────────────────

    def tool_download(self, args: dict, progress) -> list[dict]:
        from src.core.headless import download_url, options_from_settings, quality_choice

        urls = [u for u in args.get("urls") or [] if isinstance(u, str) and u.strip()]
        if not urls:
            raise ToolError("urls is empty")
        opts = options_from_settings(self.settings, _expand(args.get("output_dir") or ""))
        opts.quality = str(args.get("quality") or "best")
        try:
            quality_choice(opts.quality)
        except ValueError as e:
            raise ToolError(str(e)) from e
        opts.audio_format = args.get("audio_format") or "mp3"
        if "playlist" in args:
            opts.playlist = bool(args["playlist"])
        opts.playlist_limit = max(0, int(args.get("playlist_limit") or 0))
        opts.subtitles = [str(s) for s in args.get("subtitles") or []]

        results = []
        for url in urls:
            results.append(download_url(url.strip(), opts, self.settings, progress, self.cancel_event))
            if results[-1].cancelled:
                break
        data = {"output_dir": os.path.abspath(opts.output_dir), "results": [r.as_dict() for r in results]}
        if not any(r.ok for r in results):
            raise ToolError(json.dumps(data, ensure_ascii=False, indent=2))
        return [_text(json.dumps(data, ensure_ascii=False, indent=2))]

    def tool_media_info(self, args: dict, _progress) -> list[dict]:
        from src.cli import media_info
        url = str(args.get("url") or "").strip()
        if not url:
            raise ToolError("url is required")
        s = self.settings
        data = media_info(url, s.cookies_path, s.get("cookies_browser", "") or "")
        return [_text(json.dumps(data, ensure_ascii=False, indent=2))]

    def tool_transcript(self, args: dict, _progress) -> list[dict]:
        from src.core.media_tools import fetch_transcript
        source = _expand(str(args.get("source") or "").strip())
        if not source:
            raise ToolError("source is required")
        s = self.settings
        data = fetch_transcript(source, [str(x) for x in args.get("languages") or []],
                                s.cookies_path, s.get("cookies_browser", "") or "")
        head = {k: v for k, v in data.items() if k != "text"}
        return [_text(json.dumps(head, ensure_ascii=False) + "\n\n" + data["text"])]

    def tool_frames(self, args: dict, progress) -> list[dict]:
        from src.core.headless import local_media
        from src.core.media_tools import extract_frames, format_time
        source = _expand(str(args.get("source") or "").strip())
        if not source:
            raise ToolError("source is required")
        path = local_media(source, self.settings, progress, self.cancel_event)
        count = min(max(int(args.get("count") or 6), 1), 24)
        timestamps = [float(t) for t in args.get("timestamps") or []][:24] or None
        width = min(max(int(args.get("width") or 640), 160), 1280)
        data = extract_frames(path, count, timestamps, width)

        duration = f", duration {format_time(data['duration'])}" if data["duration"] else ""
        content = [_text(f"{os.path.basename(data['file'])}{duration}. File: {data['file']}")]
        for frame in data["frames"]:
            with open(frame["path"], "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            content.append(_text(f"Frame at {frame['label']} ({frame['time']} s): {frame['path']}"))
            content.append({"type": "image", "data": encoded, "mimeType": "image/jpeg"})
        return content


class _ProtocolError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path)) if path else path


def serve(stdin=None, stdout_fd: int | None = None) -> int:
    """
    Читает запросы из stdin и отвечает в stdout. Всё остальное, что могло бы попасть в stdout
    (print в библиотеках, вывод ffmpeg), перенаправляется в stderr, чтобы не ломать протокол.
    """
    if stdout_fd is None:
        sys.stdout.flush()
        stdout_fd = os.dup(1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
    out = os.fdopen(stdout_fd, "wb", buffering=0)
    stdin = stdin or sys.stdin.buffer
    write_lock = threading.Lock()

    def write(message: dict) -> None:
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with write_lock:
            out.write(data)

    server = Server(write)
    inbox: "queue.Queue[dict | None]" = queue.Queue()

    def reader() -> None:
        # Отдельный поток, чтобы уведомление об отмене дошло, пока идёт долгая загрузка
        for raw in stdin:
            line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                write(_error(None, -32700, "Parse error"))
                continue
            if not isinstance(message, dict):
                write(_error(None, -32600, "Invalid Request"))
                continue
            if message.get("method") == "notifications/cancelled":
                request_id = (message.get("params") or {}).get("requestId")
                if request_id is not None and request_id == server.current_id:
                    server.cancel_event.set()
                continue
            inbox.put(message)
        inbox.put(None)

    log.info("mcp: сервер запущен (MediaHarvester %s)", __version__)
    threading.Thread(target=reader, name="mcp-reader", daemon=True).start()
    while True:
        message = inbox.get()
        if message is None:
            break
        if "method" not in message:
            continue  # ответы клиента на наши запросы (их мы не шлём)
        response = server.handle(message)
        if response is not None:
            write(response)
    log.info("mcp: клиент закрыл соединение")
    return 0
