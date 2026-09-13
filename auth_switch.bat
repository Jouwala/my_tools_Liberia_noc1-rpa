@echo off
REM One-click toggle for the shared auth switch (uniplam portal + myapp).
REM Usage: auth_switch.bat [status^|on^|off^|toggle]
python "%~dp0auth_switch.py" %*
