"""Headless tests for the pure logic. No pygame import anywhere in here."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from aw_clone.turn import TurnPlan, resolve_movement
from aw_clone.units import UNIT_TYPES, Unit, spawn


def blank_map(width: int = 10, height: int = 10, terrain=Terrain.PLAIN) -> GameMap:
    m = GameMap(width=width, height=height)
    for y in range(height):
        for x in range(width):
            m.set(x, y, terrain)
    return m


def diagonal_steps(start: tuple[int, int], path: list[tuple[int, int]]) -> int:
    """Count diagonal steps in a path. Should always be zero now."""
    count = 0
    previous = start
    for tile in path:
        if tile[0] != previous[0] and tile[1] != previous[1]:
            count += 1
        previous = tile
    return count


# ------------------------------------------------------------------ grid ----
def test_movement_is_orthogonal_only():
    """As in Advance Wars 2: up, down, left, right. No diagonals."""
    assert set(DIRECTIONS) == {(0, -1), (1, 0), (0, 1), (-1, 0)}
    for dx, dy in DIRECTIONS:
        assert (dx == 0) != (dy == 0), "every direction must be purely orthogonal"


def test_every_step_costs_the_same():
    assert GameMap.step_cost() == 1


def test_on_zero_penalty_terrain_any_route_costs_the_manhattan_distance():
    """Manhattan distance is exact, and detours cost nothing extra."""
    m = blank_map(width=9, height=9)
    for y in range(9):
        for x in range(9):
            m.set(x, y, Terrain.ROAD)
    # L-shaped and Z-shaped routes both cost 8 to cross a 4x4 block.
    elbow = [(1, 0), (2, 0), (3, 0), (4, 0), (4, 1), (4, 2), (4, 3), (4, 4)]
    assert path_cost(m, elbow, "boot") == 8
    assert len(elbow) == abs(4 - 0) + abs(4 - 0)


def test_a_diagonal_offset_is_not_a_single_step():
    """is_adjacent must reject diagonals as well as long leaps."""
    assert is_adjacent((0, 0), (1, 0))
    assert is_adjacent((0, 0), (0, 1))
    assert is_adjacent((0, 0), (-1, 0))
    assert is_adjacent((0, 0), (0, -1))
    assert not is_adjacent((0, 0), (1, 1))
    assert not is_adjacent((0, 0), (2, 0))


def test_terrain_penalties_differ_by_movement_class():
    assert GameMap.terrain_penalty("boot", Terrain.FOREST) == 1
    assert GameMap.terrain_penalty("tread", Terrain.FOREST) == 3
    assert GameMap.terrain_penalty("boot", Terrain.MOUNTAIN) == 3


def test_enter_cost_is_the_step_plus_the_terrain_penalty():
    m = blank_map()  # all plain
    # Plain has no penalty for infantry, so a step is exactly 1.
    assert m.enter_cost("boot", (1, 0)) == 1

    # Tracked vehicles still pay a plain penalty.
    assert m.enter_cost("tread", (1, 0)) == 2

    m.set(1, 0, Terrain.ROAD)
    assert m.enter_cost("tread", (1, 0)) == 1


def test_terrain_penalty_stacks_with_the_step_cost():
    m = blank_map()
    m.set(1, 0, Terrain.MOUNTAIN)
    assert m.enter_cost("boot", (1, 0)) == 1 + 3


def test_air_ignores_terrain_entirely():
    m = blank_map()
    m.set(1, 1, Terrain.MOUNTAIN)
    assert m.enter_cost("air", (1, 1)) == 1


def test_mountains_block_treads_but_not_boots():
    m = blank_map()
    m.set(5, 5, Terrain.MOUNTAIN)
    assert not m.passable(5, 5, "tread")
    assert m.passable(5, 5, "boot")


def test_sea_is_impassable_for_ground_but_fine_for_air():
    m = blank_map()
    m.set(3, 3, Terrain.SEA)
    assert not m.passable(3, 3, "boot")
    assert not m.passable(3, 3, "tread")
    assert m.passable(3, 3, "air")


# --------------------------------------------------------------- movement ----
def test_a_six_point_infantryman_covers_six_plains():
    """Plain is free for infantry, so a step costs exactly 1."""
    m = blank_map()
    got = reachable(m, (0, 0), 6, "boot")
    assert got[(6, 0)] == 0  # six tiles, budget spent
    assert (7, 0) not in got


def test_tracked_units_get_one_fewer_plain_tile_for_the_same_budget():
    """The plain penalty is per movement class, not global."""
    m = blank_map()
    assert reachable(m, (0, 0), 6, "tread")[(3, 0)] == 0
    assert (4, 0) not in reachable(m, (0, 0), 6, "tread")


def test_reaching_an_offset_tile_takes_the_sum_of_both_offsets():
    """With no diagonals, (3,3) is six steps away, not four."""
    m = blank_map()
    got = reachable(m, (0, 0), 6, "boot")
    assert got[(3, 3)] == 0  # 3 across + 3 down
    assert (4, 4) not in got  # would need 8 steps


def test_move_range_is_a_diamond_not_a_square():
    """Orthogonal-only movement produces a diamond-shaped reach envelope.

    Starts in the middle of a wide map so all four axes are on the board.
    """
    m = blank_map(width=11, height=11)
    got = reachable(m, (5, 5), 4, "boot")
    for corner in [(9, 5), (5, 9), (1, 5), (5, 1)]:
        assert corner in got, f"{corner} should be exactly four steps away"
    # A square corner would be eight steps away, so it must be unreachable.
    for far in [(9, 9), (1, 9), (9, 1), (1, 1)]:
        assert far not in got, f"{far} should be out of reach on 4 points"


def test_reach_envelope_is_exactly_manhattan_distance():
    m = blank_map(width=11, height=11)
    got = reachable(m, (5, 5), 3, "boot")
    for x in range(11):
        for y in range(11):
            distance = abs(x - 5) + abs(y - 5)
            if distance <= 3:
                assert (x, y) in got, f"({x},{y}) at distance {distance} should be in reach"
            else:
                assert (x, y) not in got, f"({x},{y}) at distance {distance} should not"


def test_roads_are_cheaper_so_budget_covers_more_tiles():
    m = blank_map()
    for x in range(m.width):
        for y in range(m.height):
            m.set(x, y, Terrain.ROAD)
    # Road has no penalty, so a step is exactly 1.
    assert reachable(m, (0, 0), 6, "boot")[(6, 0)] == 0
    assert (7, 0) not in reachable(m, (0, 0), 6, "boot")


def test_blocked_tiles_are_never_returned():
    m = blank_map()
    got = reachable(m, (0, 0), 10, "boot", blocked={(1, 0)})
    assert (1, 0) not in got


# ------------------------------------------------------------- pathfinding ----
def test_path_excludes_the_start_tile():
    m = blank_map()
    path = find_path(m, (0, 0), (3, 0), "boot")
    assert path[0] == (1, 0)
    assert path[-1] == (3, 0)
    assert (0, 0) not in path


def test_path_respects_budget_and_returns_none_when_over():
    m = blank_map()
    # Plain is free for infantry, so nine tiles costs nine points.
    assert find_path(m, (0, 0), (9, 0), "boot", budget=8) is None
    assert find_path(m, (0, 0), (9, 0), "boot", budget=9) is not None


def test_path_cost_matches_the_cost_table():
    m = blank_map()
    m.set(1, 0, Terrain.ROAD)
    path = [(1, 0), (2, 0)]
    # road step (1 + 0) then plain step (1 + 0) for infantry
    assert path_cost(m, path, "boot") == 2
    # the same route is dearer for a tracked vehicle on plain
    assert path_cost(m, path, "tread") == 3


def test_path_cost_is_one_per_tile_on_roads():
    m = blank_map()
    for x in range(m.width):
        for y in range(m.height):
            m.set(x, y, Terrain.ROAD)
    assert path_cost(m, [(1, 0), (2, 0)], "boot") == 2
    assert path_cost(m, [(1, 1), (1, 2), (1, 3)], "boot") == 3


def test_astar_finds_the_road_gap_in_a_mountain_wall():
    """A road pass is worth a detour across impassable-looking ground."""
    m = blank_map(width=9, height=9)
    for y in range(9):
        m.set(4, y, Terrain.MOUNTAIN)  # full wall
    m.set(4, 4, Terrain.ROAD)  # the only cheap crossing
    path = find_path(m, (0, 4), (8, 4), "boot")
    assert path is not None
    assert (4, 4) in path, "should route through the road gap"


def test_astar_crosses_the_wall_over_the_peak_when_there_is_no_road():
    """Without a pass, boots go over the mountain; tracks cannot."""
    m = blank_map(width=9, height=9)
    for y in range(9):
        m.set(4, y, Terrain.MOUNTAIN)

    booted = find_path(m, (0, 4), (8, 4), "boot")
    assert booted is not None

    tracked = find_path(m, (0, 4), (8, 4), "tread")
    assert tracked is None, "a tracked vehicle cannot climb the wall"


def test_astar_never_produces_a_diagonal_step():
    """Paths are sums of orthogonal moves only, whatever the terrain."""
    m = blank_map(width=9, height=9)
    for movement_class in ("boot", "tread"):
        path = find_path(m, (0, 0), (4, 4), movement_class)
        assert path is not None
        assert diagonal_steps((0, 0), path) == 0
        for i, tile in enumerate(path):
            previous = (0, 0) if i == 0 else path[i - 1]
            assert is_adjacent(previous, tile)


def test_astar_routes_around_a_diagonal_only_gap():
    """With no diagonals, a hole must be skirted orthogonally."""
    m = blank_map(width=7, height=7)
    for x in range(7):
        for y in range(7):
            if x + y == 6 and x == 3:
                m.set(x, y, Terrain.SEA)  # block a would-be diagonal shortcut
    path = find_path(m, (0, 0), (6, 6), "boot")
    assert path is not None
    assert (3, 3) not in path, "must not cut through the blocked tile"
    assert diagonal_steps((0, 0), path) == 0


def test_astar_cost_on_roads_equals_the_manhattan_distance():
    """No penalties anywhere, so the route costs exactly the step count."""
    m = blank_map(width=9, height=9)
    for y in range(9):
        for x in range(9):
            m.set(x, y, Terrain.ROAD)
    path = find_path(m, (0, 0), (4, 4), "boot")
    assert path is not None
    assert path_cost(m, path, "boot") == 8
    assert len(path) == 8  # 4 across + 4 down, no diagonals
    assert diagonal_steps((0, 0), path) == 0


# ------------------------------------------------------------- turn plan ----
def test_move_range_excludes_the_unit_own_tile_blocking_others():
    m = blank_map()
    units = [Unit(1, 1, UNIT_TYPES["infantry"], 0, 0)]
    units.append(spawn(units, 2, "infantry", 2, 0))
    plan = TurnPlan(m, units, active_owner=1)
    rng = plan.move_range(units[0])
    assert (0, 0) in rng  # own tile is included for rendering
    assert (2, 0) not in rng  # occupied by the enemy


def test_set_move_stores_the_path_and_rejects_unreachable():
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    plan = TurnPlan(m, units, active_owner=1)
    assert plan.set_move(units[0], (3, 0)) is True
    assert plan.order_for(1).move.path[-1] == (3, 0)
    assert plan.set_move(units[0], (9, 9)) is False


# ------------------------------------------------------- simultaneous move ----
def make_pair(m: GameMap):
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    units.append(spawn(units, 1, "infantry", 0, 1))
    return units


def test_all_units_advance_on_the_same_tick():
    m = blank_map()
    units = make_pair(m)
    orders = {
        1: Order(1, MoveOrder([(1, 0), (2, 0), (3, 0)])),
        2: Order(2, MoveOrder([(0, 2), (1, 2), (2, 2)])),
    }
    res = resolve_movement(m, units, orders)
    assert res.steps[0].moved == {1: (1, 0), 2: (0, 2)}
    assert units[0].pos == (3, 0)
    assert units[1].pos == (2, 2)


def test_head_to_head_contention_resolves_by_unit_id():
    """Both want the same tile. Lower id wins, the loser reroutes or halts."""
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    units.append(spawn(units, 2, "infantry", 4, 0))
    orders = {
        1: Order(1, MoveOrder([(1, 0), (2, 0)])),
        2: Order(2, MoveOrder([(3, 0), (2, 0)])),
    }
    resolve_movement(m, units, orders)
    # Unit 1 holds the contested tile; unit 2 does not end up on top of it.
    assert units[0].pos == (2, 0)
    assert units[1].pos != units[0].pos


def test_units_never_finish_stacked_on_one_tile():
    """The core invariant, checked across a pile-on of same-destination orders."""
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    units.append(spawn(units, 2, "infantry", 0, 2))
    units.append(spawn(units, 1, "infantry", 2, 0))
    orders = {
        1: Order(1, MoveOrder([(1, 0), (2, 0)])),
        2: Order(2, MoveOrder([(1, 1), (2, 0)])),
        3: Order(3, MoveOrder([(3, 0), (2, 0)])),
    }
    resolve_movement(m, units, orders)
    positions = [u.pos for u in units]
    assert len(set(positions)) == len(positions)
    # The lowest id keeps the contested square; the others hold or reroute.
    assert units[0].pos == (2, 0)


def test_a_unit_follows_through_a_gap_the_leader_opens():
    """Plain is free for infantry, so a 4-tile path completes with points to spare."""
    m = blank_map(width=10, height=3)
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 1))
    units.append(spawn(units, 2, "infantry", 0, 0))
    orders = {
        1: Order(1, MoveOrder([(1, 1), (2, 1), (3, 1), (4, 1)])),
        2: Order(2, MoveOrder([(1, 0), (2, 0), (3, 0), (4, 0)])),
    }
    res = resolve_movement(m, units, orders)
    assert units[0].pos == (4, 1)
    assert units[1].pos == (4, 0)
    assert len(res.steps) == 4  # one frame per tick, both moved together


def test_a_slower_tracked_unit_trails_an_infantry_leader():
    """The class difference now shows on plain: 8 tracked points vs 6 infantry."""
    m = blank_map(width=12, height=3)
    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 0, 1))  # tread, 8 pts, 2 per plain = 4
    units.append(spawn(units, 2, "infantry", 0, 0))  # boot, 6 pts, 1 per plain = 6
    orders = {
        1: Order(1, MoveOrder([(x, 1) for x in range(1, 7)])),
        2: Order(2, MoveOrder([(x, 0) for x in range(1, 9)])),
    }
    resolve_movement(m, units, orders)
    assert units[0].pos == (4, 1)  # tracked unit pays 2 per plain tile
    assert units[1].pos == (6, 0)  # infantry pays 1


def test_move_points_run_out_partway_and_the_unit_halts():
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 0, 0))  # 8 points, plain costs 2
    orders = {1: Order(1, MoveOrder([(x, 0) for x in range(1, 9)]))}
    res = resolve_movement(m, units, orders)
    assert units[0].pos == (4, 0)  # exactly 4 tiles on 8 points
    assert res.arrived[1] == (4, 0)
    # Running out of budget is not the same as being blocked.
    assert orders[1].move.pending_blocked is False


def test_spending_the_budget_is_not_reported_as_blocked():
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))  # 6 pts, 1 per plain tile
    orders = {1: Order(1, MoveOrder([(x, 0) for x in range(1, 9)]))}
    resolve_movement(m, units, orders)
    assert units[0].pos == (6, 0)  # stops where the budget runs out
    # Running out of budget is not being blocked.
    assert orders[1].move.pending_blocked is False


def test_a_malformed_path_does_not_teleport_a_unit_for_free():
    """Step cost reads only the offset's sign, so a leap would look cheap.

    The planner never emits non-adjacent tiles, but the resolver refuses them
    rather than letting a six-tile jump cost a single point.
    """
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    orders = {1: Order(1, MoveOrder([(6, 0)]))}  # one illegal six-tile leap
    resolve_movement(m, units, orders)
    assert units[0].pos == (0, 0)
    assert orders[1].move.pending_blocked is True


def test_resolution_is_deterministic_across_repeated_runs():
    def run():
        m = blank_map(width=12, height=12)
        units: list[Unit] = []
        for i in range(6):
            units.append(spawn(units, 1 if i % 2 else 2, "infantry", i % 5, 5 + (i % 2)))
        orders = {
            u.unit_id: Order(u.unit_id, MoveOrder([(u.x + 1, u.y), (u.x + 2, u.y)]))
            for u in units
        }
        resolve_movement(m, units, orders)
        return [u.pos for u in units]

    results = {tuple(run()) for _ in range(5)}
    assert len(results) == 1


def test_resolve_without_orders_is_a_no_op():
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 2, 2))
    res = resolve_movement(m, units, {})
    assert res.steps == []
    assert units[0].pos == (2, 2)


def test_queued_orders_are_not_mutated_by_resolution():
    """Resolution copies paths; the plan must stay intact for re-resolution."""
    m = blank_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    original = [(1, 0), (2, 0)]
    order = Order(1, MoveOrder(list(original)))
    resolve_movement(m, units, {1: order})
    assert order.move.path == original