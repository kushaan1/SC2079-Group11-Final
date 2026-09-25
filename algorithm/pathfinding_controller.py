# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
The HTTP surface of the planner: request/response models and the ``POST /pathfinding/`` route.

This module is the ONLY place in ``algorithm/`` that knows about HTTP. Everything below it
speaks in domain types (``World``, ``Obstacle``, ``SearchResult``) and raises domain errors;
this layer decides how those become status codes and JSON.

**The wire contract is fixed** (AGENTS.md 2.2). The RPi's client was generated from the
prior-year team's OpenAPI schema, so the request shape and the route are reproduced from their
controller field for field, including choices this file would otherwise make differently (see
:meth:`PathfindingResponseSegment.from_segment` on ``verbose``). There are exactly nine
deliberate departures, all additive or error-path-only, and recorded in
``docs/protocols/algorithm-service.md`` (items 8 and 9 below pending the protocol doc's next
update, which is the owner's):

1. ``PathfindingResponse.unreachable`` — new field. The obstacles the robot will NOT visit,
   with a reason each. Without it a dropped obstacle is invisible to the caller: the response
   simply has one fewer segment than the request had obstacles, and the warning goes to stdout
   on the planning machine.
2. Duplicate ``image_id``\\ s are rejected with 422 rather than accepted. See
   :meth:`PathfindingRequest.reject_duplicate_image_ids`.
3. An ``image_id`` that satisfies the schema's ``minimum: 1`` but falls outside
   ``config.IMAGE_ID_MIN..IMAGE_ID_MAX`` returns 422, not 500.
4. ``strategy`` request field and ``seconds`` response field — both new, both additive. A
   request that omits ``strategy`` gets the shortest-time route (:class:`Strategy`), which is
   what the prior-year contract's caller wanted and could not ask for; ``seconds`` is what that
   route was chosen to minimise, so a caller can see the number rather than trust it.

5. The response names the field ``obstacle_id``, not ``image_id``. The value is the caller's
   obstacle number and the image on it is unknown until CV reads it, so the prior-year name
   described data that cannot exist when the request is sent. Renamed on the response only -
   the request still accepts ``image_id`` so ``openapi.json``, the fixtures and the simulator
   keep working. Agreed with the RPi owner before the change.

6. A response instruction may read ``PIVOT_LEFT_45``, ``PIVOT_RIGHT_45``, ``PIVOT_LEFT_90`` or
   ``PIVOT_RIGHT_90`` — a new member of :attr:`PathfindingResponseSegment.instructions`'
   existing union, appended so the other three keep their positions in the schema. Emitted only
   with ``config.PIVOT_TURNS`` on, which is off by default, so nothing reaches a caller until
   the flag is switched. **The four token strings are placeholders**: the RPi and STM owners
   have not agreed what the firmware expects, and settling on different names is one edit to
   :class:`~pathfinding.search.instructions.PivotInstruction`. Requests do not widen — see the
   note on :data:`CardinalDirection`.
7. ``PathfindingResponseSegment.end`` - new field, the car's stopping pose (centre, cm,
   heading), present even when ``verbose`` is false. It is what a mid-run re-plan feeds back
   as the tablet shape's ``robot``; see :func:`_android_robot`.
8. ``PathfindingResponseSegment.poses`` - new field, the pose after every instruction, aligned
   with ``instructions``. Verbose only. Replaces the RPi's own dead reckoning for the tablet's
   ROBOT marker.
9. ``PathfindingResponseSegment.centre_path`` - new field, the robot centre through the whole
   segment including inside turns, at most ``config.CENTRE_PATH_SPACING_CM`` apart along an
   arc. Verbose only. What the tablet draws the route from; ``path`` stays the rear-pivot cells
   it always was.

The reasoning behind all nine is in ``algorithm/PROVENANCE.md`` under "Design decisions".

Stub mode is selected per-request from ``current_app.config["MDP_STUB"]`` rather than by an
import-time flag, so the same module serves both modes and a test can flip it.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from typing import Literal

import numpy as np
from flask import current_app, make_response, request
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel, Field, model_validator

import config
from pathfinding.report import UnreachableReason
from pathfinding.search.instructions import (
    MiscInstruction, MoveInstruction, PivotInstruction, Straight, TurnInstruction,
)
from pathfinding.search.search import Segment, search
from pathfinding.search.tour import plan_optimal
from pathfinding.world.objective import generate_objectives
from pathfinding.world.primitives import Direction, Point, Vector
from pathfinding.world.world import Obstacle, Robot, World

logger = logging.getLogger(__name__)

api = APIBlueprint(
    "/pathfinding",
    __name__,
    url_prefix="/pathfinding",
    abp_tags=[Tag(name="Pathfinding")],
)


# ---------------------------------------------------------------------------------------
# Shared leaf models
#
# Declared before the models that reference them. The reference relied on forward
# references resolved by a pydantic rebuild; ordering them leaf-first means the models are
# complete the moment they are defined, which matters because flask-openapi3 introspects
# them at import to build the schema.
# ---------------------------------------------------------------------------------------


