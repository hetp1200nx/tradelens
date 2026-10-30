@echo off
rem Makes TradeLens go online automatically every time you sign in to Windows.
rem Run once. To undo, delete "TradeLens online.bat" from the Startup folder (Win+R, type shell:startup).
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
  echo @echo off
  echo start "TradeLens online" /min cmd /c "cd /d "%~dp0" ^&^& start_online.bat"
) > "%STARTUP%\TradeLens online.bat"
echo Done. TradeLens will start (minimised) each time you sign in to Windows.
pause
