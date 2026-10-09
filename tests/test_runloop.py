"""Smoke test for the run loop, which is where the launch crash surfaced.

Drives the real Game object headlessly for a handful of frames with synthetic
events, so the main loop's call sequence is exercised rather than assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pygame = pytest.importorskip("pygame")

import main as game_main  # noqa: E402


@pytest.fixture()
def game(monkeypatch):
    """A headless Game instance, torn down after the test."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    instance = game_main.Game(headless=True)
    instance.screenshot_path = "test_loop.png"
    yield instance
    pygame.quit()


def test_game_constructs_with_sane_dimensions(game):
    assert game.map_w == game.game_map.width * game.CELL
    assert game.panel_w > 0
    assert game.max_cam_x >= 0 and game.max_cam_y >= 0


def test_camera_update_runs_against_real_pygame_keys(game):
    """The exact call that raised ValueError on launch.

    pygame.key.get_pressed() returns a ScancodeWrapper, which the renderer must
    handle without unpacking it as a pair.
    """
    keys = pygame.key.get_pressed()
    camera = game_main.R.update_camera(
        keys, (0, 0), (game.max_cam_x, game.max_cam_y)
    )
    assert isinstance(camera, tuple) and len(camera) == 2
    assert 0 <= camera[0] <= game.max_cam_x
    assert 0 <= camera[1] <= game.max_cam_y


def test_run_loop_advances_frames_and_renders(game):
    """Drives the same statements run() uses, without entering the loop."""
    for _ in range(3):
        panned = game_main.R.update_camera(
            pygame.key.get_pressed(),
            game.camera,
            (game.max_cam_x, game.max_cam_y),
        )
        if panned != game.camera:
            game.camera = panned
        elif game.selected is not None:
            game.camera = game.camera_for(game.selected)
        game.tick_message()
        game.advance_playback(16)
        game.draw()
    assert Path(game.screenshot_path).exists()
    Path(game.screenshot_path).unlink()


def test_selecting_a_unit_and_resolving_runs_end_to_end(game):
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    assert game.selected is not None
    assert game.camera == game.camera_for(game.selected)

    # Order every controllable unit, then resolve.
    for unit in game.plan.controllable:
        game.plan.set_move(unit, (unit.x + 2, unit.y))
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert game.playback_steps, "resolution produced no frames"

    for _ in range(200):
        game.advance_playback(game.MOVE_TICK_MS)
        game.draw()
        if not game.playback_steps:
            break
    assert game.turn_number == 2
    Path(game.screenshot_path).unlink(missing_ok=True)


def test_quit_event_stops_the_loop(game):
    game.handle_event(pygame.event.Event(pygame.QUIT))
    assert game.running is False


def test_camera_follows_selection_and_stays_in_bounds(game):
    game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
    for unit in game.units:
        game.selected = unit
        game.camera = game.camera_for(unit)
        assert 0 <= game.camera[0] <= game.max_cam_x
        assert 0 <= game.camera[1] <= game.max_cam_y
        # The selected unit must be inside the viewport.
        screen_x = unit.x * game.CELL - game.camera[0]
        screen_y = unit.y * game.CELL - game.camera[1]
        assert 0 <= screen_x <= game.view_w
        assert 0 <= screen_y <= game.view_h