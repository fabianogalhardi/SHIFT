@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python robo_uti.py --teste
echo.
echo O texto digitado esta na pasta "saidas". O Notion NAO foi alterado no teste.
pause
