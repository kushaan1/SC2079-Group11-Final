"""
What a move costs. Two models: DISTANCE_CELLS is the search's original objective (grid cells,
arc_length cells per turn); TIME_SECONDS is the estimate the optimiser minimises and the
simulator clock shows. Both read config at call time.
"""
from __future__ import annotations

from typing import Iterable, Protocol

import config
from pathfinding.search.instructions import Move, Turn, TurnInstruction


class Weights(Protocol):
    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float: ...

    def straight(self, cells: int, cell_size: int = 1) -> float: ...


class _Distance:
    """
    The search's original objective: grid cells. A straight costs its cell count and a turn
    costs ``arc_length`` in cells, so the two halves add. Consumers that want centimetres
    multiply by ``cell_size`` themselves (the simulator does); at the default 1 cm cell the two
    are the same number.
    """

    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        return turn.arc_length(cell_size)

    def straight(self, cells: int, cell_size: int = 1) -> float:
        return cells


class _Time:
    """Estimated seconds: a flat charge per turn, distance over speed per straight."""

    def turn(self, turn: TurnInstruction, cell_size: int = 1) -> float:
        return config.TURN_TIME_S

    def straight(self, cells: int, cell_size: int = 1) -> float:
        return cells * cell_size / config.ROBOT_SPEED_CM_S


DISTANCE_CELLS: Weights = _Distance()
TIME_SECONDS: Weights = _Time()


def move_cost(move: Turn | Move, weights: Weights, cell_size: int) -> float:
    """The cost of one move under ``weights``."""
    if isinstance(move, Turn):
        return weights.turn(move.turn, cell_size)
    return weights.straight(len(move.vectors), cell_size)


def seconds(moves: Iterable[Turn | Move], cell_size: int) -> float:
    """Estimated driving time of a sequence of moves under the time model."""
    return sum((move_cost(m, TIME_SECONDS, cell_size) for m in moves), 0.0)
