@echo off
rem Arranca el motor y lo reinicia si se cae.
cd /d "%~dp0.."
if not exist live\logs mkdir live\logs
:loop
python -m live.engine --config live\config.toml
echo [%date% %time%] el motor se ha detenido; reinicio en 30 s >> live\logs\reinicios.log
timeout /t 30 /nobreak > nul
goto loop