class PathfindingPoint(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)

    @classmethod
    def from_point(cls, point: Point) -> PathfindingPoint:
        return cls(x=point.x, y=point.y)

    def to_point(self) -> Point:
        return Point(self.x, self.y)


# The only headings a REQUEST may name. An obstacle face and the robot's start pose are
# physical facts about the arena, and all four are cardinal; the diagonals exist so the
# experimental eight-heading search can drive and turn through them (see `Direction`), never so
# a caller can declare one. Widening `Direction` for that experiment must not widen what the
# RPi is allowed to send - and it did: a face of NORTHWEST parsed, then fell out of the
# objective generator's match as None and became a 500 three frames later.
#
# A Literal of the four strings rather than a second enum: the published schema keeps exactly
# the four values it has always had, and an unknown one is a 422 from the schema layer, in
# pydantic's own error shape, before any of our code runs. The strings rather than the enum
# members because pydantic renders the members into the error message by repr - "Input should
# be <Direction.NORTH: 'NORTH'>, ..." - and the person reading that message is the RPi owner at
# 2 am. The cost is one `Direction(...)` at each use, alongside the `to_point()` conversions
# already there.
#
# Responses are NOT restricted: with the diagonals switched on, a path vector legitimately
# carries NORTHEAST and an instruction legitimately carries FORWARD_LEFT_45, and with
# `config.PIVOT_TURNS` on an instruction legitimately carries PIVOT_LEFT_90. Both are the same
# rule in the same direction - the planner chooses the motion primitives, the caller describes
# the arena - so neither widens this Literal. There is no request field a pivot could go in:
# a caller cannot ask for one, any more than it can ask for a BACKWARD_RIGHT. See
# docs/protocols/algorithm-service.md.
CardinalDirection = Literal["NORTH", "EAST", "SOUTH", "WEST"]


class PathfindingVector(BaseModel):
    direction: Direction = Field(description="The direction")
    x: int = Field(ge=0)
    y: int = Field(ge=0)

    @classmethod
    def from_vector(cls, vector: Vector) -> PathfindingVector:
        return cls(direction=vector.direction, x=vector.x, y=vector.y)

    def to_vector(self) -> Vector:
        return Vector(self.direction, self.x, self.y)


# ---------------------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------------------


class Strategy(str, Enum):
    """
    Which visiting order to plan.

    An enum rather than a free string, so an unknown value is a 422 from the schema instead of
    a silent fall-through to one of the two planners; the ``str`` mixin is what keeps it
    serialising as the bare ``"greedy"``/``"optimal"`` on the wire and in ``openapi.json``.

    ``OPTIMAL`` is the default because it is never worse than greedy on the planner's own score:
    at least as many obstacles photographed and, at equal count, no more driving time. Greedy's
    real route is one of the candidates it compares against (see
    :func:`~pathfinding.search.tour.plan_optimal`). ``GREEDY`` stays selectable because it is an order of
    magnitude quicker to plan, which matters when someone is iterating on an arena by hand,
    and because it is the behaviour every response before 2026-09-03 had - a caller comparing
    against a recorded plan needs to be able to ask for the old one.
    """

    GREEDY = "greedy"
    OPTIMAL = "optimal"


# ---------------------------------------------------------------------------------------
# The Android shape
# ---------------------------------------------------------------------------------------
#
# Android talks to the RPi over Bluetooth and the RPi relays the bytes WITHOUT translating
# them, so the tablet's payload is the request body this service receives:
#
#     {"command": "imageRec", "algorithm": "greedy",
#      "obstacles": [{"id": 1, "x": 10, "y": 6, "face": "N"}]}
#
# Four things differ from the canonical shape, and one of them is dangerous:
#
#   `id`            the honest name for what the canonical shape calls `image_id`
#   `face`          a single letter rather than the full cardinal
#   `x`, `y`        ONE point rather than two corners, and in 10 cm GRID CELLS, not cm
#   `robot`         OPTIONAL. Absent means the start corner facing north (the Task 1
#                   convention). Present, it is the car's CENTRE in cm plus a heading - the
#                   same shape every segment's `end` reports, so a mid-run re-plan hands one
#                   straight back as the other (checklist A.5, see `_android_robot`).
#
# The cells are the dangerous part. Read as centimetres, {"x": 10, "y": 6} places an obstacle
# at 10..19 x 6..15 - inside the robot's own 0..30 start box - so the failure is a physically
# impossible arena rather than a merely wrong route, and nothing in the canonical schema would
# have rejected it. Both ends of the conversion are therefore asserted against a hand-computed
# arena in `tests/test_android_request.py` rather than against this code's own output.
#
# Converting here, rather than giving Android its own route, is what keeps the canonical shape
# working: `testdata/*.json`, every other test module and the simulator all speak it, and the
# simulator carries checklist items B.1 to B.3.

