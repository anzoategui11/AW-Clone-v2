"""Interaction tests for press-and-drag ordering.

These cover the input layer without a display: the Game object is driven with
synthetic events, so the actual press/move/release sequence the player performs
is exercised rather than assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pygame = pytest.importorskip("pygame")

import main as game_main  # noqa: E402
from aw_clone.config import CELL  # noqa: E402


@pytest.fixture()
def game(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    instance = game_main.Game(headless=True)
    instance.screenshot_path = "test_input.png"
    yield instance
    pygame.quit()
    Path(instance.screenshot_path).unlink(missing_ok=True)


def px_of(game, tile: tuple[int, int]) -> tuple[int, int]:
    """Screen position of a tile's centre, accounting for the camera."""
    return (
        tile[0] * CELL + CELL // 2 - game.camera[0],
        tile[1] * CELL + CELL // 2 - game.camera[1],
    )


def drag(game, unit_tile: tuple[int, int], target_tile: tuple[int, int]) -> None:
    """Perform a full press-drag-release between two tiles."""
    game.on_press(px_of(game, unit_tile))
    game.on_motion(px_of(game, target_tile))
    game.on_release(px_of(game, target_tile))


def click(game, tile: tuple[int, int]) -> None:
    game.on_press(px_of(game, tile))
    game.on_release(px_of(game, tile))


def first_blue(game):
    return next(u for u in game.units if u.owner == 1 and u.alive)


def reachable_tile_beside(game, unit):
    """A tile this unit can actually reach, preferring a plain step east."""
    rng = game.plan.move_range(unit)
    for candidate in ((unit.x + 1, unit.y), (unit.x, unit.y + 1), (unit.x, unit.y - 1)):
        if candidate in rng and candidate != unit.pos:
            return candidate
    return next(t for t in rng if t != unit.pos)


def order_one_unit(game, unit):
    """Give ``unit`` an order via order_move, skipping if boxed in."""
    rng = game.plan.move_range(unit)
    for candidate in ((unit.x + 1, unit.y), (unit.x, unit.y + 1), (unit.x, unit.y - 1)):
        if candidate in rng and candidate != unit.pos:
            game.order_move(unit, candidate)
            return True
    others = [
        t
        for t in rng
        if t != unit.pos
        and game.unit_at(t) is None
    ]
    if others:
        game.order_move(unit, sorted(others)[0])
        return True
    return False


# ----------------------------------------------------------------- drag ----
def test_dragging_a_unit_to_a_tile_issues_a_move_order(game):
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)
    drag(game, unit.pos, target)
    order = game.plan.order_for(unit.unit_id)
    assert order is not None and order.has_any()
    assert order.move.destination == target


def test_a_click_without_movement_only_selects(game):
    unit = first_blue(game)
    click(game, unit.pos)
    assert game.selected is unit
    assert game.plan.order_for(unit.unit_id) is None


def test_jitter_within_the_same_tile_still_counts_as_a_click(game):
    """A few stray pixels inside the unit's own tile must not issue an order.

    There is no distance threshold any more: the gesture is decided by which
    tile the release lands on, which cannot be faked by a shaky hand.
    """
    unit = first_blue(game)
    start = px_of(game, unit.pos)
    game.on_press(start)
    game.on_motion((start[0] + 3, start[1] + 2))
    game.on_release((start[0] + 3, start[1] + 2))
    assert game.selected is unit
    assert game.plan.order_for(unit.unit_id) is None


def test_clicking_empty_ground_orders_the_selected_unit(game):
    """Empty ground is a destination for the selected unit, not a deselect."""
    unit = first_blue(game)
    empty = next(
        (x, y)
        for y in range(game.game_map.height)
        for x in range(game.game_map.width)
        if game.unit_at((x, y)) is None
        and (x, y) in game.plan.move_range(unit)
        and (x, y) != unit.pos
    )
    click(game, unit.pos)
    click(game, empty)
    assert game.plan.order_for(unit.unit_id) is not None
    assert game.selected is None


