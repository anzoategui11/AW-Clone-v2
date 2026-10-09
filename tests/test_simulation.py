"""Integration tests: full turns, AI behaviour, and map invariants."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aw_clone import ai
from aw_clone.grid import Terrain, path_cost
from aw_clone.orders import MoveOrder, Order
from aw_clone.scenario import build_map, new_game, setup_units
from aw_clone.turn import TurnPlan, resolve_movement
from aw_clone.units import Unit, spawn


def assert_no_overlap(units: list[Unit]) -> None:
    seen: dict[tuple[int, int], int] = {}
    for u in units:
        if not u.alive:
            continue
        assert u.pos not in seen, (
            f"units {seen.get(u.pos)} and {u.unit_id} both occupy {u.pos}"
        )
        seen[u.pos] = u.unit_id


def assert_on_map(game_map, units: list[Unit]) -> None:
    for u in units:
        if u.alive:
            assert game_map.in_bounds(u.x, u.y), f"unit {u.unit_id} left the map"


# ------------------------------------------------------------------ map ----
def test_scenario_map_is_symmetric_enough_to_be_fair():
    m = build_map()
    assert m.width == 24 and m.height == 16
    # Two HQs, mirrored corners.
    assert m.at(1, 1).terrain is Terrain.HQ
    assert m.at(m.width - 2, m.height - 2).terrain is Terrain.HQ


def test_scenario_has_crossings_so_both_sides_can_engage():
    """The river must not be an impassable wall: bridges are the chokepoints."""
    m = build_map()
    river_x = m.width // 2
    bridges = [y for y in range(m.height) if m.at(river_x, y).terrain is Terrain.BRIDGE]
    assert len(bridges) >= 2, "need at least two ways across"


def test_starting_forces_are_mirror_images():
    m = build_map()
    units = setup_units(m)
    blue = sorted((u.unit_type.key, u.x, u.y) for u in units if u.owner == 1)
    red = sorted((u.unit_type.key, u.x, u.y) for u in units if u.owner == 2)
    assert len(blue) == len(red) == 6
    # Each red unit mirrors a blue unit across the map.
    mirrored = sorted(
        (key, m.width - 1 - x, m.height - 1 - y) for key, x, y in red
    )
    assert blue == mirrored


def test_units_do_not_start_in_impassable_terrain():
    m, units = new_game()
    for u in units:
        assert m.passable(u.x, u.y, u.movement_class), (
            f"{u.unit_type.name} starts on impassable {m.at(u.x, u.y).terrain}"
        )


# --------------------------------------------------- simultaneous movement ----
def test_both_factions_move_on_the_same_ticks():
    """The core promise: Blue and Red advance together, not in sequence."""
    m, units = new_game()
    orders = {}
    for u in units:
        step = 1 if u.owner == 1 else -1
        # Paths are built tile by tile: the resolver only accepts adjacent
        # steps, since step cost reads the offset's direction.
        path = [(u.x + step * i, u.y) for i in range(1, 4)]
        orders[u.unit_id] = Order(u.unit_id, MoveOrder(path))
    res = resolve_movement(m, units, orders)

    assert res.steps, "nothing moved"
    first = res.steps[0].moved
    blue_moved = [uid for uid in first if units[uid - 1].owner == 1]
    red_moved = [uid for uid in first if units[uid - 1].owner == 2]
    assert blue_moved and red_moved, (
        f"both factions must move on tick 0, got blue={blue_moved} red={red_moved}"
    )


def test_turns_keep_the_board_consistent_over_many_rounds():
    """Run the AI against itself for a dozen turns; assert invariants hold."""
    m, units = new_game()

    for turn in range(12):
        blue_orders = ai.plan_turn(m, units, 1)
        red_orders = ai.plan_turn(m, units, 2)
        combined = {**blue_orders, **red_orders}
        resolve_movement(m, units, combined)

        assert_no_overlap(units)
        assert_on_map(m, units)
        for u in units:
            u.reset_for_turn()


def test_ai_units_close_the_distance_between_the_sides():
    """Red should advance meaningfully over a few turns."""
    m, units = new_game()

    def mean_blue_x() -> float:
        blue = [u.x for u in units if u.owner == 1]
        return sum(blue) / len(blue)

    def mean_red_x() -> float:
        red = [u.x for u in units if u.owner == 2]
        return sum(red) / len(red)

    start_gap = mean_blue_x() - mean_red_x()
    for _ in range(4):
        orders = ai.plan_turn(m, units, 2)
        resolve_movement(m, units, orders)
        for u in units:
            u.reset_for_turn()
    end_gap = mean_blue_x() - mean_red_x()
    assert end_gap > start_gap, "Red never closed the distance"


def test_ai_never_issues_an_order_it_cannot_pay_for():
    """Every AI path must fit inside the unit's move-point budget."""
    m, units = new_game()
    orders = ai.plan_turn(m, units, 2)
    assert orders, "AI produced no orders"
    for unit_id, order in orders.items():
        unit = next(u for u in units if u.unit_id == unit_id)
        cost = path_cost(m, order.move.path, unit.movement_class)
        assert cost <= unit.unit_type.move_points, (
            f"unit {unit_id} path costs {cost} > {unit.unit_type.move_points}"
        )


