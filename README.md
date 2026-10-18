# Advance Wars Clone

An Advance Wars 2 clone with **simultaneous turns**. Both factions plan in
secret, then every order resolves at once.

## Current scope

Deliberately narrow so the resolution rules can be settled before combat exists.

- Grid, terrain, and move-point pathfinding
- Move orders only, planned hidden then resolved together
- Simultaneous movement with deterministic conflict handling
- Keyboard cursor for ordering, mouse still supported
- Basic AI opponent, pixel-art terrain and unit sprites
- No combat, no win condition, no pass-device flow yet

## Running

```powershell
.\.venv\Scripts\python.exe main.py
```

Regenerate sprites after editing `aw_clone/assets/generate.py`:

```powershell
.\.venv\Scripts\python.exe -m aw_clone.assets.generate
```

There is no test suite at the moment. The rules below were checked by running
the scenario directly, so they are documented here rather than pinned by
assertions.

Headless render for checking the UI without a window:

```powershell
.\.venv\Scripts\python.exe main.py --headless --select --center --out plan.png
.\.venv\Scripts\python.exe main.py --headless --resolve --center --frames 4 --out mid.png
```

## AI planning is currently disabled

`AI_PLANNING_ENABLED = False` in `main.py`. Red does not plan orders or move, so
turns contain only your own units. This is temporary while the movement rules
are being tuned, since the AI kept arriving at the same chokepoints each turn
and made it hard to isolate how a single order resolves.

The AI code is untouched and still fully covered by tests; only the call site is
switched off. Set the flag to `True` to restore simultaneous play — nothing else
needs changing.

## Controls

| Input | Action |
| --- | --- |
| `W` `A` `S` `D` | Move the cursor one tile (hold to repeat) |
| `Space` | Act at the cursor: select the unit there, deselect it, send the selected unit there, or cancel that unit's order if it is already selected |
| Arrow keys | Pan the camera |
| Drag a unit to a tile | Queue a move |
| Click a unit, then click a tile | Queue a move (same thing, two clicks) |
| Click a selected unit again | Deselect it, or cancel its order if it has one |
| Click a unit that has an order | Select it, leaving the order in place |
| Click an enemy | Nothing; orders cannot target enemies yet |
| Right click | Cancel the order on the unit under the mouse |
| Tab | Next unit without an order |
| Enter | End turn and resolve |
| R | Clear all orders |

## Ordering rules

`planning_blocked_tiles()` in `aw_clone/turn.py` is the single definition of a
legal order. `TurnPlan` and the AI both call it, so the player and the opponent
can never disagree about what is allowed.

### You draw the route

Moving the cursor with `WASD` draws the route tile by tile. Nothing is drawn the
moment a unit is picked up; the line starts once the cursor leaves the unit and
grows with every step, so the order ends up being the path you walked rather than
one the planner chose for you. Pressing `Space` then assigns that drawing.

Every step is checked against the movement rules as it is taken, so a drawing is
never trusted:

| Cursor is… | What is drawn |
| --- | --- |
| Inside the unit's range, drawing legal | The drawing |
| Inside the range, drawing over the move points | A computed route instead |
| Outside the range | Nothing, until the cursor returns |

Cost only rises along a route, so once a drawing has overrun the move points it
can never recover by carrying on — that is why circling back over your own route
hands over to the computed path rather than snapping back to the drawing.

`TurnPlan.path_is_legal()` is the check: every step orthogonal, nothing entered
that cannot be entered, nothing entered that is blocked except a friendly's tile,
the whole route inside the move points, and finishing on a square the unit may
rest on. A drawing that fails any of it is replaced by `find_path()`, so a bad
drawing can never turn into an order the resolver would refuse.

### What a legal destination is

A unit may be ordered to end on a tile unless:

- **A friendly unit is standing on it and has no orders.** It will still be
  there, so the square is not available.
- **A friendly unit has been ordered to take that exact square.** Two units are
  never sent to the same destination. The lower `unit_id` would win the contest
  at resolution time, so the order is refused at planning time instead.
- **An enemy unit is standing on it.** Always blocked.

A friendly unit's tile is **transparent**: the unit may walk *through* it but
may not come to rest on it. Treating those tiles as hard blockers made a single
friendly unit in front cut off everything behind it. `friendly_blockers()` marks
them and `search()` reads them as `passable_only` — routed through at the tile's
normal cost, excluded from the returned range, and rejected as a destination.

Crossing a friendly is not free. It is charged the terrain cost like any other
tile; the unit standing there makes it impassable, not cheap.

