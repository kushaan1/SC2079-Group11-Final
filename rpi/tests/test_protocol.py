import pytest

from rpi import protocol as p
from rpi.model import Obstacle, Pose


# --- inbound: every message in protocol.md §1 --------------------------------

def test_add():
    assert p.parse("ADD,B3,(14,15)") == p.Add(3, 14, 15)


def test_sub():
    assert p.parse("SUB,B3") == p.Sub(3)


def test_face_and_face_none():
    assert p.parse("FACE,B3,(14,15),E") == p.Face(3, 14, 15, "E")
    assert p.parse("FACE,B3,(14,15),NONE") == p.Face(3, 14, 15, None)


def test_moverobot_decimals():
    assert p.parse("MOVEROBOT,7.5,2.25,20.0") == p.MoveRobot(Pose(7.5, 2.25, 20.0))
    assert p.parse("MOVEROBOT,1.0,1.0,0.0") == p.MoveRobot(Pose(1.0, 1.0, 0.0))


@pytest.mark.parametrize("token", ["f", "b", "tl", "tr", "sl", "sr", "s"])
def test_manual_tokens(token):
    assert p.parse(token) == p.Manual(token)


def test_begin_fastest():
    assert p.parse("beginFastest") == p.BeginFastest()


def test_send_arena_json():
    line = '{"obstacles":[{"id":1,"x":10,"y":6,"face":"N"},{"id":3,"x":14,"y":15,"face":"E"}]}'
    assert p.parse(line) == p.SendArena((Obstacle(1, 10, 6, "N"), Obstacle(3, 14, 15, "E")))


def test_image_rec_with_robot():
    line = ('{"command":"imageRec","algorithm":"optimal",'
            '"robot":{"x":1.0,"y":1.0,"heading":0.0},'
            '"obstacles":[{"id":1,"x":10,"y":6,"face":"N"}]}')
    assert p.parse(line) == p.ImageRec("optimal", Pose(1.0, 1.0, 0.0), (Obstacle(1, 10, 6, "N"),))


def test_image_rec_without_robot_or_algorithm():
    line = '{"command":"imageRec","obstacles":[{"id":2,"x":12,"y":8,"face":"E"}]}'
    assert p.parse(line) == p.ImageRec("greedy", None, (Obstacle(2, 12, 8, "E"),))


def test_face_search():
    line = ('{"command":"faceSearch","robot":{"x":4.5,"y":2.0,"heading":450.0},'
            '"obstacles":[{"id":1,"x":10,"y":6,"face":"S"}]}')
    parsed = p.parse(line)
    assert parsed == p.FaceSearch(Pose(4.5, 2.0, 90.0), (Obstacle(1, 10, 6, "S"),))


def test_trailing_cr_and_whitespace_are_tolerated():
    assert p.parse("  SUB,B2\r") == p.Sub(2)


@pytest.mark.parametrize("line", [
    "", "   ", "ADD,B3", "ADD,B3,(14)", "FACE,B3,(1,2),X", "MOVEROBOT,1,2",
    "{not json", '{"command":"dance"}', '{"obstacles":[{"id":1,"x":1,"y":2,"face":"Q"}]}',
    '{"obstacles":[{"id":"one","x":1,"y":2,"face":"N"}]}', "[1,2,3]", "F", "S",
])
def test_everything_else_is_unknown_and_never_raises(line):
    assert p.parse(line) == p.Unknown(line)


# --- outbound: protocol.md §2, byte for byte ----------------------------------

def test_msg():
    assert p.msg("Scanning obstacle 2") == "MSG,Scanning obstacle 2"


def test_msg_never_lets_a_newline_through():
    assert p.msg("two\nlines\r\nhere") == "MSG,two lines here"


def test_target():
    assert p.target(2, 11) == "TARGET,B2,11"


def test_robot_two_decimals_and_whole_degrees():
    assert p.robot(Pose(5.55, 6.55, 20.0)) == "ROBOT,5.55,6.55,20"
    assert p.robot(Pose(1.0, 1.0, 269.6)) == "ROBOT,1.00,1.00,270"
    assert p.robot(Pose(1.0, 1.0, 359.7)) == "ROBOT,1.00,1.00,0"
