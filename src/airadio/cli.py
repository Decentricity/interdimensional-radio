"""airadio command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from airadio import __version__, radio, song_title
from airadio.paths import user_home


def _add_run_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--home",
        type=Path,
        default=default,
        help="runtime data directory (default: AIRADIO_HOME or ~/.local/share/airadio)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=default,
        help="verbose setup and generation output" if not suppress_defaults else argparse.SUPPRESS,
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=default,
        help="quiet setup output" if not suppress_defaults else argparse.SUPPRESS,
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        default=default,
        help=(
            "skip first-run setup even if interstitials are missing"
            if not suppress_defaults
            else argparse.SUPPRESS
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airadio",
        description="Local AI radio loop with MiniMax Music 3 generation",
    )
    parser.add_argument("--version", action="version", version=f"airadio {__version__}")
    _add_run_options(parser, suppress_defaults=False)
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="start the radio loop (default)")
    _add_run_options(run_p, suppress_defaults=True)

    title_p = sub.add_parser("title", help="print random two-word song titles")
    title_p.add_argument("--count", type=int, default=1)
    title_p.add_argument("--seed", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.verbose and args.quiet:
        parser.error("--verbose and --quiet cannot be used together")
    if args.home:
        import os

        os.environ["AIRADIO_HOME"] = str(args.home.expanduser().resolve())

    command = args.command or "run"
    if command == "run":
        try:
            return radio.run(
                user_home(),
                verbose=args.verbose,
                quiet=args.quiet,
                skip_setup=args.skip_setup,
            )
        except KeyboardInterrupt:
            radio.log("stopped")
            radio.stop_playback()
            radio.release_radio_lock()
            return 130
    if command == "title":
        import random

        rng = random.Random(args.seed)
        if args.count < 1:
            parser.error("title --count must be at least 1")
        for _ in range(args.count):
            print(song_title.random_title(rng))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
