#!/usr/bin/env python3
"""
Cursor Token Usage Notifier
Monitors Cursor AI token usage and sends macOS native notifications on changes.
Zero external dependencies — uses only Python stdlib.
"""

import sqlite3
import json
import os
import sys
import time
import subprocess
import urllib.request
import urllib.parse
import logging
from pathlib import Path
from typing import Optional, Tuple

# ─── Configuration ───────────────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = int(os.environ.get("CURSOR_NOTIFY_INTERVAL", 120))
STATE_FILE = Path(__file__).parent / ".usage_state.json"
LOG_FILE = Path(__file__).parent / "notify.log"

CURSOR_DB_PATH = Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
CURSOR_API_URL = "https://cursor.com/api/usage-summary"

DB_KEY_STATSIG_BOOTSTRAP = "workbench.experiments.statsigBootstrap"
DB_KEY_ACCESS_TOKEN = "cursorAuth/accessToken"

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("cursor-notify")

# ─── Database helpers ────────────────────────────────────────────────────────

def read_db_value(db_path: Path, key: str) -> Optional[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_credentials() -> Tuple[str, str]:
    bootstrap_raw = read_db_value(CURSOR_DB_PATH, DB_KEY_STATSIG_BOOTSTRAP)
    if not bootstrap_raw:
        raise RuntimeError("Cannot find statsigBootstrap in Cursor DB — is Cursor installed and logged in?")

    user_id = json.loads(bootstrap_raw).get("user", {}).get("userID")
    if not user_id:
        raise RuntimeError("Cannot extract userID from statsigBootstrap")

    access_token = read_db_value(CURSOR_DB_PATH, DB_KEY_ACCESS_TOKEN)
    if not access_token:
        raise RuntimeError("Cannot find access token in Cursor DB — are you logged in?")

    return user_id, access_token

# ─── API helpers ─────────────────────────────────────────────────────────────

def fetch_usage(user_id: str, access_token: str) -> dict:
    session_token = f"{user_id}::{access_token}"
    cookie = f"WorkosCursorSessionToken={urllib.parse.quote(session_token)}"

    req = urllib.request.Request(
        CURSOR_API_URL,
        headers={
            "Accept": "application/json",
            "Cookie": cookie,
            "User-Agent": "cursor-usage-notify/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

# ─── Notification ────────────────────────────────────────────────────────────

def notify(title: str, message: str, sound: str = "Purr"):
    subprocess.run(
        [
            "osascript", "-e",
            f'display notification "{message}" with title "{title}" sound name "{sound}"',
        ],
        check=False,
    )
    log.info("NOTIFICATION  %s — %s", title, message)

# ─── State persistence ───────────────────────────────────────────────────────

def load_state() -> Optional[dict]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def save_state(data: dict):
    STATE_FILE.write_text(json.dumps(data, indent=2))

# ─── Diff & notification logic ───────────────────────────────────────────────

def extract_key_metrics(usage: dict) -> dict:
    ind = usage.get("individualUsage", {})
    plan = ind.get("plan", {})
    od = ind.get("onDemand", {})
    return {
        "plan_used": plan.get("used", 0),
        "plan_limit": plan.get("limit", 0),
        "plan_remaining": plan.get("remaining", 0),
        "plan_pct": plan.get("totalPercentUsed", 0),
        "ondemand_used": od.get("used", 0),
        "ondemand_limit": od.get("limit"),
        "cycle_start": usage.get("billingCycleStart", ""),
        "cycle_end": usage.get("billingCycleEnd", ""),
        "membership": usage.get("membershipType", ""),
    }


def build_notification(prev: Optional[dict], curr: dict) -> Optional[str]:
    if prev is None:
        pct = curr["plan_pct"]
        return (
            f"Plan: {curr['plan_used']}/{curr['plan_limit']} requests "
            f"({pct:.1f}% used) · On-demand: ${curr['ondemand_used']:.2f}"
        )

    if prev == curr:
        return None

    delta_plan = curr["plan_used"] - prev["plan_used"]
    delta_od = curr["ondemand_used"] - prev["ondemand_used"]
    parts = []

    if delta_plan:
        parts.append(f"Plan +{delta_plan} → {curr['plan_used']}/{curr['plan_limit']} ({curr['plan_pct']:.1f}%)")
    if delta_od:
        parts.append(f"On-demand +${delta_od:.2f} → ${curr['ondemand_used']:.2f}")
    if curr["plan_pct"] >= 90 and (prev is None or prev["plan_pct"] < 90):
        parts.append("⚠ 90% of plan quota used!")
    if curr["plan_remaining"] == 0 and (prev is None or prev["plan_remaining"] > 0):
        parts.append("🚨 Plan quota exhausted — on-demand active!")

    if prev.get("cycle_start") != curr["cycle_start"]:
        parts.append("New billing cycle started")

    return " · ".join(parts) if parts else None

# ─── Main loop ───────────────────────────────────────────────────────────────

def run():
    log.info("Starting Cursor usage notifier (poll every %ds)", POLL_INTERVAL_SECONDS)

    user_id, access_token = get_credentials()
    log.info("Credentials loaded from local Cursor DB")

    prev_metrics = load_state()
    consecutive_errors = 0

    while True:
        try:
            usage = fetch_usage(user_id, access_token)
            curr_metrics = extract_key_metrics(usage)
            consecutive_errors = 0

            msg = build_notification(prev_metrics, curr_metrics)
            if msg:
                notify("Cursor Usage Update", msg)
                save_state(curr_metrics)
                prev_metrics = curr_metrics
            else:
                log.info("No change in usage")

        except Exception as e:
            consecutive_errors += 1
            log.error("Fetch failed (%d in a row): %s", consecutive_errors, e)

            if consecutive_errors >= 3:
                try:
                    user_id, access_token = get_credentials()
                    log.info("Refreshed credentials from DB")
                    consecutive_errors = 0
                except Exception as re:
                    log.error("Credential refresh also failed: %s", re)

            if consecutive_errors >= 10:
                notify("Cursor Usage Error", "10 consecutive failures — check notify.log", "Basso")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped by user")
    except Exception as e:
        log.critical("Fatal: %s", e)
        notify("Cursor Usage Notifier", f"Fatal error: {e}", "Basso")
        sys.exit(1)