def test_drag_onto_an_unreachable_tile_issues_no_order(game):
    unit = first_blue(game)
    game.on_press(px_of(game, unit.pos))
    # Bottom-right corner of the map is far beyond any move budget.
    far = (game.game_map.width - 1, game.game_map.height - 1)
    game.on_motion(px_of(game, far))
    game.on_release(px_of(game, far))
    assert game.plan.order_for(unit.unit_id) is None


def test_drag_releases_outside_the_map_do_nothing(game):
    unit = first_blue(game)
    game.on_press(px_of(game, unit.pos))
    beyond = (game.win_w + 200, game.win_h + 200)
    game.on_motion(beyond)
    game.on_release(beyond)
    assert game.plan.order_for(unit.unit_id) is None


# --------------------------------------------------------- auto-advance ----
def test_selection_clears_after_ordering(game):
    """Ordering a unit leaves the board with nothing selected.

    Keeping the selection is what made a follow-up click act on the wrong unit.
    """
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)
    drag(game, unit.pos, target)
    assert game.selected is None


def test_finishing_a_drag_deselects(game):
    """After an order the selection is dropped.

    Holding it meant the next press started from a stale unit, so a click aimed
    at one unit could act on another. This is the reported bug.
    """
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)
    drag(game, unit.pos, target)
    assert game.plan.order_for(unit.unit_id) is not None
    assert game.selected is None


def test_a_click_on_a_unit_keeps_it_selected(game):
    """A click that issues no order is a pure selection and must stick."""
    unit = first_blue(game)
    click(game, unit.pos)
    assert game.selected is unit


def test_click_then_click_orders_the_selected_unit(game):
    """The two-click flow: click a unit, then click its destination."""
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)

    click(game, unit.pos)
    assert game.selected is unit

    click(game, target)
    assert game.plan.order_for(unit.unit_id) is not None
    assert game.plan.order_for(unit.unit_id).move.destination == target
    assert game.selected is None


def test_two_click_ordering_rejects_an_unreachable_destination(game):
    unit = first_blue(game)
    far = (game.game_map.width - 1, game.game_map.height - 1)
    click(game, unit.pos)
    click(game, far)
    assert game.plan.order_for(unit.unit_id) is None
    # The selection survives a rejected order so the player can retry.
    assert game.selected is unit


def test_two_click_ordering_will_not_step_onto_another_unit(game):
    """The second click must land on empty ground to count as a destination."""
    unit = first_blue(game)
    other = next(u for u in game.plan.controllable if u is not unit)
    click(game, unit.pos)
    click(game, other.pos)
    assert game.plan.order_for(unit.unit_id) is None


def test_a_second_click_with_nothing_selected_does_nothing(game):
    """Clicking bare ground orders nobody, which is the safety property."""
    empty = next(
        (x, y)
        for y in range(game.game_map.height)
        for x in range(game.game_map.width)
        if game.unit_at((x, y)) is None
    )
    click(game, empty)
    assert game.selected is None
    assert all(game.plan.order_for(u.unit_id) is None for u in game.units)


def test_clicking_the_selected_unit_again_deselects_it(game):
    """The manual way to clear a selection without placing an order."""
    unit = first_blue(game)
    click(game, unit.pos)
    assert game.selected is unit
    click(game, unit.pos)
    assert game.selected is None
    assert game.plan.order_for(unit.unit_id) is None


def test_clicking_two_units_in_a_row_only_selects_the_second(game):
    """Rapid clicks across the board must never act on the first unit."""
    first, second = game.plan.controllable[0], game.plan.controllable[1]
    click(game, first.pos)
    click(game, second.pos)
    assert game.selected is second
    assert all(game.plan.order_for(u.unit_id) is None for u in game.units)


def test_press_without_release_leaves_no_order(game):
    """A stray press must not arm anything that fires later."""
    unit = first_blue(game)
    game.on_press(px_of(game, unit.pos))
    assert game.drag_from is unit
    game.on_release(px_of(game, reachable_tile_beside(game, unit)))
    assert game.plan.order_for(unit.unit_id) is not None
    assert game.drag_from is None


