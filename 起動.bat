@echo off
cd /d "%~dp0"
rem Launch the GUI without a console window; this window closes immediately.
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 syobocal_rename_unified_v1.py
) else (
    start "" pythonw syobocal_rename_unified_v1.py
)
exit /b 0
