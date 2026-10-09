"""The cost model, end to end.

Covers orthogonal-only movement, how the single step cost composes with terrain
penalties, and that the resolver spends exactly what the planner costed.
"""

from __future__ import annotations

import heapq
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aw_clone.config import IMPASSABLE_PENALTY, STEP_COST
from aw_clone.grid import (
    DIRECTIONS,
    GameMap,
    Terrain,
    find_path,
    is_adjacent,
    path_cost,
    reachable,
)
from aw_clone.orders import MoveOrder, Order
from aw_clone.turn import resolve_movement
from aw_clone.units import spawn


def make_map(width: int, height: int, rng: random.Random, terrain_choices) -> GameMap:
    m = GameMap(width=width, height=height)
    for y in range(height):
        for x in range(width):
            m.set(x, y, rng.choice(terrain_choices))
    return m


def dijkstra_cost(game_map, start, goal, movement_class) -> int | None:
    """Ground-truth cheapest cost, independent of the A* implementation."""
    if start == goal:
        return 0
    dist = {start: 0}
    frontier = [(0, start)]
    while frontier:
        cost, current = heapq.heappop(frontier)
        if cost > dist.get(current, 1 << 30):
            continue
        if current == goal:
            return cost
        for dx, dy in DIRECTIONS:
            nxt = (current[0] + dx, current[1] + dy)
            if not game_map.passable(nxt[0], nxt[1], movement_class):
                continue
            candidate = cost + game_map.enter_cost(movement_class, nxt)
            if candidate < dist.get(nxt, 1 << 30):
                dist[nxt] = candidate
                heapq.heappush(frontier, (candidate, nxt))
    return None


# ------------------------------------------------- orthogonal movement ----
def test_there_is_only_one_step_cost_and_it_is_one():
    assert STEP_COST == 1
    assert GameMap.step_cost() == 1


def test_no_direction_is_diagonal():
    for dx, dy in DIRECTIONS:
        assert not (dx and dy), f"({dx},{dy}) is a diagonal"


def test_is_adjacent_rejects_diagonals_and_leaps():
    assert is_adjacent((2, 3), (2, 4))
    assert is_adjacent((2, 3), (3, 3))
    assert not is_adjacent((2, 3), (3, 4))
    assert not is_adjacent((2, 3), (9, 3))


# ------------------------------------------------------ composition ----
def test_cost_is_step_plus_terrain_penalty():
    m = GameMap(width=5, height=5)
    for y in range(5):
        for x in range(5):
            m.set(x, y, Terrain.PLAIN)
    m.set(2, 1, Terrain.MOUNTAIN)

    # Plain is free for infantry, so the step cost stands alone.
    assert m.enter_cost("boot", (1, 0)) == STEP_COST
    # Tracks still pay a plain penalty.
    assert m.enter_cost("tread", (1, 0)) == STEP_COST + 1
    # The mountain penalty stacks on top, and blocks tracks entirely.
    assert m.enter_cost("boot", (2, 1)) == STEP_COST + 3
    assert m.enter_cost("tread", (2, 1)) >= IMPASSABLE_PENALTY


def test_forest_costs_infantry_more_than_plain():
    m = GameMap(width=5, height=5)
    for y in range(5):
        for x in range(5):
            m.set(x, y, Terrain.PLAIN)
    m.set(1, 0, Terrain.FOREST)
    assert m.enter_cost("boot", (1, 0)) == STEP_COST + 1


def test_cost_accumulates_over_every_tile_entered():
    """Each tile in the path is charged, not just the destination."""
    m = GameMap(width=6, height=6)
    for y in range(6):
        for x in range(6):
            m.set(x, y, Terrain.PLAIN)
    m.set(1, 2, Terrain.FOREST)
    # Three steps, one of which crosses a forest penalty.
    assert path_cost(m, [(1, 0), (1, 1), (1, 2)], "boot") == 3 + 1


def test_road_steps_cost_exactly_one():
    m = GameMap(width=6, height=6)
    for y in range(6):
        for x in range(6):
            m.set(x, y, Terrain.ROAD)
    assert path_cost(m, [(1, 0), (2, 0), (3, 0)], "boot") == 3


def test_impassable_terrain_is_a_wall_for_ground():
    m = GameMap(width=6, height=6)
    for y in range(6):
        for x in range(6):
            m.set(x, y, Terrain.PLAIN)
    for y in range(6):
        m.set(3, y, Terrain.SEA)
    assert find_path(m, (0, 0), (5, 0), "boot") is None
    assert find_path(m, (0, 0), (5, 0), "air") is not None


