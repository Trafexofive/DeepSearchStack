# yt-lab Android Client

Share YouTube links from your phone → auto-summarize via yt-lab.

## Architecture

```
Phone (Termux)                    Host (PC)
─────────────────────────────────────────────
YouTube App → Share → Termux
                        │
                  termux-url-opener
                        │
                  curl localhost:8021 ──ADB reverse──→ yt-lab :8021
                                                          │
                                                     yt-extractor :8020
                                                     inference-gateway
                                                        │
                                                  Summary → notification
```

## One-time setup

**On phone (Termux):**
```bash
bash /sdcard/yt-lab-setup.sh
```

**On host:**
```bash
./clients/android/quick-start.sh
```

## Daily use

1. **Video**: YouTube app → Share → Termux → auto-extracts transcript + summarizes
2. **Channel**: Share a channel URL → ingests latest 10 videos
3. **Watch**: Share with "watch" intent → adds channel to watch list
4. **Widget**: Add Termux:Widget to home screen → tap "yt-lab-status" for dashboard
5. **Manual**: `~/bin/termux-url-opener <youtube-url>` in Termux

## Requirements

- Termux + Termux:API from F-Droid
- ADB on host
- yt-lab stack running