Enemy tiles stay hard blockers, so an enemy does wall off a corridor.

A friendly unit's tile becomes a legal destination once that unit has been
ordered away, which is what lets one unit trail another:

```python
plan.set_move(leader, (3, 2))   # leader steps off (0,2)
plan.set_move(follower, leader.pos)   # legal: (0,2) is expected to be free
plan.set_move(follower, (3, 2))       # refused: that is the leader's destination
```

Only a friendly unit's **endpoint** is reserved. The tiles it walks over are
left fair, so a follower can trail along the same corridor. A unit may always
stay put, and may always re-confirm the destination it was already given.

Enemy orders are invisible during a planning phase, so nothing is inferred from
them. That is the simultaneous-turn asymmetry: you may plan into a square an
enemy has secretly claimed, and lose the contest when orders resolve.

Planning is optimistic about vacated tiles. If the friendly unit you are
following gets blocked during resolution, the follower is blocked too and
re-routes. The resolver is the authority on where units actually end up.

## How resolution works

`resolve_movement()` in `aw_clone/turn.py` replays every queued path at once and
returns a list of `MoveStep` frames. The engine never sleeps; the UI plays the
frames back on a timer. That split is what keeps the rules testable without a
display.

Each tick:

1. Every unit that can afford its next tile proposes that tile.
2. Contention for the same tile is settled by ascending `unit_id`.
3. A winner whose destination is held by a unit that did **not** move aside is
   invalidated, and that invalidation repeats until it stabilises.
4. Swap attempts are rejected: units cannot trade places in one tick.
5. Units that stalled re-path around the blocker, or halt and set
   `pending_blocked`.

Step 3 is the subtle one. Occupancy has to be judged against units that
*actually moved*, not units that merely proposed a move. A unit that proposes to
move away and then gets blocked is still standing on its tile, and treating it
as vacated was what let two units end up stacked on the same square.

Determinism comes from iterating units in ascending `unit_id` order rather than
relying on dict or set ordering, so the same orders always produce the same
turn. `tests/test_resolution.py` pins this down with a seeded contention test.

## Movement costs

Movement is orthogonal only, as in Advance Wars 2. A unit steps up, down, left
or right; there are no diagonal moves, so every route across the board is a sum
of orthogonal steps. Entering a tile costs the step plus the terrain penalty:

```
cost = STEP_COST (1) + terrain penalty
```

Manhattan distance is therefore the exact cost on featureless ground, which is
why the move-range overlay is a diamond rather than a square. Pathfinding itself
is a plain Dijkstra, shared with the overlay so the two can never disagree about
what a unit can afford.

Road, bridge and HQ have no penalty, so stepping onto one costs exactly 1.

| Terrain penalty | Boot | Tread | Air |
| --- | --- | --- | --- |
| Road / Bridge / HQ | 0 | 0 | 0 |
| Plain | 0 | 1 | 0 |
| Forest | 1 | 3 | 0 |
| River | 2 | 3 | 0 |
| Mountain | 3 | impassable | 0 |
| Sea | impassable | impassable | 0 |

Plain is free for infantry, so they cross five tiles on 5 points while a tracked
unit on the same ground gets two. Every unit type has 5 move points; the
per-class terrain table is what separates them.

`IMPASSABLE_PENALTY = 99` marks a penalty as a wall. Infantry cut through forests
and can climb mountains; tracked vehicles cannot. Aircraft ignore terrain but
still cost a point per orthogonal step.

## Layout

```
main.py                  entry point and the planning/resolution loop
aw_clone/
  config.py              tunables: costs, palette, display, tick timing
  grid.py                Tile, GameMap, terrain costs, search, find_path
  units.py               UnitType, Unit, roster, spawn helper
  orders.py              Order / MoveOrder
  turn.py                TurnPlan and resolve_movement
  ai.py                  heuristic opponent
  scenario.py            map construction and starting forces
  assets/generate.py     procedural sprite generation
  assets/loader.py       sprite cache
  ui/renderer.py         map, overlays, units, side panel
```

`grid.py`, `units.py`, `orders.py`, `turn.py`, `ai.py`, and `scenario.py` have no
pygame import, so the rules can be exercised headless.

## Decisions still open

- Whether a unit that dies during simultaneous combat still deals its damage
  (currently the snapshot model says yes)
- Whether hidden orders need an explicit pass-device curtain
- Whether capture and economy come before or after combat

## Notes

`spawn()` returns a unit and does not mutate the list, so the calling
convention is `units.append(spawn(units, ...))`. It only reads the list to pick
the next id.