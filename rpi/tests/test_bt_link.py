import os

from rpi.bt_link import BluetoothLink, LineFramer


def test_framer_splits_on_newline_and_strips_cr():
    framer = LineFramer()
    assert framer.feed(b"ADD,B1,(5,5)\r\nSUB,B2\n") == ["ADD,B1,(5,5)", "SUB,B2"]


def test_framer_buffers_a_line_that_spans_reads():
    framer = LineFramer()
    assert framer.feed(b'{"obstacles":[{"id":1,') == []
    assert framer.feed(b'"x":5,"y":5,"face":"N"}]}\n') == ['{"obstacles":[{"id":1,"x":5,"y":5,"face":"N"}]}']


def test_framer_drops_empty_lines():
    framer = LineFramer()
    assert framer.feed(b"\n\r\n\nf\n") == ["f"]


def test_framer_reset_discards_a_partial_line():
    framer = LineFramer()
    framer.feed(b"MOVERO")
    framer.reset()
    assert framer.feed(b"BOT,1,1,0\n") == ["BOT,1,1,0"]


def test_send_appends_newline_and_reports_success():
    read_fd, write_fd = os.pipe()
    link = BluetoothLink("/dev/null", on_line=lambda _line: None)
    try:
        assert link.send("MSG,hi") is False          # not attached yet
        link._attach(write_fd)
        assert link.connected is True
        assert link.send("MSG,hi") is True
        assert os.read(read_fd, 64) == b"MSG,hi\n"
    finally:
        link.close()
        os.close(read_fd)


def test_send_after_close_is_dropped_not_raised():
    read_fd, write_fd = os.pipe()
    link = BluetoothLink("/dev/null", on_line=lambda _line: None)
    link._attach(write_fd)
    link.close()
    os.close(read_fd)
    assert link.send("MSG,hi") is False


def test_reconnect_hook_fires_on_the_second_attach_only():
    calls = []
    link = BluetoothLink("/dev/null", on_line=lambda _line: None, on_reconnect=lambda: calls.append(1))
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    try:
        link._attach(w1)
        assert calls == []
        link._mark_down()
        link._attach(w2)
        assert calls == [1]
    finally:
        link.close()
        for fd in (r1, r2):
            os.close(fd)
