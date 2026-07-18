# YouTube MCP

MCP server for driving your own YouTube channel from Claude: **upload videos,
edit metadata, set thumbnails, run pseudo-A/B thumbnail tests, and pull analytics**.

## What works (and what YouTube won't let anyone do via API)

| Capability | Status |
|---|---|
| Upload videos (resumable, with schedule) | ✅ `youtube_upload` |
| Edit title / description / tags / category / privacy | ✅ `youtube_update_metadata` |
| Set custom thumbnail | ✅ `youtube_set_thumbnail` (channel must be verified) |
| Analytics: views, watch time, avg view %, subs, likes | ✅ `youtube_analytics` |
| **Native thumbnail/title A/B "Test & Compare"** | ❌ No public API — Studio-only |
| **Impressions & click-through-rate (CTR)** | ❌ Not exposed by the Analytics API — Studio-only |

Because the last two are walled off by YouTube, the A/B tools here **rotate
thumbnails on a ledger** and compare **views gained per equal-length window** as a
CTR proxy. Useful, but not a rigorous split test. Use windows ≥ 24h.

## Setup

1. **Google Cloud** → enable *YouTube Data API v3* and *YouTube Analytics API*.
   Create an OAuth Client ID of type **Desktop app**. Add your Google account
   under *OAuth consent screen → Test users* (or publish to Production for
   durable tokens — Testing-mode refresh tokens die after 7 days idle).

2. **Credentials**
   ```bash
   cp .env.example .env
   # fill in YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET
   ```

3. **Authorize once** (opens a browser):
   ```bash
   ./run.sh authorize
   ```
   Writes a refresh token to `~/.local/share/youtube-mcp/token.json` (off the
   exFAT drive, git-ignored).

4. **Register with Claude Code** (`~/.claude.json` or project `.mcp.json`):
   ```json
   {
     "mcpServers": {
       "youtube": { "command": "/Volumes/NO NAME/youtube-mcp/run.sh" }
     }
   }
   ```

## Tools

- `youtube_whoami` — channel id, counts, verification status
- `youtube_list_uploads` — recent uploads + video ids
- `youtube_upload` — upload a local file (title, tags, category, privacy, `publish_at`, thumbnail)
- `youtube_update_metadata` — partial edit; unspecified fields preserved
- `youtube_set_thumbnail` — set a custom thumbnail
- `youtube_ab_start` / `youtube_ab_rotate` / `youtube_ab_report` — pseudo A/B thumbnails
- `youtube_analytics` — per-video analytics over a date range

## Hands-off A/B rotation (optional, launchd)

`youtube_ab_start` sets V0 live. To auto-advance every 48h without babysitting,
schedule the rotate step:

```xml
<!-- ~/Library/LaunchAgents/com.you.youtube-ab.plist -->
<plist version="1.0"><dict>
  <key>Label</key><string>com.you.youtube-ab</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Volumes/NO NAME/youtube-mcp/run.sh</string>
    <string>rotate</string>
    <string>YOUR_VIDEO_ID</string>
  </array>
  <key>StartInterval</key><integer>172800</integer>  <!-- 48h -->
</dict></plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.you.youtube-ab.plist
```

## Security

- `token.json` grants ongoing access to your channel — treat like a password.
- `.env`, `token.json`, `ab_tests.json` are git-ignored. Never commit them.
- Rotate the client secret in Google Cloud if it ever leaks.

## Author

Built by [Jayadev Rana](https://jayadevrana.in) — @bluealgocapital · [YouTube](https://www.youtube.com/@jayadevrana3657) · [GitHub](https://github.com/jayadevrana)
