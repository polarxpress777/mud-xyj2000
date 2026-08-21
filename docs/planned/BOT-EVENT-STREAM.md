# Bot event stream + world state (mieyao bot spine)

**Status:** designed, accepted, not started.
**Scope:** `tools/xyjbot/botapi.py`, `tools/xyjbot/bots/changan-mieyao-bot.py`.

## The problem

Observation is coupled to intention. `BotAPI.wait_line()` (`botapi.py:88`)
pops lines off a `queue.Queue` and **discards every line that doesn't
match the pattern the caller happens to be waiting for**. `drain()`
(`botapi.py:81`) throws the buffer away wholesale, and `status()`
(`botapi.py:190`) calls it before every poll. So while the bot waits for
A, information B is destroyed.

Every bug fixed in the 2026-08-20 session is that one shape — a line
arrived that mattered and nobody was listening at that instant:

| Bug | Prevented by this change? |
|---|---|
| Monster flees mid-fight → 180s `FIGHT_TIMEOUT` burned | yes |
| Character's own `env/wimpy` walks us out of the fight | yes |
| Target dies during `rest_until_healed()`; reward line eaten by `drain()` | yes |
| Peace room refuses `kill` → 180s burned | yes |
| 红楼一梦 entry waited on a string the mudlib never prints | mostly — see below |
| `flee` is not a command in this mudlib | no — wrong model of the game |
| `/d/moon/bedroom.lpc` compile error | already handled |

Four outright, one mostly. The current fix for the third one — squeezing
a `wait_line(REWARD_RE, 0.2)` in *before* `status()` drains — only works
because we knew in advance which line to rescue. That is a band-aid over
the structural flaw, and it is the thing to remove.

The 红楼一梦 case is the instructive one. It was fixed by waiting for
荡悠悠三更梦 instead of 进入了梦的世界, but the right condition was never
a message at all: it is **"where am I now?"**. If position is state that
every room description updates, the pillow's message is irrelevant.
**State-derived conditions beat message-derived ones**, because they do
not require knowing every string the mudlib might print.

## The biggest win: generic failure detection

Today every failure mode needs its own string — `RETREAT_RE`, `FLEE_RE`,
`WIMPY_RE`, `NOFIGHT_RE`, `DEAD_RE`, `TOLL_RE`. Four of those were added
reactively, each after a screenshot showed the bot idling.

One derived fact would have caught three of them without knowing any
string: **`in_combat`**. `combatd` prints wound lines every round, so "no
combat line in ~6s while I believe I am fighting" means the fight is
over, whatever ended it — fled, wimpy, peace room, all one condition.
That is the argument for a state layer more than for reactivity itself:
it degrades gracefully on the mudlib strings nobody has read yet.

## What to build

1. **Non-destructive stream.** Ring buffer with sequence numbers;
   `wait_for(predicate, since=cursor)`. `drain()` becomes "advance my
   cursor", not "delete". ~40 lines in `BotAPI`; changes no bot logic.
2. **A world-state object**, updated by every line before any handler
   sees it: position, hp, mount, current target, `in_combat`, room
   contents, quest state. The `RIDE` dict
   (`changan-mieyao-bot.py`) is a module global precisely because there
   is nowhere for this to live today.
3. **Combat as a tick loop over a priority ladder**, evaluated against
   state rather than "the next line I happen to see": dead → done; hp
   low → disengage; target gone → chase; can't fight here → follow out;
   intruder → retreat. Robust to orderings nobody anticipated, which is
   exactly what keeps failing.
4. **Planning stays as it is** — sequential and readable — just reading
   the same stream.

Half the dispatcher already exists: `triggers.py` is a tested engine with
cooldowns and timers. It is shaped for user config rather than bot
internals, but the routing idea is built and proven.

## Rejected: the phase split as an architecture

The framing that prompted this was "planning phase vs combat phase, with
predefined logic in planning and dynamic reaction in combat". Half right.
The split is real as **policy** — planning decisions are deterministic,
combat decisions are reactive — but it is wrong as **plumbing**:
observation must be continuous in both. Two of the session's bugs (the
dream entry, the horse left behind in 客店睡房) happened nowhere near
combat. What differs between the phases is decision cadence, not whether
events are observed.

Also rejected: rewriting the bot on an async/callback model. Blocking
Python is what makes the walker readable, and `botapi.py`'s docstring
sells that deliberately ("no async, no callbacks"). The stream removes
the *destructiveness*, not the blocking style.

## Shape of the change

- `botapi.py` — buffer + cursors + `wait_for`; keep `wait_line` as a thin
  compatibility wrapper so nothing has to move at once.
- New `botstate.py` — the world-state object and its line handlers.
- `changan-mieyao-bot.py` — port **combat only**: `fight_target()` plus
  its six result branches, ~250 lines of a ~2200-line file. Leave the
  walker, the errands and the sustenance code alone.

Do not rewrite the spine in one pass. If the tick loop earns its keep in
combat, the walker follows later.

## Done test

1. A test feeds a recorded line sequence in which the reward line arrives
   **during** a rest poll, and the bot reports the job complete. Today
   that line is destroyed by `drain()` and the assertion fails.
2. A test drives the combat tick loop with a fight that ends by a means
   the code has no pattern for (lines simply stop). The ladder reaches
   "target gone → chase" from `in_combat` going false, with no new regex.
3. All existing suites still pass unchanged: `test_chase`, `test_ride`,
   `test_westway`, `test_localise`, `test_maze`, `test_reachability`,
   `test_sustenance`, `test_abandon`, `test_triggers`.

Criterion 2 is the one that matters: it is the difference between fixing
seven bugs and stopping the eighth from being possible.
