@echo off
cd /d %~dp0
echo Abriendo http://localhost:8000 ...
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
