"""Scenario map construction and starting setup."""

from __future__ import annotations

from .grid import GameMap, Terrain
from .units import Unit, spawn

MAP_W = 24
MAP_H = 16

# A hand-built map: a road spine across the middle, a river with a single
# bridge, forests for infantry, and mountains that only infantry can climb.
BASE_TERRAIN = Terrain.PLAIN


def build_map(width: int = MAP_W, height: int = MAP_H) -> GameMap:
    m = GameMap(width=width, height=height)

    for y in range(height):
        for x in range(width):
            m.set(x, y, Terrain.PLAIN)

    # Road running east-west through the middle.
    road_y = height // 2
    for x in range(width):
        m.set(x, road_y, Terrain.ROAD)

    # Vertical road on each flank.
    for y in range(height):
        m.set(2, y, Terrain.ROAD)
        m.set(width - 3, y, Terrain.ROAD)

    # River with one bridge at the road crossing.
    river_x = width // 2
    for y in range(height):
        if y == road_y:
            m.set(river_x, y, Terrain.BRIDGE)
        else:
            m.set(river_x, y, Terrain.RIVER)

    # A second, unguarded bridge further south so flank routes exist.
    m.set(river_x, height - 3, Terrain.BRIDGE)
    m.set(river_x - 1, height - 3, Terrain.PLAIN)
    m.set(river_x + 1, height - 3, Terrain.PLAIN)

    # Forest clumps in the upper and lower thirds.
    for (fx, fy, fw, fh) in _forest_patches(width, height):
        for y in range(fy, min(fy + fh, height)):
            for x in range(fx, min(fx + fw, width)):
                if m.at(x, y).terrain in (Terrain.PLAIN,):
                    m.set(x, y, Terrain.FOREST)

    # Mountain ridge on each side, leaving the roads and passes open.
    for (mx, my, mw, mh) in _mountain_patches(width, height):
        for y in range(my, min(my + mh, height)):
            for x in range(mx, min(mx + mw, width)):
                if m.at(x, y).terrain == Terrain.PLAIN:
                    m.set(x, y, Terrain.MOUNTAIN)

    # Headquarters: each faction holds one at its back corner.
    m.set(1, 1, Terrain.HQ)
    m.set(width - 2, height - 2, Terrain.HQ)

    return m


def _forest_patches(width: int, height: int) -> list[tuple[int, int, int, int]]:
    return [
        (4, 2, 4, 3),
        (width - 9, 2, 4, 3),
        (4, height - 6, 3, 3),
        (width - 8, height - 7, 4, 3),
        (width // 2 + 2, 2, 3, 4),
        (width // 2 - 6, height - 7, 3, 4),
    ]


def _mountain_patches(width: int, height: int) -> list[tuple[int, int, int, int]]:
    return [
        (6, 6, 2, 3),
        (width - 8, 6, 2, 3),
        (6, height - 5, 2, 2),
        (width - 8, height - 6, 2, 3),
    ]


def setup_units(game_map: GameMap) -> list[Unit]:
    """Symmetric starting forces so neither side has an opening advantage."""
    units: list[Unit] = []
    w, h = game_map.width, game_map.height

    # Blue (left). Red is derived by mirroring these across both axes, so the
    # opening position is exactly fair by construction.
    blue_start = [
        ("infantry", 3, 5),
        ("infantry", 3, 9),
        ("mech", 2, 7),
        ("apc", 4, 7),
        ("anti_air", 3, 6),
        ("artillery", 2, 10),
    ]

    for key, x, y in blue_start:
        units.append(spawn(units, 1, key, x, y))
    for key, x, y in blue_start:
        units.append(spawn(units, 2, key, w - 1 - x, h - 1 - y))

    return units


def new_game() -> tuple[GameMap, list[Unit]]:
    game_map = build_map()
    units = setup_units(game_map)
    return game_map, units