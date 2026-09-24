@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: === Настройки ===
set PROJECT_NAME=CloudBackupTool
set SCRIPT_NAME=CloudBackupTool.py
set CONFIG_FILE=bt2_config.json
set SPEC_FILE=%PROJECT_NAME%.spec
set BUILD_DIR=build
set DIST_DIR=dist
set PYCACHE_DIR=__pycache__

:: === Генерация имени папки с датой/временем ===
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set datetime=%%i
set YEAR=%datetime:~0,4%
set MONTH=%datetime:~4,2%
set DAY=%datetime:~6,2%
set HOUR=%datetime:~8,2%
set MIN=%datetime:~10,2%
set SEC=%datetime:~12,2%
set TIMESTAMP=%YEAR%-%MONTH%-%DAY%_%HOUR%-%MIN%-%SEC%
set OUTPUT_DIR=%DIST_DIR%\%PROJECT_NAME% - %TIMESTAMP%

:: === Цвета для вывода ===
for /F "tokens=1,2 delims=#" %%a in ('"prompt #$H#$E# & echo on & for %%b in (1) do rem"') do (
set "DEL=%%a"
set "GREEN=%%b[32m"
set "YELLOW=%%b[33m"
set "RED=%%b[31m"
set "CYAN=%%b[36m"
set "RESET=%%b[0m"
)

:: === Заголовок ===
echo %GREEN%========================================
echo   🚀 Cloud Backup Tool — Сборка в .exe
echo   %DATE% %TIME%
echo ========================================%RESET%
echo.

:: === 1. Очистка старых артефактов ===
echo %YELLOW%🧹 Очистка старых файлов сборки...%RESET%
if exist "%BUILD_DIR%" (
echo   🗑️  Удаляю %BUILD_DIR%\
rmdir /s /q "%BUILD_DIR%"
)
if exist "%DIST_DIR%" (
echo   🗑️  Удаляю %DIST_DIR%\
rmdir /s /q "%DIST_DIR%"
)

:: Очистка __pycache__ в корне и подпапках
for /d /r %%d in (%PYCACHE_DIR%) do @if exist "%%d" (
echo   🗑️  Удаляю %%d
rmdir /s /q "%%d"
)

:: Удаление *.pyc файлов
for /r %%f in (*.pyc) do @if exist "%%f" (
del /q "%%f"
)
echo %GREEN%✅ Очистка завершена%RESET%
echo.

:: === 2. Проверка наличия файлов ===
echo %YELLOW%📋 Проверка зависимостей...%RESET%
if not exist "%SPEC_FILE%" (
echo %RED%❌ Ошибка: не найден файл %SPEC_FILE%%RESET%
echo %YELLOW%💡 Создайте spec файл командой: pyi-makespec --onefile --windowed --name "%PROJECT_NAME%" --icon "backup.ico" "%SCRIPT_NAME%"%RESET%
goto :pause_exit
)
if not exist "%SCRIPT_NAME%" (
echo %RED%❌ Ошибка: не найден %SCRIPT_NAME%%RESET%
goto :pause_exit
)
if not exist "%CONFIG_FILE%" (
echo %YELLOW%⚠️  Внимание: %CONFIG_FILE% не найден — приложение может упасть при запуске%RESET%
)

set "ICON_EXISTS=0"
if exist "backup.ico" set "ICON_EXISTS=1"
if "%ICON_EXISTS%"=="0" (
echo %YELLOW%⚠️  Внимание: backup.ico не найден — иконка не будет вшита%RESET%
)

