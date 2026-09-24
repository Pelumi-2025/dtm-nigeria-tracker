@echo off
REM Windows: double-click to install requirements (first time) and open the dashboard.
cd /d %~dp0
python -m pip install -q -r requirements.txt
start "" http://localhost:8050
python server.py
