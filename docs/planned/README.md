# planned

Designed, accepted, ready to implement. Nothing here yet.

An item arrives from [`../needs-building/`](../needs-building/) once it
has:

1. **A chosen approach**, with the alternatives that were rejected and
   why. The rejected options matter more than the chosen one — they are
   what stops the same debate reopening in three months.
2. **A rough shape of the change** — which files, which seams it
   crosses. See the seam map in
   [`../needs-building/ARCHITECTURE-REVIEW.md`](../needs-building/ARCHITECTURE-REVIEW.md);
   an item that crosses seams 1 and 4 is not a small item, whatever it
   looks like.
3. **A done test** stated before implementation starts, ideally the same
   sentence as the PRD's acceptance criterion.

## Sequencing note

The PRD items are not independent, and picking them off in priority order
is the wrong move:

- **P0-1** (self-contained image) decides where the code/state line
  falls, and **P0-3** (backups) needs that line to know what to back up.
  Design P0-1 first, even though P0-3 is the higher risk.
- **P1-4** (bot proxy lifecycle) inherits whatever P0-1 concludes about
  packaging. Doing it first means doing it twice.
- **P1-3** (prewarm) and **P1-1** (log growth) are entangled: the prewarm
  error dump is most of what fills the log.
- **P2-1** (map coverage) is the only item that touches nothing else. It
  is the safe one to hand to someone in parallel.
