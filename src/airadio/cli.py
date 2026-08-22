"""airadio command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from airadio import __version__, music3, radio, song_title
from airadio.paths import user_home


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airadio",
        description="Local AI radio loop with MiniMax Music 3 generation",
    )
    parser.add_argument("--version", action="version", version=f"airadio {__version__}")
    parser.add_argument(
        "--home",
        type=Path,
        help="runtime data directory (default: AIRADIO_HOME or ~/.local/share/airadio)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="start the radio loop (default)")

    title_p = sub.add_parser("title", help="print random two-word song titles")
    title_p.add_argument("--count", type=int, default=1)
    title_p.add_argument("--seed", type=int)

    m3 = sub.add_parser("music3", help="MiniMax Music 3 warm ComfyUI server")
    m3_sub = m3.add_subparsers(dest="music3_cmd", required=True)
    m3_sub.add_parser("start", help="start ComfyUI and hold GPU lock")
    m3_sub.add_parser("stop", help="stop warm server")
    m3_sub.add_parser("status", help="show server status")

    gen_p = m3_sub.add_parser("gen", help="generate one song")
    gen_p.add_argument("--lyrics", type=Path, required=True)
    gen_p.add_argument("--prompt", type=Path, required=True)
    gen_p.add_argument("--duration", type=int, default=120)
    gen_p.add_argument("--seed", type=int, default=7)
    gen_p.add_argument("--out", type=Path)
    gen_p.add_argument("--no-play", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.home:
        import os

        os.environ["AIRADIO_HOME"] = str(args.home.expanduser().resolve())

    command = args.command or "run"
    if command == "run":
        return radio.run(user_home())
    if command == "title":
        import random

        rng = random.Random(args.seed)
        for _ in range(args.count):
            print(song_title.random_title(rng))
        return 0
    if command == "music3":
        if args.music3_cmd == "start":
            music3.start_server()
            return 0
        if args.music3_cmd == "stop":
            music3.stop_server()
            return 0
        if args.music3_cmd == "status":
            music3.status()
            return 0
        if args.music3_cmd == "gen":
            music3.generate(
                lyrics=args.lyrics,
                caption=args.prompt,
                duration=args.duration,
                seed=args.seed,
                out=args.out,
                play=not args.no_play,
            )
            return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