# --------------------------------------------------- A* stays optimal ----
def test_astar_cost_matches_dijkstra_on_random_maps():
    """The diagonal tie-break must not compromise optimality."""
    rng = random.Random(4242)
    terrains = [
        Terrain.PLAIN,
        Terrain.PLAIN,
        Terrain.PLAIN,
        Terrain.ROAD,
        Terrain.FOREST,
        Terrain.MOUNTAIN,
        Terrain.BRIDGE,
    ]
    checked = 0
    for _ in range(30):
        m = make_map(10, 10, rng, terrains)
        start = (0, 0)
        for goal in [(9, 9), (7, 3), (2, 8), (5, 5)]:
            path = find_path(m, start, goal, "boot")
            best = dijkstra_cost(m, start, goal, "boot")
            if path is None:
                assert best is None, f"A* found nothing but {best} is reachable"
                continue
            assert best is not None
            actual = path_cost(m, path, "boot")
            assert actual == best, (
                f"A* cost {actual} but optimal is {best}: {path}"
            )
            # And every step it takes is orthogonal.
            previous = start
            for tile in path:
                assert is_adjacent(previous, tile), f"non-orthogonal step {previous}->{tile}"
                previous = tile
            checked += 1
    assert checked > 20


def test_astar_cost_matches_dijkstra_for_treads_too():
    rng = random.Random(99)
    terrains = [Terrain.PLAIN, Terrain.ROAD, Terrain.MOUNTAIN, Terrain.FOREST]
    for _ in range(20):
        m = make_map(10, 10, rng, terrains)
        goal = (9, 4)
        path = find_path(m, (0, 4), goal, "tread")
        best = dijkstra_cost(m, (0, 4), goal, "tread")
        if path is None:
            assert best is None
            continue
        assert path_cost(m, path, "tread") == best


def test_reachable_matches_dijkstra_cost_on_random_maps():
    """The move-range overlay must agree with the pathfinder."""
    rng = random.Random(7)
    terrains = [Terrain.PLAIN, Terrain.ROAD, Terrain.FOREST, Terrain.MOUNTAIN]
    for _ in range(15):
        m = make_map(9, 9, rng, terrains)
        budget = 6
        got = reachable(m, (0, 0), budget, "boot")
        for tile, remaining in got.items():
            if tile == (0, 0):
                continue
            best = dijkstra_cost(m, (0, 0), tile, "boot")
            assert best is not None and best <= budget
            assert budget - best == remaining, (
                f"{tile}: reported {remaining} left, Dijkstra says {best} spent"
            )


# ------------------------------------------- planner and resolver agree ----
def test_a_unit_ends_where_the_planner_path_ends():
    """Resolution must consume exactly the budget the planner costed."""
    m = GameMap(width=14, height=6)
    for y in range(6):
        for x in range(14):
            m.set(x, y, Terrain.PLAIN)
    for y in range(6):
        m.set(4, y, Terrain.ROAD)

    units = []
    units.append(spawn(units, 1, "apc", 0, 0))  # 8 points
    goal = (4, 0)  # road at the end of the run
    path = find_path(m, units[0].pos, goal, units[0].movement_class)
    assert path is not None
    cost = path_cost(m, path, units[0].movement_class)
    assert cost <= units[0].unit_type.move_points

    orders = {units[0].unit_id: Order(units[0].unit_id, MoveOrder(path))}
    res = resolve_movement(m, units, orders)
    assert res.arrived[units[0].unit_id] == goal
    # One frame per tile, one tile per frame.
    assert len(res.steps) == len(path)


def test_a_unit_stops_early_rather_than_overdrawing_its_budget():
    m = GameMap(width=14, height=3)
    for y in range(3):
        for x in range(14):
            m.set(x, y, Terrain.PLAIN)
    units = []
    units.append(spawn(units, 1, "infantry", 0, 0))  # 6 points, plain is free
    orders = {
        units[0].unit_id: Order(
            units[0].unit_id, MoveOrder([(x, 0) for x in range(1, 9)])
        )
    }
    res = resolve_movement(m, units, orders)
    # Six plain tiles is all 6 points buy.
    assert res.arrived[units[0].unit_id] == (6, 0)
    assert orders[units[0].unit_id].move.pending_blocked is False


def test_a_tracked_unit_is_capped_by_its_plain_penalty():
    """The same budget buys fewer plain tiles for treads than for infantry."""
    m = GameMap(width=14, height=3)
    for y in range(3):
        for x in range(14):
            m.set(x, y, Terrain.PLAIN)
    units = []
    units.append(spawn(units, 1, "apc", 0, 0))  # 8 points, tread plain = 2
    orders = {
        units[0].unit_id: Order(
            units[0].unit_id, MoveOrder([(x, 0) for x in range(1, 12)])
        )
    }
    res = resolve_movement(m, units, orders)
    assert res.arrived[units[0].unit_id] == (4, 0)