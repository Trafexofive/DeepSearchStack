#!/bin/bash
# yt-lab Android Setup — run once in Termux
# Installs dependencies and configures the share handler.

echo "══ yt-lab Android Setup ══"
echo ""

# 1. Install packages
echo "→ Installing Python + curl..."
pkg update -y && pkg install -y python curl termux-api

# 2. Set up storage access
echo "→ Setting up storage..."
termux-setup-storage

# 3. Install the URL opener
mkdir -p ~/bin
cp /sdcard/yt-lab-url-opener ~/bin/termux-url-opener
chmod +x ~/bin/termux-url-opener

# 4. Create quick-share shortcuts via Termux:Widget
mkdir -p ~/.shortcuts
cat > ~/.shortcuts/yt-lab-status << 'SHORTCUT'
#!/bin/bash
curl -s http://localhost:8021/health | python3 -m json.tool
echo ""
echo "Watching channels:"
curl -s http://localhost:8021/channels/watch | python3 -c "
import sys,json
d=json.load(sys.stdin)
for ch in d.get('channels',[]):
    print(f\"  {ch.get('name','?')} — {ch.get('url','')}\")
" 2>/dev/null || echo "  (no channels watching)"
SHORTCUT
chmod +x ~/.shortcuts/yt-lab-status

cat > ~/.shortcuts/yt-lab-summarize << 'SHORTCUT'
#!/bin/bash
read -p "Paste YouTube URL: " url
~/bin/termux-url-opener "$url"
SHORTCUT
chmod +x ~/.shortcuts/yt-lab-summarize

echo ""
echo "✅ Setup complete!"
echo ""
echo "How to use:"
echo "  1. YouTube app → Share → Termux → auto-summarizes"
echo "  2. Termux home: add 'yt-lab-status' widget for dashboard"
echo "  3. Run '~/bin/termux-url-opener <url>' manually"
echo ""
echo "Host setup (run on your PC):"
echo "  adb reverse tcp:8020 tcp:8020"
echo "  adb reverse tcp:8021 tcp:8021"
echo "  make up yt-lab"
echo ""
echo "Enjoy. 🎬"
