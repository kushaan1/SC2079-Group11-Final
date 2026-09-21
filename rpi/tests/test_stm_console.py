from rpi.stm_console import handle, run
from rpi.stm_driver import FakeStmDriver, StmAborted, StmError, StmUnavailable


class Console:
    """Captures what the console prints: the driver's mirror lines and its own notes."""

    def __init__(self, **kwargs):
        self.out = []
        self.stm = FakeStmDriver(straight_cm_per_s=10000.0, turn_s=0.0, on_line=self.out.append, **kwargs)

    def say(self, text):
        self.out.append(text)


class ErrStm(FakeStmDriver):
    def raw(self, line, abort=None):
        self.sent.append(line)
        raise StmError(line, "ERR,UNKNOWN")


class GoneStm(FakeStmDriver):
    def raw(self, line, abort=None):
        raise StmUnavailable(line, "STM unavailable")


class StoppedStm(FakeStmDriver):
    def raw(self, line, abort=None):
        raise StmAborted(line, "stopped")


def test_a_motion_command_shows_the_whole_exchange_and_its_time():
    console = Console()
    handle(console.stm, "FW 50", console.say)
    assert console.out[:3] == ["STM> FW 50", "STM< ACK,FW", "STM< DONE,FW"]
    assert console.out[3].startswith("(") and console.out[3].endswith(" s)")


def test_a_query_shows_the_first_reply_whatever_it_is():
    console = Console()
    handle(console.stm, "PING", console.say)
    assert console.out[:2] == ["STM> PING", "STM< PONG"]


def test_typed_lines_are_trimmed_and_upper_cased():
    console = Console()
    handle(console.stm, "  s  ", console.say)
    handle(console.stm, "tl 90", console.say)
    assert console.stm.sent == ["S", "TL 90"]


def test_errors_are_reported_not_raised():
    for stm, expected in ((ErrStm(), "error: ERR,UNKNOWN"),
                          (GoneStm(), "STM unavailable: STM unavailable - is the main program running?"),
                          (StoppedStm(), "stopped")):
        out = []
        handle(stm, "XYZ", out.append)
        assert out == [expected]


def test_run_reads_lines_until_quit_and_skips_blanks():
    console = Console()
    lines = iter(["", "FW 10", "   ", "quit", "FW 20"])
    run(console.stm, lambda: next(lines), console.say)
    assert console.stm.sent == ["FW 10"]


def test_run_ends_cleanly_at_end_of_input():
    console = Console()
    lines = iter(["PING"])

    def read():
        try:
            return next(lines)
        except StopIteration:
            raise EOFError()

    run(console.stm, read, console.say)
    assert console.stm.sent == ["PING"]