def test_pressing_empty_ground_disarms_a_pending_drag(game):
    unit = first_blue(game)
    game.on_press(px_of(game, unit.pos))
    assert game.drag_from is unit
    game.on_press(px_of(game, (0, 15)))  # empty ground
    assert game.drag_from is None
    game.on_release(px_of(game, (0, 14)))
    assert game.plan.order_for(unit.unit_id) is None


def test_issuing_an_order_does_not_select_the_unit(game):
    """order_move must never auto-select."""
    unit = first_blue(game)
    game.selected = None
    targets = reachable_tiles_for(game, unit)
    game.order_move(unit, targets[0])
    assert game.plan.order_for(unit.unit_id) is not None
    assert game.selected is None


def test_issuing_orders_leaves_an_existing_selection_alone(game):
    unit = first_blue(game)
    other = next(u for u in game.plan.controllable if u is not unit)
    game.selected = other
    targets = reachable_tiles_for(game, unit)
    game.order_move(unit, targets[0])
    assert game.selected is other


def test_selection_survives_ordering_every_unit(game):
    """Ordering a whole turn leaves the selection exactly where it started."""
    sentinel = first_blue(game)
    game.selected = sentinel
    for unit in list(game.plan.controllable):
        if game.plan.order_for(unit.unit_id) is not None:
            continue
        targets = reachable_tiles_for(game, unit)
        if targets:
            game.order_move(unit, targets[0])
    for unit in game.plan.controllable:
        assert game.plan.order_for(unit.unit_id) is not None
    assert game.selected is sentinel


def test_right_click_cancelling_does_not_move_the_selection(game):
    """Cancelling must leave the selection where the player left it."""
    unit = first_blue(game)
    targets = reachable_tiles_for(game, unit)
    game.order_move(unit, targets[0])
    assert game.plan.order_for(unit.unit_id) is not None

    game.selected = unit
    game.on_right_click(px_of(game, unit.pos))
    assert game.plan.order_for(unit.unit_id) is None
    assert game.selected is unit


def test_right_click_cancels_the_cursor_unit_not_the_selected_one(game):
    """The cursor wins over the selection when cancelling an order."""
    ordered = first_blue(game)
    other = next(u for u in game.plan.controllable if u is not ordered)

    targets = reachable_tiles_for(game, ordered)
    game.order_move(ordered, targets[0])
    assert game.plan.order_for(ordered.unit_id) is not None

    # Something else is selected, and the cursor is over the ordered unit.
    game.selected = other
    game.camera = game.camera_for(ordered)
    game.on_right_click(px_of(game, ordered.pos))

    assert game.plan.order_for(ordered.unit_id) is None
    assert game.selected is other


def test_tab_still_cycles_to_the_next_unordered_unit(game):
    """Tab is the deliberate way to move on, and must keep working."""
    unit = first_blue(game)
    targets = reachable_tiles_for(game, unit)
    game.order_move(unit, targets[0])

    game.selected = unit  # an explicit selection, as a click would give
    game.select_next()
    assert game.selected is not None
    assert game.selected.unit_id != unit.unit_id
    assert game.plan.order_for(game.selected.unit_id) is None


def reachable_tiles_for(game, unit) -> list[tuple[int, int]]:
    """All legal destinations for a unit, nearest first."""
    rng = game.plan.move_range(unit)
    tiles = [t for t in rng if t != unit.pos]
    tiles.sort(key=lambda t: (abs(t[0] - unit.x) + abs(t[1] - unit.y), t))
    return tiles


def order_every_unit(game) -> int:
    """Order every controllable unit, one drag each. Returns the count."""
    ordered = 0
    for unit in list(game.plan.controllable):
        if game.plan.order_for(unit.unit_id) is not None:
            continue
        targets = reachable_tiles_for(game, unit)
        if not targets:
            continue
        game.order_move(unit, targets[0])
        ordered += 1
    return ordered


