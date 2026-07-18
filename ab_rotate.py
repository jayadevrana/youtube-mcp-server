"""
Advance a pseudo-A/B thumbnail test one step from the command line, so it can be
scheduled (launchd/cron) for hands-off rotation.

  ./run.sh rotate <video_id>

Schedule example (launchd), every 48h, is documented in README.md.
"""

from __future__ import annotations

import sys

from server import youtube_ab_rotate


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ab_rotate.py <video_id>", file=sys.stderr)
        raise SystemExit(2)
    print(youtube_ab_rotate(sys.argv[1]))


if __name__ == "__main__":
    main()
