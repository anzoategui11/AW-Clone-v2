"""Hit-testing: screen position to tile must survive camera panning.

``tile_at_pixel`` inverts the camera offset the renderer applies when drawing.
Getting the sign wrong shifts every click once the view is panned, which reads
to the player as the game ignoring their input. These tests pin the round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pygame = pytest.importorskip("pygame")
pygame.init()

from aw_clone.config import CELL  # noqa: E402
from aw_clone.ui.renderer import cell_rect, tile_at_pixel  # noqa: E402


def round_trip(tile: tuple[int, int], camera: tuple[int, int]) -> tuple[int, int]:
    """Draw a tile's rect at ``camera``, then hit-test the rect's centre."""
    rect = cell_rect(tile[0], tile[1], -camera[0], -camera[1])
    return tile_at_pixel(rect.centerx, rect.centery, camera)


def test_hit_testing_is_exact_with_no_panning():
    assert tile_at_pixel(0, 0, (0, 0)) == (0, 0)
    assert tile_at_pixel(CELL, CELL, (0, 0)) == (1, 1)


def test_hit_testing_uses_the_whole_tile_not_just_its_origin():
    """Every pixel of a tile must map back to that tile."""
    for offset in range(0, CELL, 7):
        assert tile_at_pixel(offset, offset, (0, 0)) == (0, 0)
    # The last row of pixels belongs to tile (0,0); the first pixel past the
    # tile boundary starts tile (1,0).
    assert tile_at_pixel(CELL - 1, CELL - 1, (0, 0)) == (0, 0)
    assert tile_at_pixel(CELL, CELL, (0, 0)) == (1, 1)


@pytest.mark.parametrize(
    "camera",
    [(0, 0), (64, 0), (0, 64), (64, 64), (320, 224), (1000, 700)],
)
def test_round_trip_holds_for_every_camera_position(camera):
    for tile in [(0, 0), (1, 0), (0, 1), (5, 7), (12, 9), (23, 15)]:
        assert round_trip(tile, camera) == tile, (
            f"camera={camera} tile={tile} -> {round_trip(tile, camera)}"
        )


def test_panning_right_makes_a_tile_appear_further_left():
    """Drawing subtracts the camera, so hit-testing must add it back."""
    tile = (5, 5)
    rect_unpanned = cell_rect(*tile, 0, 0)
    rect_panned = cell_rect(*tile, -320, 0)
    assert rect_panned.left == rect_unpanned.left - 320
    assert tile_at_pixel(rect_panned.centerx, rect_panned.centery, (320, 0)) == tile


def test_negative_screen_coordinates_still_map_correctly():
    """A tile scrolled off the top-left has negative screen coords."""
    assert round_trip((0, 0), (500, 400)) == (0, 0)
    assert round_trip((2, 3), (500, 400)) == (2, 3)


def test_cell_rect_matches_the_tile_size():
    rect = cell_rect(4, 7, -100, -200)
    assert rect.width == CELL
    assert rect.height == CELL
    assert rect.left == 4 * CELL - 100
    assert rect.top == 7 * CELL - 200