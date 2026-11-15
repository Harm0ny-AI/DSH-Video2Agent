@echo off
setlocal
echo Close DeepSeek Harness completely. This window will wait.
:wait
tasklist /FI "IMAGENAME eq DeepSeek Harness.exe" 2>NUL | find /I "DeepSeek Harness.exe" >NUL
if not errorlevel 1 (
  timeout /t 2 /nobreak >NUL
  goto wait
)
echo Clearing Electron UI state...
for %%R in ("%APPDATA%\@deepseek-ai\dsh-desktop" "%APPDATA%\DSH Desktop") do (
  for %%D in ("Cache" "Code Cache" "Service Worker" "Local Storage") do (
    if exist "%%~R\%%~D" rmdir /s /q "%%~R\%%~D"
  )
)
echo Done. Starting DSH...
if not defined DSH_EXE set "DSH_EXE=DeepSeek Harness.exe"
start "" "%DSH_EXE%"
timeout /t 2 /nobreak >NUL
exit /b 0
