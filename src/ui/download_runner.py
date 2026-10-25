"""Запуск, ход и отмена скачивания; выбор движка для ссылки."""
import threading
from src.config import (
    ACCENT_BLUE,
    ACCENT_BLUE_HOVER,
    STATUS_RED,
    VK_ANDROID_USER_AGENT,
    VK_MUSIC_USER_AGENT,
)
from src.core.download_queue import (
    DONE,
    ERROR,
    QueueItem,
    RUNNABLE,
    run_queue,
)
from src.core.router import detect_url_type, gallery_platform_name
from src.core.gallery_engine import download_gallery
from src.core.insta_engine import download_instagram
from src.core.track_search import download_track_list, parse_track_list
from src.core.ytdlp_engine import download_video
from src.core.vk_engine import download_vk_music, download_vk_photos


class DownloadRunnerMixin:
    # ──────────────────────────────────────────────────────
    # УПРАВЛЕНИЕ ЗАНЯТОСТЬЮ UI
    # ──────────────────────────────────────────────────────
    def _set_ui_busy_main(self, busy: bool):
        self.is_downloading = busy
        state = "disabled" if busy else "normal"

        if busy:
            self.btn_download.configure(
                state="normal",
                text="Остановить скачивание",
                fg_color=STATUS_RED,
                hover_color="#A83232"
            )
        else:
            self.btn_download.configure(
                state="normal",
                text="Начать скачивание",
                fg_color=ACCENT_BLUE,
                hover_color=ACCENT_BLUE_HOVER
            )

        self.combo_mode.configure(state=state)
        if hasattr(self, "combo_quality"):
            self.combo_quality.configure(state=state)
        if hasattr(self, "btn_probe_quality"):
            self.btn_probe_quality.configure(state=state)
        if hasattr(self, "chk_playlist"):
            self.chk_playlist.configure(state=state)

        if busy:
            self._hide_folder_button()
            self._hide_details_button()
        self._refresh_queue_view()

    def _set_busy(self, busy: bool):
        self.after(0, self._set_ui_busy_main, busy)

    # ──────────────────────────────────────────────────────
    # ЗАПУСК И ОТМЕНА СКАЧИВАНИЯ
    # ──────────────────────────────────────────────────────
    def start_download_thread(self):
        # Если загрузка уже идёт — кнопка работает как "Остановить скачивание"
        if self.is_downloading:
            self.cancel_event.set()
            self.btn_download.configure(text="Отмена...", state="disabled")
            self.update_status("Остановка скачивания...", state="warning")
            return

        if self._tracklist_mode:
            tracklist_text = self.txt_tracks.get("1.0", "end")
            count = len(parse_track_list(tracklist_text))
            if not count:
                self.update_status("Ошибка: вставьте список треков (по одному в строке)", state="error")
                return
            item = QueueItem(url=f"Список треков: {count}", label="Поиск на YouTube → MP3")
            self._launch_download([item], False, tracklist_text)
            return

        entry_text = self.entry_url.get().strip()
        runnable_in_queue = [it for it in self.queue if it.status in RUNNABLE]

        if runnable_in_queue:
            # Ссылка из поля ввода тоже уходит в очередь
            if entry_text:
                self._enqueue_text(entry_text)
                self._clear_url()
            items = [it for it in self.queue if it.status in RUNNABLE]
            use_queue = True
        elif entry_text:
            # Одиночная загрузка без очереди (как раньше)
            items = [QueueItem(url=entry_text, label=detect_url_type(entry_text)["label"])]
            use_queue = False
        else:
            self.update_status("Ошибка: вставьте ссылку на источник", state="error")
            return

        self._launch_download(items, use_queue)

    def _launch_download(self, items: list[QueueItem], use_queue: bool, tracklist: str = ""):
        # Снимок настроек из интерфейса (рабочий поток не трогает виджеты)
        opts = {
            "mode": self.combo_mode.get(),
            "tokens": {kind: self.settings.get_vk_token(kind) for kind in ("photos", "music", "music_android")},
            "music_client": self.settings.get("music_client", "kate"),
            "cookies_path": self.settings.cookies_path,
            "quality": self.combo_quality.get(),
            "allow_playlist": bool(self.chk_playlist.get()),
            "download_path": self.download_path,
            "tracklist": tracklist,
        }

        self.cancel_event.clear()
        self._set_ui_busy_main(True)
        threading.Thread(
            target=self._download_process, args=(items, opts, use_queue), daemon=True
        ).start()

    def _download_process(self, items: list[QueueItem], opts: dict, use_queue: bool):
        def on_change():
            if use_queue:
                self.after(0, self._refresh_queue_view)

        def run_one(item: QueueItem, number: int, total: int) -> str:
            prefix = f"[{number}/{total}] " if total > 1 else ""

            def cb(text, state="idle", progress=None, percent_str=""):
                # Промежуточный успех элемента не должен выглядеть как конец всей очереди
                if prefix and state == "success":
                    state = "working"
                self.update_status(prefix + text, state, progress, percent_str)

            self.update_status(prefix + "Определение источника...", state="working",
                               progress=0, percent_str="0%")
            return self._download_one(item.url, opts, cb)

        try:
            summary = run_queue(items, run_one, self.cancel_event, on_change)
        finally:
            self._set_busy(False)

        done, failed, total = summary["done"], summary["failed"], summary["total"]
        saved = [it.folder for it in items if it.status == DONE and it.folder]
        if saved:
            self.last_saved_folder = saved[-1]
            self.after(0, self._show_folder_button)

        self.last_errors = [it for it in items if it.status == ERROR]
        if self.last_errors:
            self.after(0, self._show_details_button)

        if summary["cancelled"] or self.cancel_event.is_set():
            self.update_status(
                "Загрузка отменена пользователем" if total == 1
                else f"Очередь остановлена: готово {done} из {total}",
                state="warning")
        elif total == 1:
            if failed:
                self.update_status(items[0].message[:90], state="error")
            # при успехе движок уже показал «Готово…»
        elif failed:
            self.update_status(
                f"Очередь завершена: готово {done} из {total}, ошибок {failed}",
                state="warning", progress=1.0, percent_str="100%")
        else:
            self.update_status(
                f"Очередь завершена: готово {done} из {total}",
                state="success", progress=1.0, percent_str="100%")

    def _download_one(self, target_url: str, opts: dict, cb) -> str:
        """Скачивает одну ссылку нужным движком. Возвращает путь к папке; ошибки — исключением."""
        mode = opts["mode"]
        detected = detect_url_type(target_url)
        if "Автоопределение" in mode:
            engine = detected["engine"]
        elif "Видео" in mode:
            engine = "ytdlp"
        elif "Instagram" in mode:
            engine = "insta"
        elif "Галереи" in mode:
            engine = "gallery"
        elif "Фотографии" in mode:
            engine = "vk_photos"
        elif "по списку" in mode:
            engine = "tracklist"
        elif "Музыка" in mode:
            engine = "vk_music"
        else:
            engine = "ytdlp"

        download_path = opts["download_path"]

        if engine == "tracklist":
            return download_track_list(
                text=opts["tracklist"],
                download_path=download_path,
                progress_callback=cb,
                cookies_path=opts["cookies_path"],
                cancel_event=self.cancel_event
            )

        if engine == "insta":
            return download_instagram(
                url=target_url,
                download_path=download_path,
                cookies_path=opts["cookies_path"],
                status_callback=cb,
                cancel_event=self.cancel_event
            )
        if engine == "gallery":
            return download_gallery(
                url=target_url,
                download_path=download_path,
                platform_name=gallery_platform_name(target_url) or "Gallery",
                cookies_path=opts["cookies_path"],
                status_callback=cb,
                cancel_event=self.cancel_event,
                listing=bool(detected.get("listing")),
            )
        if engine == "vk_photos":
            return download_vk_photos(
                token_raw=opts["tokens"]["photos"],
                url=target_url,
                download_path=download_path,
                progress_callback=cb,
                cancel_event=self.cancel_event
            )
        if engine == "vk_music":
            android = opts["music_client"] == "android"
            return download_vk_music(
                token_raw=opts["tokens"]["music_android" if android else "music"],
                url=target_url,
                download_path=download_path,
                progress_callback=cb,
                cancel_event=self.cancel_event,
                user_agent=VK_ANDROID_USER_AGENT if android else VK_MUSIC_USER_AGENT
            )

        title = download_video(
            url=target_url,
            download_path=download_path,
            quality_choice=opts["quality"],
            progress_callback=cb,
            cookies_path=opts["cookies_path"],
            cancel_event=self.cancel_event,
            # Плейлист включается и сам, если ссылка ведёт на список (SoundCloud set, профиль TikTok)
            allow_playlist=opts["allow_playlist"] or bool(detected.get("playlist"))
        )
        cb(f"Готово: {title[:40]}", "success", 1.0, "100%")
        return download_path
