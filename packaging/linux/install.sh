#!/bin/sh
# Установка MediaHarvester из архива: ярлык в меню приложений, иконка и команда `mediaharvester`.
# Без прав администратора ставится в ~/.local; от root (или с PREFIX=/usr/local) — на всю систему.
# Удаление: ./uninstall.sh
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)

if [ -z "${PREFIX:-}" ]; then
    if [ "$(id -u)" = 0 ]; then PREFIX=/usr/local; else PREFIX="$HOME/.local"; fi
fi

LIB="$PREFIX/lib/mediaharvester"
BIN="$PREFIX/bin"
APPS="$PREFIX/share/applications"
ICONS="$PREFIX/share/icons/hicolor"

if [ ! -x "$HERE/app/mediaharvester" ]; then
    echo "Не найден app/mediaharvester: запускайте install.sh из распакованного архива." >&2
    exit 1
fi

mkdir -p "$LIB" "$BIN" "$APPS" "$ICONS"
rm -rf "$LIB"
mkdir -p "$LIB"
cp -a "$HERE/app/." "$LIB/"
ln -sf "$LIB/mediaharvester" "$BIN/mediaharvester"

# Иконки всех размеров
if [ -d "$HERE/icons/hicolor" ]; then
    cp -a "$HERE/icons/hicolor/." "$ICONS/"
fi

# Ярлык с абсолютным путём к программе (меню не всегда видит ~/.local/bin)
sed "s|@EXEC@|$LIB/mediaharvester|" "$HERE/mediaharvester.desktop" > "$APPS/mediaharvester.desktop"
chmod 644 "$APPS/mediaharvester.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "$ICONS" >/dev/null 2>&1 || true

echo "MediaHarvester установлен в $LIB"
echo "Запуск: из меню приложений или командой mediaharvester"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Подсказка: $BIN нет в PATH, поэтому команда mediaharvester в терминале может не находиться." ;;
esac
