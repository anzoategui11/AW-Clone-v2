"""Unit definitions. Combat stats exist but are inert until a later milestone."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MovementClass(str, Enum):
    BOOT = "boot"
    TREAD = "tread"
    AIR = "air"


@dataclass(frozen=True)
class UnitType:
    key: str
    name: str
    movement_class: MovementClass
    move_points: int
    # Combat stats are declared now so the roster is stable, even though the
    # resolution layer does not use them yet.
    max_hp: int = 100
    attack: int = 0
    defense: int = 0
    weapon_range_min: int = 0
    weapon_range_max: int = 0
    hit_rate: int = 100
    counter_hit_rate: int = 0
    sprite: str = ""


UNIT_TYPES: dict[str, UnitType] = {
    "infantry": UnitType(
        key="infantry",
        name="Infantry",
        movement_class=MovementClass.BOOT,
        move_points=5,
        max_hp=100,
        attack=50,
        defense=60,
        weapon_range_min=1,
        weapon_range_max=1,
        hit_rate=95,
        counter_hit_rate=25,
        sprite="infantry",
    ),
    "mech": UnitType(
        key="mech",
        name="Mech",
        movement_class=MovementClass.BOOT,
        move_points=5,
        max_hp=150,
        attack=60,
        defense=50,
        weapon_range_min=1,
        weapon_range_max=1,
        hit_rate=85,
        counter_hit_rate=20,
        sprite="mech",
    ),
    "artillery": UnitType(
        key="artillery",
        name="Artillery",
        movement_class=MovementClass.TREAD,
        move_points=5,
        max_hp=80,
        attack=90,
        defense=30,
        weapon_range_min=2,
        weapon_range_max=3,
        hit_rate=85,
        counter_hit_rate=10,
        sprite="artillery",
    ),
    "anti_air": UnitType(
        key="anti_air",
        name="Anti-Air",
        movement_class=MovementClass.TREAD,
        move_points=5,
        max_hp=100,
        attack=75,
        defense=55,
        weapon_range_min=1,
        weapon_range_max=2,
        hit_rate=100,
        counter_hit_rate=15,
        sprite="anti_air",
    ),
    "apc": UnitType(
        key="apc",
        name="APC",
        movement_class=MovementClass.TREAD,
        move_points=5,
        max_hp=120,
        attack=0,
        defense=40,
        weapon_range_min=0,
        weapon_range_max=0,
        hit_rate=0,
        counter_hit_rate=0,
        sprite="apc",
    ),
}


@dataclass
class Unit:
    unit_id: int
    owner: int  # faction id
    unit_type: UnitType
    x: int
    y: int
    hp: int = field(default=None)  # type: ignore[assignment]

    # Per-turn state.
    move_points_left: int = 0
    has_moved: bool = False

    def __post_init__(self) -> None:
        if self.hp is None:
            self.hp = self.unit_type.max_hp

    @property
    def pos(self) -> tuple[int, int]:
        return (self.x, self.y)

    @property
    def movement_class(self) -> str:
        return self.unit_type.movement_class.value

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def reset_for_turn(self) -> None:
        self.move_points_left = self.unit_type.move_points
        self.has_moved = False

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Unit(#{self.unit_id} {self.unit_type.name} p{self.owner} @({self.x},{self.y}) hp={self.hp})"


def spawn(units: list[Unit], owner: int, unit_type: str, x: int, y: int) -> Unit:
    """Create a unit with a fresh id. Returns it; the caller adds it.

    Deliberately does not mutate ``units`` -- it only reads the list to pick the
    next id. Callers append, so ``units.append(spawn(units, ...))`` is the
    expected usage and nothing gets double-inserted.
    """
    next_id = max((u.unit_id for u in units), default=0) + 1
    unit = Unit(
        unit_id=next_id,
        owner=owner,
        unit_type=UNIT_TYPES[unit_type],
        x=x,
        y=y,
    )
    unit.reset_for_turn()
    return unit