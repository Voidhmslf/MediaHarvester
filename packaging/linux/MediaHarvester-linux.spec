# -*- mode: python ; coding: utf-8 -*-
# Сборка для Linux (PyInstaller, папка вместо одного файла: так быстрее запуск и проще упаковать в AppImage).
# Запускается из packaging/linux/build.sh внутри контейнера со старой glibc.
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

datas = [
    (os.path.join(ROOT, 'assets', 'logo.ico'), 'assets'),
    (os.path.join(ROOT, 'assets', 'fonts'), 'assets/fonts'),
    (os.path.join(ROOT, 'assets', 'brand'), 'assets/brand'),
]
binaries = []
hiddenimports = [
    'gallery_dl',
    'vkpymusic',
    'yt_dlp',
    'imageio_ffmpeg',
    'PIL._tkinter_finder',
    'customtkinter',
]

# imageio_ffmpeg везёт статический ffmpeg: он нужен для склейки видео и MP3
for package_name in ('customtkinter', 'imageio_ffmpeg', 'gallery_dl', 'vkpymusic'):
    d, b, h = collect_all(package_name)
    datas += d
    binaries += b
    hiddenimports += h

datas = list({(str(src), str(dst)): (src, dst) for src, dst in datas}.values())
hiddenimports = list(dict.fromkeys(hiddenimports))

a = Analysis(
    [os.path.join(ROOT, 'main.py')],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Встроенное окно входа VK (pywebview) на Linux не используется: вход идёт через обычный браузер
    excludes=[
        'webview', 'gi', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'scipy', 'pandas', 'numpy', 'matplotlib',
        'IPython', 'ipykernel', 'jupyter_client', 'jupyter_core', 'jedi', 'parso', 'prompt_toolkit',
        'zmq', 'debugpy', 'tornado', 'nbformat', 'traitlets', 'lxml', 'jinja2', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mediaharvester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='MediaHarvester',
)
