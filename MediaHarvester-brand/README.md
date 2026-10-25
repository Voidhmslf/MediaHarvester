# MediaHarvester — набор логотипа и иконок

Знак: оранжевая плитка `#D9480F`, в ней белый треугольник «плей» падает в чашу.
**Один и тот же файл работает и в светлой, и в тёмной теме**, менять цвета по теме не нужно
(плитка/надпись 4.3:1 на `#FFFFFF` и 4.4:1 на `#121212`).

## Правило размеров (важно)

| Размер | Файл |
| --- | --- |
| 16–20 px | `source/mediaharvester-mark-small.svg` (упрощённый, без выреза в чаше) |
| ≥ 24 px | `source/mediaharvester-mark.svg` |
| Шапка, About, сайт | `source/mediaharvester-lockup.svg` (знак + надпись, мин. высота 20 px) |

Все готовые PNG/ICO уже собраны по этому правилу.

## Структура

```
source/    SVG-исходники: mark, mark-small, lockup, glyph-white / glyph-orange / glyph-currentcolor (глиф без плитки)
png/       mark/mediaharvester-{16..1024}.png, lockup/*-{32,64,128}h.png — для UI внутри приложения
windows/   mediaharvester.ico (16,20,24,32,40,48,64,128,256)
macos/     mediaharvester.icns, mediaharvester.iconset/ (для `iconutil -c icns`), 1024 px по сетке Apple
linux/     hicolor/<N>x<N>/apps/mediaharvester.png, scalable/*.svg, symbolic/*-symbolic.svg, mediaharvester.desktop
web/       favicon.ico, favicon.svg, apple-touch-icon.png, icon-192/512, icon-maskable-512, site.webmanifest, head-snippet.html
android/   res/ (готовая папка ресурсов) + play-store-icon-512.png
tokens/    brand-colors.json / .css
preview.png — контрольный лист: как выглядит везде
```

## Интеграция (инструкции для Claude Code)

### Desktop (стек любой)
- **Иконка окна/приложения:** Windows — `windows/mediaharvester.ico`; macOS — `macos/mediaharvester.icns`; Linux — PNG 256/512 или `linux/hicolor/scalable/apps/mediaharvester.svg`.
  - Electron: `BrowserWindow({ icon })` + `build.win.icon` / `build.mac.icon` / `build.linux.icon` (папка `linux/hicolor`) в electron-builder.
  - Tauri: положить файлы в `src-tauri/icons/` и прописать в `bundle.icon`.
  - PyInstaller: `--icon windows/mediaharvester.ico` (Windows) / `.icns` (macOS); Qt/PySide: `QIcon("png/mark/mediaharvester-256.png")`.
- **Логотип в интерфейсе:** `source/mediaharvester-lockup.svg` или `mark.svg` как есть, без перекраски — одинаково в обеих темах.
- **Иконка в трее:** Windows/Linux — `png/mark/mediaharvester-16/20/24/32.png`; монохромная (macOS menu bar, symbolic) — `source/mediaharvester-glyph-currentcolor.svg` (template image).
- **Linux:** скопировать `linux/hicolor/*` в `/usr/share/icons/hicolor/` (или `~/.local/share/icons/hicolor/`), `.desktop` в `/usr/share/applications/`, затем `gtk-update-icon-cache`.

### Android (нативный Kotlin/Compose)
1. Скопировать содержимое `android/res/` в `app/src/main/res/` с заменой (старые `ic_launcher*` удалить, в том числе `.webp`).
2. В `AndroidManifest.xml`:
   ```xml
   <application
       android:icon="@mipmap/ic_launcher"
       android:roundIcon="@mipmap/ic_launcher_round" ...>
   ```
3. Иконка уведомлений (загрузки): `NotificationCompat.Builder(...).setSmallIcon(R.drawable.ic_stat_mediaharvester).setColor(0xFFD9480F.toInt())`.
4. Состав: адаптивная иконка (API 26+) = фон `@color/ic_launcher_background` + вектор `ic_launcher_foreground` + `ic_launcher_monochrome` (тематические иконки Android 13+, нужен `compileSdk ≥ 33`); PNG в `mipmap-*dpi` — для API < 26.
5. Google Play: `android/play-store-icon-512.png` (512×512, без прозрачности, Play сам скругляет).

### Android через Flutter
Скопировать `android/res/*` в `android/app/src/main/res/` (как выше) — это надёжнее генератора.
Если удобнее `flutter_launcher_icons`:
```yaml
flutter_launcher_icons:
  android: true
  image_path: "assets/brand/png/mark/mediaharvester-1024.png"
  adaptive_icon_background: "#D9480F"
  adaptive_icon_foreground: "assets/brand/android/res/mipmap-xxxhdpi/ic_launcher_foreground.png"
  adaptive_icon_monochrome: "assets/brand/android/res/mipmap-xxxhdpi/ic_launcher_foreground.png"
```

### Web (сайт/лендинг)
Файлы из `web/` в корень сайта, содержимое `web/head-snippet.html` в `<head>`.

## Правила использования
- Не перекрашивать, не добавлять обводку/тень/градиент, не вращать и не растягивать.
- Отступ вокруг знака ≥ ¼ его высоты.
- Не ставить на оранжево-красный фон и пёстрые фото.

## Цвета
`harvest #D9480F` (бренд, главная кнопка «Скачать»), `on-harvest #FFFFFF`. Полный набор для светлой и тёмной тем — в `tokens/`.

Надпись: Inter Display Bold (OFL), переведена в кривые — шрифт не нужен.
