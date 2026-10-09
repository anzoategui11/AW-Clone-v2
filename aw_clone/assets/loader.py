"""Asset loading. Sprites are generated once by ``generate.py`` and cached."""

from __future__ import annotations

import random
from pathlib import Path

import pygame

from ..config import TILE_SIZE
from ..grid import Terrain

SPRITES_DIR = Path(__file__).resolve().parent / "sprites"

_cache: dict[str, pygame.Surface] = {}


def _load(rel_path: str) -> pygame.Surface | None:
    if rel_path in _cache:
        return _cache[rel_path]
    path = SPRITES_DIR / rel_path
    if not path.exists():
        return None
    surface = pygame.image.load(str(path)).convert_alpha()
    _cache[rel_path] = surface
    return surface


def terrain_surface(terrain: Terrain, seed: int) -> pygame.Surface:
    """Terrain tile with a stable random variant, so maps do not look tiled."""
    variant = random.Random(seed * 2654435761).randint(0, 3)
    surface = _load(f"terrain/{terrain.value}_{variant}.png")
    if surface is None:
        # Fallback keeps the game playable if sprites were never generated.
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((90, 90, 90))
    return surface


def unit_surface(unit_type_key: str, owner: int) -> pygame.Surface:
    surface = _load(f"units/{unit_type_key}_p{owner}.png")
    if surface is None:
        surface = pygame.Surface((TILE_SIZE, TILE_SIZE))
        surface.fill((200, 200, 200))
        surface.set_colorkey((200, 200, 200))
    return surface


def asset_report() -> dict[str, int]:
    terrain = len(list((SPRITES_DIR / "terrain").glob("*.png"))) if (SPRITES_DIR / "terrain").exists() else 0
    units = len(list((SPRITES_DIR / "units").glob("*.png"))) if (SPRITES_DIR / "units").exists() else 0
    return {"terrain": terrain, "units": units}