_FACES = {"N": "NORTH", "E": "EAST", "S": "SOUTH", "W": "WEST"}

# The tablet indexes the arena in whole obstacle widths. Derived rather than written as 20 so
# that a change to either constant cannot leave this silently disagreeing with the arena.
_CELLS_ACROSS = config.ARENA_SIZE_CM // config.OBSTACLE_SIZE_CM

# The only task this service plans. Optional in the payload because the Android owner's first
# sample omitted it; an unrecognised value is still refused rather than assumed.
_COMMAND = "imageRec"

# Deferred, NOT unknown - worth a different message. Planning one of these as `optimal` would
# hand back a route that looks correct and ignores the setting, and the first evidence would be
# the robot driving arcs on competition day.
_DEFERRED_ALGORITHMS = {"turnInPlace"}


def _point(pair: tuple[int, int]) -> dict[str, int]:
    return {"x": pair[0], "y": pair[1]}


def _android_obstacle(index: int, obstacle: object) -> dict:
    """Convert one tablet obstacle into the canonical shape, or say precisely what is wrong."""
    if not isinstance(obstacle, dict):
        raise ValueError(f"obstacles[{index}] must be an object with id, x, y and face.")

    missing = [key for key in ("id", "x", "y", "face") if key not in obstacle]
    if missing:
        raise ValueError(
            f"obstacles[{index}] is missing {', '.join(missing)}; each obstacle needs id, x, y and face."
        )

    face = obstacle["face"]
    if face not in _FACES:
        raise ValueError(
            f"obstacles[{index}].face is {face!r}; expected one of {', '.join(sorted(_FACES))} - "
            f"the face the image is on."
        )

    cells = {}
    for axis in ("x", "y"):
        cell = obstacle[axis]
        # `bool` is an `int` in Python and True would otherwise convert to cell 1.
        if isinstance(cell, bool) or not isinstance(cell, int) or not 0 <= cell < _CELLS_ACROSS:
            raise ValueError(
                f"obstacles[{index}].{axis} is {cell!r}; it is a GRID CELL index and must be a "
                f"whole number in 0..{_CELLS_ACROSS - 1}. Centimetres are not accepted here - "
                f"cell {_CELLS_ACROSS // 2} means {_CELLS_ACROSS // 2 * config.OBSTACLE_SIZE_CM} cm."
            )
        cells[axis] = cell * config.OBSTACLE_SIZE_CM

    return {
        "image_id": obstacle["id"],
        "direction": _FACES[face],
        "south_west": _point((cells["x"], cells["y"])),
        "north_east": _point((cells["x"] + config.OBSTACLE_SIZE_CM - 1,
                              cells["y"] + config.OBSTACLE_SIZE_CM - 1)),
    }


# Half the planning footprint: centre +- this is a box of extent ROBOT_FOOTPRINT_CM - 1, which is
# even, so `Robot.planned`'s parity bump never fires and the pose is planned exactly as sent.
_HALF_FOOTPRINT = config.ROBOT_FOOTPRINT_CM // 2


def _android_robot(robot: object) -> dict:
    """
    The start pose of a tablet-shape request, in the canonical corners form.

    Absent, it is ``config.START_POSE`` - the Task 1 convention agreed with the Android owner.
    Present, it is the car's CENTRE in centimetres plus a heading, expanded to the planning
    footprint here. Centre-and-heading rather than corners, and centimetres rather than the
    cells the obstacles use, for one reason: it is exactly what every segment's ``end``
    reports, so the RPi re-plans from where the car stopped by handing ``end`` back as
    ``robot`` with no arithmetic in between. A cell would be too coarse to say where a car
    actually stopped, and corners would make the RPi do the +-15 itself.
    """
    if robot is None:
        return {
            "direction": config.START_POSE["direction"],
            "south_west": _point(config.START_POSE["south_west"]),
            "north_east": _point(config.START_POSE["north_east"]),
        }
    if not isinstance(robot, dict):
        raise ValueError("robot must be an object with x, y (the car's centre, in cm) and direction.")

    missing = [key for key in ("x", "y", "direction") if key not in robot]
    if missing:
        raise ValueError(
            f"robot is missing {', '.join(missing)}; send the car's centre x, y in centimetres and "
            f"its direction - the `end` of a previous segment is exactly this shape."
        )

    direction = robot["direction"]
    cardinals = tuple(_FACES.values())
    if direction not in cardinals:
        raise ValueError(f"robot.direction is {direction!r}; expected one of {', '.join(cardinals)}.")

    low, high = _HALF_FOOTPRINT, config.ARENA_SIZE_CM - 1 - _HALF_FOOTPRINT
    centre = {}
    for axis in ("x", "y"):
        value = robot[axis]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(
                f"robot.{axis} is {value!r}; it is the car's CENTRE in centimetres and must be a whole "
                f"number in {low}..{high}, so the {config.ROBOT_FOOTPRINT_CM} cm footprint stays inside "
                f"the arena. Not a grid cell."
            )
        centre[axis] = value

    return {
        "direction": direction,
        "south_west": _point((centre["x"] - _HALF_FOOTPRINT, centre["y"] - _HALF_FOOTPRINT)),
        "north_east": _point((centre["x"] + _HALF_FOOTPRINT, centre["y"] + _HALF_FOOTPRINT)),
    }


