"""
python -m simulator                       open the window
python -m simulator --arena FILE          open with an arena loaded
python -m simulator --snapshot OUT.png    render FILE (default testdata/02) to a PNG, no window
python -m simulator --selftest            open, plan, step through, exit; a crash means a bug
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulator", description="MDP arena simulator.")
    parser.add_argument("--arena", default="testdata/02-four-obstacles.json", help="request JSON to load")
    parser.add_argument("--snapshot", metavar="OUT.png", help="render headlessly to a PNG and exit")
    parser.add_argument("--frame", type=int, default=None, help="playback frame for --snapshot (default: last)")
    parser.add_argument("--scale", type=float, default=3.2, help="pixels per cm for --snapshot")
    parser.add_argument("--selftest", action="store_true", help="open the window, drive one route, exit")
    args = parser.parse_args(argv)

    if args.snapshot:
        from simulator.snapshot import write
        write(args.arena, args.snapshot, args.frame, args.scale)
        print(f"wrote {args.snapshot}")
        return 0

    from simulator.app import run
    return run(arena_path=args.arena, selftest=args.selftest)


if __name__ == "__main__":
    sys.exit(main())
