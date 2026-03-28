# Cursor Usage Notifier

Get native macOS notifications every time your Cursor AI token usage changes.

Monitors plan requests, on-demand spend, quota warnings, and billing cycle resets — all running silently in the background.

## What You Get

- **Real-time usage deltas** — "Plan +3 → 142/500 (28.4%)"
- **On-demand cost tracking** — "On-demand +$0.45 → $2.30"
- **Quota warnings** — alerts at 90% and when the plan is fully exhausted
- **Billing cycle resets** — notifies you when a new cycle starts
- **Auto-recovery** — re-reads credentials if the token rotates, retries on transient failures

## Prerequisites

| Requirement | Check |
|-------------|-------|
| macOS | Any recent version (Ventura, Sonoma, Sequoia) |
| Python 3 | Pre-installed on macOS. Verify: `python3 --version` |
| Cursor | Installed and **signed in** to your account |

> No `pip install`, no `brew`, no external dependencies — stdlib only.

## Setup (any Mac, 30 seconds)

### 1. Get the files onto the machine

**Option A — Git clone:**

```bash
git clone https://github.com/MojdehAqaei/cursor-usage-notifier.git ~/cursor-usage-notifier
```

**Option B — Copy manually:**

```bash
scp -r cursor-usage-notifier/ you@other-mac:~/cursor-usage-notifier/
```

**Option C — AirDrop / USB / iCloud Drive:**

Just put the `cursor-usage-notifier` folder anywhere you like (your home directory is conventional).

### 2. Run setup

```bash
cd ~/cursor-usage-notifier
chmod +x setup.sh uninstall.sh cursor_usage_notify.py
./setup.sh
```

That's it. The setup script will:

1. Verify Python 3 is available
2. Verify Cursor is installed and you're signed in
3. Generate a LaunchAgent plist with correct paths for *this* machine
4. Register it with `launchctl` so it starts now and on every login

You should see a macOS notification within ~2 minutes with your current usage snapshot.

### 3. (Optional) Change the polling interval

Default is every **120 seconds**. To change it, set the environment variable before running setup:

```bash
CURSOR_NOTIFY_INTERVAL=60 ./setup.sh
```

## Managing the Service

| Action | Command |
|--------|--------|
| **Stop** | `launchctl unload ~/Library/LaunchAgents/com.cursor.usage-notify.plist` |
| **Start** | `launchctl load ~/Library/LaunchAgents/com.cursor.usage-notify.plist` |
| **Restart** | Stop, then Start |
| **View logs** | `tail -f ~/cursor-usage-notifier/notify.log` |
| **Check status** | `launchctl list \| grep cursor` |
| **Uninstall** | `~/cursor-usage-notifier/uninstall.sh` |

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  Cursor IDE (local)                                 │
│  ~/Library/.../state.vscdb  ←── credentials live    │
└──────────────┬──────────────────────────────────────┘
               │ reads userId + accessToken
               ▼
┌──────────────────────────────┐
│  cursor_usage_notify.py      │
│  (runs via launchd)          │──── polls every N sec
└──────────────┬───────────────┘
               │ GET cursor.com/api/usage-summary
               │ Cookie: WorkosCursorSessionToken=...
               ▼
┌──────────────────────────────┐
│  Cursor API                  │
│  → plan used / limit / %     │
│  → on-demand spend           │
│  → billing cycle dates       │
└──────────────┬───────────────┘
               │ compare with .usage_state.json
               ▼
        ┌──────────────┐
        │ osascript     │ ← macOS Notification Center
        │ display notif │
        └──────────────┘
```

1. **Credentials** are read directly from Cursor's local SQLite database — no manual token copying.
2. **Session token** is constructed as `userId::accessToken` and sent as the `WorkosCursorSessionToken` cookie.
3. **Diffing** compares the current API response against the last saved state (`.usage_state.json`). Only fires a notification when something actually changes.
4. **Notifications** use the built-in `osascript` / Notification Center — no extra apps needed.

## Files

```
cursor-usage-notifier/
├── cursor_usage_notify.py   # Main script (the only thing that runs)
├── setup.sh                 # One-command installer — generates plist, registers agent
├── uninstall.sh             # Clean removal of agent + runtime files
├── .gitignore               # Excludes runtime/generated files
├── README.md                # This file
│
│  ── generated at runtime ──
├── .usage_state.json        # Last-known usage (diffing baseline)
├── notify.log               # Application log
├── launchd_stdout.log       # launchd stdout capture
└── launchd_stderr.log       # launchd stderr capture
```

## Troubleshooting

**"Cursor database not found"**
→ Cursor isn't installed, or it's installed in a non-default location.
   Standard path: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`

**"No Cursor credentials found"**
→ Open Cursor and sign in to your account. The credentials are written to the database on login.

**No notifications appearing**
→ Check macOS **System Settings → Notifications → Script Editor** and ensure notifications are allowed.
→ Check the log: `tail -20 ~/cursor-usage-notifier/notify.log`

**"10 consecutive failures" notification**
→ Likely an expired/rotated token. Restarting Cursor usually refreshes it. Then restart the agent:
```bash
launchctl unload ~/Library/LaunchAgents/com.cursor.usage-notify.plist
launchctl load  ~/Library/LaunchAgents/com.cursor.usage-notify.plist
```

**Want to move the folder somewhere else?**
→ Move it, then re-run `./setup.sh` from the new location. The plist is regenerated with the correct paths.
