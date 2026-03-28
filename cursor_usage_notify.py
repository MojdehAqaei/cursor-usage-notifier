#!/usr/bin/env python3
"""
Cursor Token Usage Notifier
Notifies after every Cursor AI request with model, token count, and cost.
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
from typing import Optional, Tuple, List, Dict

# ─── Configuration ───────────────────────────────────────────────────────────

POLL_INTERVAL = int(os.environ.get("CURSOR_NOTIFY_INTERVAL", 15))
SUMMARY_EVERY = int(os.environ.get("CURSOR_SUMMARY_EVERY", 40))
STATE_FILE = Path(__file__).parent / ".usage_state.json"
LOG_FILE = Path(__file__).parent / "notify.log"

CURSOR_DB_PATH = Path.home() / "Library/Application Support/Cursor/User/globalStorage/state.vscdb"
EVENTS_API_URL = "https://cursor.com/api/dashboard/get-filtered-usage-events"
SUMMARY_API_URL = "https://cursor.com/api/usage-summary"

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
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
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

# ─── HTTP helper ─────────────────────────────────────────────────────────────

def _make_cookie(user_id: str, access_token: str) -> str:
    session = "%s::%s" % (user_id, access_token)
    return "WorkosCursorSessionToken=%s" % urllib.parse.quote(session)


def _headers(cookie: str) -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cookie": cookie,
        "User-Agent": "cursor-usage-notify/2.0",
        "Origin": "https://cursor.com",
    }

# ─── Events API ──────────────────────────────────────────────────────────────

def fetch_events(cookie: str, since_ms: int) -> List[dict]:
    now_ms = int(time.time() * 1000)
    body = json.dumps({
        "teamId": 0,
        "startDate": str(since_ms),
        "endDate": str(now_ms),
        "page": 1,
        "pageSize": 50,
    }).encode()

    req = urllib.request.Request(
        EVENTS_API_URL, data=body, headers=_headers(cookie), method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    raw = data.get("usageEventsDisplay", [])
    events = []
    for e in raw:
        tok = e.get("tokenUsage", {})
        inp = int(tok.get("inputTokens", 0) or 0)
        out = int(tok.get("outputTokens", 0) or 0)
        cache_w = int(tok.get("cacheWriteTokens", 0) or 0)
        cache_r = int(tok.get("cacheReadTokens", 0) or 0)
        cents = float(tok.get("totalCents", 0) or 0)
        events.append({
            "id": e.get("id", "%s-%s" % (e.get("timestamp"), e.get("model"))),
            "ts": int(e.get("timestamp", 0)),
            "model": e.get("model", "unknown"),
            "kind": e.get("kind", "unknown"),
            "input": inp,
            "output": out,
            "cache_write": cache_w,
            "cache_read": cache_r,
            "total_tokens": inp + out + cache_w + cache_r,
            "cost": cents / 100.0,
        })
    events.sort(key=lambda x: x["ts"])
    return events

# ─── Summary API ───────────────────────────────────────────────────────────

def fetch_summary(cookie: str) -> dict:
    req = urllib.request.Request(
        SUMMARY_API_URL, headers=_headers(cookie), method="GET"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

# ─── Notification ────────────────────────────────────────────────────────────

def notify(title: str, message: str, sound: str = "Purr"):
    safe_msg = message.replace('"', '\\"').replace("'", "\\'")
    safe_title = title.replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e",
         'display notification "%s" with title "%s" sound name "%s"'
         % (safe_msg, safe_title, sound)],
        check=False,
    )
    log.info("NOTIF  %s — %s", title, message)

# ─── Formatting ──────────────────────────────────────────────────────────────

def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fK" % (n / 1_000)
    return str(n)


def _short_model(model: str) -> str:
    replacements = [
        ("claude-4-opus", "claude-4-opus"),
        ("claude-3.5-sonnet", "sonnet-3.5"),
        ("claude-3-5-sonnet", "sonnet-3.5"),
        ("claude-3.7-sonnet", "sonnet-3.7"),
        ("claude-3-7-sonnet", "sonnet-3.7"),
        ("gpt-4o-mini", "4o-mini"),
        ("gpt-4o", "gpt-4o"),
        ("gpt-4", "gpt-4"),
        ("cursor-small", "cursor-sm"),
    ]
    lower = model.lower()
    for pattern, short in replacements:
        if pattern in lower:
            return short
    return model.split("/")[-1][:20]


def event_notification(ev: dict) -> str:
    model = _short_model(ev["model"])
    inp = _fmt_tokens(ev["input"])
    out = _fmt_tokens(ev["output"])
    total = _fmt_tokens(ev["total_tokens"])
    cost = ev["cost"]

    parts = ["%s  %s" % (ev["kind"], model)]
    parts.append("%s tok (%s in / %s out)" % (total, inp, out))
    if cost > 0:
        parts.append("$%.4f" % cost)
    return " \u00b7 ".join(parts)


def summary_notification(data: dict) -> str:
    ind = data.get("individualUsage", {})
    plan = ind.get("plan", {})
    od = ind.get("onDemand", {})
    used = plan.get("used", 0)
    limit = plan.get("limit", 0)
    pct = plan.get("totalPercentUsed", 0)
    od_used = od.get("used", 0)
    parts = ["Plan: %d/%d (%.1f%%)" % (used, limit, pct)]
    if od_used:
        parts.append("On-demand: $%.2f" % od_used)
    return " \u00b7 ".join(parts)

# ─── State persistence ───────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"last_event_ts": 0, "seen_ids": []}


def save_state(state: dict):
    state["seen_ids"] = state["seen_ids"][-200:]
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ─── Main loop ───────────────────────────────────────────────────────────────

def run():
    log.info("Starting Cursor usage notifier (poll every %ds, summary every %d polls)",
             POLL_INTERVAL, SUMMARY_EVERY)

    user_id, access_token = get_credentials()
    cookie = _make_cookie(user_id, access_token)
    log.info("Credentials loaded from local Cursor DB")

    state = load_state()
    seen_ids = set(state.get("seen_ids", []))
    last_event_ts = state.get("last_event_ts", 0)
    consecutive_errors = 0
    poll_count = 0
    first_run = last_event_ts == 0

    if first_run:
        last_event_ts = int(time.time() * 1000) - 86_400_000

    while True:
        try:
            events = fetch_events(cookie, last_event_ts)
            consecutive_errors = 0

            new_events = [e for e in events if e["id"] not in seen_ids]

            if first_run:
                for e in new_events:
                    seen_ids.add(e["id"])
                    if e["ts"] > last_event_ts:
                        last_event_ts = e["ts"]
                first_run = False
                save_state({"last_event_ts": last_event_ts, "seen_ids": list(seen_ids)})
                log.info("First run: indexed %d existing events, watching for new ones", len(new_events))
            elif new_events:
                for ev in new_events:
                    msg = event_notification(ev)
                    notify("Cursor: %s" % _short_model(ev["model"]), msg)
                    seen_ids.add(ev["id"])
                    if ev["ts"] > last_event_ts:
                        last_event_ts = ev["ts"]
                save_state({"last_event_ts": last_event_ts, "seen_ids": list(seen_ids)})
            else:
                log.info("No new events")

            poll_count += 1
            if poll_count % SUMMARY_EVERY == 0:
                try:
                    summary = fetch_summary(cookie)
                    notify("Cursor Usage Summary", summary_notification(summary))
                except Exception as se:
                    log.warning("Summary fetch failed: %s", se)

        except Exception as e:
            consecutive_errors += 1
            log.error("Fetch failed (%d in a row): %s", consecutive_errors, e)

            if consecutive_errors >= 3:
                try:
                    user_id, access_token = get_credentials()
                    cookie = _make_cookie(user_id, access_token)
                    log.info("Refreshed credentials from DB")
                    consecutive_errors = 0
                except Exception as re:
                    log.error("Credential refresh also failed: %s", re)

            if consecutive_errors >= 10:
                notify("Cursor Usage Error",
                       "10 consecutive failures - check notify.log", "Basso")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Stopped by user")
    except Exception as e:
        log.critical("Fatal: %s", e)
        notify("Cursor Usage Notifier", "Fatal error: %s" % e, "Basso")
        sys.exit(1)
