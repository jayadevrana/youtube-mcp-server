"""
OAuth + Google API client helpers for the YouTube MCP server.

Two APIs are used:
  - YouTube Data API v3      -> uploads, metadata, thumbnails
  - YouTube Analytics API v2 -> views, watch time, impressions, CTR

Credentials flow:
  1. authorize.py runs the one-time consent (opens a browser, you approve).
     It writes a refresh token to YOUTUBE_TOKEN_PATH.
  2. Everything after that (server.py, ab_rotate.py) loads that token and
     silently refreshes the short-lived access token as needed.

The token file is a SECRET (it grants ongoing access to your channel). It is
stored off the exFAT drive by default and is git-ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

# Scopes: upload + full manage (metadata/thumbnails) + analytics read.
# force-ssl is what thumbnails.set actually requires.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()


def token_path() -> Path:
    raw = os.environ.get("YOUTUBE_TOKEN_PATH", "~/.local/share/youtube-mcp/token.json")
    return Path(os.path.expanduser(raw))


def state_dir() -> Path:
    raw = os.environ.get("YOUTUBE_STATE_DIR", "~/.local/share/youtube-mcp")
    p = Path(os.path.expanduser(raw))
    p.mkdir(parents=True, exist_ok=True)
    return p


def client_config() -> dict:
    """The installed-app client config, built from env (no client_secret.json file)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET not set. "
            "Copy .env.example to .env and fill them in."
        )
    return {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def load_credentials() -> Credentials:
    """Load stored creds and refresh if expired. Raises if not yet authorized."""
    tp = token_path()
    if not tp.exists():
        raise RuntimeError(
            f"No token at {tp}. Run:  ./run.sh authorize   (one-time browser consent)."
        )
    creds = Credentials.from_authorized_user_file(str(tp), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        else:
            raise RuntimeError(
                "Stored credentials are invalid and cannot be refreshed. "
                "Re-run:  ./run.sh authorize"
            )
    return creds


def youtube_data():
    """YouTube Data API v3 client."""
    return build("youtube", "v3", credentials=load_credentials(), cache_discovery=False)


def youtube_analytics():
    """YouTube Analytics API v2 client."""
    return build(
        "youtubeAnalytics", "v2", credentials=load_credentials(), cache_discovery=False
    )
