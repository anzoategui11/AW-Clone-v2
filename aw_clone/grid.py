"""Grid, terrain, and A* pathfinding over move points."""

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


def reachable(
    game_map: GameMap,
    start: tuple[int, int],
    budget: int,
    movement_class: str,
    blocked: set[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], int]:
    """Dijkstra flood-fill of every tile reachable within ``budget``.

    Returns a mapping of tile -> remaining move points. ``blocked`` holds tiles
    occupied by other units; they can never be entered.
    """
    blocked = blocked or set()
    best: dict[tuple[int, int], int] = {start: budget}
    # Heap keyed by negative remaining points, so we expand the richest first.
    frontier: list[tuple[int, int, int, int]] = [(-budget, start[0], start[1], 0)]
    seen_cost: dict[tuple[int, int], int] = {start: 0}

    while frontier:
        neg_remaining, cx, cy, spent = heapq.heappop(frontier)
        if spent > seen_cost.get((cx, cy), 1 << 30):
            continue
        remaining = -neg_remaining
        for dx, dy in DIRECTIONS:
            nx, ny = cx + dx, cy + dy
            if not game_map.passable(nx, ny, movement_class):
                continue
            if (nx, ny) in blocked and (nx, ny) != start:
                continue
            cost = game_map.enter_cost(movement_class, (nx, ny))
            new_spent = spent + cost
            if new_spent > budget:
                continue
            if new_spent < seen_cost.get((nx, ny), 1 << 30):
                seen_cost[(nx, ny)] = new_spent
                new_remaining = budget - new_spent
                best[(nx, ny)] = new_remaining
                heapq.heappush(frontier, (-new_remaining, nx, ny, new_spent))
    return best


def find_path(
    game_map: GameMap,
    start: tuple[int, int],
    goal: tuple[int, int],
    movement_class: str,
    blocked: set[tuple[int, int]] | None = None,
    budget: int | None = None,
) -> list[tuple[int, int]] | None:
    """A* from ``start`` to ``goal``, or ``None`` if unreachable.

    Returns the tile list *excluding* the start tile. ``budget`` caps the total
    move points spent; omit it for a pure reachability query.
    """
    blocked = blocked or set()
    if start == goal:
        return []

    def heuristic(x: int, y: int) -> int:
        # Manhattan distance, which is the exact number of orthogonal steps
        # needed to reach a tile on featureless ground. Terrain penalties are
        # non-negative, so ignoring them keeps this admissible.
        return abs(x - goal[0]) + abs(y - goal[1])

    frontier: list[tuple[int, int, tuple[int, int]]] = [(heuristic(*start), 0, start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}

    while frontier:
        _, g, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return path[1:]
        if g > g_score.get(current, 1 << 30):
            continue

        cx, cy = current
        for dx, dy in DIRECTIONS:
            nx, ny = cx + dx, cy + dy
            if not game_map.passable(nx, ny, movement_class):
                continue
            if (nx, ny) in blocked:
                continue
            tentative = g + game_map.enter_cost(movement_class, (nx, ny))
            if budget is not None and tentative > budget:
                continue
            if tentative < g_score.get((nx, ny), 1 << 30):
                g_score[(nx, ny)] = tentative
                came_from[(nx, ny)] = current
                heapq.heappush(
                    frontier, (tentative + heuristic(nx, ny), tentative, (nx, ny))
                )
    return None


def path_cost(
    game_map: GameMap,
    path: list[tuple[int, int]],
    movement_class: str,
) -> int:
    """Total move points spent walking ``path``.

    Every step costs the same, so this is a plain sum over the tiles entered.
    """
    total = 0
    for tile in path:
        total += game_map.enter_cost(movement_class, tile)
    return total