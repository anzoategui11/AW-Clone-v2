"""Turn planning and simultaneous movement resolution.

The resolution model in one paragraph: every unit with a queued path is
advanced one tile per *tick*, and all ticks are computed against the same
board state, so nobody observes a stale world. Occupancy is re-evaluated every
tick, which is what lets a unit follow another unit through a gap that only
opens mid-move. Determinism comes from a fixed unit iteration order (ascending
``unit_id``) rather than dict or set ordering.

Resolution emits a list of :class:`MoveStep` frames. The engine never sleeps;
the UI plays the frames back on a timer. That keeps the rules testable without
a display and makes the tie-break behaviour observable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grid import GameMap, find_path, is_adjacent, reachable
from .orders import MoveOrder, Order
from .units import Unit


@dataclass
class MoveStep:
    """One tick of resolved movement. ``moved`` is unit_id -> destination."""

    tick: int
    moved: dict[int, tuple[int, int]] = field(default_factory=dict)
    blocked: dict[int, tuple[int, int]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.moved)


@dataclass
class MoveResolution:
    steps: list[MoveStep] = field(default_factory=list)
    final_positions: dict[int, tuple[int, int]] = field(default_factory=dict)
    arrived: dict[int, tuple[int, int]] = field(default_factory=dict)


def vacated_positions(units: list[Unit], orders: dict[int, Order]) -> set[tuple[int, int]]:
    """Current positions of units that have been ordered to move away.

    These tiles are expected to be empty once orders resolve, so they are legal
    destinations even though a unit is standing on them during planning.
    """
    vacated: set[tuple[int, int]] = set()
    for unit in units:
        if not unit.alive:
            continue
        order = orders.get(unit.unit_id)
        if order is not None and order.has_any():
            vacated.add(unit.pos)
    return vacated


def claimed_destinations(orders: dict[int, Order]) -> set[tuple[int, int]]:
    """Squares that units have been told to end their move on."""
    claimed: set[tuple[int, int]] = set()
    for order in orders.values():
        if order.has_any() and order.move is not None:
            destination = order.move.destination
            if destination is not None:
                claimed.add(destination)
    return claimed


def friendly_blockers(
    units: list[Unit],
    orders: dict[int, Order],
    unit: Unit,
) -> set[tuple[int, int]]:
    """Friendly tiles that may be crossed but never stopped on.

    A friendly unit standing in the way cannot be displaced, but it also must not
    act as a wall. Treating these as hard blockers made a unit in front cut off
    everything behind it, which made a friendly formation silently block a
    whole column.

    Crossing one is not a shortcut, though: the tile costs what it costs like
    any other. A friendly is transparent, not free. This is what the search
    reads as ``passable_only``.

    Only tiles held by friendly units that have *no* order appear here. A
    friendly unit that has been ordered away is expected to be empty by
    resolution time, so its tile is a normal legal destination.
    """
    blockers: set[tuple[int, int]] = set()
    for other in units:
        if not other.alive or other.unit_id == unit.unit_id:
            continue
        if other.owner != unit.owner:
            continue
        order = orders.get(other.unit_id)
        if order is not None and order.has_any():
            continue  # ordered away, so expected to be free
        blockers.add(other.pos)
    return blockers


def planning_blocked_tiles(
    units: list[Unit],
    orders: dict[int, Order],
    unit: Unit,
) -> set[tuple[int, int]]:
    """Tiles ``unit`` may not be ordered to end its move on.

    This is the single source of truth for ordering legality. Both the player's
    :class:`TurnPlan` and the AI go through it, so the two can never disagree
    about what a legal order is.

    The rules, in priority order:

    * A friendly unit's tile is blocked only while that unit has *no* orders.
      Once it has been ordered away the tile is expected to be free, so it
      becomes a legal destination and a unit may follow it out.
    * A square another friendly unit has been ordered to take is blocked, so two
      units are never sent to the same destination.
    * Every other occupied tile is blocked, including all enemy tiles. Enemy
      orders are not known during a planning phase, so nothing is inferred from
      them.

    Only a friendly unit's *endpoint* is reserved. The tiles it walks over are
    left fair, so a follower can trail along the same corridor.

    Note this is about *destinations*. Pathing treats a friendly blocker as
    transparent via :func:`friendly_blockers`, so a unit can route past one.
    """
    occupied = {
        u.pos: u for u in units if u.alive and u.unit_id != unit.unit_id
    }
    vacated = vacated_positions(units, orders)
    claimed = claimed_destinations(orders)

    blocked: set[tuple[int, int]] = set()
    for tile, other in occupied.items():
        if other.owner == unit.owner and tile in vacated:
            # Ordered away, so the tile is expected to be empty on resolution.
            continue
        blocked.add(tile)

    blocked |= claimed
    # A unit must always be able to stay put, even if a friendly unit was
    # ordered onto the square it currently occupies.
    blocked.discard(unit.pos)
    # A unit must also be able to keep, or return to, the square it has already
    # been told to take. Without this, re-ordering a unit to its existing
    # destination would be rejected by its own claim.
    own_order = orders.get(unit.unit_id)
    if own_order is not None and own_order.has_any() and own_order.move is not None:
        own_destination = own_order.move.destination
        if own_destination is not None:
            blocked.discard(own_destination)
    return blocked


class TurnPlan:
    """Collects one faction's orders before resolution."""

    def __init__(self, game_map: GameMap, units: list[Unit], active_owner: int):
        self.game_map = game_map
        self.units = units
        self.active_owner = active_owner
        self.orders: dict[int, Order] = {}

    # ------------------------------------------------------------ queries ----
    @property
    def controllable(self) -> list[Unit]:
        return [u for u in self.units if u.owner == self.active_owner and u.alive]

    def order_for(self, unit_id: int) -> Order | None:
        return self.orders.get(unit_id)

    def occupancy(self, ignore: set[int] | None = None) -> dict[tuple[int, int], Unit]:
        """Map of tile -> occupying unit, optionally skipping some unit ids."""
        ignore = ignore or set()
        return {u.pos: u for u in self.units if u.alive and u.unit_id not in ignore}

    def vacated_tiles(self) -> set[tuple[int, int]]:
        """Current positions of friendly units that have been ordered to move."""
        return vacated_positions(self.units, self.orders)

    def claimed_tiles(self) -> set[tuple[int, int]]:
        """Destinations that friendly units have been ordered to occupy."""
        return claimed_destinations(self.orders)

    def blocked_tiles_for(self, unit: Unit) -> set[tuple[int, int]]:
        """Tiles this unit may not be ordered to end its move on.

        Delegates to :func:`planning_blocked_tiles` so the player and the AI
        share one definition of a legal order. Friendly tiles are in here too;
        :meth:`passable_only_for` marks which of those may be crossed anyway.
        """
        return planning_blocked_tiles(self.units, self.orders, unit)

    def passable_only_for(self, unit: Unit) -> set[tuple[int, int]]:
        """Friendly tiles that can be crossed but not stopped on.

        Kept alongside :meth:`blocked_tiles_for` rather than folded into it:
        these tiles appear in both, and the search gives them priority. So they
        are never offered as a destination while still not walling anything off.
        """
        return friendly_blockers(self.units, self.orders, unit)

    def move_range(self, unit: Unit) -> dict[tuple[int, int], int]:
        """Tiles the unit can reach this turn, mapped to points remaining.

        Friendly blockers are passed as ``passable_only`` so the search routes
        through them at the tile's normal cost, while they stay out of the
        returned range because a unit may not come to rest on a friendly unit.
        """
        return reachable(
            self.game_map,
            unit.pos,
            unit.unit_type.move_points,
            unit.movement_class,
            blocked=self.blocked_tiles_for(unit),
            passable_only=self.passable_only_for(unit),
        )

    def preview_path(self, unit: Unit, target: tuple[int, int]) -> list[tuple[int, int]]:
        """Path for the hover preview. Empty if the target is unreachable."""
        path = find_path(
            self.game_map,
            unit.pos,
            target,
            unit.movement_class,
            blocked=self.blocked_tiles_for(unit),
            budget=unit.unit_type.move_points,
            passable_only=self.passable_only_for(unit),
        )
        return path or []

    # ------------------------------------------------------------- orders ----
    def set_move(self, unit: Unit, target: tuple[int, int]) -> bool:
        """Queue a Move order. Returns False if the target is out of reach."""
        if unit.owner != self.active_owner or not unit.alive:
            return False
        if target == unit.pos:
            self.orders[unit.unit_id] = Order(unit_id=unit.unit_id)
            return True

        # preview_path already refuses a target sitting on a friendly unit, so
        # the queued order can never disagree with the path the player was shown.
        path = self.preview_path(unit, target)
        if not path:
            return False

        self.orders[unit.unit_id] = Order(unit_id=unit.unit_id, move=MoveOrder(path=path))
        return True

    def clear(self, unit_id: int) -> None:
        self.orders.pop(unit_id, None)

    def clear_all(self) -> None:
        self.orders.clear()

    def ordered_units(self) -> list[Unit]:
        return sorted(self.controllable, key=lambda u: u.unit_id)


