"""A hand-typed STM console over our own driver: `python3 -m rpi.stm_console`.

For calibration and STM bring-up without a tablet. Every line you type goes to the
board as one command through the same `SerialStmDriver` the runs use - same framing,
the same ACK-then-DONE wait on motion verbs, the same stop-and-resync on silence - so
what works here works in a run. The board's replies are printed as they arrive.

The main program holds the serial port, so stop it first (`pkill -f '^python3 -m rpi'`).
"""

import argparse
import sys
import time
from typing import Callable, List, Optional

from rpi.main import make_stm
from rpi.stm_driver import StmAborted, StmDriver, StmError, StmUnavailable

Say = Callable[[str], None]
QUIT = ("quit", "exit", "q")


def handle(stm: StmDriver, typed: str, say: Say) -> None:
    """One typed line: send it, then note the outcome. The exchange itself is printed
    by the driver's mirror hook as it happens."""
    line = typed.strip().upper()     # the firmware's verbs and arguments are all upper-case
    if not line:
        return
    started = time.monotonic()
    try:
        stm.raw(line)
    except StmAborted:
        say("stopped")
    except StmUnavailable as error:
        say("STM unavailable: %s - is the main program running?" % error.reply)
    except StmError as error:
        say("error: %s" % error.reply)
    else:
        say("(%.1f s)" % (time.monotonic() - started))


def run(stm: StmDriver, read: Callable[[], str], say: Say) -> None:
    """Read lines until quit or end of input."""
    while True:
        try:
            typed = read()
        except EOFError:
            return
        if typed.strip().lower() in QUIT:
            return
        handle(stm, typed, say)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rpi.stm_console", description="type commands to the STM")
    parser.add_argument("--fake", action="store_true", help="talk to the fake STM instead of the board")
    args = parser.parse_args(argv)

    def say(text: str) -> None:
        print(text, flush=True)

    stm = make_stm(args.fake, on_line=say)
    try:
        stm.start()
    except StmUnavailable as error:
        say("STM not reachable: %s" % error.reply)
        say("Is the main program running? Stop it first: pkill -f '^python3 -m rpi'")
        stm.close()
        return 1
    say("STM link up. Type a command (FS 50, TL 90, PING, RANGE ...); s = stop, quit = exit, Ctrl-C = S.")

    def read() -> str:
        while True:
            try:
                return input("> ")
            except KeyboardInterrupt:
                print()
                stm.stop()          # S, then the usual resync; the prompt comes back
                say("stopped")

    try:
        run(stm, read, say)
    finally:
        stm.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
