"""Rendering: map, overlays, units, and resolution playback."""

from __future__ import annotations

import math

import pygame

from ..assets.loader import terrain_surface, unit_surface
from ..config import (
    CELL,
    COLORS,
    FACTION_NAMES,
    MOVE_TICK_MS,
    ORDER_ARROW_ALPHA,
    ORDER_ARROW_STEP,
    ORDER_ARROW_WIDTH,
    ORDER_SHINE_LENGTH,
    ORDER_SHINE_MS,
    ORDER_SHINE_SAMPLES,
    OVERLAY_ALPHA,
    SIDE_PANEL_W,
)
from ..grid import GameMap, Terrain
from ..turn import MoveResolution
from ..units import MovementClass, Unit


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


def _corner_brackets(
    screen: pygame.Surface,
    rect: pygame.Rect,
    colour: tuple[int, int, int],
    arm: int,
    thickness: int = 3,
) -> None:
    """Four L-shaped corners hugging ``rect``.

    Brackets rather than a full outline: they read as a target and do not fight
    with the unit sprite underneath. Shared by the drag target and the keyboard
    cursor so every pointer on the board looks like a pointer.
    """
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
    _corner_brackets(screen, rect, colour, CELL // 3)


def draw_cursor(
    screen: pygame.Surface,
    camera: tuple[int, int],
    tile: tuple[int, int],
    valid: bool | None = None,
) -> None:
    """Mark where the keyboard cursor is pointing.

    Same bracket shape as the drag target, so both pointers read as pointers.
    ``valid`` is ``False`` when a unit is selected and this tile is out of its
    reach, which turns the brackets red instead of white. ``None`` means there is
    nothing to judge it against.
    """
    cam_x, cam_y = camera
    rect = cell_rect(tile[0], tile[1], -cam_x, -cam_y)
    colour = COLORS["cursor"] if valid is not False else COLORS["block"]
    _corner_brackets(screen, rect, colour, CELL // 5)


def _staircase(
    x0: int, y0: int, x1: int, y1: int, run: int = ORDER_ARROW_STEP
) -> list[tuple[int, int]]:
    """Orthogonal route from ``(x0,y0)`` to ``(x1,y1)``, only right angles.

    Alternates between the two axes in runs of ``run`` tiles, so a diagonal
    order reads as a staircase. Matches how units actually move: every step in
    the game is orthogonal.
    """
    points = [(x0, y0)]
    x, y = x0, y0
    axis = 0
    while (x, y) != (x1, y1):
        dx, dy = x1 - x, y1 - y
        # Take the axis in turn, but never stall on one with nothing left to do.
        take = axis if (dx if axis == 0 else dy) else 1 - axis
        if take == 0:
            step = min(run, abs(dx))
            x += step if dx > 0 else -step
        else:
            step = min(run, abs(dy))
            y += step if dy > 0 else -step
        points.append((x, y))
        axis ^= 1
    return points


# Scratch surface the arrows are composed on, then blitted once. Reused between
# frames so the per-frame cost is a fill rather than an allocation.
_arrow_layer: pygame.Surface | None = None


def _arrow_surface(size: tuple[int, int]) -> pygame.Surface:
    global _arrow_layer
    if _arrow_layer is None or _arrow_layer.get_size() != size:
        _arrow_layer = pygame.Surface(size, pygame.SRCALPHA)
    return _arrow_layer


def _polyline_segments(
    points: list[tuple[int, int]],
) -> tuple[list[tuple[tuple[int, int], tuple[int, int], float, float]], float]:
    """Segments with their length and the distance at which each one starts."""
    segments = []
    total = 0.0
    for start, end in zip(points, points[1:]):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length == 0:
            continue
        segments.append((start, end, length, total))
        total += length
    return segments, total


def _point_along(
    segments: list[tuple[tuple[int, int], tuple[int, int], float, float]],
    distance: float,
) -> tuple[int, int]:
    """Pixel position ``distance`` along the polyline, clamped to its ends."""
    if not segments:
        return (0, 0)
    for start, end, length, offset in segments:
        if distance <= offset + length:
            t = (distance - offset) / length
            return (
                int(start[0] + (end[0] - start[0]) * t),
                int(start[1] + (end[1] - start[1]) * t),
            )
    return segments[-1][1]


def _draw_arrow_on_layer(
    layer: pygame.Surface,
    camera: tuple[int, int],
    unit_pos: tuple[int, int],
    path: list[tuple[int, int]],
    phase: float,
) -> None:
    """Compose one order arrow onto ``layer``.

    Always takes a layer rather than a screen: these arrows are half
    transparent, and pygame ignores the alpha channel when drawing straight onto
    an opaque surface. Going through a layer is what makes the blend work.
    """
    if not path:
        return
    cam_x, cam_y = camera
    destination = path[-1]
    tiles = _staircase(unit_pos[0], unit_pos[1], destination[0], destination[1])
    points = [cell_rect(x, y, -cam_x, -cam_y).center for x, y in tiles]
    if len(points) < 2:
        return

    width = ORDER_ARROW_WIDTH
    base = (*COLORS["order_mark"], ORDER_ARROW_ALPHA)

    # Body first, then squares over the corners. Thick lines leave a notch where
    # two right angles meet, which the squares close.
    pygame.draw.lines(layer, base, False, points, width)
    for corner in points[1:-1]:
        pygame.draw.rect(
            layer,
            base,
            pygame.Rect(
                corner[0] - width // 2, corner[1] - width // 2, width, width
            ),
        )

    segments, total = _polyline_segments(points)
    if total == 0:
        return

    # Fade the shine in and out at the ends of its run so the wrap is seamless.
    edge = 0.15
    envelope = min(1.0, phase / edge, (1.0 - phase) / edge)

    step = ORDER_SHINE_LENGTH
    head = phase * total
    for index in range(ORDER_SHINE_SAMPLES):
        distance = head - index * step
        if distance < 0:
            break
        fade = (1.0 - index / ORDER_SHINE_SAMPLES) ** 2
        alpha = int(235 * fade * envelope)
        if alpha <= 4:
            continue
        tail = _point_along(segments, distance)
        tip = _point_along(segments, min(distance + step, total))
        pygame.draw.line(layer, (255, 248, 205, alpha), tail, tip, width - 1)


def draw_order_arrows(
    screen: pygame.Surface,
    camera: tuple[int, int],
    arrows: list[tuple[tuple[int, int], list[tuple[int, int]]]],
) -> None:
    """Draw every queued order in one pass, sharing a single blit.

    Each arrow is a right-angled staircase, half transparent, with a shine that
    runs from the unit to its destination and wraps. They are composed together
    on one surface and blended onto the map in a single blit; drawing them one at
    a time would let each arrow darken the ones underneath.

    While planning, the dashed preview only shows for the selected unit, so this
    is what makes everyone else's order visible.
    """
    if not arrows:
        return
    target = screen.get_clip() or screen.get_rect()
    layer = _arrow_surface(target.size)
    layer.fill((0, 0, 0, 0))
    # One shared clock, so every arrow pulses in step rather than flickering.
    phase = (pygame.time.get_ticks() % ORDER_SHINE_MS) / ORDER_SHINE_MS
    for unit_pos, path in arrows:
        _draw_arrow_on_layer(layer, camera, unit_pos, path, phase)
    screen.blit(layer, target.topleft)


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


def _entry_cost(
    game_map: GameMap, tile: tuple[int, int], movement_class: str
) -> str:
    """Move points ``tile`` charges ``movement_class``, or ``impassable``.

    Goes through the same ``passable``/``enter_cost`` pair the pathfinder uses,
    so the panel can never quote a cost the search would not charge.
    """
    if not game_map.passable(tile[0], tile[1], movement_class):
        return "impassable"
    return str(game_map.enter_cost(movement_class, tile))


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
        y += 2
        # One row per movement class, driven by the enum. Adding a class to
        # MovementClass adds a row here with nothing else to update.
        line("Terrain cost:", small, COLORS["text_dim"])
        for movement_class in MovementClass:
            line(
                f"{_entry_cost(game_map, hover, movement_class.value)}"
                f" [{movement_class.name.capitalize()}]",
                small,
                COLORS["text_dim"],
            )
        y += 6

    y += 6
    line("CONTROLS", small, COLORS["text_dim"])
    for text in (
        "Drag unit -> tile to order",
        "  or click unit, click tile",
        "",
        "WASD         move cursor",
        "Space        act at cursor",
        "Arrows       pan camera",
        "",
        "Click        select a unit",
        "Click again  deselect / cancel",
        "Right click  cancel order",
        "Tab          next unordered unit",
        "Enter        end turn / resolve",
        "R            clear all orders",
    ):
        line(text, small, COLORS["text_dim"])

    if message:
        y += 8
        screen.blit(
            font.render(message, True, COLORS["text_accent"]),
            (panel.left + 16, min(y, panel.bottom - 30)),
        )


def key_held(keys, *codes: int) -> bool:
    """Whether any of ``codes`` is currently held.

    ``keys`` is normally ``pygame.key.get_pressed()``, a ``ScancodeWrapper``.
    That type supports ``[]`` but has no ``.get()``. It returns False for key
    codes that are not held, whereas a plain dict raises ``KeyError``, so both
    are tolerated and the input rules can be exercised without a display.
    """
    for code in codes:
        try:
            if keys[code]:
                return True
        except (KeyError, IndexError):
            continue
    return False


def update_camera(
    keys,
    camera: tuple[int, int],
    max_cam: tuple[int, int],
    speed: int = 6,
) -> tuple[int, int]:
    """Pan the viewport with the arrow keys, clamped to the map bounds.

    WASD is deliberately absent: it drives the keyboard cursor instead. The two
    pointers stay separate, arrows are only for looking around.
    """
    cam_x, cam_y = camera
    max_x, max_y = max_cam

    if key_held(keys, pygame.K_LEFT):
        cam_x -= speed
    if key_held(keys, pygame.K_RIGHT):
        cam_x += speed
    if key_held(keys, pygame.K_UP):
        cam_y -= speed
    if key_held(keys, pygame.K_DOWN):
        cam_y += speed
    return (max(0, min(cam_x, max_x)), max(0, min(cam_y, max_y)))


def step_progress(elapsed_ms: float) -> float:
    """0..1 progress through a movement tick."""
    return max(0.0, min(1.0, elapsed_ms / MOVE_TICK_MS))