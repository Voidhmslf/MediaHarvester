"""Проверки при старте (ffmpeg, обновление yt-dlp) и строка версий в шапке."""
from src.ui.theme import (
    STATUS_AMBER,
    STATUS_RED,
    TEXT_MUTED,
)
from src.utils.helpers import check_ffmpeg, self_update_disabled
from src.utils.ytdlp_updater import check_for_update, current_version as ytdlp_version

from src.utils.logger import get_logger

log = get_logger("app")


class EngineStatusMixin:
    # ──────────────────────────────────────────────────────
    # ПРОВЕРКИ ПРИ СТАРТЕ: FFMPEG И YT-DLP
    # ──────────────────────────────────────────────────────
    def _background_checks(self):
        ok, info = check_ffmpeg()
        self._engine_state["ffmpeg"] = (ok, info)
        try:
            self._engine_state["ytdlp"] = ytdlp_version()
        except Exception:
            self._engine_state["ytdlp"] = "?"
        log.info("Окружение: yt-dlp %s, ffmpeg %s (%s)", self._engine_state["ytdlp"], ok, info)
        self.after(0, self._render_engine_info)

        if not ok:
            self.update_status(
                "FFmpeg не найден: видео выше 720p и конвертация в MP3 могут не работать",
                state="warning")

        if self_update_disabled() or not self.settings.get("auto_update_ytdlp", True):
            return
        self._engine_state["update"] = "checking"
        self.after(0, self._render_engine_info)
        result = check_for_update()
        log.info("Проверка обновления yt-dlp: %s %s %s", result.status, result.latest, result.message)
        if result.status == "updated":
            self._engine_state["update"] = f"updated:{result.latest}"
        else:
            self._engine_state["update"] = ""
        self.after(0, self._render_engine_info)

    def _render_engine_info(self):
        st = self._engine_state
        parts, color = [], TEXT_MUTED
        if st["ytdlp"]:
            parts.append(f"yt-dlp {st['ytdlp']}")
        if st["update"] == "checking":
            parts.append("проверка обновлений...")
        elif st["update"].startswith("updated:"):
            parts.append(f"обновлён до {st['update'].split(':', 1)[1]} — перезапустите программу")
            color = STATUS_AMBER
        if st["ffmpeg"] is not None:
            ok, info = st["ffmpeg"]
            parts.append(f"ffmpeg {info}" if ok else f"ffmpeg: {info}")
            if not ok:
                color = STATUS_RED
        text = " • ".join(parts)
        self.lbl_engine_info.configure(text=text, text_color=color)
        if text:
            self.lbl_engine_info.pack(fill="x")
        else:
            self.lbl_engine_info.pack_forget()  # пустая строка отнимала бы место под подзаголовком

    def _on_auto_update_toggled(self):
        self.settings.set("auto_update_ytdlp", bool(self.chk_auto_update.get()))
