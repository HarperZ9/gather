@echo off
chcp 65001 >nul
if "%GATHER_WHISPER_PYTHON%"=="" (
  echo set GATHER_WHISPER_PYTHON to a Python with faster_whisper installed 1>&2
  exit /b 2
)
"%GATHER_WHISPER_PYTHON%" -I -X utf8 "%~dp0whisper_bridge.py" %*
