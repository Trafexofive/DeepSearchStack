#!/bin/bash
# yt-lab Android Quick Start — run from host PC
# Boots yt-lab, sets up ADB reverse, pushes setup to phone.

set -e
cd "$(dirname "$0")/../.."

echo "══ yt-lab Android Quick Start ══"
echo ""

# 1. Boot yt-lab if not running
if ! curl -s http://localhost:8021/health > /dev/null 2>&1; then
    echo "→ Booting yt-lab..."
    make up yt-lab
    sleep 3
else
    echo "→ yt-lab already running"
fi

# 2. Set up ADB reverse
echo "→ Setting up ADB reverse..."
adb reverse tcp:8020 tcp:8020 2>/dev/null || echo "  (8020 already forwarded)"
adb reverse tcp:8021 tcp:8021 2>/dev/null || echo "  (8021 already forwarded)"
adb reverse --list

# 3. Push scripts to phone
echo "→ Pushing scripts to phone..."
adb push clients/android/termux-url-opener /sdcard/yt-lab-url-opener
adb push clients/android/setup.sh /sdcard/yt-lab-setup.sh

echo ""
echo "✅ Host side ready."
echo ""
echo "On your phone, open Termux and run:"
echo "  bash /sdcard/yt-lab-setup.sh"
echo ""
echo "Then share any YouTube video → Termux → auto-summarized."
