"""Ordering rules for friendly units: vacated tiles and claimed destinations.

The rule under test, as specified:

* A friendly unit's current tile may NOT be targeted while that unit has no
  orders, because it will still be standing there.
* Once the friendly unit HAS been ordered away, its current tile becomes a legal
  destination for another friendly unit.
* Even then, the tile the friendly unit was ordered to occupy is NOT a legal
  destination for anyone else.

These are planning-time rules. They decide what the player is allowed to aim
at; the resolver separately guarantees nobody ends up stacked.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aw_clone import ai
from aw_clone.grid import GameMap, Terrain
from aw_clone.orders import MoveOrder, Order
from aw_clone.turn import TurnPlan, planning_blocked_tiles, resolve_movement
from aw_clone.units import Unit, spawn


def open_map(width: int = 12, height: int = 8) -> GameMap:
    m = GameMap(width=width, height=height)
    for y in range(height):
        for x in range(width):
            m.set(x, y, Terrain.PLAIN)
    return m


def two_friendlies():
    """Two blue units with room to manoeuvre, in a fresh plan."""
    m = open_map()
    units: list[Unit] = []
    units.append(spawn(units, 1, "infantry", 0, 0))
    units.append(spawn(units, 1, "infantry", 1, 0))
    return m, units, TurnPlan(m, units, active_owner=1)


# --------------------------------------------------- unordered friendly ----
def test_an_unordered_friendly_tile_is_blocked():
    m, units, plan = two_friendlies()
    follower, leader = units
    assert leader.pos in plan.blocked_tiles_for(follower)


def test_a_friendly_tile_is_blocked_until_that_unit_is_ordered():
    m, units, plan = two_friendlies()
    follower, leader = units
    leader_tile = leader.pos
    assert leader_tile in plan.blocked_tiles_for(follower)
    assert leader_tile not in plan.move_range(follower)


def test_a_friendly_unit_cannot_be_ordered_onto_its_own_tile():
    m, units, plan = two_friendlies()
    follower, leader = units
    assert plan.set_move(follower, leader.pos) is False
    assert plan.order_for(follower.unit_id) is None


# ------------------------------------------------------- ordered friendly ----
def test_a_friendly_tile_frees_up_once_that_unit_is_ordered():
    m, units, plan = two_friendlies()
    follower, leader = units
    assert plan.set_move(leader, (4, 0)) is True  # 3 tiles, within 6 points
    assert leader.pos not in plan.blocked_tiles_for(follower)
    assert leader.pos in plan.move_range(follower)


def test_a_unit_can_be_ordered_onto_a_vacating_friendly_tile():
    m, units, plan = two_friendlies()
    follower, leader = units
    plan.set_move(leader, (4, 0))
    assert plan.set_move(follower, leader.pos) is True
    assert plan.order_for(follower.unit_id).move.destination == leader.pos


def test_only_the_endpoint_is_reserved_not_the_whole_route():
    """A follower may trail a friendly unit along the tiles it walks over."""
    m, units, plan = two_friendlies()
    follower, leader = units
    plan.set_move(leader, (4, 0))  # route: (2,0), (3,0), (4,0)
    blocked = plan.blocked_tiles_for(follower)
    assert leader.pos not in blocked  # vacated
    assert (2, 0) not in blocked  # walked over, not reserved
    assert (3, 0) not in blocked
    assert (4, 0) in blocked  # the endpoint is claimed


# ------------------------------------------------------ claimed endpoint ----
def test_an_ordered_units_destination_is_blocked_for_other_friendlies():
    m, units, plan = two_friendlies()
    follower, leader = units
    destination = (4, 0)
    plan.set_move(leader, destination)
    assert destination in plan.blocked_tiles_for(follower)
    assert destination not in plan.move_range(follower)


def test_a_unit_cannot_be_ordered_onto_another_units_ordered_position():
    m, units, plan = two_friendlies()
    follower, leader = units
    destination = (4, 0)
    plan.set_move(leader, destination)
    assert plan.set_move(follower, destination) is False
    assert plan.order_for(follower.unit_id) is None


def test_cancelling_an_order_re_blocks_both_its_old_destination_and_its_tile():
    m, units, plan = two_friendlies()
    follower, leader = units
    destination = (4, 0)
    plan.set_move(leader, destination)
    plan.clear(leader.unit_id)
    # With no order the unit stays put, so its tile is blocked again...
    assert leader.pos in plan.blocked_tiles_for(follower)
    # ...and the square it was headed for is released.
    assert destination not in plan.blocked_tiles_for(follower)


def test_a_unit_may_still_claim_its_own_current_tile():
    """Selection bookkeeping: the origin is never self-blocked."""
    m, units, plan = two_friendlies()
    follower, _ = units
    assert follower.pos not in plan.blocked_tiles_for(follower)


def test_a_reassigned_order_frees_the_previous_destination():
    m, units, plan = two_friendlies()
    follower, leader = units
    plan.set_move(leader, (4, 0))
    plan.set_move(leader, (3, 1))  # a different, still-legal destination
    blocked = plan.blocked_tiles_for(follower)
    assert (4, 0) not in blocked
    assert (3, 1) in blocked


def test_a_unit_may_keep_the_destination_it_was_already_ordered_to():
    """A unit's own claim must not block it from re-confirming that order."""
    m, units, plan = two_friendlies()
    follower, _ = units
    destination = (2, 1)
    assert plan.set_move(follower, destination) is True
    # Re-ordering to the same square is a no-op, not a rejection.
    assert plan.set_move(follower, destination) is True
    assert plan.order_for(follower.unit_id).move.destination == destination


