"""Grid, terrain, and move-point pathfinding."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import Enum

from .config import IMPASSABLE_PENALTY, MOVE_PENALTIES, STEP_COST


class Terrain(str, Enum):
    PLAIN = "plain"
    ROAD = "road"
    FOREST = "forest"
    MOUNTAIN = "mountain"
    RIVER = "river"
    BRIDGE = "bridge"
    SEA = "sea"
    HQ = "hq"


@dataclass
class Tile:
    terrain: Terrain = Terrain.PLAIN
    # Ocean edge tiles: coastal water, cannot be entered by ground units.
    #: ``owner`` marks HQ/capture tiles so the UI can tint them per faction.

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Tile({self.terrain.value})"


@dataclass
class GameMap:
    width: int
    height: int
    tiles: list[list[Tile]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tiles:
            self.tiles = [
                [Tile(Terrain.PLAIN) for _ in range(self.width)]
                for _ in range(self.height)
            ]

    # ------------------------------------------------------------ access ----
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def at(self, x: int, y: int) -> Tile:
        return self.tiles[y][x]

    def set(self, x: int, y: int, terrain: Terrain) -> None:
        self.tiles[y][x] = Tile(terrain)

    # ------------------------------------------------------------- costs ----
    @staticmethod
    def step_cost() -> int:
        """Move points for one orthogonal step. There is only one step cost."""
        return STEP_COST

    @staticmethod
    def terrain_penalty(movement_class: str, terrain: Terrain) -> int:
        """Extra move points this terrain charges on top of the step."""
        return MOVE_PENALTIES[movement_class][terrain.value]

    def enter_cost(self, movement_class: str, tile: tuple[int, int]) -> int:
        """Move points to enter ``tile``.

        Every step costs the same, so this depends only on the destination
        terrain and not on where the unit came from.
        """
        return STEP_COST + self.terrain_penalty(movement_class, self.at(*tile).terrain)

    def passable(self, x: int, y: int, movement_class: str) -> bool:
        """Whether a tile can be entered at all, regardless of direction."""
        if not self.in_bounds(x, y):
            return False
        return (
            self.terrain_penalty(movement_class, self.at(x, y).terrain)
            < IMPASSABLE_PENALTY
        )


# Orthogonal movement only. There are no diagonals: every route across the board
# is a sum of up, down, left and right steps, as in Advance Wars 2.
DIRECTIONS: tuple[tuple[int, int], ...] = (
    (0, -1),
    (1, 0),
    (0, 1),
    (-1, 0),
)


def is_adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Whether ``b`` is one orthogonal step from ``a``.

    Guards against malformed paths. Diagonals are rejected too, since they are
    not a legal move.
    """
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return (dx, dy) == (1, 0) or (dx, dy) == (0, 1)


# Stand-in for "no budget", used when a caller only wants reachability. Far more
# than any real route could cost.
NO_BUDGET = 1 << 30


def search(
    game_map: GameMap,
    start: tuple[int, int],
    budget: int,
    movement_class: str,
    blocked: set[tuple[int, int]] | None = None,
    passable_only: set[tuple[int, int]] | None = None,
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], tuple[int, int]]]:
    """Cheapest cost to reach every tile within ``budget``.

    This is the single search behind both the move-range overlay and
    pathfinding, so the two can never disagree about what a unit can afford.
    Returns the move points spent reaching each tile and, for each, the tile it
    was reached from.

    ``blocked`` holds tiles that cannot be entered at all, such as enemy units.

    ``passable_only`` holds tiles that may be crossed but never stopped on, such
    as a friendly unit standing in the way. They take precedence over
    ``blocked``, so a friendly unit is transparent rather than acting as a wall,
    but they still cost whatever the tile costs like any other: crossing one is
    not a shortcut.

    This is a plain Dijkstra shared by both callers. An A* used to sit in front
    of this, but on a map this size the search is instant either way and one
    implementation is easier to keep honest than two.
    """
    blocked = blocked or set()
    passable_only = passable_only or set()

    spent: dict[tuple[int, int], int] = {start: 0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    # Heap keyed by negative remaining points, so we expand the richest first.
    frontier: list[tuple[int, int, int, int]] = [(-budget, start[0], start[1], 0)]

    while frontier:
        _, cx, cy, cost = heapq.heappop(frontier)
        if cost > spent.get((cx, cy), NO_BUDGET):
            continue
        for dx, dy in DIRECTIONS:
            nx, ny = cx + dx, cy + dy
            if not game_map.passable(nx, ny, movement_class):
                continue
            # Crossable tiles win over `blocked`: a unit may pass through one
            # even though it may not stand on it. The start is never blocked.
            if (nx, ny) in blocked and (nx, ny) not in passable_only and (nx, ny) != start:
                continue
            new_cost = cost + game_map.enter_cost(movement_class, (nx, ny))
            if new_cost > budget:
                continue
            if new_cost >= spent.get((nx, ny), NO_BUDGET):
                continue
            spent[(nx, ny)] = new_cost
            came_from[(nx, ny)] = (cx, cy)
            heapq.heappush(frontier, (-(budget - new_cost), nx, ny, new_cost))
    return spent, came_from


def reachable(
    game_map: GameMap,
    start: tuple[int, int],
    budget: int,
    movement_class: str,
    blocked: set[tuple[int, int]] | None = None,
    passable_only: set[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], int]:
    """Tiles reachable within ``budget``, mapped to move points remaining.

    ``passable_only`` tiles are left out of the result: a unit may cross one but
    may not come to rest on it, so nothing downstream should offer it as a
    destination.
    """
    passable_only = passable_only or set()
    spent, _ = search(game_map, start, budget, movement_class, blocked, passable_only)
    return {
        tile: budget - cost
        for tile, cost in spent.items()
        if tile not in passable_only
    }


def find_path(
    game_map: GameMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    movement_class: str,
    blocked: set[tuple[int, int]] | None = None,
    budget: int | None = None,
    passable_only: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]] | None:
    """Cheapest route from ``start`` to ``goal``, or ``None`` if unreachable.

    Returns the tile list *excluding* the start tile. ``budget`` caps the move
    points spent; omit it for a pure reachability query. The route may pass
    through ``passable_only`` tiles but may not end on one.
    """
    passable_only = passable_only or set()
    if start == goal:
        return []
    if goal in passable_only or goal in (blocked or set()):
        return None

    spent, came_from = search(
        game_map,
        start,
        NO_BUDGET if budget is None else budget,
        movement_class,
        blocked,
        passable_only,
    )
    if goal not in spent:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    path.reverse()
    return path[1:]