# Advance Wars Clone

An Advance Wars 2 clone with **simultaneous turns**. Both factions plan in
secret, then every order resolves at once.

## Current scope

Deliberately narrow so the resolution rules can be settled before combat exists.

- Grid, terrain, and move-point pathfinding
- Move orders only, planned hidden then resolved together
- Simultaneous movement with deterministic conflict handling
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

Run the tests (no display needed):

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Headless render for checking the UI without a window:

```powershell
.\.venv\Scripts\python.exe main.py --headless --select --center --out plan.png
.\.venv\Scripts\python.exe main.py --headless --resolve --center --frames 4 --out mid.png
```

## Controls

| Input | Action |
| --- | --- |
| Drag a unit to a tile | Queue a move |
| Click a unit, then click a tile | Queue a move (same thing, two clicks) |
| Click a selected unit again | Deselect it |
| Click an enemy | Nothing; orders cannot target enemies yet |
| Right click | Cancel the order on the unit under the cursor |
| Tab | Next unit without an order |
| Enter | End turn and resolve |
| R | Clear all orders |
| Arrows / WASD | Pan the camera |

## Ordering rules

`planning_blocked_tiles()` in `aw_clone/turn.py` is the single definition of a
legal order. `TurnPlan` and the AI both call it, so the player and the opponent
can never disagree about what is allowed.

A unit may be ordered to end on a tile unless:

- **A friendly unit is standing on it and has no orders.** It will still be
  there, so the square is not available.
- **A friendly unit has been ordered to take that exact square.** Two units are
  never sent to the same destination. The lower `unit_id` would win the contest
  at resolution time, so the order is refused at planning time instead.
- **An enemy unit is standing on it.** Always blocked.

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

Manhattan distance is therefore the exact cost on featureless ground, and it is
the A* heuristic. The move-range overlay is a diamond rather than a square for
the same reason.

Road, bridge and HQ have no penalty, so stepping onto one costs exactly 1.

| Terrain penalty | Boot | Tread | Air |
| --- | --- | --- | --- |
| Road / Bridge / HQ | 0 | 0 | 0 |
| Plain | 0 | 1 | 0 |
| Forest | 1 | 3 | 0 |
| River | 2 | 3 | 0 |
| Mountain | 3 | impassable | 0 |
| Sea | impassable | impassable | 0 |

Plain is free for infantry, so they cross six tiles on 6 points while a tracked
unit on the same ground gets four. The per-class table is the main lever for
separating the two.

`IMPASSABLE_PENALTY = 99` marks a penalty as a wall. Infantry cut through forests
and can climb mountains; tracked vehicles cannot. Aircraft ignore terrain but
still cost a point per orthogonal step.

## Layout

```
main.py                  entry point and the planning/resolution loop
aw_clone/
  config.py              tunables: costs, palette, display, tick timing
  grid.py                Tile, GameMap, terrain costs, Dijkstra, A*
  units.py               UnitType, Unit, roster, spawn helper
  orders.py              Order / MoveOrder
  turn.py                TurnPlan and resolve_movement
  ai.py                  heuristic opponent
  scenario.py            map construction and starting forces
  assets/generate.py     procedural sprite generation
  assets/loader.py       sprite cache
  ui/renderer.py         map, overlays, units, side panel
tests/
  test_logic.py          terrain, costs, pathfinding, turn plans
  test_resolution.py     contention, swaps, bottlenecks, invariants
  test_simulation.py     scenario fairness, AI behaviour, multi-turn runs
```

`grid.py`, `units.py`, `orders.py`, `turn.py`, `ai.py`, and `scenario.py` have
no pygame import, which is why the tests run headless.

## Decisions still open

- Whether a unit that dies during simultaneous combat still deals its damage
  (currently the snapshot model says yes)
- Whether hidden orders need an explicit pass-device curtain
- Whether capture and economy come before or after combat

## Notes

`spawn()` returns a unit and does not mutate the list, so the calling
convention is `units.append(spawn(units, ...))`. It only reads the list to pick
the next id.