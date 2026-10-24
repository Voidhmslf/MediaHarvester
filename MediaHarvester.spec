# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/logo.ico', 'assets')]
binaries = []
hiddenimports = [
    'gallery_dl',
    'vkpymusic',
    'yt_dlp',
    'imageio_ffmpeg',
    'PIL._tkinter_finder',
    'curl_cffi',
    'customtkinter',
    'webview',
]

for package_name in ('customtkinter', 'imageio_ffmpeg', 'gallery_dl', 'vkpymusic', 'webview', 'clr_loader', 'pythonnet'):
    d, b, h = collect_all(package_name)
    datas += d
    binaries += b
    hiddenimports += h

# Удаляем возможные дубликаты
datas = list({(str(src), str(dst)): (src, dst) for src, dst in datas}.values())
hiddenimports = list(dict.fromkeys(hiddenimports))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Пакеты из окружения разработки, которые приложению не нужны (научный стек, Jupyter/IPython, lxml).
    # selenium, trio, rich, av, cryptography, curl_cffi и т.п. НЕ исключать: их требуют vkpymusic и yt-dlp.
    excludes=[
        'scipy', 'pandas', 'numpy', 'matplotlib',
        'IPython', 'ipykernel', 'ipython_pygments_lexers', 'jupyter_client', 'jupyter_core',
        'jedi', 'parso', 'prompt_toolkit', 'zmq', 'debugpy', 'tornado', 'nbformat', 'traitlets',
        'lxml', 'jinja2', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MediaHarvester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/logo.ico'],
)
