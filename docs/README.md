# docs/ — the work pipeline

Three folders, one per stage. An item moves left to right and never skips
a stage.

| Folder | Means | Entry test |
|---|---|---|
| [`needs-building/`](needs-building/) | A problem worth solving. **Not yet designed.** | Someone can state the user-visible problem and why it matters. |
| [`planned/`](planned/) | Designed and accepted. Ready to implement. | There is an agreed approach, a rough shape of the change, and a way to tell when it is done. |
| [`built/`](built/) | Shipped and verified. | It works, it is tested, and the test is checked in. |

## Rules that keep this honest

- **`needs-building/` holds problems, `planned/` holds solutions.** If an
  item in `needs-building/` already prescribes an implementation, the
  design step got skipped and the reasoning was never checked.
- **Nothing enters `built/` on the strength of "the code is written".**
  It enters when a test proves it, and the test lives in the repo.
- **Record what was measured, not what was intended.** Every entry in
  `built/` carries its verification numbers. A claim with no number is a
  guess with better grammar.
- **Items may move backwards.** A "built" thing that turns out broken
  goes back to `needs-building/` with what was learned.

## Why the stages are separate

The split exists because the expensive mistakes on this project have all
been the same mistake: acting on a plausible story instead of a verified
one. Three real examples, all from a single session:

- The bot's rest loop was "obviously" waiting for slow healing. It was
  waiting for healing the mudlib had switched **off** (`feature/damage.lpc:465`).
- The `#N` command gap was 1 second because a comment said the busy flag
  landed on the next heartbeat. It does not — `start_busy()` is a plain
  synchronous assignment (`feature/action.lpc:6`).
- `docker/README.md` said the native driver "happens to work" with a
  stale config path. It does not; it refuses to boot.

Each was cheap to check and expensive to assume. `needs-building/` is
where the checking happens.
