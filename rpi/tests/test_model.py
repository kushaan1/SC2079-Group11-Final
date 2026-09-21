from rpi.model import (
    ARC_KINDS, START_POSE, Arc, Capture, Obstacle, Plan, Pose, Segment, Straight, Verdict,
)


def test_start_pose_is_bottom_left_facing_north():
    assert START_POSE == Pose(1.0, 1.0, 0.0)


def test_capture_instances_are_equal():
    assert Capture() == Capture()


def test_instructions_are_value_types():
    assert Straight("FORWARD", 30) == Straight("FORWARD", 30)
    assert Arc("FORWARD_LEFT", 90) != Arc("FORWARD_LEFT", 45)


def test_arc_kinds_are_the_planner_tokens():
    assert ARC_KINDS == ("FORWARD_LEFT", "FORWARD_RIGHT", "BACKWARD_LEFT", "BACKWARD_RIGHT")


def test_plan_holds_segments_and_unreachable():
    segment = Segment(3, (Straight("FORWARD", 10), Capture()), Pose(2.0, 2.0, 90.0), 1.5)
    plan = Plan((segment,), ((5, "NO_PATH"),))
    assert plan.segments[0].image_id == 3
    assert plan.unreachable == ((5, "NO_PATH"),)


def test_obstacle_face_may_be_none():
    assert Obstacle(1, 4, 5, None).face is None


def test_verdict_defaults():
    assert Verdict("no_detection") == Verdict("no_detection", None, None)
