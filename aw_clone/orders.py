"""Orders. Only Move exists so far; the union is the extension point."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MoveOrder:
    """A queued path for a unit, expressed as absolute tiles.

    ``path`` excludes the unit's current tile. ``pending_blocked`` is filled in
    by the resolver when a unit cannot complete its path.
    """

    path: list[tuple[int, int]] = field(default_factory=list)
    pending_blocked: bool = False

    @property
    def destination(self) -> tuple[int, int] | None:
        return self.path[-1] if self.path else None


@dataclass
class Order:
    unit_id: int
    move: MoveOrder | None = None

    def has_any(self) -> bool:
        return self.move is not None and bool(self.move.path)