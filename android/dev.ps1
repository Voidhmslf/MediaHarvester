# Пересобрать debug APK и поставить его в эмулятор (запускает эмулятор, если он не запущен).
# Использование: powershell -File android\dev.ps1
$tools = Join-Path $env:USERPROFILE "android-dev"
$env:JAVA_HOME = Join-Path $tools "jdk"
$env:ANDROID_HOME = Join-Path $tools "sdk"
$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"

if (-not (& $adb devices | Select-String "emulator-\d+\s+device")) {
    Start-Process (Join-Path $env:ANDROID_HOME "emulator\emulator.exe") -ArgumentList "-avd", "mh_phone", "-no-snapshot-save"
    & $adb wait-for-device
    while ((& $adb shell getprop sys.boot_completed) -notmatch "1") { Start-Sleep 2 }
}

Push-Location $PSScriptRoot
try {
    & .\gradlew.bat assembleX64Debug
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $adb install -r app\build\outputs\apk\x64\debug\app-x64-debug.apk
    & $adb shell am start -n app.mediaharvester/.MainActivity
} finally {
    Pop-Location
}
