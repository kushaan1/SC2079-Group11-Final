"""
Characterisation tests for the integer-state search core.

``segment.py`` was rewritten onto integer state indices; the contract is that it returns
exactly what the dict/``Vector`` version returned, tie-breaks included. These tests pin the
current output against a committed baseline. The baseline was regenerated from the rewritten
implementation after independent old-vs-new differential checks (see the Task 6 review), so it
is a characterisation lock against future drift, not itself the proof of equivalence.

Regenerate the baseline (from whatever implementation is checked out) with::

    ./.venv/bin/python tests/test_segment_fast.py

which rewrites ``tests/baselines/segment-baseline.json`` (committed, so a fresh checkout runs the
equality tests). Point ``MDP_BASELINE`` elsewhere to override. Regenerate only when the planner
is meant to change; the diff of the baseline is then part of the review.
``MDP_SKIP_TIMING=1`` skips the timing sanity test on a slow machine.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathfinding import cost
from pathfinding.search.instructions import MiscInstruction, Move, MoveInstruction, Turn, TurnInstruction
from pathfinding.search.search import search
from pathfinding.search.segment import reach, segment
from pathfinding.world.objective import generate_objectives
from simulator.arena import load

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
CASES = ("01-single-obstacle.json", "02-four-obstacles.json", "03-unreachable.json", "04-five-obstacles.json")

BASELINE = os.environ.get("MDP_BASELINE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "baselines", "segment-baseline.json")


def _vector(v):
    """A Vector as JSON. Coordinates go through int() so a numpy int would be caught here."""
    assert type(v.x) is int and type(v.y) is int, f"non-int coordinate: {v!r}"
    return [v.direction.value, v.x, v.y]


def _move(move):
    match move:
        case None:
            return None
        case Turn():
            return ["TURN", move.turn.value, [_vector(v) for v in move.vectors]]
        case Move():
            return ["MOVE", move.move.value, [_vector(v) for v in move.vectors]]
    raise AssertionError(f"unknown move {move!r}")


def _instruction(instruction):
    match instruction:
        case MoveInstruction():
            return f"{instruction.move.value}:{instruction.amount}"
        case TurnInstruction() | MiscInstruction():
            return instruction.value
    raise AssertionError(f"unknown instruction {instruction!r}")


def world_of(name):
    return load(os.path.join(TESTDATA, name)).world()


def snapshot(name):
    """Everything one testdata arena pins: greedy plan, one raw segment, and a reach matrix row."""
    world = world_of(name)
    generated = generate_objectives(world)

    result = search(world, generated)
    plan = [
        {
            "image_id": s.image_id,
            "cost": s.cost,
            "seconds": s.seconds,
            "instructions": [_instruction(i) for i in s.instructions],
            "vectors": [_vector(v) for v in s.vectors],
        }
        for s in result.segments
    ]

    raw = segment(world, world.robot.vector, generated.objectives)
    first = None if raw is None else {
        "image_id": raw[0].image_id,
        "cost": raw[1],
        "parts": [[_vector(v), _move(m)] for v, m in raw[2]],
    }

    reached = reach(world, world.robot.vector, generated.objectives, cost.TIME_SECONDS)

    return {
        "search": plan,
        "unreachable": [[u.image_id, u.reason.value] for u in result.unreachable],
        "segment": first,
        "reach": {str(o.image_id): c for o, c in sorted(reached.items(), key=lambda kv: kv[0].image_id)},
    }


def baseline():
    if not os.path.exists(BASELINE):
        pytest.skip(f"no baseline at {BASELINE}; regenerate with python tests/test_segment_fast.py")
    with open(BASELINE) as handle:
        return json.load(handle)


@pytest.mark.parametrize("name", CASES)
def test_matches_the_recorded_baseline(name):
    expected = baseline()[name]
    actual = snapshot(name)

    # Compared field by field so a failure names the half that moved.
    assert actual["unreachable"] == expected["unreachable"]
    assert actual["reach"] == expected["reach"]
    assert actual["segment"] == expected["segment"]
    assert len(actual["search"]) == len(expected["search"])
    for got, want in zip(actual["search"], expected["search"]):
        assert got == want


def test_costs_are_plain_floats():
    """A numpy float would compare equal and then serialise differently over the wire."""
    world = world_of("02-four-obstacles.json")
    generated = generate_objectives(world)

    found = segment(world, world.robot.vector, generated.objectives)
    assert found is not None
    assert type(found[1]) is float

    for value in reach(world, world.robot.vector, generated.objectives, cost.TIME_SECONDS).values():
        assert type(value) is float


@pytest.mark.skipif(os.environ.get("MDP_SKIP_TIMING") == "1", reason="MDP_SKIP_TIMING=1")
def test_reach_is_fast_enough():
    world = world_of("02-four-obstacles.json")
    generated = generate_objectives(world)
    reach(world, world.robot.vector, generated.objectives, cost.TIME_SECONDS)  # warm the caches

    start = time.perf_counter()
    reach(world, world.robot.vector, generated.objectives, cost.TIME_SECONDS)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5, f"reach() took {elapsed:.2f} s"


if __name__ == "__main__":
    data = {name: snapshot(name) for name in CASES}
    with open(BASELINE, "w") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    print(f"wrote {BASELINE}")
