"""Токен VK: карточка, вход (браузер/окно), экспериментальный клиент, диагностика токена."""
import os
import threading
import time
import webbrowser
import customtkinter as ctk
from src.config import (
    ACCENT_BLUE,
    ACCENT_BLUE_HOVER,
    AUTH_URL_MUSIC,
    AUTH_URL_MUSIC_ANDROID,
    AUTH_URL_PHOTOS,
    BG_MAIN,
    STATUS_AMBER,
    STATUS_GREEN,
    STATUS_RED,
    SURFACE_CARD_BORDER,
    SURFACE_INNER,
    SURFACE_INNER_BORDER,
    TEXT_MAIN,
    TEXT_MUTED,
    TEXT_SECONDARY,
    VK_ANDROID_USER_AGENT,
    VK_MUSIC_USER_AGENT,
)
from src.core.vk_engine import VKPYMUSIC_AVAILABLE, extract_token
from src.core.vk_auth import fetch_user_name, find_auth_result, login_in_window
from src.utils.logger import register_secret, get_logger
from src.utils import clipboard as sysclip

log = get_logger("app")


class VkTokenPanelMixin:
    def _build_token_card(self):
        self.card_token = self._card(self.main_scroll)

        hrow = ctk.CTkFrame(self.card_token, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(hrow, text="Токен доступа ВКонтакте",
                     font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(side="left")
        self.badge_token_status = ctk.CTkLabel(
            hrow, text="Требуется",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color=SURFACE_INNER, text_color=TEXT_MUTED,
            corner_radius=4, padx=6, pady=2)
        self.badge_token_status.pack(side="right")

        self.btn_auth = ctk.CTkButton(
            self.card_token, text="Войти через ВКонтакте",
            height=34, corner_radius=6, font=self.font_main,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
            text_color=TEXT_MAIN, command=self.start_browser_login)
        self.btn_auth.pack(fill="x", padx=14, pady=(0, 4))

        self.btn_auth_window = ctk.CTkButton(
            self.card_token, text="Войти во встроенном окне (может не сработать)",
            height=24, corner_radius=4, font=self.font_small,
            fg_color="transparent", hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_MUTED, command=self.start_vk_login)
        self.btn_auth_window.pack(fill="x", padx=14, pady=(0, 4))

        self.btn_token_check = ctk.CTkButton(
            self.card_token, text="Проверить токен",
            height=24, corner_radius=4, font=self.font_small,
            fg_color="transparent", hover_color=SURFACE_CARD_BORDER,
            text_color=TEXT_MUTED, command=self.check_vk_token)
        self.btn_token_check.pack(fill="x", padx=14, pady=(0, 8))

        self.btn_experiment = ctk.CTkButton(
            self.card_token, text="⚠ Эксперимент: войти как официальное приложение VK…",
            height=24, corner_radius=4, font=self.font_small,
            fg_color="transparent", hover_color=SURFACE_CARD_BORDER,
            text_color=STATUS_AMBER, command=self.toggle_experimental_client)
        self.lbl_experiment_warning = ctk.CTkLabel(
            self.card_token, text="", font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=STATUS_AMBER, justify="left", wraplength=420)

        erow = ctk.CTkFrame(self.card_token, fg_color="transparent")
        erow.pack(fill="x", padx=14, pady=(0, 6))
        self.entry_token = ctk.CTkEntry(
            erow,
            placeholder_text="...или вставьте ссылку/токен вручную",
            font=self.font_main, height=34, corner_radius=6,
            fg_color=SURFACE_INNER, border_width=1,
            border_color=SURFACE_INNER_BORDER,
            text_color=TEXT_MAIN, placeholder_text_color=TEXT_MUTED)
        self.entry_token.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry_token.bind("<KeyRelease>", self._on_token_changed)

        ctk.CTkButton(
            erow, text="Вставить", width=74, height=34, corner_radius=6,
            font=self.font_small,
            fg_color=SURFACE_CARD_BORDER,
            hover_color=SURFACE_INNER_BORDER,
            text_color=TEXT_SECONDARY,
            command=lambda: self.paste_clipboard(self.entry_token)
        ).pack(side="right")

        self.lbl_token_hint = ctk.CTkLabel(
            self.card_token,
            text=self._TOKEN_HINT,
            font=self.font_subtitle, text_color=TEXT_MUTED, justify="left")
        self.lbl_token_hint.pack(anchor="w", padx=14, pady=(0, 10))

    def _set_token_kind(self, kind: str):
        """Переключает поле токена на токен для фото или для музыки (их выдают разные приложения VK)."""
        self._auth_url = {"music": AUTH_URL_MUSIC, "music_android": AUTH_URL_MUSIC_ANDROID}.get(kind, AUTH_URL_PHOTOS)
        if kind == self._token_kind:
            self._update_experiment_ui()
            return
        self._token_kind = kind
        self.entry_token.delete(0, "end")
        token = self.settings.get_vk_token(kind)
        if token:
            self.entry_token.insert(0, token)
        self._update_token_badge()
        self._update_experiment_ui()

    def _music_kind(self) -> str:
        """Какой токен нужен для музыки: обычный (Kate Mobile) или экспериментальный (VK для Android)."""
        return "music_android" if self.settings.get("music_client", "kate") == "android" else "music"

    def _music_hint(self) -> str:
        if self._music_kind() == "music_android":
            return ("ЭКСПЕРИМЕНТ: вход от имени приложения VK для Android. Подтвердите доступ в браузере "
                    "и скопируйте адрес страницы. Возможны ограничения аккаунта VK")
        return ("VK сейчас может не отдавать музыку по этому токену — тогда используйте режим «Треки по списку». "
                "Вход: подтвердите доступ в браузере и скопируйте адрес страницы")

    def _update_experiment_ui(self):
        """Кнопка эксперимента и предупреждение видны только для музыки VK."""
        is_music = self._token_kind in ("music", "music_android")
        if not is_music:
            self.btn_experiment.pack_forget()
            self.lbl_experiment_warning.pack_forget()
            return
        android = self._token_kind == "music_android"
        self.btn_experiment.configure(
            text="Вернуться к обычному входу (Kate Mobile)" if android
            else "⚠ Эксперимент: войти как официальное приложение VK…")
        self.lbl_experiment_warning.configure(
            text=("Включён экспериментальный вход. Он нарушает правила VK: возможны запрос подтверждений, "
                  "ограничения и блокировка аккаунта." if android else
                  "Эксперимент нарушает правила VK и может привести к ограничениям аккаунта (подробности — по кнопке)."))
        if not self.btn_experiment.winfo_ismapped():
            self.btn_experiment.pack(fill="x", padx=14, pady=(0, 2), after=self.btn_token_check)
        if not self.lbl_experiment_warning.winfo_ismapped():
            self.lbl_experiment_warning.pack(anchor="w", padx=14, pady=(0, 8), after=self.btn_experiment)
        self.lbl_token_hint.configure(text=self._music_hint())

    def toggle_experimental_client(self):
        """Включает/выключает экспериментальный вход музыки через приложение VK для Android."""
        if self._login_busy:
            return
        if self._token_kind == "music_android":
            self.settings.set("music_client", "kate")
            self._set_token_kind("music")
            self.update_status("Вернулся обычный вход для музыки (Kate Mobile)", state="idle")
            return
        if not self._confirm_experiment():
            return
        self.settings.set("music_client", "android")
        self._set_token_kind("music_android")
        log.warning("Включён экспериментальный вход музыки через VK для Android")
        self.start_browser_login()

    def _confirm_experiment(self) -> bool:
        """Окно с предупреждением о рисках; продолжить можно только после явного согласия."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Эксперимент: риск для аккаунта")
        dialog.geometry("520x400")
        dialog.configure(fg_color=BG_MAIN)
        dialog.transient(self)
        result = {"ok": False}
        try:
            if os.path.exists(self.icon_path):
                dialog.after(250, lambda: dialog.iconbitmap(self.icon_path))
        except Exception:
            pass

        ctk.CTkLabel(dialog, text="⚠ Вход как официальное приложение VK", font=self.font_title,
                     text_color=STATUS_AMBER).pack(anchor="w", padx=18, pady=(16, 8))
        ctk.CTkLabel(
            dialog, justify="left", anchor="w", font=self.font_main, text_color=TEXT_SECONDARY, wraplength=480,
            text=("VK не отдаёт музыку сторонним программам. Этот вариант пробует войти от имени официального "
                  "приложения VK для Android, чтобы получить доступ к аудио.\n\n"
                  "Что может случиться:\n"
                  "•  VK сочтёт вход подозрительным: запросит подтверждение, разлогинит устройства;\n"
                  "•  временные ограничения аккаунта;\n"
                  "•  в худшем случае — блокировка аккаунта.\n\n"
                  "Это нарушает правила VK. Используйте запасной аккаунт, а не основной. "
                  "Безопасная альтернатива без обращения к VK — режим «Треки по списку».\n\n"
                  "Авторы программы не отвечают за последствия для аккаунта.")
        ).pack(anchor="w", padx=18)

        agree = ctk.CTkCheckBox(dialog, text="Я понимаю риск и действую на свой страх", font=self.font_main,
                                text_color=TEXT_MAIN, fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER)
        agree.pack(anchor="w", padx=18, pady=(12, 8))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=18, pady=(0, 14))
        btn_go = ctk.CTkButton(buttons, text="Продолжить", height=34, corner_radius=6, font=self.font_main,
                               fg_color=STATUS_RED, hover_color="#A83232", text_color=TEXT_MAIN, state="disabled",
                               command=lambda: (result.update(ok=True), dialog.destroy()))
        btn_go.pack(side="right")
        ctk.CTkButton(buttons, text="Отмена", height=34, corner_radius=6, font=self.font_main,
                      fg_color=SURFACE_CARD_BORDER, hover_color=SURFACE_INNER_BORDER, text_color=TEXT_SECONDARY,
                      command=dialog.destroy).pack(side="right", padx=(0, 8))
        agree.configure(command=lambda: btn_go.configure(state="normal" if agree.get() else "disabled"))

        dialog.after(150, lambda: (dialog.grab_set(), dialog.focus_force()))
        self.wait_window(dialog)
        return result["ok"]

    def _update_token_badge(self):
        token = self.entry_token.get().strip()
        mode = self.combo_mode.get()

        if "Музыка" in mode and not VKPYMUSIC_AVAILABLE:
            self.badge_token_status.configure(
                text="Недоступно", text_color=STATUS_RED, fg_color=SURFACE_INNER)
        elif token:
            self.badge_token_status.configure(
                text="Сохранён", text_color=STATUS_GREEN, fg_color=SURFACE_INNER)
        else:
            self.badge_token_status.configure(
                text="Требуется", text_color=STATUS_AMBER, fg_color=SURFACE_INNER)

    def _on_token_changed(self, event=None):
        raw = self.entry_token.get().strip()
        extracted = extract_token(raw)
        if extracted != self.settings.get_vk_token(self._token_kind):
            self.settings.set_vk_token(self._token_kind, extracted)
            register_secret(extracted)
        self._update_token_badge()

    # ──────────────────────────────────────────────────────
    # АВТОРИЗАЦИЯ И ВЫБОР ПАПКИ
    # ──────────────────────────────────────────────────────
    _TOKEN_HINT = ("Нажмите «Войти»: в браузере подтвердите доступ и скопируйте адрес страницы "
                   "(Ctrl+L, Ctrl+C) — токен подхватится сам. Пароль программе не передаётся")

    def check_vk_token(self):
        """Проверяет текущий токен: какие методы VK отвечают (подробности — в логе, без самого токена)."""
        token = self.settings.get_vk_token(self._token_kind)
        if not token:
            self.update_status("Сначала войдите через ВКонтакте", state="warning")
            return
        kind = self._token_kind
        self.btn_token_check.configure(state="disabled", text="Проверяю...")
        self.update_status("Проверяю токен: перебираю параметры запроса (около 20 секунд)...", state="working")

        def _worker():
            try:
                from src.core.vk_diag import run_diagnostics
                agents = {"kate": VK_MUSIC_USER_AGENT, "android_official": VK_ANDROID_USER_AGENT,
                          "android": "VKAndroidApp/8.52-17600 (Android 14; SDK 34; arm64-v8a; Samsung Galaxy S24; ru; 2960x1440)",
                          "none": ""}
                summary, _ = run_diagnostics(token, kind, agents)
                state = "success" if summary.startswith("Токен рабочий") else "warning"
            except Exception as e:
                log.exception("Диагностика токена")
                summary, state = f"Не удалось проверить токен: {e}"[:90], "error"

            def _done():
                self.btn_token_check.configure(state="normal", text="Проверить токен")
                self.update_status(summary[:140], state=state)
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _set_login_busy(self, busy: bool):
        self._login_busy = busy
        self.btn_auth.configure(text="Отменить вход" if busy else "Войти через ВКонтакте")
        self.btn_auth_window.configure(state="disabled" if busy else "normal")

    def start_vk_login(self):
        """Встроенное окно входа VK (запасной способ: VK ID не всегда отдаёт токен во встроенном окне)."""
        if self._login_busy:
            self._login_cancel.set()
            self._clipboard_watch_until = 0.0
            return
        self._login_cancel.clear()
        self._login_kind = self._token_kind
        self._set_login_busy(True)
        self.update_status("Открыто окно входа ВКонтакте. Подтвердите доступ...", state="working")
        url = self._auth_url

        def _worker():
            outcome = login_in_window(url, self._login_cancel)
            self.after(0, lambda: self._finish_vk_login(outcome))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_vk_login(self, outcome):
        log.info("Вход VK (окно): %s %s", outcome.status, outcome.detail)
        self._set_login_busy(False)
        if outcome.status == "ok":
            self._accept_vk_token(outcome.result.token)
        elif outcome.status == "unavailable":
            # Окно WebView2 недоступно — запасной путь через обычный браузер
            self.update_status("Окно входа недоступно, открываю обычный браузер...", state="warning")
            self.start_browser_login()
        elif outcome.status == "denied":
            self.update_status("ВКонтакте отклонил вход: " + (outcome.detail or "доступ не выдан")[:50],
                               state="error")
        elif outcome.status == "timeout":
            self.update_status("Время на вход истекло. Нажмите «Войти» ещё раз", state="warning")
        else:  # closed / cancelled
            self.update_status("Вход отменён", state="idle")

    def start_browser_login(self):
        """Основной вход: обычный браузер + автоматический захват адреса из буфера обмена."""
        if self._login_busy:
            # повторное нажатие на «Отменить вход»
            self._login_cancel.set()
            self._clipboard_watch_until = 0.0
            return
        self._login_cancel.clear()
        self._login_kind = self._token_kind
        self._set_login_busy(True)
        webbrowser.open(self._auth_url)
        self._clipboard_watch_until = time.monotonic() + 600
        self.update_status(
            "В браузере нажмите «Продолжить», затем скопируйте адрес страницы: Ctrl+L, Ctrl+C. Токен подхватится сам",
            state="warning")
        self.after(700, self._watch_clipboard)

    def _watch_clipboard(self):
        if not self._login_busy:
            return
        if self._login_cancel.is_set() or time.monotonic() > self._clipboard_watch_until:
            timed_out = not self._login_cancel.is_set()
            self._set_login_busy(False)
            self.update_status(
                "Время на вход истекло" if timed_out else "Вход отменён",
                state="warning" if timed_out else "idle")
            return
        text = self._read_clipboard() or ""
        result = find_auth_result(text)
        if result:
            self._set_login_busy(False)
            sysclip.clear()  # токен не должен оставаться в буфере обмена (Tk-буфер не трогаем: он залипает)
            self._accept_vk_token(result.token)
            return
        self.after(700, self._watch_clipboard)

    def _accept_vk_token(self, token: str):
        """Сохраняет токен, показывает его в поле и проверяет владельца в фоне."""
        register_secret(token)
        self.settings.set_vk_token(self._login_kind, token)
        if self._login_kind == self._token_kind:
            self.entry_token.delete(0, "end")
            self.entry_token.insert(0, token)
        self._update_token_badge()
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.update_status("Токен сохранён. Проверяю вход...", state="working")

        def _verify():
            try:
                name = fetch_user_name(token)
            except Exception:
                self.after(0, lambda: self.update_status(
                    "ВКонтакте не принял токен. Войдите заново", state="error"))
                return
            text = (f"Вход выполнен: {name}" if name else "Токен сохранён") + ". Вкладку VK можно закрыть"
            self.after(0, lambda: self.update_status(text, state="success"))

        threading.Thread(target=_verify, daemon=True).start()
