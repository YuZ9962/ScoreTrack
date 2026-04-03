@echo off
setlocal

echo === smoke: import CLI entry ===
python -c "import src.main; print('src.main ok')"
if errorlevel 1 exit /b 1

echo === smoke: real Streamlit startup ===
powershell -NoProfile -ExecutionPolicy Bypass -Command "$log = Join-Path $env:TEMP 'scoretrack_streamlit_smoke.log'; $err = Join-Path $env:TEMP 'scoretrack_streamlit_smoke.err.log'; Remove-Item $log,$err -ErrorAction SilentlyContinue; $p = Start-Process python -ArgumentList '-m','streamlit','run','app/app.py','--server.headless','true','--server.port','8511' -RedirectStandardOutput $log -RedirectStandardError $err -PassThru; Start-Sleep -Seconds 10; if ($p.HasExited) { if (Test-Path $log) { Get-Content $log }; if (Test-Path $err) { Get-Content $err }; exit $p.ExitCode }; Stop-Process -Id $p.Id -Force; Write-Output 'streamlit process stayed alive for 10s'; exit 0"
if errorlevel 1 exit /b 1

echo === smoke done ===
exit /b 0
