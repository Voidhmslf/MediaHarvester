#!/bin/sh
# Удаляет то, что поставил install.sh. Настройки и скачанные файлы не трогает
# (настройки лежат в ~/.local/share/MediaHarvester).
set -eu

if [ -z "${PREFIX:-}" ]; then
    if [ "$(id -u)" = 0 ]; then PREFIX=/usr/local; else PREFIX="$HOME/.local"; fi
fi

rm -rf "$PREFIX/lib/mediaharvester"
rm -f "$PREFIX/bin/mediaharvester"
rm -f "$PREFIX/share/applications/mediaharvester.desktop"
find "$PREFIX/share/icons/hicolor" -name 'mediaharvester*' -type f -delete 2>/dev/null || true

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true

echo "MediaHarvester удалён. Настройки остались в ~/.local/share/MediaHarvester: удалите папку, если они не нужны."
