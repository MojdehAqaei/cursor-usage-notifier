# Cursor Usage Notifier

Get a native macOS notification **after every Cursor AI request** showing the model, token count, and cost.

Also sends periodic usage summaries with plan quota and on-demand spend.

## What You Get

**Per-request notifications:**
- `chat  sonnet-3.7 · 12.4K tok (8.1K in / 4.3K out) · $0.0234`
- `agent_edit  gpt-4o · 3.2K tok (2.1K in / 1.1K out) · $0.0089`

**Periodic summaries (every ~10 min by default):**
- `Plan: 142/500 (28.4%) · On-demand: $2.30`

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

You'll get a notification after your next Cursor request.

### 3. (Optional) Tune the intervals

| Variable | Default | What it does |
|----------|---------|-------------|
| `CURSOR_NOTIFY_INTERVAL` | `15` | Seconds between polls for new events |
| `CURSOR_SUMMARY_EVERY` | `40` | Number of polls between usage summaries (~10 min at default) |

Set them before running setup:

```bash
CURSOR_NOTIFY_INTERVAL=10 CURSOR_SUMMARY_EVERY=60 ./setup.sh
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
│  (runs via launchd)          │──── polls every 15s
└──────────────┬───────────────┘
               │ POST cursor.com/api/dashboard/get-filtered-usage-events
               │ Cookie: WorkosCursorSessionToken=...
               ▼
┌──────────────────────────────┐
│  Cursor Events API           │
│  → per-request: model,       │
│    in/out/cache tokens, cost │
└──────────────┬───────────────┘
               │ new events? (compare IDs with .usage_state.json)
               ▼
        ┌──────────────┐
        │ osascript     │ ← macOS Notification Center
        │ display notif │
        └──────────────┘
```

1. **Credentials** are read from Cursor's local SQLite database — no manual token copying.
2. **Events API** returns individual requests with model, token breakdown (input / output / cache read / cache write), and cost in cents.
3. **Deduplication** tracks seen event IDs in `.usage_state.json`. On first run it indexes existing events silently, then only notifies on new ones.
4. **Summary** periodically calls `/api/usage-summary` for plan quota and on-demand totals.
5. **Auto-recovery** re-reads credentials from the DB if the token rotates.

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
├── .usage_state.json        # Last-seen event IDs + timestamp
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