def _from_android(data: dict) -> dict:
    """
    Rewrite a tablet payload into the canonical request shape.

    Raised as ``ValueError`` rather than returning a partial request, so pydantic renders each
    one through the same 422 body as every other validation failure and the RPi has one error
    shape to read rather than two.
    """
    command = data.get("command", _COMMAND)
    if command != _COMMAND:
        raise ValueError(
            f"command {command!r} is not supported; this service plans {_COMMAND!r} (Task 1) only."
        )

    algorithm = data.get("algorithm", Strategy.OPTIMAL.value)
    if algorithm in _DEFERRED_ALGORITHMS:
        raise ValueError(
            f"algorithm {algorithm!r} is not implemented yet - send "
            f"{Strategy.GREEDY.value!r} or {Strategy.OPTIMAL.value!r}. Refused rather than "
            f"planned as arcs, so the setting cannot appear to work when it does nothing."
        )
    if algorithm not in {strategy.value for strategy in Strategy}:
        raise ValueError(
            f"algorithm {algorithm!r} is not one of "
            f"{Strategy.GREEDY.value!r} or {Strategy.OPTIMAL.value!r}."
        )

    obstacles = data.get("obstacles")
    if not isinstance(obstacles, list) or not obstacles:
        raise ValueError("obstacles must be a list holding at least one obstacle.")

    return {
        "verbose": data.get("verbose", True),
        "strategy": algorithm,
        "robot": _android_robot(data.get("robot")),
        "obstacles": [_android_obstacle(index, obstacle) for index, obstacle in enumerate(obstacles)],
    }


class PathfindingRequestRobot(BaseModel):
    direction: CardinalDirection = Field(description="The direction of the robot.")
    south_west: PathfindingPoint = Field(description="The south-west corner of the robot.")
    north_east: PathfindingPoint = Field(description="The north-east corner of the robot.")

    def to_robot(self) -> Robot:
        """Build the domain Robot. The parity bump lives in Robot.planned; see it for why."""
        return Robot.planned(Direction(self.direction), self.south_west.to_point(), self.north_east.to_point())


class PathfindingRequestObstacle(BaseModel):
    # ge=1 reproduces openapi.json's `minimum: 1` EXACTLY, and is deliberately looser than the
    # 1-40 range config declares. Tightening the schema here would be the tidier-looking
    # choice, but the schema is the published contract (AGENTS.md 2.2) and the RPi
    # client was generated from it. The narrower domain rule is enforced one layer down, in
    # Obstacle.__post_init__, and mapped to 422 by the route — see PROVENANCE.md and
    # `_construct_world`.
    image_id: int = Field(ge=1, description="The image ID.")
    direction: CardinalDirection = Field(description="The direction of the image.")
    south_west: PathfindingPoint = Field(description="The south-west corner of the obstacle.")
    north_east: PathfindingPoint = Field(description="The north-east corner of the obstacle.")

    def to_obstacle(self) -> Obstacle:
        return Obstacle(Direction(self.direction), self.south_west.to_point(), self.north_east.to_point(),
                        self.image_id)


