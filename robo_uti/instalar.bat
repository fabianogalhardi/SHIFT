@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Instalando o robo de exames da UTI ===

where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.12 em https://www.python.org/downloads/
  echo e marque "Add python.exe to PATH" na instalacao. Depois rode este arquivo de novo.
  pause
  exit /b 1
)

if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium

echo.
echo === Credenciais ===
python credenciais.py

echo.
echo === Agendando todos os dias as 06:00 ===
schtasks /create /f /sc daily /st 06:00 /tn "Robo UTI - exames" /tr "\"%~dp0rodar_robo.bat\""

echo.
echo Pronto. Para testar agora vendo o navegador, rode: testar.bat
pause
