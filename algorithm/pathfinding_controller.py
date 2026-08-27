# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
The HTTP surface of the planner: request/response models and the ``POST /pathfinding/`` route.

This module is the ONLY place in ``algorithm/`` that knows about HTTP. Everything below it
speaks in domain types (``World``, ``Obstacle``, ``SearchResult``) and raises domain errors;
this layer decides how those become status codes and JSON.

**The wire contract is fixed** (AGENTS.md 2.2). The RPi's client was generated from the
prior-year team's OpenAPI schema, so the request shape and the route are reproduced from their
controller field for field, including choices this file would otherwise make differently (see
:meth:`PathfindingResponseSegment.from_segment` on ``verbose``). There are exactly three
deliberate departures, all additive or error-path-only, and all recorded in
``docs/protocols/algorithm-service.md``:

1. ``PathfindingResponse.unreachable`` — new field. The obstacles the robot will NOT visit,
   with a reason each. Without it a dropped obstacle is invisible to the caller: the response
   simply has one fewer segment than the request had obstacles, and the warning goes to stdout
   on the planning machine.
2. Duplicate ``image_id``\\ s are rejected with 422 rather than accepted. See
   :meth:`PathfindingRequest.reject_duplicate_image_ids`.
3. An ``image_id`` that satisfies the schema's ``minimum: 1`` but falls outside
   ``config.IMAGE_ID_MIN..IMAGE_ID_MAX`` returns 422, not 500.

The reasoning behind all three is in ``algorithm/PROVENANCE.md`` under "Design decisions".

Stub mode is selected per-request from ``current_app.config["MDP_STUB"]`` rather than by an
import-time flag, so the same module serves both modes and a test can flip it.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from http import HTTPStatus

import numpy as np
from flask import current_app, make_response, request
from flask_openapi3 import APIBlueprint, Tag
from pydantic import BaseModel, Field, model_validator

import config
from pathfinding.report import UnreachableReason
from pathfinding.search.instructions import MiscInstruction, MoveInstruction, Straight, TurnInstruction
from pathfinding.search.search import Segment, search
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


class PathfindingRequestRobot(BaseModel):
    direction: Direction = Field(description="The direction of the robot.")
    south_west: PathfindingPoint = Field(description="The south-west corner of the robot.")
    north_east: PathfindingPoint = Field(description="The north-east corner of the robot.")

    def to_robot(self) -> Robot:
        """
        Build the domain :class:`~pathfinding.world.world.Robot`, applying the parity bump.

        The turning geometry assumes the robot's centre cell is genuinely central, which holds
        only when both corner extents are even — i.e. when the footprint in cells is odd. An
        odd extent is therefore bumped by one, so a robot declared as spanning 0..29 (30 cm) is
        planned as 0..30 (31 cm).

        This is the same rule as :func:`config.planned_footprint_cm`, expressed corner-wise
        because that is what a request gives us. It is reproduced from the reference
        controller verbatim rather than rewritten, because the constant it implies
        (``config.ROBOT_FOOTPRINT_CM = 31``) was chosen to match what this expression actually
        does.

        **Known duplication:** the parity rule is implemented three times — here, in
        ``config.planned_footprint_cm``, and in ``smoke.py:make_robot``. Unifying them is
        deliberately deferred, because the three call sites take different inputs (corners,
        a scalar footprint, corners again) and collapsing them risks changing behaviour for
        no functional gain. If a fourth copy appears, unify them.
        """
        south_west = self.south_west.to_point()
        north_east = self.north_east.to_point()

        if (north_east.x - south_west.x) % 2 != 0 and (north_east.y - south_west.y) % 2 != 0:
            north_east = Point(north_east.x + 1, north_east.y + 1)

        return Robot(self.direction, south_west, north_east)


class PathfindingRequestObstacle(BaseModel):
    # ge=1 reproduces openapi.json's `minimum: 1` EXACTLY, and is deliberately looser than the
    # 11-40 range config declares. Tightening the schema here would be the tidier-looking
    # choice, but the schema is the published contract (AGENTS.md 2.2) and the RPi
    # client was generated from it. The narrower domain rule is enforced one layer down, in
    # Obstacle.__post_init__, and mapped to 422 by the route — see PROVENANCE.md and
    # `_construct_world`.
    image_id: int = Field(ge=1, description="The image ID.")
    direction: Direction = Field(description="The direction of the image.")
    south_west: PathfindingPoint = Field(description="The south-west corner of the obstacle.")
    north_east: PathfindingPoint = Field(description="The north-east corner of the obstacle.")

    def to_obstacle(self) -> Obstacle:
        return Obstacle(self.direction, self.south_west.to_point(), self.north_east.to_point(), self.image_id)


class PathfindingRequest(BaseModel):
    verbose: bool = Field(
        default=True,
        description="Whether to attach the path and cost alongside the movement instructions in the response.",
    )
    robot: PathfindingRequestRobot = Field(description="The initial position of the robot.")
    obstacles: list[PathfindingRequestObstacle] = Field(min_length=1)

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
    image_id: int
    cost: int | None = Field(description="The cost, included only if verbose is true.")
    instructions: list[MiscInstruction | TurnInstruction | MoveInstruction]
    path: list[PathfindingVector] | None = Field(
        description="The path (unordered), included only if verbose is true."
    )

    @classmethod
    def from_segment(cls, verbose: bool, segment: Segment) -> PathfindingResponseSegment:
        # The reference emits 0 and [] when not verbose, not null, even though both fields are
        # declared nullable. Preserved verbatim: a client that switched on `cost is None` would
        # break against the reference too, and the frozen contract makes the reference's actual
        # behaviour the contract rather than the schema's permissiveness.
        return cls(
            image_id=segment.image_id,
            cost=segment.cost if verbose else 0,
            instructions=segment.instructions,
            path=[PathfindingVector.from_vector(vector) for vector in segment.vectors] if verbose else [],
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

    image_id: int
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
    result = search(world, objectives)

    pathfinding_response = PathfindingResponse(
        segments=[
            PathfindingResponseSegment.from_segment(verbose=body.verbose, segment=segment)
            for segment in result.segments
        ],
        unreachable=[
            PathfindingResponseUnreachable(image_id=entry.image_id, reason=entry.reason)
            for entry in result.unreachable
        ],
    )

    dump(world, result.segments)

    elapsed_ms = (datetime.now() - started).total_seconds() * 1000
    logger.info(
        "Planned %s/%s obstacles in %.0f ms; unreachable: %s",
        len(result.segments),
        len(world.obstacles),
        elapsed_ms,
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
      ``config.IMAGE_ID_MIN..IMAGE_ID_MAX``. Reachable because the schema's ``minimum: 1`` is
      looser than the domain's 11-40; IDs 1-10 satisfy one and violate the other.
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
            # An image_id of 1-10 satisfies the schema and violates the domain. This
            # is the only route from a well-formed request to a domain ValueError, so the
            # message from Obstacle names the range and is passed through as-is.
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
                image_id=obstacle.image_id,
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
