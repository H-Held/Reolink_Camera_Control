"""Command line interface: ``python -m reolink_camera_control``.

Examples::

    python -m reolink_camera_control play alert.wav
    python -m reolink_camera_control play song.mp3 --volume 0.8
    python -m reolink_camera_control tone --freq 880 --duration 2
    python -m reolink_camera_control siren --times 2
    python -m reolink_camera_control snap picture.jpg

Connection settings come from --host/--user/--password, from the
REOLINK_HOST / REOLINK_USER / REOLINK_PASSWORD environment variables, or
from a ``.env`` file in the current directory.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import ReolinkCamera, ReolinkError


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from *path* into os.environ (existing vars win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m reolink_camera_control",
                                description="Control a Reolink camera")
    p.add_argument("--host", default=None, help="camera IP (env: REOLINK_HOST)")
    p.add_argument("--user", default=None, help="user (env: REOLINK_USER)")
    p.add_argument("--password", default=None, help="password (env: REOLINK_PASSWORD)")
    p.add_argument("--port", type=int, default=None, help="API port (env: REOLINK_PORT, default 443)")
    p.add_argument("--scheme", choices=["https", "http"], default=None,
                   help="API scheme (env: REOLINK_SCHEME, default https)")
    sub = p.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="play a local audio file on the camera speaker")
    play.add_argument("file", type=Path)
    play.add_argument("--volume", "-v", type=float, default=1.0, help="gain, 1.0 = unchanged")

    tone = sub.add_parser("tone", help="play a sine tone on the camera speaker")
    tone.add_argument("--freq", "-f", type=float, default=440.0)
    tone.add_argument("--duration", "-d", type=float, default=3.0)
    tone.add_argument("--volume", "-v", type=float, default=1.0)

    siren = sub.add_parser("siren", help="control the built-in siren")
    group = siren.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", action="store_true")
    group.add_argument("--off", action="store_true")
    group.add_argument("--times", type=int, metavar="N")

    snap = sub.add_parser("snap", help="save a JPEG snapshot")
    snap.add_argument("file", type=Path)

    sub.add_parser("info", help="print device information")
    return p


def main(argv=None) -> int:
    _load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args(argv)

    host = args.host or os.environ.get("REOLINK_HOST")
    user = args.user or os.environ.get("REOLINK_USER")
    password = args.password or os.environ.get("REOLINK_PASSWORD")
    if not (host and user and password):
        print("Missing connection settings. Set REOLINK_HOST, REOLINK_USER and "
              "REOLINK_PASSWORD (see .env.example) or pass --host/--user/--password.",
              file=sys.stderr)
        return 2

    port = args.port or int(os.environ.get("REOLINK_PORT", "443"))
    scheme = args.scheme or os.environ.get("REOLINK_SCHEME", "https")

    try:
        with ReolinkCamera(host, user, password, port=port, scheme=scheme) as cam:
            if args.command == "play":
                if not args.file.is_file():
                    print(f"File not found: {args.file}", file=sys.stderr)
                    return 1
                cam.play_audio_file(str(args.file), volume=args.volume)
            elif args.command == "tone":
                cam.play_tone(args.freq, args.duration, volume=args.volume)
            elif args.command == "siren":
                if args.on:
                    cam.siren_on()
                elif args.off:
                    cam.siren_off()
                else:
                    cam.siren_times(args.times)
            elif args.command == "snap":
                print(f"Saved {cam.snap_to_file(str(args.file))}")
            elif args.command == "info":
                info = cam.get_device_info()
                print(f"{info.name}: {info.model}, firmware {info.firmware}, serial {info.serial}")
    except ReolinkError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
