import math
import os

from pathfinding.search.instructions import Turn, TurnInstruction
from pathfinding.search.search import search
from pathfinding.world.objective import generate_objectives
from simulator.arena import load
from simulator.geometry import HEADING_DEG

TESTDATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")


def planned(name):
    world = load(os.path.join(TESTDATA, name)).world()
    return world, search(world, generate_objectives(world))


def test_vectors_are_8_connected_within_every_move():
    _, result = planned("02-four-obstacles.json")
    for segment in result.segments:
        for move in segment.moves:
            cells = move.vectors[:-1] if isinstance(move, Turn) else move.vectors
            for u, v in zip(cells, cells[1:]):
                assert max(abs(u.x - v.x), abs(u.y - v.y)) == 1, (segment.image_id, move, u, v)


def test_moves_flatten_to_vectors_and_turns_are_quarter_turns():
    _, result = planned("02-four-obstacles.json")
    seen = set()
    for segment in result.segments:
        flat = [v for m in segment.moves for v in m.vectors]
        assert flat == segment.vectors
        seen |= {m.turn for m in segment.moves if isinstance(m, Turn)}
    # Which of the four quarter turns appear is a property of the arena, not a contract.
    assert seen and seen <= {t for t in TurnInstruction if t.degrees == 90}


def test_arc_is_the_rear_point_path_and_end_is_the_centre():
    world, result = planned("02-four-obstacles.json")
    for segment in result.segments:
        for move in segment.moves:
            if not isinstance(move, Turn):
                continue
            lead = move.turn.lead(world.cell_size)
            *arc, end = move.vectors
            t = math.radians(HEADING_DEG[end.direction])
            cx, cy = arc[-1].x + lead * math.sin(t), arc[-1].y + lead * math.cos(t)
            assert math.isclose(cx, end.x, abs_tol=1.01) and math.isclose(cy, end.y, abs_tol=1.01), (segment.image_id, move.turn, arc[-1], end)