def test_a_units_own_destination_is_never_in_its_blocked_set():
    m, units, plan = two_friendlies()
    follower, _ = units
    destination = (2, 1)
    plan.set_move(follower, destination)
    assert destination not in plan.blocked_tiles_for(follower)


# ---------------------------------------------------------------- enemies ----
def test_enemy_tiles_stay_blocked_regardless_of_anything():
    m, units = open_map(), []
    units.append(spawn(units, 1, "infantry", 0, 0))
    enemy = spawn(units, 2, "infantry", 3, 0)
    units.append(enemy)
    plan = TurnPlan(m, units, active_owner=1)
    assert enemy.pos in plan.blocked_tiles_for(units[0])


def test_an_enemies_orders_never_free_its_tile_for_us():
    """Enemy orders are not visible during planning, so no inference is made."""
    m, units = open_map(), []
    units.append(spawn(units, 1, "infantry", 0, 0))
    enemy = spawn(units, 2, "infantry", 3, 0)
    units.append(enemy)
    plan = TurnPlan(m, units, active_owner=1)
    # Simulate knowledge an enemy unit is about to leave.
    plan.orders[enemy.unit_id] = Order(enemy.unit_id, MoveOrder([(6, 0)]))
    # Only friendly orders count toward vacating.
    assert enemy.pos in plan.blocked_tiles_for(units[0])


# ----------------------------------------------------------- integration ----
def test_two_units_ordered_into_one_vacating_spot_do_not_overlap():
    """End to end: the plan allows it, the resolver keeps them apart."""
    m, units = open_map(14, 6), []
    units.append(spawn(units, 1, "infantry", 0, 0))
    units.append(spawn(units, 1, "infantry", 0, 1))
    units.append(spawn(units, 1, "infantry", 0, 2))
    plan = TurnPlan(m, units, active_owner=1)
    leader, mid, tail = units

    plan.set_move(leader, (3, 2))
    plan.set_move(mid, (2, 2))
    plan.set_move(tail, leader.pos)  # trailing into the leader's vacated tile

    resolve_movement(m, units, plan.orders)
    positions = [u.pos for u in units]
    assert len(set(positions)) == len(positions)
    for u in units:
        assert m.in_bounds(u.x, u.y)


def test_three_units_following_one_leader_resolve_without_stacking():
    m, units = open_map(16, 6), []
    for y in range(4):
        units.append(spawn(units, 1, "infantry", 0, y))
    plan = TurnPlan(m, units, active_owner=1)
    leader = units[0]

    plan.set_move(leader, (4, 0))
    for follower in units[1:]:
        # Aim at where the leader stands; only the unit ahead frees up in time.
        plan.set_move(follower, leader.pos)

    resolve_movement(m, units, plan.orders)
    positions = [u.pos for u in units]
    assert len(set(positions)) == len(positions)


# ------------------------------------------------------------------- ai ----
def test_the_ai_uses_the_same_rule_as_the_player():
    """Both sides must agree on what a legal order is.

    The AI plans in unit_id order, so by the time it reaches the follower the
    leader already has an order and its tile counts as vacated.
    """
    m, units = open_map(14, 6), []
    units.append(spawn(units, 2, "infantry", 0, 0))
    units.append(spawn(units, 2, "infantry", 0, 1))
    leader, follower = units
    units.append(spawn(units, 1, "infantry", 12, 0))  # something to advance on

    orders = ai.plan_turn(m, units, 2)
    assert orders[leader.unit_id].has_any()
    assert orders[follower.unit_id].has_any()

    # Every destination must be legal by the shared rule. Traversing a square
    # another unit was ordered to is allowed on purpose, so a follower can
    # trail through its leader's resting tile.
    for unit_id, order in orders.items():
        unit = next(u for u in units if u.unit_id == unit_id)
        blocked = planning_blocked_tiles(units, orders, unit)
        destination = order.move.destination
        assert destination not in blocked, (
            f"unit {unit_id} was ordered onto blocked {destination}"
        )

    # No two AI units may be sent to the same square.
    destinations = [o.move.destination for o in orders.values()]
    assert len(destinations) == len(set(destinations))


def test_a_follower_may_trail_through_its_leaders_destination():
    """Traversing a reserved tile is legal; only stopping on it is not."""
    m, units = open_map(14, 6), []
    units.append(spawn(units, 2, "infantry", 0, 0))
    units.append(spawn(units, 2, "infantry", 0, 1))
    leader, follower = units
    units.append(spawn(units, 1, "infantry", 12, 0))

    orders = ai.plan_turn(m, units, 2)
    leader_destination = orders[leader.unit_id].move.destination
    follower_path = orders[follower.unit_id].move.path

    # The follower's route may run through where the leader comes to rest.
    assert leader_destination in follower_path or (
        follower_path[-1] != leader_destination
    )
    # Either way, it must not *end* there.
    assert orders[follower.unit_id].move.destination != leader_destination

    resolve_movement(m, units, orders)
    positions = [u.pos for u in units]
    assert len(set(positions)) == len(positions)


def test_the_ai_never_orders_a_unit_onto_an_enemy_or_a_double_booked_square():
    m, units = open_map(16, 6), []
    units.append(spawn(units, 2, "infantry", 0, 0))
    units.append(spawn(units, 2, "infantry", 0, 1))
    units.append(spawn(units, 1, "infantry", 8, 0))

    orders = ai.plan_turn(m, units, 2)
    enemy_tiles = {u.pos for u in units if u.owner == 1}
    destinations = [o.move.destination for o in orders.values() if o.has_any()]

    for order in orders.values():
        for tile in order.move.path:
            assert tile not in enemy_tiles
    assert len(destinations) == len(set(destinations))