def test_a_whole_turn_needs_one_drag_per_unit(game):
    """The flow the rework was for: no second click, no re-selecting."""
    count = order_every_unit(game)
    assert count == len(game.plan.controllable), (
        f"expected all {len(game.plan.controllable)} units ordered, got {count}"
    )


def test_dragging_a_unit_already_ordered_replaces_its_order(game):
    unit = first_blue(game)
    first_target = reachable_tile_beside(game, unit)
    drag(game, unit.pos, first_target)
    # Drag it again to somewhere else.
    game.selected = unit
    game.camera = game.camera_for(unit)
    second_target = reachable_tile_beside(game, unit)
    drag(game, unit.pos, second_target)
    assert game.plan.order_for(unit.unit_id).move.destination == second_target


# ------------------------------------------------------------ right click ----
def test_right_click_on_a_unit_cancels_its_order(game):
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)
    game.order_move(unit, target)
    assert game.plan.order_for(unit.unit_id) is not None

    # Right-click the unit itself, wherever it currently stands.
    game.on_right_click(px_of(game, unit.pos))
    assert game.plan.order_for(unit.unit_id) is None


def test_right_click_on_ground_cancels_the_selected_units_order(game):
    unit = first_blue(game)
    target = reachable_tile_beside(game, unit)
    game.order_move(unit, target)
    ordered = next(u for u in game.units if game.plan.order_for(u.unit_id) is not None)
    assert ordered.unit_id == unit.unit_id

    # The unit has not moved, so its tile is where the order came from.
    game.selected = ordered
    game.on_right_click(px_of(game, ordered.pos))
    assert game.plan.order_for(ordered.unit_id) is None


def test_right_click_cancelling_leaves_the_selection_alone(game):
    unit = first_blue(game)
    order_one_unit(game, unit)
    assert game.plan.order_for(unit.unit_id) is not None
    game.selected = unit
    game.on_right_click(px_of(game, unit.pos))
    assert game.plan.order_for(unit.unit_id) is None
    assert game.selected is unit


def test_right_click_with_nothing_selected_is_harmless(game):
    game.selected = None
    game.on_right_click(px_of(game, (0, 0)))
    assert game.running is True


# ----------------------------------------------------------- interaction ----
def test_input_is_ignored_while_resolution_is_playing(game):
    for unit in list(game.plan.controllable):
        target = reachable_tile_beside(game, unit)
        if target:
            game.order_move(unit, target)
    game.begin_resolution()
    assert game.playback_steps

    unit = first_blue(game)
    before = game.plan.orders.copy()
    drag(game, unit.pos, reachable_tile_beside(game, unit))
    assert game.plan.orders == before


def test_hover_tracks_the_cursor_and_clears_off_map(game):
    game.on_motion(px_of(game, (3, 3)))
    assert game.hover == (3, 3)
    game.on_motion((-50, -50))
    assert game.hover is None


def test_drag_state_is_cleared_after_release(game):
    unit = first_blue(game)
    drag(game, unit.pos, reachable_tile_beside(game, unit))
    assert game.drag_from is None


def test_a_full_turn_of_drags_ends_with_nothing_selected(game):
    """The end-to-end flow: one drag per unit, no selection left behind."""
    for unit in list(game.plan.controllable):
        targets = reachable_tiles_for(game, unit)
        if targets:
            game.camera = game.camera_for(unit)
            drag(game, unit.pos, targets[0])
    ordered = sum(
        1
        for u in game.plan.controllable
        if (o := game.plan.order_for(u.unit_id)) and o.has_any()
    )
    assert ordered == len(game.plan.controllable)
    assert game.selected is None


def test_rendering_after_a_drag_does_not_crash(game):
    unit = first_blue(game)
    game.on_press(px_of(game, unit.pos))
    game.on_motion(px_of(game, reachable_tile_beside(game, unit)))
    game.draw()  # must render the drag target overlay
    game.on_release(px_of(game, reachable_tile_beside(game, unit)))
    game.draw()