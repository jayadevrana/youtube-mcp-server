"""
One-time OAuth consent. Run:  ./run.sh authorize

Opens a browser, you approve the scopes, and a refresh token is written to
YOUTUBE_TOKEN_PATH. After this, the MCP server runs unattended.

NOTE: if your OAuth app is in "Testing" mode in Google Cloud, add your Google
account under APIs & Services -> OAuth consent screen -> Test users, or the
consent screen will block you. Testing-mode refresh tokens also expire after
7 days of non-use; publish the app to "Production" for durable access.
"""

from __future__ import annotations

from google_auth_oauthlib.flow import InstalledAppFlow

from auth import SCOPES, client_config, token_path


def main() -> None:
    tp = token_path()
    tp.parent.mkdir(parents=True, exist_ok=True)

    flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
    # Opens the system browser; spins a tiny localhost server to catch the redirect.
    creds = flow.run_local_server(
        port=0,
        prompt="consent",              # force a refresh_token to be issued
        access_type="offline",
        authorization_prompt_message="Opening browser to authorize YouTube access...",
        success_message="Authorized. You can close this tab and return to the terminal.",
    )
    tp.write_text(creds.to_json())
    print(f"\n✅ Refresh token saved to {tp}")
    print("You can now run the MCP server (./run.sh) or ab_rotate.py.")


if __name__ == "__main__":
    main()
