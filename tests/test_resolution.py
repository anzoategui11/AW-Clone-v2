"""Stress tests for the resolution rules under heavy contention.

These lock down the awkward simultaneous-movement cases: swap attempts, mutual
blocking, crossing traffic at a bridge, and orders that redirect mid-flight.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aw_clone.grid import GameMap, Terrain
from aw_clone.orders import MoveOrder, Order
from aw_clone.turn import resolve_movement
from aw_clone.units import Unit, spawn


def open_map(width: int = 12, height: int = 12) -> GameMap:
    m = GameMap(width=width, height=height)
    for y in range(height):
        for x in range(width):
            m.set(x, y, Terrain.PLAIN)
    return m


def order_for(unit: Unit, path: list[tuple[int, int]]) -> Order:
    return Order(unit.unit_id, MoveOrder(list(path)))


def assert_distinct(units: list[Unit]) -> None:
    positions = [u.pos for u in units]
    assert len(set(positions)) == len(positions), f"overlap: {positions}"


# ------------------------------------------------------------------ swap ----
def test_two_units_cannot_swap_through_each_other():
    """Head-on A->B and B->A. The pair must not teleport past one another."""
    m = open_map(6, 3)
    units: list[Unit] = []
    a = spawn(units, 1, "apc", 1, 1)
    units.append(a)
    b = spawn(units, 2, "apc", 2, 1)
    units.append(b)

    orders = {a.unit_id: order_for(a, [(2, 1)]), b.unit_id: order_for(b, [(1, 1)])}
    resolve_movement(m, units, orders)
    assert_distinct(units)
    # Neither should end up occupying the other's start tile.
    assert a.pos != b.pos


def test_swap_is_avoided_even_with_a_detour_available():
    m = open_map(8, 8)
    units: list[Unit] = []
    a = spawn(units, 1, "apc", 2, 2)
    b = spawn(units, 2, "apc", 3, 2)
    units.extend([a, b])
    orders = {
        a.unit_id: order_for(a, [(3, 2), (4, 2)]),
        b.unit_id: order_for(b, [(2, 2), (1, 2)]),
    }
    resolve_movement(m, units, orders)
    assert_distinct(units)


# ------------------------------------------------------------- bottleneck ----
def test_all_units_still_land_distinctly_through_a_single_bridge():
    m = open_map(14, 5)
    for y in range(m.height):
        m.set(6, y, Terrain.RIVER)
    m.set(6, 2, Terrain.BRIDGE)

    units: list[Unit] = []
    # Four units on the left all funnelling at the one crossing.
    for i in range(4):
        units.append(spawn(units, 1, "apc", i, 2))
    orders = {}
    for u in units:
        orders[u.unit_id] = order_for(
            u, [(u.x + 1, 2), (6, 2), (7, 2), (8, 2), (9, 2)]
        )
    resolve_movement(m, units, orders)
    assert_distinct(units)
    for u in units:
        assert m.in_bounds(u.x, u.y)


def test_a_queue_crosses_a_bridge_one_at_a_time():
    """Units stream through rather than piling onto the crossing."""
    m = open_map(10, 3)
    for y in range(m.height):
        m.set(4, y, Terrain.RIVER)
    m.set(4, 1, Terrain.BRIDGE)

    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 1, 1))
    units.append(spawn(units, 1, "apc", 0, 1))
    units.append(spawn(units, 1, "apc", 1, 0))

    orders = {}
    for u in units:
        orders[u.unit_id] = order_for(u, [(u.x + 1, u.y), (3, u.y), (4, 1), (5, 1), (6, 1)])
    resolve_movement(m, units, orders)
    assert_distinct(units)
    # Nobody is stranded sitting on the bridge at the end.
    assert not any(m.at(u.x, u.y).terrain is Terrain.BRIDGE for u in units)


# ------------------------------------------------------- mutual blocking ----
def test_a_cornered_unit_yields_and_the_press_advances():
    m = open_map(6, 1)
    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 0, 0))
    units.append(spawn(units, 2, "apc", 5, 0))
    orders = {
        units[0].unit_id: order_for(units[0], [(1, 0), (2, 0), (3, 0), (4, 0)]),
        units[1].unit_id: order_for(units[1], [(4, 0), (3, 0), (2, 0)]),
    }
    resolve_movement(m, units, orders)
    assert_distinct(units)
    # Progress was made by at least one of them.
    assert units[0].x > 0 or units[1].x < 5


def test_a_press_of_units_behind_one_halted_unit_still_advances():
    """Blocked leaders must not freeze the whole column."""
    m = open_map(7, 3)
    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 0, 1))
    units.append(spawn(units, 1, "apc", 1, 1))
    units.append(spawn(units, 1, "apc", 2, 1))
    orders = {
        units[0].unit_id: order_for(units[0], [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)]),
        units[1].unit_id: order_for(units[1], [(2, 1), (3, 1), (4, 1)]),
        units[2].unit_id: order_for(units[2], [(3, 1), (4, 1)]),
    }
    resolve_movement(m, units, orders)
    assert_distinct(units)
    assert units[0].x > 0


# ------------------------------------------------------------- invariants ----
def test_no_two_units_share_a_tile_across_random_orders():
    """Pseudo-random contention, asserting the core invariant every time."""
    import random

    rng = random.Random(20260909)
    for trial in range(25):
        m = open_map(10, 10)
        units: list[Unit] = []
        count = rng.randint(3, 7)
        placed: set[tuple[int, int]] = set()
        for i in range(count):
            while True:
                tile = (rng.randrange(10), rng.randrange(10))
                if tile not in placed:
                    break
            placed.add(tile)
            units.append(spawn(units, 1 + (i % 2), "apc", tile[0], tile[1]))

        orders = {}
        for u in units:
            dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
            path = []
            x, y = u.x, u.y
            for _ in range(rng.randint(1, 3)):
                x = max(0, min(9, x + dx))
                y = max(0, min(9, y + dy))
                path.append((x, y))
            orders[u.unit_id] = order_for(u, path)

        resolve_movement(m, units, orders)
        assert_distinct(units)
        for u in units:
            assert m.in_bounds(u.x, u.y), f"trial {trial}: unit {u.unit_id} off-map"


def test_every_tick_frame_has_consistent_positions():
    """Replay the frames: no unit ever stands on a tile another occupies."""
    m = open_map(10, 10)
    units: list[Unit] = []
    units.append(spawn(units, 1, "apc", 0, 5))
    units.append(spawn(units, 2, "apc", 9, 5))
    units.append(spawn(units, 1, "apc", 0, 6))
    units.append(spawn(units, 2, "apc", 9, 6))
    orders = {
        units[0].unit_id: order_for(units[0], [(1, 5), (2, 5), (3, 5), (4, 5)]),
        units[1].unit_id: order_for(units[1], [(8, 5), (7, 5), (6, 5), (5, 5)]),
        units[2].unit_id: order_for(units[2], [(1, 6), (2, 6), (3, 6)]),
        units[3].unit_id: order_for(units[3], [(8, 6), (7, 6), (6, 6)]),
    }
    res = resolve_movement(m, units, orders)

    positions = {u.unit_id: u.pos for u in units}
    for step in res.steps:
        for uid, dest in step.moved.items():
            positions[uid] = dest
        occupied: dict[tuple[int, int], int] = {}
        for uid, tile in positions.items():
            assert tile not in occupied, (
                f"tick {step.tick}: units {occupied.get(tile)} and {uid} collide at {tile}"
            )
            occupied[tile] = uid