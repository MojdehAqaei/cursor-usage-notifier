#!/bin/bash
set -e

LABEL="com.cursor.usage-notify"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/cursor_usage_notify.py"
PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
POLL_INTERVAL="${CURSOR_NOTIFY_INTERVAL:-15}"
SUMMARY_EVERY="${CURSOR_SUMMARY_EVERY:-40}"

# ─── Helpers ──────────────────────────────────────────────────────────────────

red()   { printf '\033[1;31m%s\033[0m\n' "$*"; }
green() { printf '\033[1;32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[0;90m%s\033[0m\n' "$*"; }

fail() { red "✗ $*"; exit 1; }

# ─── Preflight checks ────────────────────────────────────────────────────────

echo ""
echo "══════════════════════════════════════════════"
echo "  Cursor Usage Notifier — Setup"
echo "══════════════════════════════════════════════"
echo ""

# macOS only
[[ "$(uname)" == "Darwin" ]] || fail "This tool only supports macOS."

# Python 3
PYTHON="$(command -v python3 2>/dev/null)" || fail "python3 not found. Install Xcode CLT: xcode-select --install"
echo "  python3 ........... $PYTHON ($($PYTHON --version 2>&1))"

# Cursor installed & logged in
CURSOR_DB="$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb"
[[ -f "$CURSOR_DB" ]] || fail "Cursor database not found at:\n  $CURSOR_DB\n  Is Cursor installed?"

$PYTHON -c "
import sqlite3, json, sys
from pathlib import Path
db = Path.home() / 'Library/Application Support/Cursor/User/globalStorage/state.vscdb'
conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
tok = conn.execute(\"SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'\").fetchone()
conn.close()
if not tok:
    print('  credentials ....... NOT FOUND', file=sys.stderr)
    sys.exit(1)
print('  credentials ....... ok')
" || fail "No Cursor credentials found. Open Cursor and sign in first."

echo "  script ............ $SCRIPT_PATH"
echo ""

# ─── Unload existing agent ────────────────────────────────────────────────────

if launchctl list 2>/dev/null | grep -q "$LABEL"; then
    dim "→ Stopping existing agent..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# ─── Generate plist ───────────────────────────────────────────────────────────

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>${SCRIPT_PATH}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>${SCRIPT_DIR}/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${SCRIPT_DIR}/launchd_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>CURSOR_NOTIFY_INTERVAL</key>
        <string>${POLL_INTERVAL}</string>
        <key>CURSOR_SUMMARY_EVERY</key>
        <string>${SUMMARY_EVERY}</string>
    </dict>
</dict>
</plist>
PLIST

dim "→ Generated plist at $PLIST_DST"

# ─── Load agent ───────────────────────────────────────────────────────────────

launchctl load "$PLIST_DST"

echo ""
green "✓ Cursor Usage Notifier is running!"
echo ""
echo "  Poll interval : every ${POLL_INTERVAL}s  (set CURSOR_NOTIFY_INTERVAL before setup to change)"
echo "  Summary every : ${SUMMARY_EVERY} polls (~$((POLL_INTERVAL * SUMMARY_EVERY / 60)) min)"
echo "  Logs          : $SCRIPT_DIR/notify.log"
echo "  LaunchAgent   : $PLIST_DST"
echo ""
echo "  Manage:"
echo "    Stop    →  launchctl unload ~/Library/LaunchAgents/${LABEL}.plist"
echo "    Start   →  launchctl load   ~/Library/LaunchAgents/${LABEL}.plist"
echo "    Uninstall → $SCRIPT_DIR/uninstall.sh"
echo ""
