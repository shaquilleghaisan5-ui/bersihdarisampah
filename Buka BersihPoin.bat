@echo off
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 goto use_py
goto use_python

:use_py
py -3 -c "import flask" >nul 2>nul
if errorlevel 1 py -3 -m pip install -r requirements.txt
if errorlevel 1 goto failed
py -3 app.py
if errorlevel 1 goto failed
goto end

:use_python
python -c "import flask" >nul 2>nul
if errorlevel 1 python -m pip install -r requirements.txt
if errorlevel 1 goto failed
python app.py
if errorlevel 1 goto failed
goto end

:failed
echo BersihPoin gagal dijalankan. Pastikan Python sudah terpasang dan coba lagi.
pause

:end