def resolve_movement(
    game_map: GameMap,
    units: list[Unit],
    orders: dict[int, Order],
    max_ticks: int = 512,
) -> MoveResolution:
    """Execute every queued path simultaneously and return the frame list.

    Each tick: propose a next tile for every unit that can still move, settle
    conflicts by ``unit_id``, then commit. A unit blocked by a stationary unit
    re-paths around it when a detour exists, otherwise it halts and flags
    ``pending_blocked`` on its order.
    """
    resolution = MoveResolution()

    active = {
        unit_id: order
        for unit_id, order in orders.items()
        if order.move is not None and order.move.path
    }
    actors: dict[int, Unit] = {}
    paths: dict[int, list[tuple[int, int]]] = {}
    for unit in units:
        order = active.get(unit.unit_id)
        if order is None or not unit.alive:
            continue
        # Copy the path: resolution must not mutate the queued order.
        paths[unit.unit_id] = list(order.move.path)
        actors[unit.unit_id] = unit

    if not actors:
        resolution.final_positions = {u.unit_id: u.pos for u in units}
        return resolution

    spent: dict[int, int] = {uid: 0 for uid in actors}
    tick = 0

    while actors and tick < max_ticks:
        proposals: dict[int, tuple[int, int]] = {}
        stalled: dict[int, tuple[int, int]] = {}
        # Units that simply ran out of move points. Kept separate from
        # `stalled` because exhausting your budget is not a blockage: the unit
        # did what it could and should not be flagged as blocked.
        exhausted: set[int] = set()

        for unit_id in sorted(actors):
            unit = actors[unit_id]
            path = paths[unit_id]
            if not path:
                continue

            if not is_adjacent(unit.pos, path[0]):
                # A malformed path should never reach the resolver, but if one
                # does, halt rather than charge it as a single cheap step.
                paths[unit_id] = []
                exhausted.add(unit_id)
                active[unit_id].move.pending_blocked = True
                continue

            remaining = unit.unit_type.move_points - spent[unit_id]
            if remaining <= 0:
                exhausted.add(unit_id)
                continue

            step_cost = game_map.enter_cost(unit.movement_class, path[0])
            if step_cost > remaining:
                # Cannot afford the next tile on this path. Try a cheaper way
                # around; if none exists, we are out of points, not blocked.
                exhausted.add(unit_id)
                continue

            proposals[unit_id] = path[0]

        if not proposals:
            # Nothing more happens this tick: every actor is out of points or
            # out of path. Settle and stop.
            for unit_id in exhausted:
                if paths[unit_id]:
                    detour = find_path(
                        game_map,
                        actors[unit_id].pos,
                        paths[unit_id][-1],
                        actors[unit_id].movement_class,
                        blocked={
                            u.pos
                            for u in actors.values()
                            if u.unit_id != unit_id
                        },
                        budget=max(
                            0, actors[unit_id].unit_type.move_points - spent[unit_id]
                        ),
                    )
                    paths[unit_id] = detour or []
            break

        # --- conflict resolution -------------------------------------------
        # Two stages, because "is this tile freeing up?" is circular: whether a
        # unit moves aside can depend on whether it wins its own tile.
        #
        # Stage 1 settles pure contention -- two units wanting the same tile --
        # in ascending unit_id order. Stage 2 then invalidates any winner whose
        # destination is held by a unit that is not itself moving away this
        # tick. Invalidation frees that tile, which can revive another claim,
        # so stage 2 repeats until it reaches a fixed point.
        occupied_by_active = {u.pos: u.unit_id for u in actors.values()}

        winners: dict[int, tuple[int, int]] = {}
        taken: dict[tuple[int, int], int] = {}
        for unit_id in sorted(proposals):  # ascending id breaks ties
            dest = proposals[unit_id]
            if dest in taken:
                stalled[unit_id] = dest  # lost the race; retry or sidestep
                continue
            taken[dest] = unit_id
            winners[unit_id] = dest

        # Units are solid: two units may not trade places in one tick. For each
        # swap pair (A wants B's tile while B wants A's tile), keep the lower
        # unit_id's claim and drop the other's, so it re-routes on a later tick.
        swapped_out: list[int] = []
        for unit_id in sorted(winners):
            dest = winners[unit_id]
            occupant_id = occupied_by_active.get(dest)
            if occupant_id is None:
                continue
            # A swap means the occupant's destination is this unit's own
            # current tile.
            if winners.get(occupant_id) == actors[unit_id].pos:
                swapped_out.append(unit_id if unit_id < occupant_id else occupant_id)
        for unit_id in dict.fromkeys(swapped_out):
            dest = winners.pop(unit_id, None)
            if dest is not None:
                taken.pop(dest, None)
                stalled[unit_id] = dest

        changed = True
        while changed:
            changed = False
            for unit_id in sorted(winners):
                dest = winners[unit_id]
                occupant_id = occupied_by_active.get(dest)
                if occupant_id is None or occupant_id == unit_id:
                    continue
                # The occupant only vacates if it actually won a move to some
                # other tile. A unit that only *proposed* a move and then got
                # blocked is still sitting on this tile.
                if winners.get(occupant_id, dest) != dest:
                    continue
                del winners[unit_id]
                taken.pop(dest, None)
                stalled[unit_id] = dest
                changed = True
                break

        step = MoveStep(tick=tick, moved=dict(winners), blocked=dict(stalled))

        # --- commit ---------------------------------------------------------
        for unit_id, dest in winners.items():
            unit = actors[unit_id]
            spent[unit_id] += game_map.enter_cost(unit.movement_class, dest)
            unit.x, unit.y = dest
            paths[unit_id].pop(0)

        resolution.steps.append(step)

        # --- re-path the stalled --------------------------------------------
        # Recomputed after committing, so the board reflects this tick.
        # Includes every living unit, not just movers: an idle unit still
        # blocks the tile it stands on.
        live_occupancy = {
            u.pos: u.unit_id
            for u in actors.values()
            if u.unit_id not in winners
        }
        for unit_id, blocked_tile in stalled.items():
            unit = actors[unit_id]
            remaining = unit.unit_type.move_points - spent[unit_id]
            desired = paths[unit_id][-1] if paths[unit_id] else unit.pos
            # Everything occupied except our own tile is a hard blocker. Tiles
            # this unit's own movers just vacated are genuinely free.
            hard_blocked = {
                tile for tile, other_id in live_occupancy.items() if other_id != unit_id
            }
            detour = find_path(
                game_map,
                unit.pos,
                desired,
                unit.movement_class,
                blocked=hard_blocked,
                budget=remaining,
            )
            if detour:
                paths[unit_id] = detour
                order = active[unit_id]
                if order.move is not None:
                    order.move.pending_blocked = False
            else:
                # No way around it: finish here and remember we stalled.
                paths[unit_id] = []
                order = active[unit_id]
                if order.move is not None:
                    order.move.pending_blocked = True

        tick += 1

    # Final resting place of every unit that had an order, whether it completed
    # the path or ran out of budget partway.
    for unit_id, unit in actors.items():
        resolution.arrived[unit_id] = unit.pos

    resolution.final_positions = {u.unit_id: u.pos for u in units if u.alive}
    return resolution