def test_ai_moves_are_valid_orders_for_the_plan_system():
    m, units = new_game()
    orders = ai.plan_turn(m, units, 2)
    for unit_id, order in orders.items():
        unit = next(u for u in units if u.unit_id == unit_id)
        assert m.passable(*order.move.destination, unit.movement_class)


def test_ai_only_paths_through_tiles_that_will_be_clear():
    """A route may cross a friendly unit's tile only if that unit is moving.

    This is the AI side of the ordering rule: tiles occupied by units with no
    orders are hard blockers, tiles vacated by an ordered unit are fair game.
    """
    m, units = new_game()
    orders = ai.plan_turn(m, units, 2)

    occupied_by = {u.pos: u for u in units if u.alive}
    moving_away = {
        next(u for u in units if u.unit_id == uid).pos
        for uid, order in orders.items()
        if order.has_any()
    }

    for unit_id, order in orders.items():
        unit = next(u for u in units if u.unit_id == unit_id)
        for tile in order.move.path:
            blocker = occupied_by.get(tile)
            if blocker is None or blocker.unit_id == unit_id:
                continue
            assert blocker.owner == unit.owner and tile in moving_away, (
                f"unit {unit_id} paths through {tile}, still held by unit "
                f"{blocker.unit_id} which was not ordered away"
            )


def test_ai_never_orders_two_units_to_the_same_destination():
    """The endpoint is what gets reserved, so no two AI units may share one."""
    m, units = new_game()
    orders = ai.plan_turn(m, units, 2)
    seen: dict[tuple[int, int], int] = {}
    for unit_id, order in sorted(orders.items()):
        if not order.has_any():
            continue
        destination = order.move.destination
        assert destination not in seen, (
            f"units {seen[destination]} and {unit_id} both ordered to {destination}"
        )
        seen[destination] = unit_id


def test_ai_does_not_step_onto_an_enemy_unit():
    """No combat yet, so an enemy tile is never a legal endpoint or waypoint."""
    m, units = new_game()
    orders = ai.plan_turn(m, units, 2)
    enemy_tiles = {u.pos for u in units if u.owner == 1 and u.alive}
    for order in orders.values():
        for tile in order.move.path:
            assert tile not in enemy_tiles, f"AI routed through enemy tile {tile}"


def test_sides_close_and_then_jostle_without_overlapping():
    """Long AI-vs-AI run: forces meet, and the no-overlap rule still holds.

    This is the case that used to break: units converging on the same bridge.
    """
    m, units = new_game()
    for turn in range(25):
        combined = {**ai.plan_turn(m, units, 1), **ai.plan_turn(m, units, 2)}
        resolve_movement(m, units, combined)
        assert_no_overlap(units)
        assert_on_map(m, units)
        for u in units:
            u.reset_for_turn()

    blue = [u.x for u in units if u.owner == 1]
    red = [u.x for u in units if u.owner == 2]
    # They should be in the same neighbourhood by now, not still at their bases.
    assert abs(sum(blue) / len(blue) - sum(red) / len(red)) < 6


def test_planning_and_ai_orders_resolve_without_crashing():
    m, units = new_game()
    plan = TurnPlan(m, units, active_owner=1)
    for unit in plan.controllable:
        plan.set_move(unit, (unit.x + 2, unit.y))
    red = ai.plan_turn(m, units, 2)
    combined = {**plan.orders, **red}
    res = resolve_movement(m, units, combined)
    assert res.final_positions
    assert_no_overlap(units)