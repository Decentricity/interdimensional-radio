"""airadio command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from airadio import __version__, interstitial_provenance, radio, song_title
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

    interstitials_p = sub.add_parser(
        "interstitials", help="inspect and audit interstitial provenance"
    )
    interstitial_commands = interstitials_p.add_subparsers(
        dest="interstitial_command", required=True
    )
    info_p = interstitial_commands.add_parser(
        "info", help="show the generation record for a WAV"
    )
    info_p.add_argument("audio", type=Path)
    lyrics_p = interstitial_commands.add_parser(
        "lyrics", help="print the exact lyrics used to generate a WAV"
    )
    lyrics_p.add_argument("audio", type=Path)
    interstitial_commands.add_parser(
        "audit", help="verify every interstitial against its provenance hashes"
    )

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
    if command == "interstitials":
        home = user_home()
        if args.interstitial_command in ("info", "lyrics"):
            try:
                audio = interstitial_provenance.resolve_audio(home, args.audio)
                if args.interstitial_command == "info":
                    print(
                        json.dumps(
                            interstitial_provenance.load_record(audio), indent=2
                        )
                    )
                else:
                    print(interstitial_provenance.read_lyrics(audio), end="")
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                parser.error(str(exc))
            return 0
        if args.interstitial_command == "audit":
            issues = interstitial_provenance.audit(home)
            audio_root = home / "interstitials" / "audio"
            total = sum(1 for _ in audio_root.rglob("*.wav")) if audio_root.is_dir() else 0
            if issues:
                for issue in issues:
                    print(f"FAIL {issue.audio}: {issue.problem}")
                print(f"Audit failed: {len(issues)} issue(s) across {total} WAV(s).")
                return 1
            print(f"Audit passed: {total} WAV(s) have verified provenance.")
            return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
