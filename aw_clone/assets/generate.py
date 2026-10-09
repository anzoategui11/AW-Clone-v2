"""Procedural pixel-art sprite generation.

Sprites are authored as small ASCII grids, one character per pixel, then
upscaled with NEAREST so they stay crisp. Regenerating is cheap, which keeps art
iteration to a code edit plus one command.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Palette: terrain keys map to (base, detail, shadow).
TERRAIN_PALETTE: dict[str, tuple[str, str, str]] = {
    "plain": ("7ba05b", "6b8f4e", "5c7d42"),
    "road": ("b0a48c", "9c9078", "8a7f69"),
    "forest": ("3f7a44", "356a39", "2a552d"),
    "mountain": ("8d8a86", "76736f", "605d5a"),
    "river": ("5b93c9", "4a7fb4", "3d6d9c"),
    "bridge": ("a8814f", "96713f", "806033"),
    "sea": ("3f6fa8", "356094", "2c5180"),
    "hq": ("c8a84a", "b0923a", "8f7530"),
}

# Base unit silhouette, tinted per faction.
UNIT_SHAPES: dict[str, dict[str, str]] = {
    "infantry": {
        "shadow": "000000",
        "body": "C",
        "trim": "E",
        "visor": "V",
        "accent": "A",
    },
    "mech": {
        "shadow": "000000",
        "body": "C",
        "trim": "E",
        "visor": "V",
        "accent": "A",
    },
    "artillery": {
        "shadow": "000000",
        "body": "C",
        "trim": "E",
        "visor": "V",
        "accent": "A",
    },
    "anti_air": {
        "shadow": "000000",
        "body": "C",
        "trim": "E",
        "visor": "V",
        "accent": "A",
    },
    "apc": {
        "shadow": "000000",
        "body": "C",
        "trim": "E",
        "visor": "V",
        "accent": "A",
    },
}

# '.' transparent, 'o' outline, 'c' body, 't' trim, 'v' visor, 'a' accent, 's' shadow
UNIT_ART: dict[str, list[str]] = {
    # Small figure with a helmet, reads clearly at 16px.
    "infantry": [
        "................",
        ".....oooooo.....",
        "....occcccco....",
        "....ocvvvvco....",
        "....occcccco....",
        ".....occcco.....",
        "....oaaaaaao....",
        "...oaccccccao...",
        "...occ....cco...",
        "...occ....cco...",
        "..oaccc..cccao..",
        "..occc....ccco..",
        "..occc....ccco..",
        "..osss....ssso..",
        "................",
        "................",
    ],
    # Bulkier torso with shoulder pads.
    "mech": [
        "................",
        "..ooo......ooo..",
        ".occcco....occcco",
        ".ocvvco....ocvvco",
        ".occcccoooccccco",
        "..occccccccccco..",
        "..oaacccccaacao..",
        "..occccaaaccco...",
        "..occccccccccc o",
        "..occccaaacccco.",
        "..oaccccccccdao.",
        "...occccccccccc o",
        "...occc..occcco.",
        "...osss..ossss..",
        "................",
        "................",
    ],
    # Wide chassis with a long barrel.
    "artillery": [
        "................",
        "................",
        "..........ooo...",
        "..........oto...",
        "..oooo....oto...",
        ".occcccooooto...",
        "ocvvccoccccto...",
        "occcccccccccо..",
        ".occccccccccco.",
        "..oaccccccccao.",
        "...occccccccco..",
        "...occ....cco...",
        "...occ....cco...",
        "..osss....ssso..",
        "................",
        "................",
    ],
    # Tracked vehicle with a raised missile rack.
    "anti_air": [
        "................",
        "......oooo......",
        ".....occccco....",
        "..oooocvvvcooo..",
        "..otttcccccccco.",
        "..occccccccccccc o",
        "..occaaacccaaaco.",
        "..occccccccccccc o",
        "..otttttttttttto.",
        "...occcccccccc o.",
        "...occc...cccco..",
        "...occc...cccco..",
        "..ossss...sssso..",
        "................",
        "................",
        "................",
    ],
    # Four-wheeled transport.
    "apc": [
        "................",
        "................",
        "...oooooooooo...",
        "..occcccccccco..",
        ".ocvvvvvvvvvvco.",
        ".occccccccccccc o",
        ".occcaaaaaaaccco.",
        ".occccccccccccc o",
        ".occccccccccccc o",
        "..otttttttttto..",
        "..occc....cccco.",
        "..osss....sssso.",
        "................",
        "................",
        "................",
        "................",
    ],
}

FACTION_TINT: dict[int, dict[str, str]] = {
    1: {"body": "4a7fd0", "trim": "3a63a8", "visor": "a8d4ff", "accent": "dce8f8"},
    2: {"d0_placeholder": "", "body": "c85048", "trim": "a03c36", "visor": "ffc0a8", "accent": "f8dcdc"},
}


def _hex(color: str) -> tuple[int, int, int]:
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def render_unit_sprite(unit_key: str, owner: int, size: int = 16) -> Image.Image:
    """Render one unit sprite as a transparent RGBA image."""
    art = UNIT_ART[unit_key]
    tint = FACTION_TINT[owner]
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    px = img.load()

    char_color = {
        "o": (26, 24, 22, 255),
        "c": _hex(tint["body"]),
        "t": _hex(tint["trim"]),
        "v": _hex(tint["visor"]),
        "a": _hex(tint["accent"]),
        "s": (0, 0, 0, 90),
    }

    for y, row in enumerate(art):
        for x, ch in enumerate(row[:16]):
            if ch == "." or ch == " ":
                continue
            color = char_color.get(ch)
            if color is None:
                continue
            px[x, y] = color

    return img.resize((size, size), Image.NEAREST)


def render_terrain_sprite(terrain: str, variant: int, size: int = 16) -> Image.Image:
    """Render a terrain tile. ``variant`` shifts texture so large areas tile."""
    base, detail, shadow = (_hex(c) for c in TERRAIN_PALETTE[terrain])
    img = Image.new("RGBA", (size, size), base + (255,))
    px = img.load()

    # Deterministic speckle: hash the coordinate rather than using RNG so a tile
    # looks identical every time it is generated.
    for y in range(size):
        for x in range(size):
            h = (x * 73856093) ^ (y * 19349663) ^ (variant * 83492791)
            h = (h ^ (h >> 13)) & 0xFF
            roll = h % 100

            if terrain in ("plain", "forest"):
                if roll < 14:
                    px[x, y] = detail + (255,)
                elif roll > 94:
                    px[x, y] = shadow + (255,)
                if terrain == "forest" and roll > 70:
                    px[x, y] = shadow + (255,)
            elif terrain == "road":
                if roll < 8:
                    px[x, y] = detail + (255,)
            elif terrain in ("river", "sea"):
                # Horizontal banding suggests flowing water.
                wave = (y + variant * 2) % 8
                if wave == 0:
                    px[x, y] = detail + (255,)
                elif wave == 1 and roll < 40:
                    px[x, y] = shadow + (255,)
                elif roll < 6:
                    px[x, y] = (255, 255, 255, 90)
            elif terrain == "mountain":
                if roll < 22:
                    px[x, y] = detail + (255,)
                elif roll > 88:
                    px[x, y] = shadow + (255,)
            elif terrain == "bridge":
                if y % 4 == 0:
                    px[x, y] = detail + (255,)
                elif y % 4 == 1:
                    px[x, y] = shadow + (255,)
            elif terrain == "hq":
                if roll < 18:
                    px[x, y] = detail + (255,)
                elif roll > 90:
                    px[x, y] = shadow + (255,)

    return img


def generate_all(out_dir: Path, tile_size: int = 16) -> dict[str, int]:
    """Write every sprite to ``out_dir``. Returns a count per category."""
    terrain_dir = out_dir / "terrain"
    unit_dir = out_dir / "units"
    terrain_dir.mkdir(parents=True, exist_ok=True)
    unit_dir.mkdir(parents=True, exist_ok=True)

    counts = {"terrain": 0, "units": 0}

    for terrain in TERRAIN_PALETTE:
        for variant in range(4):
            sprite = render_terrain_sprite(terrain, variant, tile_size)
            sprite.save(terrain_dir / f"{terrain}_{variant}.png")
            counts["terrain"] += 1

    for unit_key in UNIT_ART:
        for owner in (1, 2):
            sprite = render_unit_sprite(unit_key, owner, tile_size)
            sprite.save(unit_dir / f"{unit_key}_p{owner}.png")
            counts["units"] += 1

    return counts


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "sprites"
    result = generate_all(target)
    print(f"Generated {result['terrain']} terrain and {result['units']} unit sprites in {target}")