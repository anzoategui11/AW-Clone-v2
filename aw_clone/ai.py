"""Heuristic AI: advance toward the enemy and prefer favourable terrain.

With Move-only orders the AI has one job, and the interesting part is how it
sequences it. Each unit scores candidate destinations by how much closer it gets
to the enemy, with small tie-breakers for terrain cost and keeping units spread
out so they do not pile onto a single tile.
"""

from __future__ import annotations

import math

from .grid import GameMap, Terrain, find_path, reachable
from .orders import MoveOrder, Order
from .turn import planning_blocked_tiles
from .units import Unit

# Reward a unit for finishing on cheap, defensible ground.
TERRAIN_PREFERENCE: dict[Terrain, float] = {
    Terrain.PLAIN: 0.0,
    Terrain.ROAD: -0.4,
    Terrain.FOREST: 0.6,  # infantry hide here
    Terrain.HQ: 0.8,
    Terrain.BRIDGE: 1.2,  # chokepoints are dangerous
    Terrain.RIVER: 2.0,
    Terrain.MOUNTAIN: -0.3,
    Terrain.SEA: 5.0,
}


def plan_turn(
    game_map: GameMap,
    units: list[Unit],
    active_owner: int,
) -> dict[int, Order]:
    """Return a MoveOrder for every AI-controlled unit.

    Legality comes from :func:`planning_blocked_tiles`, the same helper the
    player's plan uses, so the AI can do everything the player can (including
    trailing a unit that has already been ordered away) and nothing they
    cannot. Orders are built one unit at a time and fed back in, so each unit
    sees the ones planned before it.
    """
    mine = [u for u in units if u.owner == active_owner and u.alive]
    enemies = [u for u in units if u.owner != active_owner and u.alive]
    orders: dict[int, Order] = {}
    if not mine or not enemies:
        return orders

    for unit in sorted(mine, key=lambda u: u.unit_id):
        blocked = planning_blocked_tiles(units, orders, unit)

        target = _choose_destination(game_map, unit, enemies, blocked)
        if target is None or target == unit.pos:
            continue

        path = find_path(
            game_map,
            unit.pos,
            target,
            unit.movement_class,
            blocked=blocked,
            budget=unit.unit_type.move_points,
        )
        if path:
            orders[unit.unit_id] = Order(unit.unit_id, MoveOrder(path=path))

    return orders


def _choose_destination(
    game_map: GameMap,
    unit: Unit,
    enemies: list[Unit],
    blocked: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """Best tile within budget: closest to the enemy, mild terrain preference."""
    best_score = -math.inf
    best_tile: tuple[int, int] | None = None

    budget = unit.unit_type.move_points
    options = reachable(
        game_map, unit.pos, budget, unit.movement_class, blocked=blocked
    )
    if not options:
        return None

    for tile, remaining in options.items():
        if tile == unit.pos:
            continue
        # Manhattan, because that is the real number of orthogonal steps.
        distance = min(
            abs(enemy.x - tile[0]) + abs(enemy.y - tile[1]) for enemy in enemies
        )
        terrain = game_map.at(*tile).terrain
        terrain_bonus = TERRAIN_PREFERENCE.get(terrain, 0.0)

        # Closer is better; cheaper terrain and unused move points are
        # tie-breakers only, so they never override a real positional gain.
        score = -distance * 10 + terrain_bonus + (remaining / max(budget, 1)) * 0.5

        # Deterministic tie-break on coordinates.
        if score > best_score or (score == best_score and (best_tile is None or tile < best_tile)):
            best_score = score
            best_tile = tile

    return best_tile