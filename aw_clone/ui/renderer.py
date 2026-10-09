"""Rendering: map, overlays, units, and resolution playback."""

from __future__ import annotations

import pygame

from ..assets.loader import terrain_surface, unit_surface
from ..config import (
    CELL,
    COLORS,
    FACTION_NAMES,
    MOVE_TICK_MS,
    OVERLAY_ALPHA,
    SIDE_PANEL_W,
)
from ..grid import GameMap, Terrain
from ..turn import MoveResolution
from ..units import Unit


def cell_rect(x: int, y: int, offset_x: int, offset_y: int) -> pygame.Rect:
    return pygame.Rect(offset_x + x * CELL, offset_y + y * CELL, CELL, CELL)


def tile_at_pixel(mx: int, my: int, camera: tuple[int, int]) -> tuple[int, int]:
    """Map a screen position to the tile under it.

    ``camera`` is a *subtraction* applied when drawing, so a tile is drawn at
    ``tile * CELL - camera``. Inverting that means *adding* the camera back.
    Subtracting it here (as an earlier version did) silently shifted every
    click whenever the view was panned, so clicks landed on the wrong tile.
    """
    cam_x, cam_y = camera
    return (mx + cam_x) // CELL, (my + cam_y) // CELL


def draw_map(
    screen: pygame.Surface,
    game_map: GameMap,
    camera: tuple[int, int],
    viewport: pygame.Rect,
) -> None:
    cam_x, cam_y = camera
    tile = CELL

    for ty in range(game_map.height):
        for tx in range(game_map.width):
            screen_x = tx * tile - cam_x
            screen_y = ty * tile - cam_y
            if screen_x + tile < viewport.left or screen_x > viewport.right:
                continue
            if screen_y + tile < viewport.top or screen_y > viewport.bottom:
                continue
            surface = pygame.transform.scale(
                terrain_surface(game_map.at(tx, ty).terrain, seed=tx * 31 + ty * 17),
                (tile, tile),
            )
            screen.blit(surface, (screen_x, screen_y))

    # HQ markers so bases read clearly regardless of terrain colour.
    for ty in range(game_map.height):
        for tx in range(game_map.width):
            if game_map.at(tx, ty).terrain is not Terrain.HQ:
                continue
            rect = cell_rect(tx, ty, -cam_x, -cam_y)
            pygame.draw.rect(
                screen, COLORS["text_accent"], rect.inflate(-CELL // 3, -CELL // 3), 3
            )


def draw_move_range(
    screen: pygame.Surface,
    camera: tuple[int, int],
    reachable: dict[tuple[int, int], int],
    origin: tuple[int, int],
) -> None:
    """Blue overlay on reachable tiles, brighter the closer to the origin."""
    cam_x, cam_y = camera
    if not reachable:
        return

    # Cheap approach: pre-tint each terrain variant once per frame batch.
    best = max(reachable.values()) or 1
    for (tx, ty), remaining in reachable.items():
        if (tx, ty) == origin:
            continue
        rect = cell_rect(tx, ty, -cam_x, -cam_y)
        strength = 0.35 + 0.65 * (remaining / best)
        overlay = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
        overlay.fill(
            (*COLORS["move_range"], int(OVERLAY_ALPHA * strength))
        )
        screen.blit(overlay, rect.topleft)

    # Outline the reachable region so its extent is unambiguous.
    for (tx, ty) in reachable:
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            if (tx + dx, ty + dy) in reachable:
                continue
            px, py = cell_rect(tx, ty, -cam_x, -cam_y).topleft
            if dx == 1:
                screen.fill(COLORS["move_range_edge"], pygame.Rect(px + CELL - 2, py, 2, CELL))
            elif dx == -1:
                screen.fill(COLORS["move_range_edge"], pygame.Rect(px, py, 2, CELL))
            elif dy == 1:
                screen.fill(COLORS["move_range_edge"], pygame.Rect(px, py + CELL - 2, CELL, 2))
            else:
                screen.fill(COLORS["move_range_edge"], pygame.Rect(px, py, CELL, 2))


def draw_path_preview(
    screen: pygame.Surface,
    camera: tuple[int, int],
    path: list[tuple[int, int]],
    valid: bool = True,
) -> None:
    """Dotted line along the planned route, with a marker on the destination.

    ``valid`` recolours the preview red when the target cannot be reached, so
    an impossible destination is obvious before the player releases the mouse.
    """
    if not path:
        return
    cam_x, cam_y = camera
    colour = COLORS["path"] if valid else COLORS["block"]
    for i, (tx, ty) in enumerate(path):
        rect = cell_rect(tx, ty, -cam_x, -cam_y)
        if i == len(path) - 1:
            pygame.draw.circle(screen, colour, rect.center, CELL // 4, 3)
        else:
            pygame.draw.rect(
                screen, colour, rect.inflate(-CELL * 2 // 3, -CELL * 2 // 3), 2
            )


def draw_drag_target(
    screen: pygame.Surface,
    camera: tuple[int, int],
    tile: tuple[int, int],
    reachable_tiles: set[tuple[int, int]],
) -> None:
    """Highlight the tile under the cursor during a drag.

    A green corner marker means the drop is legal; red means it is not. This is
    the whole feedback loop for press-and-drag ordering, so it needs to be
    readable at a glance.
    """
    cam_x, cam_y = camera
    rect = cell_rect(tile[0], tile[1], -cam_x, -cam_y)
    ok = tile in reachable_tiles
    colour = COLORS["move_range_edge"] if ok else COLORS["block"]

    fill = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
    fill.fill((*colour, 70))
    screen.blit(fill, rect.topleft)

    # Corner brackets rather than a full outline: they read as a target and do
    # not fight with the unit sprite underneath.
    arm = CELL // 3
    thickness = 3
    for cx, cy, dx, dy in (
        (rect.left, rect.top, 1, 1),
        (rect.right - 1, rect.top, -1, 1),
        (rect.left, rect.bottom - 1, 1, -1),
        (rect.right - 1, rect.bottom - 1, -1, -1),
    ):
        pygame.draw.line(
            screen, colour, (cx, cy), (cx + dx * arm, cy), thickness
        )
        pygame.draw.line(
            screen, colour, (cx, cy), (cx, cy + dy * arm), thickness
        )


def draw_order_arrow(
    screen: pygame.Surface,
    camera: tuple[int, int],
    unit_pos: tuple[int, int],
    path: list[tuple[int, int]],
) -> None:
    """Small arrow from a unit to its ordered destination, for queued orders.

    While planning, the dashed preview only shows for the selected unit, so
    this gives the other units' orders a compact, always-visible marker.
    """
    if not path:
        return
    cam_x, cam_y = camera
    start = cell_rect(unit_pos[0], unit_pos[1], -cam_x, -cam_y).center
    end = cell_rect(path[-1][0], path[-1][1], -cam_x, -cam_y).center
    pygame.draw.line(screen, COLORS["order_mark"], start, end, 2)


def draw_unit(
    screen: pygame.Surface,
    unit: Unit,
    camera: tuple[int, int],
    selected: bool = False,
    has_order: bool = False,
    interpolating: tuple[int, int, float] | None = None,
) -> None:
    """Draw a unit. ``interpolating`` is (from_x, from_y, t in 0..1)."""
    cam_x, cam_y = camera
    if interpolating is not None:
        fx, fy, t = interpolating
        px = (fx + (unit.x - fx) * t) * CELL - cam_x
        py = (fy + (unit.y - fy) * t) * CELL - cam_y
    else:
        px = unit.x * CELL - cam_x
        py = unit.y * CELL - cam_y

    rect = pygame.Rect(int(px), int(py), CELL, CELL)

    # Soft drop shadow grounds the sprite on the tile.
    shadow = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
    pygame.draw.ellipse(
        shadow, (0, 0, 0, 70), pygame.Rect(2, CELL - 8, CELL - 4, 6)
    )
    screen.blit(shadow, rect.topleft)

    sprite = pygame.transform.scale(
        unit_surface(unit.unit_type.sprite, unit.owner), (CELL, CELL)
    )
    screen.blit(sprite, rect.topleft)

    if selected:
        pygame.draw.rect(screen, COLORS["cursor"], rect, 2)
        pygame.draw.rect(screen, COLORS["cursor"], rect.inflate(4, 4), 1)

    if has_order:
        mark = pygame.Rect(rect.centerx - 5, rect.top + 2, 10, 10)
        pygame.draw.rect(screen, COLORS["order_mark"], mark, 2)


def draw_side_panel(
    screen: pygame.Surface,
    panel_rect: pygame.Rect,
    game_map: GameMap,
    units: list[Unit],
    turn_number: int,
    phase: str,
    orders_queued: int,
    orders_total: int,
    selected: Unit | None,
    hover: tuple[int, int] | None,
    message: str,
) -> None:
    panel = panel_rect
    screen.fill(COLORS["panel"], panel)
    pygame.draw.line(screen, COLORS["panel_edge"], (panel.left, 0), (panel.left, panel.bottom), 2)

    font = pygame.font.SysFont("consolas", 15)
    small = pygame.font.SysFont("consolas", 13)
    y = 16

    def line(text: str, f=font, color=None) -> None:
        nonlocal y
        screen.blit(f.render(text, True, color or COLORS["text"]), (panel.left + 16, y))
        y += f.get_height() + 4

    line("ADVANCE WARS CLONE")
    y += 6
    line(f"Turn {turn_number}", font, COLORS["text_accent"])
    line(f"Phase: {phase}", small, COLORS["text_dim"])
    y += 8

    counts = {1: 0, 2: 0}
    for u in units:
        if u.alive:
            counts[u.owner] = counts.get(u.owner, 0) + 1
    line(f"{FACTION_NAMES[1]} units: {counts.get(1, 0)}", small, COLORS["p1"])
    line(f"{FACTION_NAMES[2]} units: {counts.get(2, 0)}", small, COLORS["p2"])
    line(f"Orders: {orders_queued}/{orders_total}", small, COLORS["text_dim"])
    y += 10

    if selected is not None:
        line(f"SELECTED", small, COLORS["text_dim"])
        line(selected.unit_type.name)
        line(f"HP {selected.hp}/{selected.unit_type.max_hp}", small)
        line(
            f"Move {selected.unit_type.move_points} ({selected.movement_class})",
            small,
            COLORS["text_dim"],
        )
        line(f"Attack {selected.unit_type.attack}", small, COLORS["text_dim"])
        line(
            f"Range {selected.unit_type.weapon_range_min}-"
            f"{selected.unit_type.weapon_range_max}",
            small,
            COLORS["text_dim"],
        )
        y += 8
    else:
        line("No unit selected", small, COLORS["text_dim"])
        y += 8

    if hover is not None:
        tile = game_map.at(*hover)
        line(f"Hover: {hover[0]},{hover[1]}", small, COLORS["text_dim"])
        line(f"Terrain: {tile.terrain.value}", small, COLORS["text_dim"])
        y += 6

    y += 6
    line("CONTROLS", small, COLORS["text_dim"])
    for text in (
        "Drag unit -> tile to order",
        "  or click unit, click tile",
        "",
        "Click        select a unit",
        "Click again  deselect",
        "Right click  cancel order",
        "Tab          next unordered unit",
        "Enter        end turn / resolve",
        "R            clear all orders",
        "Arrows/WASD  pan camera",
    ):
        line(text, small, COLORS["text_dim"])

    if message:
        y += 8
        screen.blit(
            font.render(message, True, COLORS["text_accent"]),
            (panel.left + 16, min(y, panel.bottom - 30)),
        )


def update_camera(
    keys,
    camera: tuple[int, int],
    max_cam: tuple[int, int],
    speed: int = 6,
) -> tuple[int, int]:
    """Pan the viewport, clamped to the map bounds.

    ``keys`` is normally ``pygame.key.get_pressed()``, a ``ScancodeWrapper``.
    That type supports ``[]`` but has no ``.get()``. It returns False for key
    codes that are not held, whereas a plain dict raises ``KeyError``, so both
    are tolerated and the tests can run without a display.
    """
    cam_x, cam_y = camera
    max_x, max_y = max_cam

    def down(*codes: int) -> bool:
        for code in codes:
            try:
                if keys[code]:
                    return True
            except (KeyError, IndexError):
                continue
        return False

    if down(pygame.K_LEFT, pygame.K_a):
        cam_x -= speed
    if down(pygame.K_RIGHT, pygame.K_d):
        cam_x += speed
    if down(pygame.K_UP, pygame.K_w):
        cam_y -= speed
    if down(pygame.K_DOWN, pygame.K_s):
        cam_y += speed
    return (max(0, min(cam_x, max_x)), max(0, min(cam_y, max_y)))


def step_progress(elapsed_ms: float) -> float:
    """0..1 progress through a movement tick."""
    return max(0.0, min(1.0, elapsed_ms / MOVE_TICK_MS))