echo %GREEN%✅ Все проверки пройдены%RESET%
echo.
:: === 2.5. Проверка Python и зависимостей ===
echo %YELLOW%🐍 Проверка Python и зависимостей...%RESET%
:: Приоритет: .venv > системный python
if exist ".venv\Scripts\python.exe" (
set "PYTHON=.venv\Scripts\python.exe"
echo   ✅ Используем .venv
) else (
set "PYTHON=python"
where python >nul 2>nul
if !ERRORLEVEL! neq 0 (
echo %RED%❌ Ошибка: python не найден в PATH%RESET%
echo %YELLOW%💡 Установите Python 3.8+ и добавьте его в PATH%RESET%
echo %YELLOW%💡 Или создайте venv: py -3.14 -m venv .venv%RESET%
goto :pause_exit
)
echo   ℹ️  .venv не найден, используем системный python
)
!PYTHON! -c "import schedule, pystray, PIL, sv_ttk, PyInstaller, psutil, requests, watchdog" >nul 2>nul
if !ERRORLEVEL! neq 0 (
echo %YELLOW%⚠️  Некоторые зависимости не установлены. Устанавливаю...%RESET%
!PYTHON! -m pip install -r requirements.txt
if !ERRORLEVEL! neq 0 (
echo %RED%❌ Не удалось установить зависимости%RESET%
goto :pause_exit
)
echo %GREEN%✅ Зависимости установлены%RESET%
)
echo %GREEN%✅ Python и зависимости в порядке%RESET%
echo.

:: === 3. Создание выходной папки ===
echo %YELLOW%📁 Создание выходной папки...%RESET%
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
echo   ✅ %OUTPUT_DIR%
echo.

:: === 4. Сборка через PyInstaller ===
echo %YELLOW%🔨 Запуск PyInstaller...%RESET%
echo   Spec-файл: %SPEC_FILE%
echo   Выходная папка: %OUTPUT_DIR%
echo.

:: Замер времени
set START_TIME=%TIME%
!PYTHON! -m PyInstaller "%SPEC_FILE%"

:: === КРИТИЧНО: сохраняем код выхода СРАЗУ ===
set "PYI_EXIT_CODE=%ERRORLEVEL%"

:: === 5. Копирование файлов в выходную папку ===
echo.
if %PYI_EXIT_CODE% equ 0 (
echo %GREEN%✅ Сборка успешна!%RESET%
if exist "%DIST_DIR%\%PROJECT_NAME%.exe" (
echo %YELLOW%📦 Копирование файлов для запуска...%RESET%

:: Копируем .exe
copy /Y "%DIST_DIR%\%PROJECT_NAME%.exe" "%OUTPUT_DIR%\" >nul
echo   ✅ %PROJECT_NAME%.exe

:: Копируем config
if exist "%CONFIG_FILE%" (
copy /Y "%CONFIG_FILE%" "%OUTPUT_DIR%\" >nul
echo   ✅ %CONFIG_FILE%
)

:: Копируем иконку (опционально)
if exist "backup.ico" (
copy /Y "backup.ico" "%OUTPUT_DIR%\" >nul
echo   ✅ backup.ico
)

set EXE_PATH=%OUTPUT_DIR%\%PROJECT_NAME%.exe
for %%A in ("!EXE_PATH!") do set EXE_SIZE=%%~zA
echo.
echo %GREEN%========================================
echo   📊 Результат:
echo ========================================%RESET%
echo %CYAN%📦 Путь: !EXE_PATH!%RESET%
echo %CYAN%📏 Размер: !EXE_SIZE! байт%RESET%
echo %CYAN%📁 Папка: %OUTPUT_DIR%%RESET%
echo.

:: Открываем папку с результатом
echo %YELLOW%📂 Открытие папки с результатом...%RESET%
explorer "%OUTPUT_DIR%"
)
) else (
echo %RED%========================================
echo   ❌ Ошибка сборки (код: %PYI_EXIT_CODE%)
echo ========================================%RESET%
echo %YELLOW%💡 Проверьте:
echo   • Установлены ли зависимости: pip install -r requirements.txt
echo   • Есть ли права на запись в папку
echo   • Логи ошибок в %BUILD_DIR%\%PROJECT_NAME%\%RESET%
)

:: === 6. Пауза перед закрытием ===
:pause_exit
echo.
echo %GREEN%🎉 Готово!%RESET%
echo.
echo %CYAN%Нажмите любую клавишу для выхода...%RESET%
pause >nul