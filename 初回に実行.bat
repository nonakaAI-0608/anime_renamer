@echo off
chcp 65001 >nul
title Syobocal Requirements Installer

echo Installing requests...
py -m pip install requests
if errorlevel 1 goto error

echo.
echo Installing tkinterdnd2...
py -m pip install tkinterdnd2
if errorlevel 1 goto error

echo.
echo Installation completed successfully.
pause
exit /b 0

:error
echo.
echo Installation failed. Please check the error message above.
pause
exit /b 1