class PathfindingRequest(BaseModel):
    verbose: bool = Field(
        default=True,
        description="Whether to attach the path and cost alongside the movement instructions in the response.",
    )
    # Additive and optional, so a client generated from the prior-year schema keeps working and
    # gets the better route without being changed. See Strategy on why optimal is the default.
    strategy: Strategy = Field(
        default=Strategy.OPTIMAL,
        description="Visiting order: 'optimal' (shortest estimated time, default) or 'greedy' (nearest first).",
    )
    robot: PathfindingRequestRobot = Field(description="The initial position of the robot.")
    obstacles: list[PathfindingRequestObstacle] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def accept_the_android_shape(cls, data: object) -> object:
        """
        Rewrite a tablet payload into this model's fields before validating it.

        The discriminator is the shape of ``robot``, and it is total rather than a guess: the
        canonical form requires ``robot`` and requires it to carry ``south_west``, while the
        tablet form either omits ``robot`` or gives a centre ``x``/``y``. So "a robot with
        corners" is canonical and everything else is the tablet's, with no sniffing at the
        obstacles. Converting in a ``before`` validator rather than on a second route is what
        keeps ``openapi.json``, the simulator and every ``testdata`` fixture speaking one shape
        while the tablet speaks another - see the "Android shape" block above for the
        conversion and why the units matter.
        """
        if not isinstance(data, dict):
            return data
        robot = data.get("robot")
        if isinstance(robot, dict) and "south_west" in robot:
            return data
        return _from_android(data)

    @model_validator(mode="after")
    def reject_duplicate_image_ids(self) -> PathfindingRequest:
        """
        Reject a request in which two obstacles share an ``image_id``.

        This is the right layer for the check: ``image_id`` is an identifier the *caller*
        assigns, so a collision is a malformed request, not a planning failure.

        Why it is load-bearing rather than pedantic. :class:`~pathfinding.search.search.
        SearchResult` promises that ``segments`` and ``unreachable`` partition the obstacles —
        every obstacle in exactly one list, no ``image_id`` in both. That promise is what makes
        the response readable at all: the RPi decides what the robot will and will not
        photograph by reading the two lists. With duplicate IDs the promise is *falsifiable
        while the check still passes* — image 11 can legitimately appear in both lists (one
        obstacle planned, the other not) and the multiset comparison in ``search()`` sees
        nothing wrong. A caller then cannot tell whether image 11 is being visited. Two
        obstacles are also value-identical if their corners and direction match, which
        collapses them into one dict key in ``ObjectiveGeneration.objectives`` and loses one
        outright.

        Rejecting is correct rather than merely convenient: two obstacles cannot carry the same
        image in the competition, so there is no legitimate request this refuses.
        """
        seen: set[int] = set()
        duplicates: set[int] = set()
        for obstacle in self.obstacles:
            if obstacle.image_id in seen:
                duplicates.add(obstacle.image_id)
            seen.add(obstacle.image_id)

        if duplicates:
            raise ValueError(
                f"image_id must be unique across obstacles; {sorted(duplicates)} appears more than once. "
                f"Each obstacle carries a different image, and the response identifies obstacles by "
                f"image_id alone."
            )

        return self


# ---------------------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------------------


class PathfindingResponseSegment(BaseModel):
    # Named for what it carries. The value is the caller's obstacle number, and in Task 1 the
    # image on that obstacle is unknown until CV reads it three hops later - so the prior-year
    # `image_id` named a value that cannot exist at the time the request is sent. Renamed on
    # the RESPONSE only: the request still accepts `image_id`, which is what openapi.json, the
    # testdata fixtures and the simulator speak. See PROVENANCE.md.
    obstacle_id: int = Field(description="The obstacle number the caller sent, echoed unchanged.")
    cost: int | None = Field(description="The cost, included only if verbose is true.")
    # `PivotInstruction` is APPENDED to the union, never spliced into it: the existing three
    # members keep their positions in the schema's `anyOf`, so a client generated from the
    # prior-year `openapi.json` sees an extra alternative rather than a reordered list. A pivot
    # reaches a caller only with `config.PIVOT_TURNS` on - see the note on `CardinalDirection`
    # for why the request side does NOT widen to match.
    instructions: list[MiscInstruction | TurnInstruction | MoveInstruction | PivotInstruction]
    path: list[PathfindingVector] | None = Field(
        description="The cells of the path in driving order, included only if verbose is true."
    )
    # Additive, and last so the reference's own key order is untouched. Not the same quantity as
    # `cost`, which stays centimetres of path: `seconds` prices the turns too, and a turn costs
    # config.TURN_TIME_S regardless of how few cells its arc happens to occupy. That is why the
    # optimiser minimises this one and not `cost`.
    seconds: float = Field(
        default=0.0,
        description="Estimated driving time of this segment in seconds under the time model, "
        "only if verbose is true.",
    )
    # Additive. Where the car stops for CAPTURE_IMAGE - its centre in cm and its heading, i.e.
    # the last `path` vector - but reported even when `verbose` is false, because a quiet caller
    # still needs it to re-plan: handed back as the tablet shape's `robot`, it re-plans from
    # where the car is (checklist A.5: standing at a face, bull's-eye seen, route to the next
    # face from HERE). None only when there is no geometry to report - stub mode, or a segment
    # in which the car did not move.
    end: PathfindingVector | None = Field(
        default=None,
        description="Where the car stops for CAPTURE_IMAGE: its centre in cm and its heading. "
        "Present regardless of verbose. Send it back as `robot` to re-plan from there.",
    )
    # Additive. The car's centre pose after EVERY instruction, one entry per entry of
    # `instructions` (CAPTURE_IMAGE repeats the last, so poses[-1] == end whenever `end` is set).
    # The exception is a segment in which the car does not move, because it already stands on
    # this obstacle's goal pose - two adjacent obstacles facing the same way can share one.
    # There are no vectors to take `end` from, so it is None, and the single pose, for
    # CAPTURE_IMAGE, is where the car already stands (the previous segment's last pose, or the
    # request's `robot` for the first segment). This is what the RPi should report to the tablet
    # after each command: the RPi's own dead reckoning carried a second copy of the turning radii
    # and a 45-degree formula of its own, and drifted 15-38 cm from the planned car within a
    # segment before snapping to `end`. With this it looks the pose up instead. Verbose only,
    # like `path`, as the RPi owner's handover specified: the RPi always asks verbose, and a
    # quiet response then carries no geometry but `end`, the one piece a re-plan needs, exactly
    # as before this field existed (the key is sent, as []). Empty in stub mode like `path`.
    poses: list[PathfindingVector] = Field(
        default_factory=list,
        description="The car's centre pose after each instruction, aligned one-to-one with "
        "`instructions`; the last equals `end` whenever `end` is set; in a segment where the car "
        "does not move, `end` is null and the single pose is where it already stands (the "
        "previous segment's last pose, or the request's `robot` for the first segment). Only "
        "when verbose. Report these to the tablet instead of dead-reckoning.",
    )
    # Additive. The robot centre through the whole segment, in driving order, INCLUDING inside
    # turns, where `path` holds the rear pivot's cells instead. Starts at the segment's start
    # pose, contains every entry of `poses`, and along an arc consecutive points are at most
    # config.CENTRE_PATH_SPACING_CM apart; a straight may be just its two ends. Verbose only,
    # like `path`; empty in stub mode for the same reason `end` is None there.
    centre_path: list[PathfindingPoint] = Field(
        default_factory=list,
        description="The robot centre through the segment in driving order, turns included, "
        "at most CENTRE_PATH_SPACING_CM (5 cm) between points along an arc. Only when verbose. "
        "Draw the route from this, not from `path`.",
    )

    @classmethod
    def from_segment(cls, verbose: bool, segment: Segment) -> PathfindingResponseSegment:
        # The reference emits 0 and [] when not verbose, not null, even though both fields are
        # declared nullable. Preserved verbatim: a client that switched on `cost is None` would
        # break against the reference too, and the frozen contract makes the reference's actual
        # behaviour the contract rather than the schema's permissiveness. `seconds` follows the
        # same rule for consistency rather than because a client depends on it, and so do
        # `poses` and `centre_path`: [] when quiet, so the key is there in both modes and a
        # client reads one shape.
        return cls(
            obstacle_id=segment.image_id,
            cost=segment.cost if verbose else 0,
            instructions=segment.instructions,
            path=[PathfindingVector.from_vector(vector) for vector in segment.vectors] if verbose else [],
            seconds=round(segment.seconds, 2) if verbose else 0.0,
            end=PathfindingVector.from_vector(segment.vectors[-1]) if segment.vectors else None,
            poses=[PathfindingVector.from_vector(pose) for pose in segment.poses] if verbose else [],
            centre_path=[PathfindingPoint.from_point(point) for point in segment.centre_path] if verbose else [],
        )


