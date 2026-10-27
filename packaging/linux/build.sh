#!/bin/sh
# Сборка MediaHarvester для Linux. Запускается внутри контейнера python:3.11-bullseye (старая glibc 2.31):
#   docker run --rm -v "<папка проекта>:/src:ro" -v "<папка результата>:/out" python:3.11-bullseye sh /src/packaging/linux/build.sh
# На выходе в /out:
#   MediaHarvester-<версия>-linux-<arch>.tar.gz   — работает на любом дистрибутиве, ставится через install.sh
#   MediaHarvester-<версия>-linux-<arch>.AppImage — один файл, если задан APPIMAGETOOL (см. README)
set -eu

SRC=/src
WORK=/tmp/mh-build
OUT=/out
ARCH=$(uname -m)

VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/src/version.py")
NAME="MediaHarvester-$VERSION-linux-$ARCH"

rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"
cd "$WORK"

# Копируем только нужное: так в сборку не попадут android/, dist/ и чужие настройки
mkdir -p proj
cp -r "$SRC/main.py" "$SRC/src" "$SRC/assets" "$SRC/requirements.txt" proj/
find proj -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f proj/settings.json

python -m venv venv
. venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r proj/requirements.txt pyinstaller

cd proj
pyinstaller --noconfirm --clean --distpath "$WORK/dist" --workpath "$WORK/pybuild" \
    "$SRC/packaging/linux/MediaHarvester-linux.spec"
cd "$WORK"

APP="$WORK/dist/MediaHarvester"
[ -x "$APP/mediaharvester" ] || { echo "Сборка не создала $APP/mediaharvester" >&2; exit 1; }
# imageio_ffmpeg кладёт бинарник как обычный файл: следим, чтобы он остался исполняемым
find "$APP" -path '*imageio_ffmpeg/binaries/*' -type f -exec chmod 755 {} +

# ── Архив ─────────────────────────────────────────────
PKG="$WORK/pkg/$NAME"
mkdir -p "$PKG/icons"
cp -a "$APP" "$PKG/app"
cp -a "$SRC/MediaHarvester-brand/linux/hicolor" "$PKG/icons/hicolor"
rm -f "$PKG"/icons/hicolor/symbolic/apps/*   # символьная иконка нужна только для трея
cp "$SRC/packaging/linux/install.sh" "$SRC/packaging/linux/uninstall.sh" "$SRC/packaging/linux/mediaharvester.desktop" "$PKG/"
cp "$SRC/LICENSE" "$PKG/"
chmod 755 "$PKG/install.sh" "$PKG/uninstall.sh"
tar -C "$WORK/pkg" -czf "$OUT/$NAME.tar.gz" "$NAME"
echo "Готово: $OUT/$NAME.tar.gz"

# ── AppImage (по желанию) ─────────────────────────────
if [ -n "${APPIMAGETOOL:-}" ] && [ -f "$APPIMAGETOOL" ]; then
    APPDIR="$WORK/MediaHarvester.AppDir"
    mkdir -p "$APPDIR/usr/lib"
    cp -a "$APP" "$APPDIR/usr/lib/mediaharvester"
    cp "$SRC/packaging/linux/AppRun" "$APPDIR/AppRun"
    chmod 755 "$APPDIR/AppRun"
    sed "s|@EXEC@|mediaharvester|" "$SRC/packaging/linux/mediaharvester.desktop" > "$APPDIR/mediaharvester.desktop"
    cp "$SRC/MediaHarvester-brand/linux/hicolor/256x256/apps/mediaharvester.png" "$APPDIR/mediaharvester.png"
    cp "$SRC/MediaHarvester-brand/linux/hicolor/256x256/apps/mediaharvester.png" "$APPDIR/.DirIcon"
    # --appimage-extract-and-run: в контейнере нет FUSE, поэтому сам appimagetool запускаем распакованным
    ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run \
        ${APPIMAGE_RUNTIME:+--runtime-file "$APPIMAGE_RUNTIME"} "$APPDIR" "$OUT/$NAME.AppImage"
    echo "Готово: $OUT/$NAME.AppImage"
fi

(cd "$OUT" && sha256sum "$NAME".* > "SHA256SUMS-linux-$ARCH.txt")
