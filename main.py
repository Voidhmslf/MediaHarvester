import sys

if __name__ == "__main__":
    # Перехват для сборки PyInstaller, чтобы вызов sys.executable не рестартовал GUI
    if len(sys.argv) > 1 and sys.argv[1] == "--gallery-dl-worker":
        import gallery_dl
        sys.argv = ["gallery-dl"] + sys.argv[2:]
        sys.exit(gallery_dl.main())

    # Окно входа в VK запускается отдельным процессом: pywebview требует главный поток
    if len(sys.argv) > 2 and sys.argv[1] == "--vk-login-worker":
        from src.core.vk_auth import run_login_window, BLANK_PREFIX
        sys.exit(run_login_window(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else BLANK_PREFIX))

    # Linux-сборка: возвращаем системный LD_LIBRARY_PATH, чтобы xdg-open и браузер запускались нормально
    from src.utils.helpers import restore_system_env
    restore_system_env()

    # Подключаем скачанную свежую версию yt-dlp (если есть) до импорта остального кода
    try:
        from src.utils.ytdlp_updater import activate_override
        activate_override()
    except Exception:
        pass

    from src.ui.app import MediaHarvesterApp
    app = MediaHarvesterApp()
    app.mainloop()
