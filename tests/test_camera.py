"""Regression tests for camera panning and following.

The ``update_camera`` signature changed during development (the argument order
was swapped), which broke the run loop at runtime. These tests cover the
function directly so a signature change fails here instead of on launch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pygame = pytest.importorskip("pygame")
pygame.init()

from aw_clone.config import CELL  # noqa: E402
from aw_clone.scenario import new_game  # noqa: E402
from aw_clone.ui.renderer import update_camera  # noqa: E402


class FakeScancodeWrapper:
    """Mimics pygame.key.get_pressed(): supports ``[]``, has no ``.get()``.

    The real ScancodeWrapper is read-only, so this stands in for it rather than
    mutating one.
    """

    def __init__(self, pressed: set[int]) -> None:
        self._pressed = pressed

    def __getitem__(self, key: int) -> bool:
        # The real ScancodeWrapper covers every known key code and returns
        # False for the ones that are not held, rather than raising KeyError.
        return key in self._pressed


def no_keys() -> dict[str, bool]:
    """An all-False key state, as pygame.key.get_pressed() would return."""
    return {}


def fake_keys(*codes: int) -> FakeScancodeWrapper:
    return FakeScancodeWrapper(set(codes))


def test_no_keys_holds_the_camera_still():
    assert update_camera(no_keys(), (100, 100), (500, 500)) == (100, 100)


def test_right_key_increases_x():
    keys = {pygame.K_RIGHT: True}
    assert update_camera(keys, (100, 100), (500, 500))[0] > 100


def test_left_key_decreases_x():
    keys = {pygame.K_LEFT: True}
    assert update_camera(keys, (100, 100), (500, 500))[0] < 100


def test_up_key_decreases_y():
    keys = {pygame.K_UP: True}
    assert update_camera(keys, (100, 100), (500, 500))[1] < 100


def test_wasd_is_an_alias_for_the_arrow_keys():
    assert update_camera({pygame.K_d: True}, (100, 100), (500, 500)) == (
        update_camera({pygame.K_RIGHT: True}, (100, 100), (500, 500))
    )


def test_camera_clamps_at_the_left_edge():
    """Panning past the origin must not produce negative offsets."""
    keys = {pygame.K_LEFT: True}
    cam_x, cam_y = update_camera(keys, (0, 0), (500, 500))
    assert cam_x == 0
    assert cam_y == 0


def test_camera_clamps_at_the_far_edge():
    keys = {pygame.K_RIGHT: True}
    cam_x, _ = update_camera(keys, (500, 0), (500, 500))
    assert cam_x == 500


def test_repeated_pans_eventually_reach_the_clamp():
    camera = (0, 0)
    keys = {pygame.K_RIGHT: True}
    for _ in range(500):
        camera = update_camera(keys, camera, (300, 300))
    assert camera[0] == 300


def test_works_with_a_scancode_wrapper_style_key_state():
    """pygame's real key object supports [] but not .get().

    This is the exact bug that broke the run loop at launch, so it gets a
    direct regression test rather than relying on the real object.
    """
    assert update_camera(fake_keys(), (100, 100), (500, 500)) == (100, 100)
    assert update_camera(fake_keys(pygame.K_RIGHT), (100, 100), (500, 500))[0] == 106
    assert update_camera(fake_keys(pygame.K_LEFT), (100, 100), (500, 500))[0] == 94
    assert update_camera(fake_keys(pygame.K_DOWN), (100, 100), (500, 500))[1] == 106


def test_multiple_pan_keys_combine():
    """Holding two directions should net out to no movement on that axis."""
    assert update_camera(
        fake_keys(pygame.K_LEFT, pygame.K_RIGHT), (100, 100), (500, 500)
    ) == (100, 100)
    assert update_camera(fake_keys(pygame.K_UP, pygame.K_DOWN), (100, 100), (500, 500)) == (
        100,
        100,
    )


def test_panning_is_clamped_with_a_scancode_wrapper_too():
    camera = (0, 0)
    for _ in range(500):
        camera = update_camera(fake_keys(pygame.K_RIGHT), camera, (300, 300))
    assert camera[0] == 300


def test_camera_for_centres_the_view_on_a_unit():
    """The selected unit must land in the middle of the viewport."""
    game_map, units = new_game()
    panel_w = 260
    win_w, win_h = 1280, 800
    view_w = win_w - panel_w
    max_cam_x = max(0, game_map.width * CELL - view_w)
    max_cam_y = max(0, game_map.height * CELL - win_h)

    def camera_for(unit):
        tx = unit.x * CELL + CELL // 2 - view_w // 2
        ty = unit.y * CELL + CELL // 2 - win_h // 2
        return (
            max(0, min(tx, max_cam_x)),
            max(0, min(ty, max_cam_y)),
        )

    # A unit in the middle of the map should be roughly centred.
    centre_unit = units[0]
    centre_unit.x = game_map.width // 2
    centre_unit.y = game_map.height // 2
    cam_x, cam_y = camera_for(centre_unit)
    screen_x = centre_unit.x * CELL - cam_x
    assert abs(screen_x - view_w // 2) <= CELL


def test_camera_for_never_shows_space_outside_the_map():
    game_map, units = new_game()
    max_cam_x = max(0, game_map.width * CELL - 1020)
    max_cam_y = max(0, game_map.height * CELL - 800)
    for unit in units:
        for x in (0, game_map.width - 1):
            for y in (0, game_map.height - 1):
                unit.x, unit.y = x, y
                tx = x * CELL + CELL // 2 - 1020 // 2
                ty = y * CELL + CELL // 2 - 800 // 2
                cam = (
                    max(0, min(tx, max_cam_x)),
                    max(0, min(ty, max_cam_y)),
                )
                assert 0 <= cam[0] <= max_cam_x
                assert 0 <= cam[1] <= max_cam_y