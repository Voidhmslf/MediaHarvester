"""Экран «Справка»."""
from src.version import __version__
import customtkinter as ctk
from src.ui import theme
from src.ui.widgets import ScrollFrame
from src.ui.theme import (
    BTN_SECONDARY,
    BTN_SECONDARY_HOVER,
    PAD,
    R_CARD,
    SURFACE_CARD,
    SURFACE_CARD_BORDER,
    TEXT_MAIN,
    TEXT_SECONDARY,
)



class InfoViewMixin:
    # ──────────────────────────────────────────────────────
    # ЭКРАН 2: СПРАВКА
    # ──────────────────────────────────────────────────────
    def create_info_view(self):
        self.info_scroll = ScrollFrame(
            self.views_container, fg_color="transparent", **theme.scrollbar_style())
        self.info_labels = []

        hcard = self._info_card(pady=(0, theme.CARD_GAP))
        ctk.CTkLabel(hcard, text=f"Руководство MediaHarvester {__version__}", font=self.font_title,
                     text_color=TEXT_MAIN).pack(anchor="w", padx=PAD, pady=(16, 4))
        ctk.CTkLabel(hcard, text="Оформление", font=self.font_section,
                     text_color=TEXT_SECONDARY).pack(anchor="w", padx=PAD, pady=(10, 6))
        self.seg_theme = ctk.CTkSegmentedButton(
            hcard, values=list(theme.THEME_LABELS.values()), font=self.font_medium, height=34,
            command=self._on_theme_segment, corner_radius=theme.R_CTRL,
            fg_color=BTN_SECONDARY, unselected_color=BTN_SECONDARY, unselected_hover_color=BTN_SECONDARY_HOVER,
            selected_color=("#FFFFFF", "#46464D"), selected_hover_color=("#FFFFFF", "#46464D"),
            text_color=TEXT_MAIN, border_width=3)
        self.seg_theme.pack(fill="x", padx=PAD, pady=(0, 16))
        self.seg_theme.set(theme.THEME_LABELS[self.theme_choice])

        self._info_section(
            "1. Умное автоопределение (Smart Mode)",
            "Вставьте любую ссылку на видео, пост или музыку — MediaHarvester "
            "самостоятельно определит платформу (YouTube, TikTok, Instagram, X, Pinterest, Reddit, SoundCloud, VK) "
            "и подберёт оптимальный модуль скачивания без необходимости "
            "вручную переключать режим.")

        self._info_section(
            "Другие платформы: TikTok, X, Pinterest, Reddit, SoundCloud",
            "Просто вставьте ссылку — тип определится сам. Видео берутся через yt-dlp, фото и галереи "
            "через gallery-dl, и программа сама переключается между ними, если пост оказался не тем.\n"
            "Ссылки на списки (плейлист SoundCloud, профиль TikTok) скачиваются целиком. "
            "Страницы-ленты (доска Pinterest, профиль X, сабреддит) ограничены первыми 500 файлами. "
            "Для X и закрытого контента может понадобиться cookies.txt.")

        self._info_section(
            "Если что-то не скачалось",
            "В строке статуса — короткая причина, а кнопка «Подробнее» показывает, что делать, "
            "и техническую причину по каждой ссылке. «Скопировать отчёт» собирает всё для разработчика: "
            "версии, ошибки и последние строки лога (токены и ключи в ссылках скрываются).\n"
            "Лог хранится в %LOCALAPPDATA%\\MediaHarvester\\logs — откройте его кнопкой в окне «Подробнее».")

        self._info_section(
            "Треки по списку (без VK)",
            "Режим «Треки по списку (поиск на YouTube)»: вставьте список строк «Исполнитель — Название» "
            "(например, скопированный из плейлиста VK или из архива данных VK). Приложение найдёт каждый трек "
            "на YouTube, выберет оригинал (канал «Topic», официальное аудио; лайвы, каверы и ремиксы "
            "отсеиваются) и сохранит MP3 с тегами.\n"
            "Уже скачанные треки пропускаются, ненайденные записываются в _not_found.txt. "
            "К VK приложение при этом не обращается и токен не требует.")

        self._info_section(
            "⚠ Музыка VK и экспериментальный вход",
            "VK не отдаёт музыку сторонним программам, поэтому режим «Музыка ВК» может не работать "
            "(ошибки 3, 9, 15). Кнопка «Эксперимент: войти как официальное приложение VK» пробует войти "
            "от имени приложения VK для Android. Это нарушает правила VK: возможны запросы подтверждения, "
            "ограничения и блокировка аккаунта. Пользуйтесь ей только на свой риск и лучше с запасным аккаунтом. "
            "Безопасная альтернатива — «Треки по списку».")

        self._info_section(
            "Очередь ссылок",
            "Вставьте сразу несколько ссылок (по одной в строке) или нажимайте Enter / "
            "«Добавить в очередь» после каждой. «Начать скачивание» скачает всё по порядку; "
            "ошибка на одной ссылке не останавливает остальные. Неудавшиеся ссылки остаются "
            "в списке — повторный запуск скачает только их. «Остановить» прерывает всю очередь.")

        self._info_section(
            "2. Безопасная отмена загрузки",
            "Во время любого скачивания кнопка меняется на «Остановить скачивание». "
            "При нажатии процесс завершается корректно и безопасно, сохраняя уже загруженные файлы "
            "и не подвешивая графический интерфейс.")

        self._info_section(
            "3. Instagram (Фото, Карусели, Reels, Stories)",
            "Поддерживается скачивание одиночных фотопостов, каруселей "
            "(содержащих фото и видео вместе), Stories и Reels в максимальном качестве.\n"
            "Публичные посты и карусели скачиваются без входа: приложение запрашивает их у Instagram анонимно, "
            "как сайты-загрузчики. Если Instagram отказал (закрытый аккаунт, истории, лимит анонимных запросов), "
            "выберите в блоке Cookies браузер, где вы вошли в Instagram, лучше всего Firefox: для Chrome, Edge и Opera "
            "браузер нужно закрыть на время скачивания. Либо укажите файл cookies.txt: он главнее браузера.")

        self._info_section(
            "4. Экспорт cookies.txt для Instagram и YouTube 18+",
            "Для скачивания контента, требующего авторизации:\n"
            "  1. Установите расширение для браузера (например, «Get cookies.txt LOCALLY» в Chrome/Firefox).\n"
            "  2. Авторизуйтесь на сайте Instagram или YouTube.\n"
            "  3. Нажмите на иконку расширения и сохраните файл cookies.txt.\n"
            "  4. В MediaHarvester нажмите «Обзор» в блоке Cookies и выберите этот файл.")

        self._info_section(
            "5. Скачивание видео и аудио (YouTube • VK • IG Reels)",
            "Выберите желаемое качество: от 360p до 4K, либо «Только аудио (MP3)» в битрейте 320 kbps.\n"
            "При скачивании в MP3 в файл автоматически встраиваются ID3-теги исполнителя и трека.\n"
            "Включите чекбокс «Скачивать весь плейлист», чтобы сохранить все ролики подборки в отдельную папку.")

        self._info_section(
            "6. Скачивание музыки и фотоальбомов ВКонтакте",
            "Для доступа к фотоальбомам и музыке VK нажмите «Войти через ВКонтакте»: откроется ваш браузер "
            "со страницей VK. Нажмите «Продолжить», затем скопируйте адрес страницы (Ctrl+L, Ctrl+C) — "
            "программа сама заберёт токен из буфера обмена и очистит его. "
            "Логин и пароль программа не видит и не хранит.\n"
            "Кнопка «Войти во встроенном окне» — запасной способ: VK ID не всегда отдаёт токен во встроенном окне.\n"
            "Для музыки нужен отдельный вход в режиме «Музыка»: VK отдаёт аудио только токену приложения Kate Mobile, "
            "поэтому токены для фото и музыки хранятся раздельно и подставляются сами при смене режима.\n"
            "Поддерживаются ссылки на плейлист, одну песню (vk.com/audio…) и профиль (до 1000 треков). "
            "В полях ввода работают Ctrl+C, Ctrl+V, Ctrl+X, Ctrl+A в любой раскладке и меню по правой кнопке.")

        ctk.CTkButton(
            self.info_scroll, text="Вернуться к скачиванию", height=50, font=self.font_bold,
            command=self.show_downloader_view,
            **dict(theme.primary_button(), corner_radius=12)
        ).pack(fill="x", padx=2, pady=(2, 14))

    def _on_theme_segment(self, label: str):
        choice = next((key for key, text in theme.THEME_LABELS.items() if text == label), "system")
        self.set_theme(choice)

    def _info_card(self, pady=(0, theme.CARD_GAP)):
        f = ctk.CTkFrame(self.info_scroll, fg_color=SURFACE_CARD,
                         corner_radius=R_CARD, border_width=1,
                         border_color=SURFACE_CARD_BORDER)
        f.pack(fill="x", padx=2, pady=pady)
        return f

    def _info_section(self, title: str, body: str):
        card = self._info_card()
        ctk.CTkLabel(card, text=title, font=self.font_section,
                     text_color=TEXT_MAIN).pack(anchor="w", padx=PAD, pady=(14, 6))
        lbl = ctk.CTkLabel(card, text=body, font=self.font_main,
                           text_color=TEXT_SECONDARY, justify="left")
        lbl.pack(anchor="w", padx=PAD, pady=(0, 14))
        self.info_labels.append(lbl)
