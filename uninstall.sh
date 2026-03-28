#!/bin/bash
set -e

LABEL="com.cursor.usage-notify"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

echo ""
echo "══════════════════════════════════════════════"
echo "  Cursor Usage Notifier — Uninstall"
echo "══════════════════════════════════════════════"
echo ""

if launchctl list 2>/dev/null | grep -q "$LABEL"; then
    echo "→ Stopping agent..."
    launchctl unload "$PLIST" 2>/dev/null || true
fi

if [[ -f "$PLIST" ]]; then
    echo "→ Removing LaunchAgent plist..."
    rm -f "$PLIST"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "→ Cleaning runtime files..."
rm -f "$SCRIPT_DIR/.usage_state.json"
rm -f "$SCRIPT_DIR/notify.log"
rm -f "$SCRIPT_DIR/launchd_stdout.log"
rm -f "$SCRIPT_DIR/launchd_stderr.log"

echo ""
echo "✓ Uninstalled. Source files in $SCRIPT_DIR are untouched."
echo "  To fully remove, delete the directory:"
echo "    rm -rf $SCRIPT_DIR"
echo ""
