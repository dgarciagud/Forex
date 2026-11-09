@echo off
rem Arranca el motor y lo reinicia si se cae.
rem Python a usar: variable de entorno PYTHON (p. ej. C:\Users\yo\anaconda3\python.exe); si no, "python".
cd /d "%~dp0.."
if "%PYTHON%"=="" set PYTHON=python
if not exist live\logs mkdir live\logs
:loop
"%PYTHON%" -m live.engine --config live\config.toml
echo [%date% %time%] el motor se ha detenido; reinicio en 30 s >> live\logs\reinicios.log
timeout /t 30 /nobreak > nul
goto loop
