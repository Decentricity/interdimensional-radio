"""airadio command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from airadio import __version__, radio, song_title
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="verbose setup and generation output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="quiet setup (progress bar only)",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="skip first-run setup even if interstitials are missing",
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="start the radio loop (default)")
    run_p.add_argument("-v", "--verbose", action="store_true", help=argparse.SUPPRESS)
    run_p.add_argument("-q", "--quiet", action="store_true", help=argparse.SUPPRESS)
    run_p.add_argument("--skip-setup", action="store_true", help=argparse.SUPPRESS)

    title_p = sub.add_parser("title", help="print random two-word song titles")
    title_p.add_argument("--count", type=int, default=1)
    title_p.add_argument("--seed", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.home:
        import os

        os.environ["AIRADIO_HOME"] = str(args.home.expanduser().resolve())

    command = args.command or "run"
    if command == "run":
        return radio.run(
            user_home(),
            verbose=args.verbose,
            quiet=args.quiet,
            skip_setup=args.skip_setup,
        )
    if command == "title":
        import random

        rng = random.Random(args.seed)
        for _ in range(args.count):
            print(song_title.random_title(rng))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
