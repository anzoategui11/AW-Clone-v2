"""Central tunables. Keeping resolution numbers here makes them easy to adjust."""

from __future__ import annotations

# ---------------------------------------------------------------- display ----
TILE_SIZE = 16  # native sprite resolution (pixels)
TILE_SCALE = 4  # upscale factor -> 64px on screen
CELL = TILE_SIZE * TILE_SCALE
SIDE_PANEL_W = 260
FPS = 60

# Resolution animation pacing.
MOVE_TICK_MS = 130  # one tile step
FRAME_MS = 16  # animation frame cap

# ------------------------------------------------------------- turn / sim ----
NEXT_UNIT_ID = 1

# Movement is orthogonal only, as in Advance Wars 2. A unit steps up, down, left
# or right; there is no diagonal move, so every route is a sum of orthogonal
# steps. That also makes Manhattan distance the exact step count on open ground,
# which is what the AI scores its approach with.
STEP_COST = 1

# Terrain penalty added on top of the step cost, per movement class.
#
# Entering a tile costs ``STEP_COST + penalty``. Road, bridge and HQ are the
# baseline at zero penalty, so stepping onto one costs exactly 1.
#
# Everything else adds difficulty. This is the main knob for how "open" the game
# feels, so the numbers here are the first thing to tune.
MOVE_PENALTIES: dict[str, dict[str, int]] = {
    "boot": {
        "road": 0,
        "plain": 0,  # infantry move freely over open ground
        "forest": 1,  # infantry cut through woods
        "river": 2,
        "bridge": 0,
        "mountain": 3,
        "hq": 0,
        "sea": 99,
    },
    "tread": {
        "road": 0,
        "plain": 1,
        "forest": 3,  # heavy vehicles grind through trees
        "river": 3,
        "bridge": 0,
        "mountain": 99,  # tracked vehicles cannot climb
        "hq": 0,
        "sea": 99,
    },
    # Aircraft ignore terrain entirely.
    "air": {
        "road": 0,
        "plain": 0,
        "forest": 0,
        "river": 0,
        "bridge": 0,
        "mountain": 0,
        "hq": 0,
        "sea": 0,
    },
}

# A terrain penalty at or above this is treated as impassable.
IMPASSABLE_PENALTY = 99

# ------------------------------------------------------------- factions ----
FACTION_NAMES = {1: "Blue", 2: "Red"}

# Palette, loosely following the military look of Advance Wars.
COLORS: dict[str, tuple[int, int, int]] = {
    "bg": (16, 18, 24),
    "panel": (26, 30, 40),
    "panel_edge": (58, 66, 84),
    "text": (222, 228, 238),
    "text_dim": (140, 150, 168),
    "text_accent": (255, 209, 102),
    "cursor": (255, 255, 255),
    "grid": (0, 0, 0),
    "p1": (64, 128, 224),
    "p2": (216, 72, 64),
    "move_range": (86, 150, 255),
    "move_range_edge": (140, 196, 255),
    "path": (255, 236, 140),
    "order_mark": (255, 209, 102),
    "block": (232, 96, 96),
}

# Selection / range overlay alpha.
OVERLAY_ALPHA = 96