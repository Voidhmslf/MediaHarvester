import sys

if __name__ == "__main__":
    # Перехват для сборки PyInstaller, чтобы вызов sys.executable не рестартовал GUI
    if len(sys.argv) > 1 and sys.argv[1] == "--gallery-dl-worker":
        import gallery_dl
        sys.argv = ["gallery-dl"] + sys.argv[2:]
        sys.exit(gallery_dl.main())

    # Подключаем скачанную свежую версию yt-dlp (если есть) до импорта остального кода
    try:
        from src.utils.ytdlp_updater import activate_override
        activate_override()
    except Exception:
        pass

    from src.ui.app import MediaHarvesterApp
    app = MediaHarvesterApp()
    app.mainloop()
