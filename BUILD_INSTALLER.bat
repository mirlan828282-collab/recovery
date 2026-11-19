@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==========================================
echo       СБОРКА RECOVERY HDD
echo ==========================================

where py >nul 2>nul
if errorlevel 1 (
  echo Не найден Python Launcher. Установите Python 3.8 x64 с Tkinter.
  pause
  exit /b 1
)

py -3.8 -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo Устанавливаю PyInstaller 5.13.2...
  py -3.8 -m pip install pyinstaller==5.13.2
  if errorlevel 1 goto error
)

py -3.8 -m PyInstaller --noconfirm --clean --windowed --name RecoveryHDD --paths app app\main.py
if errorlevel 1 goto error

if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\RecoveryHDD.iss
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles%\Inno Setup 6\ISCC.exe" installer\RecoveryHDD.iss
) else (
  echo Inno Setup 6 не найден. EXE собран в папке dist\RecoveryHDD.
  pause
  exit /b 0
)
if errorlevel 1 goto error
echo.
echo ГОТОВО: Output\RecoveryHDD_Setup.exe
pause
exit /b 0

:error
echo.
echo СБОРКА ЗАВЕРШИЛАСЬ С ОШИБКОЙ.
pause
exit /b 1
