"""Upload generated Poland short to YouTube via Data API v3.

Required env vars (store as GitHub Secrets):
  YOUTUBE_CLIENT_ID      — OAuth2 client ID from Google Cloud Console
  YOUTUBE_CLIENT_SECRET  — OAuth2 client secret
  YOUTUBE_REFRESH_TOKEN  — refresh token obtained via one-time auth flow

Optional:
  YOUTUBE_PRIVACY        — public / unlisted / private (default: public)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

BUILD_DIR = Path("build")
VIDEO_PATH = BUILD_DIR / "output_poland_short.mp4"
METADATA_PATH = BUILD_DIR / "metadata.json"
THUMBNAIL_PATH = BUILD_DIR / "thumbnail.jpg"

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"

MAX_UPLOAD_RETRIES = 3


def _get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange refresh token for a short-lived access token."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in OAuth response (check YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN)")
    return token


def _load_metadata() -> dict:
    """Load title/description/tags from metadata.json."""
    if METADATA_PATH.is_file():
        data = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        return {
            "title": data.get("title", "Я в Польше #shorts")[:100],
            "description": data.get("description", "#польша #явпольше #shorts"),
            "tags": data.get("tags", ["польша", "явпольше", "shorts"]),
            "topic": data.get("topic", ""),
        }
    return {
        "title": "Я в Польше: советы и лайфхаки #shorts",
        "description": "Смотри до конца! #польша #явпольше #shorts",
        "tags": ["польша", "явпольше", "shorts"],
        "topic": "",
    }


def upload_video() -> str:
    """Upload video to YouTube. Returns video ID."""
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        print("[SKIP] YouTube upload: missing credentials (YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN)")
        return ""

    if not VIDEO_PATH.is_file():
        print(f"[ERROR] Video not found: {VIDEO_PATH}")
        return ""

    privacy = os.getenv("YOUTUBE_PRIVACY", "public")
    if privacy not in ("public", "unlisted", "private"):
        privacy = "public"

    meta = _load_metadata()
    print(f"  Title: {meta['title']}")
    print(f"  Privacy: {privacy}")
    print(f"  Tags: {', '.join(meta['tags'])}")

    print("  Obtaining access token...")
    access_token = _get_access_token(client_id, client_secret, refresh_token)

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": "19",  # Travel & Events
            "defaultLanguage": "ru",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    print("  Initiating upload...")
    video_data = VIDEO_PATH.read_bytes()
    video_size = len(video_data)
    init_resp = requests.post(
        UPLOAD_URL,
        params={
            "uploadType": "resumable",
            "part": "snippet,status",
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=body,
        timeout=30,
    )
    if not init_resp.ok:
        print(f"[ERROR] Upload init failed ({init_resp.status_code})")
        init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    print(f"  Uploading {video_size / 1024 / 1024:.1f} MB...")
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            upload_resp = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video_size),
                },
                data=video_data,
                timeout=600,
            )
            upload_resp.raise_for_status()
            video_id = upload_resp.json().get("id", "")
            print(f"  Uploaded! https://youtube.com/shorts/{video_id}")
            # Set custom thumbnail
            _try_set_thumbnail(video_id, access_token)
            try:
                from analytics import log_upload
                meta = _load_metadata()
                log_upload(video_id, meta["title"], meta.get("topic", ""), meta["tags"])
            except Exception as exc:
                print(f"[WARN] Analytics log failed: {exc}")
            return video_id
        except Exception as exc:
            print(f"[WARN] Upload attempt {attempt}/{MAX_UPLOAD_RETRIES} failed: {exc}")
            if attempt < MAX_UPLOAD_RETRIES:
                wait = attempt * 10
                print(f"  Retrying in {wait}s...")
                time.sleep(wait)

    print("[ERROR] All upload attempts failed.")
    return ""


def _try_set_thumbnail(video_id: str, access_token: str) -> None:
    """Upload custom thumbnail if it exists. Non-fatal on failure."""
    thumb = THUMBNAIL_PATH
    if not thumb.is_file():
        print("[THUMB] No thumbnail file found, skipping")
        return

    thumb_data = thumb.read_bytes()
    print(f"  Setting thumbnail ({len(thumb_data) / 1024:.0f} KB)...")

    for attempt in range(1, 4):
        try:
            resp = requests.post(
                THUMBNAIL_URL,
                params={"videoId": video_id},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "image/jpeg",
                    "Content-Length": str(len(thumb_data)),
                },
                data=thumb_data,
                timeout=60,
            )
            resp.raise_for_status()
            print("  Thumbnail set!")
            return
        except Exception as exc:
            print(f"[WARN] Thumbnail attempt {attempt}/3 failed: {exc}")
            if attempt < 3:
                time.sleep(attempt * 3)

    print("[WARN] Could not set thumbnail, video uploaded without it")


if __name__ == "__main__":
    vid = upload_video()
    if not vid:
        print("Upload failed.")
        sys.exit(1)
