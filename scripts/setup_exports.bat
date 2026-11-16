@echo off
echo ============================================
echo HillDesk Export Feature Setup
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Installing docxtpl...
call venv\Scripts\pip install docxtpl
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: pip install failed
    pause
    exit /b 1
)
echo.

echo [2/3] Running migrations...
call venv\Scripts\python manage.py migrate
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: migrate failed
    pause
    exit /b 1
)
echo.

echo [3/3] Generating export templates...
call venv\Scripts\python manage.py generate_export_templates
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: template generation failed
    pause
    exit /b 1
)
echo.

echo ============================================
echo SUCCESS - Export feature setup complete!
echo ============================================
echo.
echo Check event_management\templates_docx\ for 4 .docx files
echo.
pause
