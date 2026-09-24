#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
( sleep 2; (xdg-open http://localhost:8050 || open http://localhost:8050) >/dev/null 2>&1 ) &
python3 server.py
