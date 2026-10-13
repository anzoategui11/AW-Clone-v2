"""Entry point. Runs the planning phase, then plays back the resolution.

For now a single human controls Blue and the AI plays Red. Both plans are built
first, then handed to the resolver together -- that is the whole simultaneous
idea, and watching both sides move at once is the point of the exercise.
"""

from __future__ import annotations

import os
import sys

import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aw_clone import ai
from aw_clone.config import (
    CELL,
    CURSOR_INITIAL_DELAY_MS,
    CURSOR_REPEAT_MS,
    FPS,
    MOVE_TICK_MS,
    SIDE_PANEL_W,
)

# Re-exported on the Game instance for convenience and so tests can reach the
# constants through a running game object.
CELL = CELL
MOVE_TICK_MS = MOVE_TICK_MS
from aw_clone.scenario import new_game
from aw_clone.turn import TurnPlan, resolve_movement
from aw_clone.units import Unit
from aw_clone.ui import renderer as R

PLAYER_OWNER = 1
AI_OWNER = 2

# Whether the AI opponent plans orders of its own each turn.
#
# Temporarily off while the movement rules are being tuned.
# The AI code is untouched and still covered by
# tests; only the call site is disabled, so flipping this back to True restores
# simultaneous play with no other change.
AI_PLANNING_ENABLED = False

# WASD drives the keyboard cursor; the arrows are left for panning the view.
CURSOR_KEYS: dict[int, tuple[int, int]] = {
    pygame.K_w: (0, -1),
    pygame.K_a: (-1, 0),
    pygame.K_s: (0, 1),
    pygame.K_d: (1, 0),
}


