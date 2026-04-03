@echo off
setlocal

echo === [1/3] Python version ===
python --version
if errorlevel 1 exit /b 1

echo === [2/3] Running tests ===
pytest -q
if errorlevel 1 exit /b 1

echo === [3/3] verify done ===
exit /b 0