"""
YouTube MCP server.

Exposes YouTube channel operations as MCP tools:

  Identity / listing
    - youtube_whoami          : channel id, title, verification + upload eligibility
    - youtube_list_uploads    : recent uploads with video ids (needed for edits)

  Publishing
    - youtube_upload          : resumable upload of a local video file
    - youtube_update_metadata : edit title / description / tags / category / privacy
    - youtube_set_thumbnail   : set a custom thumbnail

  Pseudo A/B thumbnails  (native A/B "Test & Compare" is NOT in the public API,
                          so this rotates thumbnails on a ledger and compares
                          views-per-window; see the honest caveat in each tool)
    - youtube_ab_start        : define variants, set the first, open window 0
    - youtube_ab_rotate       : close current window, set the next variant
    - youtube_ab_report       : compare variants by views / watch-time per window

  Analytics
    - youtube_analytics       : views, watch time, avg view %, subs, etc. for a video

Auth: run  ./run.sh authorize  once (browser consent) to mint a refresh token.

Honest limitations (enforced by the YouTube API, not by this code):
  * Native thumbnail/title A/B "Test & Compare" has no public API endpoint.
  * Impressions and impression click-through-rate (CTR) are NOT exposed by the
    YouTube Analytics API — Studio-only. So A/B comparison here uses views gained
    per equal-length window as a CTR proxy, plus averageViewPercentage.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP

from auth import state_dir, youtube_analytics, youtube_data

mcp = FastMCP("youtube")

# --- small helpers -----------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ab_ledger_path():
    return state_dir() / "ab_tests.json"


def _load_ledger() -> dict:
    p = _ab_ledger_path()
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save_ledger(data: dict) -> None:
    _ab_ledger_path().write_text(json.dumps(data, indent=2))


def _my_channel_id(yt) -> str:
    resp = yt.channels().list(part="id", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for the authorized account.")
    return items[0]["id"]


# --- identity / listing ------------------------------------------------------


@mcp.tool()
def youtube_whoami() -> str:
    """Return the authorized channel's id, title, subscriber/video counts, and
    whether custom thumbnails are allowed (channel must be phone-verified)."""
    yt = youtube_data()
    resp = (
        yt.channels()
        .list(part="id,snippet,statistics,status", mine=True)
        .execute()
    )
    items = resp.get("items", [])
    if not items:
        return "No channel found for the authorized Google account."
    c = items[0]
    snip, stats, status = c["snippet"], c.get("statistics", {}), c.get("status", {})
    out = {
        "channel_id": c["id"],
        "title": snip.get("title"),
        "subscribers": stats.get("subscriberCount"),
        "total_views": stats.get("viewCount"),
        "video_count": stats.get("videoCount"),
        "custom_thumbnails_allowed": status.get("isLinked", False),
        "note": "Custom thumbnails require a verified channel (youtube.com/verify).",
    }
    return json.dumps(out, indent=2)


@mcp.tool()
def youtube_list_uploads(max_results: int = 10) -> str:
    """List the channel's most recent uploads with their video ids, titles,
    privacy status and publish time. Use the ids with the edit/analytics tools."""
    yt = youtube_data()
    ch = (
        yt.channels()
        .list(part="contentDetails", mine=True)
        .execute()["items"][0]
    )
    uploads_playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    resp = (
        yt.playlistItems()
        .list(
            part="snippet,contentDetails,status",
            playlistId=uploads_playlist,
            maxResults=min(max(max_results, 1), 50),
        )
        .execute()
    )
    videos = []
    for it in resp.get("items", []):
        videos.append(
            {
                "video_id": it["contentDetails"]["videoId"],
                "title": it["snippet"]["title"],
                "published_at": it["contentDetails"].get("videoPublishedAt"),
                "privacy": it.get("status", {}).get("privacyStatus"),
            }
        )
    return json.dumps(videos, indent=2)


# --- publishing --------------------------------------------------------------


@mcp.tool()
def youtube_upload(
    file_path: str,
    title: str,
    description: str = "",
    tags: Optional[list[str]] = None,
    category_id: str = "22",
    privacy: str = "private",
    publish_at: Optional[str] = None,
    made_for_kids: bool = False,
    thumbnail_path: Optional[str] = None,
) -> str:
    """Upload a local video file (resumable).

    file_path     : absolute path to the .mp4/.mov file.
    category_id   : YouTube category id (22=People/Blogs, 24=Entertainment,
                    27=Education, 28=Science/Tech, 20=Gaming, 10=Music).
    privacy       : 'private' | 'unlisted' | 'public'.
    publish_at    : ISO 8601 UTC time to auto-publish (implies privacy='private'
                    until then), e.g. '2026-07-15T09:00:00Z'. Optional.
    thumbnail_path: optional image to set right after upload.
    """
    from googleapiclient.http import MediaFileUpload

    if not os.path.isfile(file_path):
        return f"Error: file not found: {file_path}"

    yt = youtube_data()
    status: dict = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": made_for_kids,
    }
    if publish_at:
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": status,
    }

    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    result = {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "privacy": status["privacyStatus"]}
    if publish_at:
        result["scheduled_publish"] = publish_at

    if thumbnail_path:
        try:
            _set_thumb(yt, video_id, thumbnail_path)
            result["thumbnail"] = "set"
        except Exception as e:  # noqa: BLE001
            result["thumbnail_error"] = str(e)

    return json.dumps(result, indent=2)


@mcp.tool()
def youtube_update_metadata(
    video_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category_id: Optional[str] = None,
    privacy: Optional[str] = None,
) -> str:
    """Edit an existing video's metadata. Only the fields you pass change; the
    rest are preserved (the API requires sending the full snippet, so this reads
    the current values first and merges)."""
    yt = youtube_data()
    cur = yt.videos().list(part="snippet,status", id=video_id).execute().get("items", [])
    if not cur:
        return f"Error: no video with id {video_id}"
    snippet = cur[0]["snippet"]
    status = cur[0]["status"]

    if title is not None:
        snippet["title"] = title
    if description is not None:
        snippet["description"] = description
    if tags is not None:
        snippet["tags"] = tags
    if category_id is not None:
        snippet["categoryId"] = category_id
    if privacy is not None:
        status["privacyStatus"] = privacy

    body = {"id": video_id, "snippet": snippet, "status": status}
    yt.videos().update(part="snippet,status", body=body).execute()
    return json.dumps({"video_id": video_id, "updated": True}, indent=2)


def _set_thumb(yt, video_id: str, image_path: str) -> None:
    from googleapiclient.http import MediaFileUpload

    if not os.path.isfile(image_path):
        raise FileNotFoundError(image_path)
    media = MediaFileUpload(image_path, resumable=False)
    yt.thumbnails().set(videoId=video_id, media_body=media).execute()


@mcp.tool()
def youtube_set_thumbnail(video_id: str, image_path: str) -> str:
    """Set a custom thumbnail (JPG/PNG, <2MB, 1280x720 recommended). Channel must
    be verified for custom thumbnails to be accepted."""
    yt = youtube_data()
    try:
        _set_thumb(yt, video_id, image_path)
    except Exception as e:  # noqa: BLE001
        return f"Error setting thumbnail: {e}"
    return json.dumps({"video_id": video_id, "thumbnail": "set"}, indent=2)


# --- pseudo A/B thumbnails ---------------------------------------------------


@mcp.tool()
def youtube_ab_start(video_id: str, variant_paths: list[str], hours_per_variant: int = 48) -> str:
    """Begin a pseudo thumbnail A/B test.

    Records a ledger of the variant image paths, sets the FIRST variant live now,
    and opens window 0. Call youtube_ab_rotate when a window ends (or schedule
    ab_rotate.py via launchd/cron) to advance to the next variant.

    CAVEAT: YouTube's native thumbnail A/B ("Test & Compare") has no public API,
    and impressions/CTR are not exposed by the Analytics API. This measures views
    gained per equal-length window as a CTR proxy, so use windows >= 24h and keep
    all other variables constant. Not a statistically rigorous split test.
    """
    if len(variant_paths) < 2:
        return "Error: need at least 2 variant image paths to A/B test."
    for p in variant_paths:
        if not os.path.isfile(p):
            return f"Error: variant image not found: {p}"

    yt = youtube_data()
    try:
        _set_thumb(yt, video_id, variant_paths[0])
    except Exception as e:  # noqa: BLE001
        return f"Error setting first variant: {e}"

    ledger = _load_ledger()
    ledger[video_id] = {
        "hours_per_variant": hours_per_variant,
        "current_index": 0,
        "variants": [{"path": p, "label": f"V{i}"} for i, p in enumerate(variant_paths)],
        "windows": [{"index": 0, "label": "V0", "path": variant_paths[0], "started_at": _now_iso(), "ended_at": None}],
    }
    _save_ledger(ledger)
    return json.dumps(
        {
            "video_id": video_id,
            "test_started": True,
            "live_variant": "V0",
            "total_variants": len(variant_paths),
            "hours_per_variant": hours_per_variant,
            "next": "Call youtube_ab_rotate after this window, or schedule ab_rotate.py.",
        },
        indent=2,
    )


@mcp.tool()
def youtube_ab_rotate(video_id: str) -> str:
    """Advance a running A/B test to the next variant: closes the current window
    and sets the next thumbnail live. Wraps back to V0 after the last variant so
    you can gather multiple rounds. Returns which variant is now live."""
    ledger = _load_ledger()
    test = ledger.get(video_id)
    if not test:
        return f"Error: no A/B test running for {video_id}. Call youtube_ab_start first."

    # close current window
    for w in test["windows"]:
        if w["ended_at"] is None:
            w["ended_at"] = _now_iso()

    next_index = (test["current_index"] + 1) % len(test["variants"])
    variant = test["variants"][next_index]

    yt = youtube_data()
    try:
        _set_thumb(yt, video_id, variant["path"])
    except Exception as e:  # noqa: BLE001
        return f"Error setting variant {variant['label']}: {e}"

    test["current_index"] = next_index
    test["windows"].append(
        {
            "index": next_index,
            "label": variant["label"],
            "path": variant["path"],
            "started_at": _now_iso(),
            "ended_at": None,
        }
    )
    _save_ledger(ledger)
    return json.dumps({"video_id": video_id, "now_live": variant["label"], "window": len(test["windows"])}, indent=2)


@mcp.tool()
def youtube_ab_report(video_id: str) -> str:
    """Compare A/B variants by views gained during each variant's live window
    (a CTR proxy), plus averageViewPercentage. Uses the YouTube Analytics API per
    window date range. Windows still open are reported as 'in progress'."""
    ledger = _load_ledger()
    test = ledger.get(video_id)
    if not test:
        return f"Error: no A/B test recorded for {video_id}."

    ya = youtube_analytics()
    rows = []
    agg: dict[str, dict] = {}
    for w in test["windows"]:
        start_d = w["started_at"][:10]
        end_iso = w["ended_at"] or _now_iso()
        end_d = end_iso[:10]
        try:
            resp = ya.reports().query(
                ids="channel==MINE",
                startDate=start_d,
                endDate=end_d,
                metrics="views,estimatedMinutesWatched,averageViewPercentage",
                filters=f"video=={video_id}",
            ).execute()
            data = resp.get("rows", [[0, 0, 0]])[0]
            views, mins, avgpct = data[0], data[1], data[2]
        except Exception as e:  # noqa: BLE001
            views, mins, avgpct, note = 0, 0, 0, str(e)
            rows.append({"label": w["label"], "error": note})
            continue

        entry = {
            "label": w["label"],
            "window_days": f"{start_d} -> {end_d}" + (" (in progress)" if not w["ended_at"] else ""),
            "views": views,
            "minutes_watched": mins,
            "avg_view_pct": avgpct,
        }
        rows.append(entry)
        a = agg.setdefault(w["label"], {"views": 0, "minutes": 0, "windows": 0})
        a["views"] += views
        a["minutes"] += mins
        a["windows"] += 1

    winner = max(agg.items(), key=lambda kv: kv[1]["views"])[0] if agg else None
    return json.dumps(
        {
            "video_id": video_id,
            "per_window": rows,
            "totals_by_variant": agg,
            "leading_variant_by_views": winner,
            "caveat": "Views-per-window proxy, not true CTR — impressions/CTR aren't in the API. "
            "Analytics data lags ~1-2 days.",
        },
        indent=2,
    )


# --- analytics ---------------------------------------------------------------


@mcp.tool()
def youtube_analytics(
    video_id: str,
    start_date: str,
    end_date: str,
    metrics: str = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,comments,shares",
) -> str:
    """Pull YouTube Analytics for one video over a date range.

    start_date / end_date : 'YYYY-MM-DD'. Data lags ~1-2 days.
    metrics               : comma-separated. NOTE: impressions and CTR are NOT
                            available via the API (Studio-only), so they can't be
                            requested here.
    """
    ya = youtube_analytics()
    try:
        resp = ya.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=metrics,
            filters=f"video=={video_id}",
        ).execute()
    except Exception as e:  # noqa: BLE001
        return f"Analytics error: {e}"

    headers = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = resp.get("rows", [])
    result = [dict(zip(headers, r)) for r in rows] or [{h: 0 for h in headers}]
    return json.dumps({"video_id": video_id, "range": f"{start_date}..{end_date}", "data": result}, indent=2)


# --- playlists ---------------------------------------------------------------


@mcp.tool()
def youtube_playlist_create(title: str, description: str = "", privacy: str = "public") -> str:
    """Create a playlist. Playlists auto-play the next video, which boosts session
    time — one of the highest-leverage YouTube SEO levers. Returns the playlist id."""
    yt = youtube_data()
    pl = yt.playlists().insert(
        part="snippet,status",
        body={"snippet": {"title": title, "description": description},
              "status": {"privacyStatus": privacy}},
    ).execute()
    pid = pl["id"]
    return json.dumps({"playlist_id": pid, "url": f"https://www.youtube.com/playlist?list={pid}"}, indent=2)


@mcp.tool()
def youtube_playlist_add(playlist_id: str, video_id: str) -> str:
    """Add a video to a playlist."""
    yt = youtube_data()
    yt.playlistItems().insert(
        part="snippet",
        body={"snippet": {"playlistId": playlist_id,
                          "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
    ).execute()
    return json.dumps({"playlist_id": playlist_id, "added": video_id}, indent=2)


# --- SEO tooling -------------------------------------------------------------

import re  # noqa: E402


@mcp.tool()
def youtube_seo_audit(video_id: str) -> str:
    """Score a video's on-page SEO (0-100) and return concrete fixes. Checks title
    length/front-loading, description length + first-150-char keyword, tag count,
    hashtags, and chapters. NOTE: on-page metadata is only ~half of YouTube SEO —
    CTR (thumbnail/title) and retention/satisfaction outweigh all of it."""
    yt = youtube_data()
    items = yt.videos().list(part="snippet", id=video_id).execute().get("items", [])
    if not items:
        return f"Error: no video with id {video_id}"
    s = items[0]["snippet"]
    title = s.get("title", "")
    desc = s.get("description", "")
    tags = s.get("tags", [])

    score, recs = 0, []

    # title: <=70 chars, keyword front-loaded
    if len(title) <= 70:
        score += 15
    else:
        recs.append(f"Title is {len(title)} chars — trim to <=70 so it isn't truncated.")
    if len(title) >= 30:
        score += 5
    else:
        recs.append("Title is short — add the primary keyword phrase.")

    # description length + early keyword
    if len(desc) >= 250:
        score += 20
    elif len(desc) >= 150:
        score += 10
        recs.append("Description is thin — aim for 250+ chars so YouTube fully indexes the topic.")
    else:
        recs.append("Description under 150 chars — YouTube may not index the topic. Expand it.")
    if desc[:150].strip():
        score += 10

    # tags (minor signal in 2026)
    if 5 <= len(tags) <= 15:
        score += 10
    elif tags:
        score += 5
        recs.append(f"You have {len(tags)} tags — 5-15 is the sweet spot (tags are a minor signal now).")
    else:
        recs.append("No tags — add 5-15 for edge-case/misspelling coverage.")

    # hashtags (first 3 render above the title)
    hashtags = re.findall(r"#\w+", desc)
    if hashtags:
        score += 10
    else:
        recs.append("No hashtags — add 3 relevant ones; the first 3 show above the title.")

    # chapters: >=3 timestamps starting at 0:00
    ts = re.findall(r"(?m)^\s*(\d{1,2}:\d{2})", desc)
    if len(ts) >= 3 and ts[0] in ("0:00", "00:00"):
        score += 15
    else:
        recs.append("No chapters — add timestamps starting at 0:00 (helps ranking + Google AI Overviews).")

    # links / CTA
    if "http" in desc:
        score += 5

    verdict = "strong" if score >= 80 else "decent" if score >= 60 else "needs work"
    return json.dumps(
        {
            "video_id": video_id,
            "seo_score": score,
            "verdict": verdict,
            "title_len": len(title),
            "desc_len": len(desc),
            "tag_count": len(tags),
            "hashtags": hashtags[:5],
            "chapters_detected": len(ts),
            "recommendations": recs or ["On-page metadata looks solid. Focus next on CTR + retention."],
            "reminder": "Metadata is ~half of SEO. CTR (thumbnail/title) and retention/satisfaction matter more.",
        },
        indent=2,
    )


@mcp.tool()
def youtube_competitor_tags(query: str, max_videos: int = 10) -> str:
    """Reverse-engineer what ranks for a search term: pull the top videos for a
    query and aggregate their tags by frequency. Use to find high-signal keywords
    to mirror in your own titles/descriptions."""
    yt = youtube_data()
    search = yt.search().list(part="id", q=query, type="video", order="relevance",
                              maxResults=min(max(max_videos, 1), 25)).execute()
    ids = [it["id"]["videoId"] for it in search.get("items", []) if it["id"].get("videoId")]
    if not ids:
        return json.dumps({"query": query, "note": "no videos found"}, indent=2)
    vids = yt.videos().list(part="snippet", id=",".join(ids)).execute().get("items", [])
    freq: dict[str, int] = {}
    titles = []
    for v in vids:
        titles.append(v["snippet"].get("title", ""))
        for t in v["snippet"].get("tags", []):
            k = t.lower().strip()
            freq[k] = freq.get(k, 0) + 1
    top = sorted(freq.items(), key=lambda kv: -kv[1])[:30]
    return json.dumps(
        {
            "query": query,
            "videos_sampled": len(vids),
            "top_ranking_titles": titles[:8],
            "top_tags_by_frequency": [{"tag": t, "count": c} for t, c in top],
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()