class PathfindingResponseUnreachable(BaseModel):
    """
    One obstacle the plan does not visit, and why. Additive — see this module's docstring.

    The two reasons are NOT interchangeable and the RPi should not collapse them: see
    :class:`~pathfinding.report.UnreachableReason`. ``NO_OBJECTIVES`` means no photographable
    pose exists (a geometry problem, usually the obstacle sitting too close to the wall it
    faces); ``NO_PATH`` means poses exist but this plan could not reach them from where it left
    the robot standing.
    """

    obstacle_id: int = Field(description="The obstacle number the caller sent, echoed unchanged.")
    reason: UnreachableReason = Field(
        description="Why the obstacle was dropped: NO_OBJECTIVES (no valid camera pose exists) "
        "or NO_PATH (poses exist, none reachable on this route)."
    )


class PathfindingResponse(BaseModel):
    segments: list[PathfindingResponseSegment] = Field(
        description="The data for moving the robot from the start/objective to another objective."
    )
    unreachable: list[PathfindingResponseUnreachable] = Field(
        default_factory=list,
        description="Obstacles the robot will NOT visit, with the reason for each. Additive "
        "field, absent from openapi.json. Together with `segments` this accounts for every "
        "obstacle in the request exactly once, so `len(segments) + len(unreachable)` always "
        "equals the number of obstacles sent.",
    )


# ---------------------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------------------


