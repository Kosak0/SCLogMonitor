@echo off
cd /d "%~dp0"
title Star Citizen Log Monitor
echo Iniciando Star Citizen Log Monitor...
echo.
python sc_monitor.py
if errorlevel 1 (
    echo.
    echo Error al ejecutar el programa.
    echo Asegurate de tener Python y las dependencias instaladas.
    echo.
    pause
)