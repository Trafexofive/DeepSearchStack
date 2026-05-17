#!/usr/bin/env python3
"""dss-yt — YouTube ingest for DeepSearchStack warehouse.

Host-side CLI (not Docker — YouTube blocks data center IPs).
Uses yt-dlp for transcript + metadata extraction.
Stores transcripts in warehouse via SDK.

Dependencies:
    pip install yt-dlp

Usage:
    python3 scripts/dss-yt.py video https://www.youtube.com/watch?v=VIDEO_ID
    python3 scripts/dss-yt.py channel https://www.youtube.com/@Channel --limit 10
    python3 scripts/dss-yt.py playlist https://www.youtube.com/playlist?list=ID --limit 20
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


def check_ytdlp() -> bool:
    """Check if yt-dlp is available."""
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def extract_video(url: str) -> dict | None:
    """Extract metadata + transcript for a single video via yt-dlp."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--write-subs", "--write-auto-subs",
            "--sub-lang", "en",
            "--convert-subs", "srt",
            "--skip-download",
            "--print", "after_move:%(infojson_filename)s",
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            url,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            print("  ⚠ yt-dlp timed out")
            return None

        if result.returncode != 0:
            print(f"  ⚠ yt-dlp failed: {result.stderr[:200]}")
            return None

        # Find the info.json file
        info_files = list(Path(tmpdir).glob("*.info.json"))
        if not info_files:
            print("  ⚠ No metadata extracted")
            return None

        with open(info_files[0]) as f:
            info = json.load(f)

        # Find transcript file (srt or vtt)
        subtitle_files = list(Path(tmpdir).glob("*.en.srt")) + \
                         list(Path(tmpdir).glob("*.en.vtt")) + \
                         list(Path(tmpdir).glob("*.srt")) + \
                         list(Path(tmpdir).glob("*.vtt"))

        transcript = ""
        if subtitle_files:
            transcript = subtitle_files[0].read_text(errors='replace')
            # Strip SRT timestamps to get plain text
            transcript = _strip_srt_timestamps(transcript)

        return {
            "url": info.get("webpage_url", url),
            "title": info.get("title", ""),
            "channel": info.get("channel") or info.get("uploader", ""),
            "description": info.get("description", "")[:2000],
            "duration": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "view_count": info.get("view_count", 0),
            "transcript": transcript,
            "language": info.get("language") or "en",
            "tags": info.get("tags", []),
        }


def _strip_srt_timestamps(text: str) -> str:
    """Remove SRT timestamps and index numbers, keep only text."""
    import re
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        # Skip empty lines, index numbers, and timestamps
        if not line or line.isdigit():
            continue
        if re.match(r'\d{2}:\d{2}:\d{2}[,.]\d{3}', line):
            continue
        # Remove HTML tags from VTT
        line = re.sub(r'<[^>]+>', '', line)
        cleaned.append(line)
    return '\n'.join(cleaned)


def list_channel_videos(channel_url: str, limit: int = 10) -> list[str]:
    """List video URLs from a channel."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "webpage_url",
             "--playlist-end", str(limit), channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"  ⚠ Channel listing failed: {result.stderr[:200]}")
            return []
        urls = [line.strip() for line in result.stdout.split('\n') if line.strip().startswith('http')]
        return urls
    except Exception as e:
        print(f"  ⚠ Channel listing error: {e}")
        return []


def list_playlist_videos(playlist_url: str, limit: int = 20) -> list[str]:
    """List video URLs from a playlist."""
    return list_channel_videos(playlist_url, limit)  # same yt-dlp call


async def ingest_video(dss: DSSClient, data: dict) -> bool:
    """Store video transcript + metadata in warehouse."""
    if not data.get("transcript"):
        print(f"  ⚠ No transcript — skipping: {data['title'][:60]}")
        return False

    payload = {
        "url": data["url"],
        "markdown": f"Channel: {data['channel']}\nDuration: {data['duration']}s\nViews: {data['view_count']}\nUploaded: {data['upload_date']}\n\n{data['transcript']}",
        "title": data["title"],
        "author": data["channel"],
        "published": data.get("upload_date", ""),
        "language": data.get("language", "en"),
        "word_count": len(data["transcript"].split()),
        "source_domain": "youtube.com",
        "tags": ["youtube", data["channel"]],
    }

    try:
        async with dss.client as client:
            resp = await client.post(
                f"{dss.warehouse}/ingest",
                json=payload,
                timeout=httpx.Timeout(10.0),
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("ingested"):
                    print(f"  ✓ {data['title'][:60]}")
                    return True
    except Exception as e:
        pass

    print(f"  ✗ warehouse ingest failed: {data['title'][:60]}")
    return False


# ── Commands ───────────────────────────────────────────────────

async def cmd_video(dss: DSSClient, url: str):
    print(f"YouTube: {url}")
    data = extract_video(url)
    if not data:
        print("  ✗ Extraction failed")
        return
    print(f"  Title: {data['title']}")
    print(f"  Channel: {data['channel']}")
    print(f"  Transcript: {len(data['transcript'])} chars, ~{len(data['transcript'].split())} words")
    ok = await ingest_video(dss, data)
    if ok:
        # Also try to crawl the actual YouTube page for comments/description
        try:
            async with dss.client as client:
                await client.post(
                    f"{dss.web_api}/api/ingest/urls",
                    json={"urls": [url]},
                    timeout=httpx.Timeout(30.0),
                )
        except Exception:
            pass


async def cmd_channel(dss: DSSClient, url: str, limit: int = 10):
    print(f"Channel: {url} (limit={limit})")
    urls = list_channel_videos(url, limit)
    print(f"  Found {len(urls)} videos")
    ok = 0
    for i, video_url in enumerate(urls, 1):
        print(f"\n  [{i}/{len(urls)}] {video_url}")
        data = extract_video(video_url)
        if data and await ingest_video(dss, data):
            ok += 1
    print(f"\nDone: {ok}/{len(urls)} ingested")


async def cmd_playlist(dss: DSSClient, url: str, limit: int = 20):
    await cmd_channel(dss, url, limit)


async def main():
    if not check_ytdlp():
        print("Error: yt-dlp not found. Install with: pip install yt-dlp")
        sys.exit(1)

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    url = sys.argv[2]
    limit = 10
    for i, arg in enumerate(sys.argv):
        if arg == '--limit' and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    async with DSSClient() as dss:
        if cmd == 'video':
            await cmd_video(dss, url)
        elif cmd == 'channel':
            await cmd_channel(dss, url, limit)
        elif cmd == 'playlist':
            await cmd_playlist(dss, url, limit)
        else:
            print(f"Unknown command: {cmd}")
            print(__doc__)


if __name__ == "__main__":
    import httpx
    asyncio.run(main())