@api.post("/", responses={200: PathfindingResponse})
def pathfinding(body: PathfindingRequest):
    started = datetime.now()
    capture()

    if current_app.config.get("MDP_STUB"):
        response = make_response(stub(body).model_dump(mode="json"), HTTPStatus.OK)
        response.mimetype = "application/json"
        # An out-of-band marker, so a client can assert it is NOT wired to the stub without
        # the JSON body differing from a real response. A body field would change the
        # contract; a header cannot.
        response.headers["X-MDP-Stub"] = "true"
        logger.warning("STUB MODE: returned %s fabricated segment(s). No planning was done.", len(body.obstacles))
        return response

    # Request-derived construction is separated from the search because the two failure modes
    # get different status codes: a world that cannot be built is the caller's fault (422),
    # while a search that raises is ours (500). Collapsing them would report our bugs as the
    # RPi's.
    try:
        world = _construct_world(body)
    except _InvalidRequest as invalid:
        return make_response(invalid.body(), HTTPStatus.UNPROCESSABLE_ENTITY)

    objectives = generate_objectives(world)
    # The two planners take the same inputs and return the same type, so the strategy is a
    # one-line choice here rather than a branch through the response building below.
    result = search(world, objectives) if body.strategy is Strategy.GREEDY else plan_optimal(world, objectives)

    pathfinding_response = PathfindingResponse(
        segments=[
            PathfindingResponseSegment.from_segment(verbose=body.verbose, segment=segment)
            for segment in result.segments
        ],
        unreachable=[
            PathfindingResponseUnreachable(obstacle_id=entry.image_id, reason=entry.reason)
            for entry in result.unreachable
        ],
    )

    dump(world, result.segments)

    elapsed_ms = (datetime.now() - started).total_seconds() * 1000
    logger.info(
        "Planned %s/%s obstacles with the %s strategy in %.0f ms (%.2f s of driving); unreachable: %s",
        len(result.segments),
        len(world.obstacles),
        body.strategy.value,
        elapsed_ms,
        sum(segment.seconds for segment in result.segments),
        {entry.image_id: entry.reason.value for entry in result.unreachable} or "none",
    )

    response = make_response(pathfinding_response.model_dump(mode="json"), HTTPStatus.OK)
    response.mimetype = "application/json"
    return response


class _InvalidRequest(Exception):
    """
    A request that parsed against the schema but describes something unplannable.

    The body is rendered with pydantic's own key names — ``type``, ``loc``, ``msg`` — because
    flask-openapi3 renders *its* 422s straight from ``ValidationError.errors()``, and one error
    shape is worth more to the RPi than two. That means it does NOT match
    ``openapi.json``'s ``ValidationErrorModel``, which declares ``type_``: the reference's
    schema for that model did not match what the reference's own framework emitted either.
    Recorded in ``docs/protocols/algorithm-service.md``.

    ``loc`` keeps integers as integers for the same reason — pydantic indexes list positions
    with ``0``, not ``"0"``, and a client walking the path should not have to handle both.
    """

    def __init__(self, location: list[str | int], message: str, kind: str = "value_error"):
        super().__init__(message)
        self.location = location
        self.message = message
        self.kind = kind

    def body(self) -> list[dict]:
        return [{"type": self.kind, "loc": self.location, "msg": self.message}]


def _construct_world(body: PathfindingRequest) -> World:
    """
    Turn a parsed request into a :class:`~pathfinding.world.world.World`.

    Every failure reachable from here is a statement about the *request*, which is why they all
    become 422:

    - ``ValueError`` from ``Obstacle.__post_init__`` — ``image_id`` outside
      ``config.IMAGE_ID_MIN..IMAGE_ID_MAX``. Reachable because the schema's ``minimum: 1`` has
      no upper bound while the domain's range is 1-40; an id above 40 satisfies one and violates
      the other.
    - ``AssertionError`` from ``Entity.__post_init__`` — corners inverted
      (``north_east`` below ``south_west``) or not square.
    - ``AssertionError`` from ``World.__init__`` — an entity outside the grid.

    ``AssertionError`` is caught deliberately, and only over these calls. The planner uses bare
    asserts for its input preconditions, so on this path they *are* request validation and a
    500 would blame the wrong team. Two consequences worth knowing:

    - The planner's asserts carry no message, so the text below is written here rather than
      interpolated from the exception. The original is logged with a traceback so the specific
      failing assert is still recoverable from the server log.
    - Under ``python -O`` asserts vanish and a malformed request reaches the search instead.
      **Do not run the service with -O.**

    :raises _InvalidRequest: If the request cannot describe a world.
    """
    geometry_rule = ("corners must satisfy 0 <= south_west <= north_east and describe a square "
                     "(equal width and height)")

    try:
        robot = body.robot.to_robot()
    except AssertionError as error:
        logger.warning("Rejected robot pose %s", body.robot, exc_info=True)
        raise _InvalidRequest(["robot"], f"invalid robot pose: {geometry_rule}", "assertion_error") from error

    obstacles = []
    for index, requested in enumerate(body.obstacles):
        try:
            obstacles.append(requested.to_obstacle())
        except ValueError as error:
            # An image_id above 40 satisfies the schema's `minimum: 1` and violates the domain's
            # 1-40, which is the only ValueError a request can still reach: Obstacle also refuses
            # a diagonal face, but `CardinalDirection` has already turned that into a 422 against
            # `direction` at the schema. So the loc below is right for every reachable case, and
            # the message from Obstacle names the range and is passed through as-is.
            raise _InvalidRequest(["obstacles", index, "image_id"], str(error)) from error
        except AssertionError as error:
            logger.warning("Rejected obstacle %s at index %s", requested.image_id, index, exc_info=True)
            raise _InvalidRequest(["obstacles", index], f"invalid obstacle geometry: {geometry_rule}",
                                  "assertion_error") from error

    try:
        return World(config.GRID_SIZE, robot, obstacles)
    except AssertionError as error:
        # World's asserts do not say WHICH entity fell outside the grid, so neither does this,
        # rather than guessing at one. The bound is stated so the caller can find it themselves,
        # and the traceback in the log pins it down for us.
        logger.warning("Rejected world: an entity lies outside the grid", exc_info=True)
        raise _InvalidRequest(
            [],
            f"the robot or an obstacle lies outside the {config.GRID_SIZE}x{config.GRID_SIZE}-cell arena; "
            f"every corner must satisfy 0 <= value < {config.GRID_SIZE}",
            "assertion_error",
        ) from error


