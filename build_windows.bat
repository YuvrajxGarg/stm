@echo off
REM Builds dist\Stm\Stm.exe (ffmpeg and the htdemucs model bundled). Run on Windows with Python 3.9+ installed.
cd /d "%~dp0"
if not exist models\htdemucs.onnx (
  echo Exporting the htdemucs model to models\htdemucs.onnx ^(one time^)
  py -3 -m venv .venv-model || python -m venv .venv-model
  .venv-model\Scripts\python -m pip install --upgrade pip
  .venv-model\Scripts\pip install -r tools\requirements-export.txt
  .venv-model\Scripts\python tools\export_onnx.py || exit /b 1
)
py -3 -m venv .venv-build || python -m venv .venv-build
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
pip install pyinstaller certifi -r requirements.txt
pyinstaller --noconfirm --log-level WARN Stm.spec
echo.
echo Done: dist\Stm\Stm.exe
pause
