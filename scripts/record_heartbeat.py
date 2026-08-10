#!/usr/bin/env python3
"""
Record a daily automation heartbeat for the scheduled profile refresh.
This keeps the cron-driven workflow producing a meaningful commit on every run.
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config.json")
OUT_PATH = os.path.join(ROOT, "data", "automation-heartbeat.json")

with open(CONFIG_PATH) as fh:
    CONFIG = json.load(fh)

now = datetime.datetime.now(datetime.UTC)
payload = {
    "username": CONFIG["github_username"],
    "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "date": now.date().isoformat(),
    "event": "scheduled-profile-refresh",
    "message": "Daily GitHub profile refresh heartbeat",
    "details": {
        "source": "github-actions",
        "purpose": "Keep the scheduled cron workflow producing an attributable contribution",
    },
}

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
with open(OUT_PATH, "w") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")

print(f"wrote {OUT_PATH}")