# ---------------------------------------------------------------------------------------
# Stub mode
# ---------------------------------------------------------------------------------------


def stub(body: PathfindingRequest) -> PathfindingResponse:
    """
    A schema-valid response with no planning behind it.

    This exists so the RPi and Android teams can integrate against the real wire format while
    the planner is still being fixed. It is shaped from the *request*, one segment per obstacle
    in the order sent, so a client exercises its whole receive-and-dispatch loop — segment
    count, instruction decoding, ``CAPTURE_IMAGE`` handshake — rather than a single frozen blob.

    Two deliberate choices keep it from being mistaken for a real plan:

    - ``path`` is always empty, even when ``verbose`` is true. Fabricated coordinates would let
      the simulator or the Android display render a route that looks plausible and is wrong,
      and a wrong picture is harder to debug than a missing one. The instruction stream is
      fabricated too, but a client must decode instructions to be tested at all; nothing needs
      to *believe* the path.
    - ``end`` is always ``None`` and ``poses`` and ``centre_path`` always empty, for the same
      reason as ``path``: a fabricated pose is one the RPi might feed back as ``robot`` or
      report to the tablet, and a fabricated centre line is one the tablet would draw as the
      route.
    - ``unreachable`` is always empty, so a client's happy path is what gets exercised. Point
      the client at the real planner to see genuine ``unreachable`` entries — an arena at the
      competition's legal 30 cm obstacle spacing will produce plenty (see ``algorithm/README.md``).

    The instructions are legal tokens in a legal order and the distances are plausible, but no
    geometry was computed: **do not drive a robot with this.**
    """
    segments = []
    for index, obstacle in enumerate(body.obstacles):
        segments.append(
            PathfindingResponseSegment(
                obstacle_id=obstacle.image_id,
                cost=100 + 10 * index if body.verbose else 0,
                instructions=[
                    MoveInstruction(move=Straight.FORWARD, amount=30),
                    TurnInstruction.FORWARD_RIGHT,
                    MoveInstruction(move=Straight.FORWARD, amount=10),
                    MiscInstruction.CAPTURE_IMAGE,
                ],
                path=[],
            )
        )

    return PathfindingResponse(segments=segments, unreachable=[])


# ---------------------------------------------------------------------------------------
# Diagnostics
#
# Both were called out in the audit as worth keeping. Neither is allowed to break a request:
# losing a debug artefact is not a reason to fail a plan the robot is waiting for.
# ---------------------------------------------------------------------------------------


def capture() -> None:
    """
    Write the raw request body to ``config.REPLAY_DIR/<timestamp>.json``.

    Being able to replay the exact arena that failed at 2 am is worth more than it costs. The
    file is the untouched bytes, so it can be fed straight back with ``curl -d @<file>``.

    The reference built the filename with a PEP-701 nested-quote f-string, which is a syntax
    error before Python 3.12. The timestamp is now a separate statement.
    """
    try:
        os.makedirs(config.REPLAY_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        with open(os.path.join(config.REPLAY_DIR, f"{timestamp}.json"), "w") as file:
            file.write(request.get_data(as_text=True))
    except OSError:
        logger.warning("Could not write replay capture to %s", config.REPLAY_DIR, exc_info=True)


def dump(world: World, segments: list[Segment]) -> None:
    """
    Write an ASCII picture of the grid and the planned path to ``config.DUMP_PATH``.

    Legend: ``0`` blocked (obstacle keep-out or boundary band), ``1`` free, ``9`` the obstacle
    footprints themselves, and ``2, 3, 4, ...`` the cells of segment 1, 2, 3, ... The array is
    rotated so that north is up and the text reads like the arena looks.
    """
    try:
        grid = np.array(world.grid, dtype=int)

        for obstacle in world.obstacles:
            west_x = max(obstacle.south_west.x, 0)
            east_x = min(obstacle.north_east.x + 1, world.size)
            south_y = max(obstacle.south_west.y, 0)
            north_y = min(obstacle.north_east.y + 1, world.size)
            grid[west_x:east_x, south_y:north_y] = 9

        for index, segment in enumerate(segments):
            for vector in segment.vectors:
                grid[vector.x, vector.y] = index + 2

        np.savetxt(config.DUMP_PATH, np.rot90(grid), fmt="%d")
    except OSError:
        logger.warning("Could not write grid dump to %s", config.DUMP_PATH, exc_info=True)
