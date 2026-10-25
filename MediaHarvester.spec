# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo)

# Версия берётся из единственного источника — src/version.py
_ns = {}
with open(os.path.join(SPECPATH, 'src', 'version.py'), encoding='utf-8') as _f:
    exec(_f.read(), _ns)
VERSION = _ns['__version__']
_nums = (tuple(int(p) for p in VERSION.split('.')) + (0, 0, 0, 0))[:4]

# Свойства .exe (Проводник → Свойства → Подробно)
_version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums, mask=0x3F, flags=0x0, OS=0x40004,
                      fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'MediaHarvester'),
            StringStruct('FileDescription', 'MediaHarvester - multimedia downloader'),
            StringStruct('FileVersion', VERSION),
            StringStruct('InternalName', 'MediaHarvester'),
            StringStruct('LegalCopyright', 'MIT License'),
            StringStruct('OriginalFilename', 'MediaHarvester.exe'),
            StringStruct('ProductName', 'MediaHarvester'),
            StringStruct('ProductVersion', VERSION),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)
_version_file = os.path.join(SPECPATH, 'build', 'version_info.txt')
os.makedirs(os.path.dirname(_version_file), exist_ok=True)
with open(_version_file, 'w', encoding='utf-8') as _f:
    _f.write(str(_version_info))

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
    version=_version_file,
)
