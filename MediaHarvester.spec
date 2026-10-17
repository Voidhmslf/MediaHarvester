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
]

for package_name in ('customtkinter', 'imageio_ffmpeg', 'gallery_dl', 'vkpymusic'):
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
    excludes=[],
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