class Game:
    def __init__(self, headless: bool = False):
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
        if headless:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
        pygame.init()

        self.game_map, self.units = new_game()

        # The map is the window minus the side panel; floor division keeps the
        # grid aligned to whole pixels so tiles never shimmer while panning.
        self.panel_w = SIDE_PANEL_W
        self.win_w, self.win_h = 1280, 800
        self.view_w = self.win_w - self.panel_w
        self.view_h = self.win_h
        self.map_w = self.game_map.width * CELL
        self.map_h = self.game_map.height * CELL
        self.max_cam_x = max(0, self.map_w - self.view_w)
        self.max_cam_y = max(0, self.map_h - self.view_h)

        flags = 0 if headless else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((self.win_w, self.win_h), flags)
        if not headless:
            pygame.display.set_caption("Advance Wars Clone - simultaneous turns")
        self.clock = pygame.time.Clock()

        self.viewport = pygame.Rect(0, 0, self.view_w, self.view_h)
        self.camera = (0, 0)

        self.plan = TurnPlan(self.game_map, self.units, active_owner=PLAYER_OWNER)
        self.selected: Unit | None = None
        self.hover: tuple[int, int] | None = None
        # Keyboard cursor: a tile pointer driven by WASD, used to select units
        # and place orders without a mouse. Starts on the first unit so it is
        # never parked on empty ground at the start of a game.
        self.cursor: tuple[int, int] = self._starting_cursor()
        self.cursor_timer = 0
        self.cursor_key: int | None = None
        self.message = ""
        self.message_timer = 0
        self.turn_number = 1

        # Resolution playback state.
        self.playback_steps: list = []
        self.playback_index = 0
        self.playback_timer = 0
        self.playback_from: dict[int, tuple[int, int]] = {}

        # The unit a left-press landed on, held for the duration of a drag.
        self.drag_from: Unit | None = None

        # Instance-level handles to the module constants, so a caller holding a
        # Game does not need to reach into `main` for them.
        self.CELL = CELL
        self.MOVE_TICK_MS = MOVE_TICK_MS

        self.running = True
        self.headless = headless
        self.screenshot_path = "screenshot.png"

    # ------------------------------------------------------------ helpers ----
    def unit_at(self, tile: tuple[int, int]) -> Unit | None:
        for u in self.units:
            if u.alive and u.pos == tile:
                return u
        return None

    def _starting_cursor(self) -> tuple[int, int]:
        """Where the cursor sits on a new turn: the first unit awaiting orders.

        Falls back to the map's centre if every unit already has an order, so
        the cursor is never left pointing at nothing in particular.
        """
        pending = [u for u in self.plan.controllable if not self.plan.order_for(u.unit_id)]
        if pending:
            return pending[0].pos
        return (self.game_map.width // 2, self.game_map.height // 2)

    # ------------------------------------------------------------ cursor ----
    #
    # The cursor is a tile pointer, not a screen pointer. It exists so unit
    # selection and ordering do not need a mouse, which is the whole reason it
    # is separate from ``hover``.
    #
    #   WASD   step one tile, then repeat while held
    #   Space  act on the tile it points at: select a unit standing there, or
    #          send the selected unit there if the tile is empty
    #
    # The arrows keep their old job of panning the camera. The map is larger
    # than the window, so the cursor and the camera move independently.

    def move_cursor(self, direction: tuple[int, int]) -> None:
        """Step the cursor on keydown and restart the hold-to-repeat delay.

        The step is immediate rather than waiting out the delay: a single tap
        should move exactly one tile, and holding is what earns the repeat.
        """
        self.step_cursor(direction)
        self.cursor_key = None
        self.cursor_timer = 0

    def step_cursor(self, direction: tuple[int, int]) -> bool:
        """Move the cursor one tile. Returns False at the map edge.

        Clamped rather than refused, so holding a key against a wall is a no-op
        instead of stalling the repeat timer.
        """
        dx, dy = direction
        x = min(max(self.cursor[0] + dx, 0), self.game_map.width - 1)
        y = min(max(self.cursor[1] + dy, 0), self.game_map.height - 1)
        if (x, y) == self.cursor:
            return False
        self.cursor = (x, y)
        return True

    def toggle_order_or_selection(self, unit: Unit) -> None:
        """Select, or cancel the order of an already-selected unit.

        Selection takes priority over cancelling. Landing the cursor on a unit
        that already has an order selects it and leaves the order alone, so the
        next press can undo it. That gives a four-press loop:

            Space  select        Space  select
            D  →   order         D  →   order
            A  ←   select        A  ←   select
            Space  cancel        Space  deselect

        Cancelling keeps the unit selected, so a replacement order is one move
        and one press away.
        """
        if self.selected is not unit:
            self.select(unit)
            return
        order = self.plan.order_for(unit.unit_id)
        if order is not None and order.has_any():
            self.plan.clear(unit.unit_id)
            self.notify("Order cancelled")
        else:
            self.select(None)

    def act_at_cursor(self) -> None:
        """Select, order, or cancel at the cursor.

        On one of your units: cancel its order if it has one, else select it.
        On empty ground: send the selected unit there. Rejected orders leave the
        selection alone, so you can nudge the cursor away and try again.
        """
        tile = self.cursor
        occupant = self.unit_at(tile)
        if occupant is not None:
            if occupant.owner == PLAYER_OWNER:
                self.toggle_order_or_selection(occupant)
            # An enemy under the cursor changes nothing, matching the mouse.
            return
        if self.selected is not None and self.order_move(self.selected, tile):
            self.select(None)

    def update_cursor_repeat(self, dt_ms: int) -> bool:
        """Repeat the held WASD key. Returns True if the cursor moved."""
        held = [k for k in CURSOR_KEYS if R.key_held(pygame.key.get_pressed(), k)]
        if not held:
            self.cursor_key = None
            self.cursor_timer = 0
            return False
        if self.cursor_key != held[0]:
            # A new direction was pressed; start its delay over.
            self.cursor_key = held[0]
            self.cursor_timer = 0
            return False

        self.cursor_timer += dt_ms
        if self.cursor_timer < CURSOR_INITIAL_DELAY_MS:
            return False
        # Rewind to just before the next repeat rather than clearing, so the
        # steady rate is CURSOR_REPEAT_MS and not the initial delay again.
        self.cursor_timer = CURSOR_INITIAL_DELAY_MS - CURSOR_REPEAT_MS
        return self.step_cursor(CURSOR_KEYS[held[0]])

    def notify(self, text: str, ticks: int = 180) -> None:
        self.message = text
        self.message_timer = ticks

    def tick_message(self) -> None:
        if self.message_timer > 0:
            self.message_timer -= 1
            if self.message_timer == 0:
                self.message = ""

    def select(self, unit: Unit | None) -> None:
        """Select a unit and put the cursor on it.

        Every way of picking a unit goes through here, mouse or keyboard, so the
        cursor and the selection can never drift onto different units.
        """
        self.selected = unit
        if unit is not None:
            self.cursor = unit.pos

    def select_next(self) -> None:
        """Cycle to the next unit with no queued order."""
        units = [u for u in self.plan.controllable if u.alive]
        if not units:
            self.selected = None
            return
        pending = [u for u in units if not self.plan.order_for(u.unit_id)]
        if not pending:
            self.notify("All units have orders - press Enter to resolve")
            return
        if self.selected in units:
            idx = units.index(self.selected)
            for offset in range(1, len(units) + 1):
                candidate = units[(idx + offset) % len(units)]
                if not self.plan.order_for(candidate.unit_id):
                    self.select(candidate)
                    return
        else:
            self.select(pending[0])

    def camera_for(self, unit: Unit) -> tuple[int, int]:
        """Camera offset that centres the viewport on ``unit``."""
        return self.camera_for_tile(unit.pos)

    def camera_for_tile(self, tile: tuple[int, int]) -> tuple[int, int]:
        """Camera offset that centres the viewport on a tile.

        The map is larger than the window, so a tile can sit off-screen. This
        clamps the result to the map bounds, so the view never shows empty space
        outside the grid.
        """
        target_x = tile[0] * CELL + CELL // 2 - self.view_w // 2
        target_y = tile[1] * CELL + CELL // 2 - self.view_h // 2
        return (
            max(0, min(target_x, self.max_cam_x)),
            max(0, min(target_y, self.max_cam_y)),
        )

    # ------------------------------------------------------------- input ----
    #
    # Mouse:
    #
    #   drag     press on the unit, drag to a destination, release
    #   two-click click the unit to select it, then click the destination
    #
    # A click is a press and release on the same tile, so the two modes are told
    # apart by whether the press landed on your own unit:
    #
    #   press on your unit, release elsewhere -> drag order, then deselect
    #   press on your unit, release on itself -> select it
    #   press elsewhere, selected unit exists -> order it to that tile
    #   press elsewhere, nothing selected -> nothing happens
    #
    # The selection is cleared once an order is placed, in either mode. Holding
    # it left a stale unit selected, so a later click could act on the wrong one.
    # Clicking the already-selected unit again is the way to deselect by hand.
    #
    # Keyboard:
    #
    #   WASD   move the cursor one tile
    #   Space  act on the tile under the cursor, the same two-click flow
    #   arrows pan the camera
    #
    # The two paths are deliberately interchangeable: act_at_cursor is written
    # against the same unit_at / order_move calls the mouse uses, so the cursor
    # can never grant an ordering the mouse would have refused.

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key in CURSOR_KEYS:
                self.move_cursor(CURSOR_KEYS[event.key])
            elif event.key == pygame.K_SPACE:
                # Space was a redundant alias for "resolve"; it now acts at the
                # cursor. Enter still resolves the turn.
                self.act_at_cursor()
            elif event.key == pygame.K_TAB:
                self.select_next()
            elif event.key == pygame.K_r:
                self.plan.clear_all()
                self.selected = None
                self.notify("Orders cleared")
            elif event.key == pygame.K_e:
                self.begin_resolution()
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.begin_resolution()

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.on_press(event.pos)
            elif event.button == 3:
                self.on_right_click(event.pos)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.on_release(event.pos)

        elif event.type == pygame.MOUSEMOTION:
            self.on_motion(event.pos)

    def on_motion(self, pos: tuple[int, int]) -> None:
        self.hover = self.tile_at(pos)

    def tile_at(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        """Tile under the cursor, or None if it is off the map."""
        tile = R.tile_at_pixel(pos[0], pos[1], self.camera)
        if tile is not None and self.game_map.in_bounds(*tile):
            return tile
        return None

    def on_press(self, pos: tuple[int, int]) -> None:
        """Left button down: arm a drag if the press landed on your own unit."""
        self.drag_from = None
        if self.playback_steps:
            return

        tile = self.tile_at(pos)
        clicked = self.unit_at(tile) if tile is not None else None
        if clicked is not None and clicked.owner == PLAYER_OWNER:
            # Selection itself is decided on release, so a click can toggle.
            self.drag_from = clicked
            return
        if clicked is not None:
            # An enemy under the cursor. Leave the selection alone so an
            # accidental click on one does not discard a unit mid-order.
            return

    def on_release(self, pos: tuple[int, int]) -> None:
        """Left button up: resolve the gesture into a selection or an order."""
        dragged = self.drag_from
        self.drag_from = None
        if self.playback_steps:
            return

        tile = self.tile_at(pos)

        if dragged is not None:
            # The gesture started on one of your units, so this is a drag.
            if tile == dragged.pos:
                # A click on the unit itself, same rule as Space: cancel an
                # existing order, otherwise toggle the selection.
                self.toggle_order_or_selection(dragged)
                return
            if tile is None:
                # Released off the map: keep the selection, order nothing.
                self.select(dragged)
                return
            self.order_move(dragged, tile)
            self.select(None)
            return

        # The press did not land on your unit, so this is the second click of a
        # two-click order, aimed at the currently selected unit.
        if self.selected is None or tile is None:
            return
        if self.unit_at(tile) is not None:
            # Clicking another unit selects it, which on_press already handled.
            return
        if self.order_move(self.selected, tile):
            # Only drop the selection if the order actually landed. A rejected
            # order keeps it, so the player can aim somewhere reachable instead.
            self.select(None)

    def order_move(self, unit: Unit, tile: tuple[int, int]) -> bool:
        """Queue a move for ``unit``. Does not touch the selection.

        Returns whether the order was placed.
        """
        if not self.plan.set_move(unit, tile):
            if tile != unit.pos:
                self.notify("Cannot reach that tile")
            return False

        outstanding = [
            u for u in self.plan.controllable if not self.plan.order_for(u.unit_id)
        ]
        if outstanding:
            self.notify(f"{unit.unit_type.name} ordered")
        else:
            self.notify("All units ordered - press Enter to resolve", 240)
        return True

    def on_right_click(self, pos: tuple[int, int]) -> None:
        """Cancel an order on the unit under the mouse, if it has one.

        Deliberately does not change the selection. Right-clicking a unit to
        fix its order must not pull the current selection away, so correcting a
        mistake leaves you exactly where you were.
        """
        if self.playback_steps:
            return
        tile = R.tile_at_pixel(pos[0], pos[1], self.camera)
        clicked = None
        if tile is not None and self.game_map.in_bounds(*tile):
            clicked = self.unit_at(tile)

        if clicked is not None:
            if self.plan.order_for(clicked.unit_id) is not None:
                self.plan.clear(clicked.unit_id)
                self.notify("Order cancelled")
            return
        if self.selected is not None:
            self.selected = None

    # -------------------------------------------------------- resolution ----
    def begin_resolution(self) -> None:
        if self.playback_steps:
            return

        # Both sides plan before anything resolves. With AI_PLANNING_ENABLED off,
        # only the player's orders exist, so resolution replays those alone.
        combined = dict(self.plan.orders)
        if AI_PLANNING_ENABLED:
            combined.update(ai.plan_turn(self.game_map, self.units, AI_OWNER))

        resolution = resolve_movement(self.game_map, self.units, combined)
        if not resolution.steps:
            self.notify("No movement this turn")
            self.turn_number += 1
            self.plan.clear_all()
            self.selected = None
            return

        self.playback_steps = resolution.steps
        self.playback_index = 0
        self.playback_timer = 0
        self.playback_from = self.snapshot_positions()
        for u in self.units:
            u.has_moved = True

    def snapshot_positions(self) -> dict[int, tuple[int, int]]:
        return {u.unit_id: u.pos for u in self.units}

    def advance_playback(self, dt_ms: int) -> None:
        """Drive the resolution animation. Never sleeps; the loop paces it."""
        if not self.playback_steps:
            return
        self.playback_timer += dt_ms
        if self.playback_timer < MOVE_TICK_MS:
            return
        self.playback_timer = 0

        step = self.playback_steps[self.playback_index]

        # Commit this tick's moves to the model.
        for uid, dest in step.moved.items():
            for u in self.units:
                if u.unit_id == uid:
                    u.x, u.y = dest

        # The next tick animates from where the units now are.
        self.playback_from = self.snapshot_positions()
        self.playback_index += 1

        if self.playback_index >= len(self.playback_steps):
            self.playback_steps = []
            self.playback_index = 0
            self.playback_from = {}
            self.turn_number += 1
            self.plan.clear_all()
            self.selected = None
            self.notify("Turn complete")
            for u in self.units:
                u.reset_for_turn()
                u.has_moved = False

    # -------------------------------------------------------------- draw ----
    def draw(self) -> None:
        self.screen.fill(R.COLORS["bg"])

        step = None
        if self.playback_steps:
            step = self.playback_steps[self.playback_index]

        R.draw_map(self.screen, self.game_map, self.camera, self.viewport)

        planning = self.selected is not None and not self.playback_steps
        move_range: dict[tuple[int, int], int] = {}

        if planning:
            move_range = self.plan.move_range(self.selected)
            R.draw_move_range(
                self.screen, self.camera, move_range, self.selected.pos
            )
            if self.hover is not None and self.hover != self.selected.pos:
                preview = self.plan.preview_path(self.selected, self.hover)
                R.draw_path_preview(
                    self.screen,
                    self.camera,
                    preview,
                    valid=bool(preview),
                )

        # While a drag is in progress, mark the tile under the cursor so the
        # legality of the drop is visible before releasing.
        if self.drag_from is not None and self.hover is not None:
            reach = set(self.plan.move_range(self.drag_from))
            R.draw_drag_target(self.screen, self.camera, self.hover, reach)

        # Interpolate from the previous commit toward this tick's destination.
        animating: dict[int, tuple[int, int, float]] = {}
        if step is not None:
            progress = min(1.0, self.playback_timer / MOVE_TICK_MS)
            for uid, dest in step.moved.items():
                for u in self.units:
                    if u.unit_id == uid:
                        src = self.playback_from.get(uid, dest)
                        animating[uid] = (src[0], src[1], progress)

        # Clip unit drawing to the map viewport so sprites never spill into the
        # side panel while the camera is panned.
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(self.viewport)

        # Far-to-near ordering, so lower rows overlap the row above.
        for u in sorted([x for x in self.units if x.alive], key=lambda u: (u.y, u.x)):
            order = self.plan.order_for(u.unit_id)
            has_order = bool(not self.playback_steps and order and order.has_any())
            R.draw_unit(
                self.screen,
                u,
                self.camera,
                selected=(u is self.selected and not self.playback_steps),
                has_order=has_order,
                interpolating=animating.get(u.unit_id),
            )

            # Arrow for queued orders, skipping the unit the preview already
            # traces so the two do not overlap.
            if has_order and not (u is self.selected):
                R.draw_order_arrow(self.screen, self.camera, u.pos, order.move.path)

        # The keyboard cursor goes last so its brackets sit over the sprites.
        # Red means a unit is selected and this tile is out of its reach.
        if not self.playback_steps:
            legal: bool | None = None
            if planning and self.cursor != self.selected.pos:
                legal = self.cursor in move_range
            R.draw_cursor(self.screen, self.camera, self.cursor, legal)
        self.screen.set_clip(previous_clip)

        if step is not None and step.blocked:
            self.notify(f"{len(step.blocked)} unit(s) blocked this tick", 60)

        queued = sum(
            1
            for u in self.plan.controllable
            if (o := self.plan.order_for(u.unit_id)) and o.has_any()
        )
        total = len(self.plan.controllable)
        phase = "Resolving" if self.playback_steps else "Planning (Blue)"
        R.draw_side_panel(
            self.screen,
            pygame.Rect(self.view_w, 0, self.panel_w, self.view_h),
            self.game_map,
            self.units,
            self.turn_number,
            phase,
            queued,
            total,
            self.selected,
            self.hover,
            self.message,
        )

        if self.headless:
            pygame.image.save(self.screen, self.screenshot_path)

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS)
            for event in pygame.event.get():
                self.handle_event(event)

            # Manual panning wins while a key is held. Otherwise the view tracks
            # whatever the player is working with: the selected unit, or the
            # cursor once nothing is selected. Since selecting a unit moves the
            # cursor onto it, this keeps the pointer on screen either way.
            self.update_cursor_repeat(dt)
            panned = R.update_camera(
                pygame.key.get_pressed(),
                self.camera,
                (self.max_cam_x, self.max_cam_y),
            )
            if panned != self.camera:
                self.camera = panned
            elif self.selected is not None:
                self.camera = self.camera_for(self.selected)
            else:
                self.camera = self.camera_for_tile(self.cursor)
            self.tick_message()
            self.advance_playback(dt)
            self.draw()
            pygame.display.flip()

        pygame.quit()


def main() -> None:
    headless = "--headless" in sys.argv
    frames = 0
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])

    game = Game(headless=headless)
    if not headless:
        game.run()
        return

    # Headless mode renders a fixed number of frames to a PNG so the UI can be
    # checked without a display. Simulate some clicks via a tiny script.
    if "--resolve" in sys.argv:
        for unit in game.plan.controllable:
            game.plan.set_move(unit, (unit.x + 3, unit.y))
        game.begin_resolution()
    if "--select" in sys.argv:
        game.selected = game.plan.controllable[0]

    if "--center" in sys.argv:
        # Frame the whole map, useful when checking both sides at once.
        game.camera = (game.max_cam_x // 2, game.max_cam_y // 2)

    idx = sys.argv.index("--out") + 1 if "--out" in sys.argv else None
    if idx:
        game.screenshot_path = sys.argv[idx]

    for _ in range(max(frames, 1)):
        game.advance_playback(MOVE_TICK_MS if game.playback_steps else 0)
        game.draw()
    print(f"wrote {game.screenshot_path}")
    pygame.quit()


if __name__ == "__main__":
    main()