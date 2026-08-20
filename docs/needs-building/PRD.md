# PRD — xyj2000 as a continuously hosted local MUD

**Status:** problems only. No implementation is prescribed here; see
[ARCHITECTURE-REVIEW.md](ARCHITECTURE-REVIEW.md) before designing any of it.

## Goal

Run xyj2000 as an always-on local server that survives reboots, keeps
player state safe, and can be played directly (`nc`) or through the bot
proxy — without a human watching it.

## Where we actually are

Verified by running it, not by reading it:

| | Status |
|---|---|
| Docker image builds (arm64, alpine, static FluffOS) | works — 627 MB disk / 182 MB content |
| Container boots and is playable | works — login, `goto`, 袁天罡 present |
| Player saves persist to host | works — correct ownership (`polar staff`), no root-owned files |
| Survives host reboot | works — `restart: unless-stopped` |
| Bots via proxy on :40099 | works — but the proxy is a host process, not in the image |
| Runs unattended | **no** — see P1–P4 |

## Problems

### P0-1 — The image is not self-contained

**Problem.** The image holds only the driver. The mudlib arrives by bind
mount, so `docker run xyj2000-mud` exits immediately:

```
entrypoint: /mud/config.fluffos not mounted -- check docker-compose volumes.
```

Distribution requires the image *and* a correctly-shaped host checkout at
a known relative path.

**Why it matters.** It contradicts the normal expectation that an image
is a runnable artifact. It cannot be pushed to a registry and run
anywhere. The current shape is a *development* setup — optimised for
editing `.lpc` on the host and reloading in-game with `update` — being
used as a *hosting* setup.

**Tension to resolve, not paper over.** The mudlib tree is both the code
*and* the database: `work/data/` holds every character. Baking the whole
tree in would destroy player state on each recreate; mounting the whole
tree is what we do now. The design question is where the line goes
between immutable code and mutable state — and whether the dev workflow
(live `.lpc` edits) is preserved as a separate mode or dropped.

**Outcome.** A published image runs with no host checkout, given a volume
for state. The live-edit workflow remains available and is documented as
a distinct mode.

**Acceptance.** On a machine with no clone of this repo:
`docker run -d -p 40012:40012 -v xyj-state:<state-path> <image>` yields a
playable MUD, and a character created, then `docker rm -f` + re-run,
still exists.

---

### P0-2 — Nothing detects or recovers a wedged server

**Problem.** No healthcheck is configured (verified: `health=NONE CONFIGURED`).
`restart: unless-stopped` only reacts to the process *exiting*. A driver
that is up but not accepting logins stays "running" forever.

**Outcome.** A server that stops serving is detected and restarted
without a human.

**Acceptance.** Deliberately wedge the driver; the container is restarted
automatically and the event is visible in the logs.

---

### P0-3 — No backup of the only copy of player state

**Problem.** `work/data/` (~6.3 MB of flat `.o` files) is the entire
persistence layer. There is no backup, no rotation, no restore procedure.
A bad `rm`, a corrupt write during a crash, or a mistaken
`docker compose down -v` loses every character permanently.

**Outcome.** Point-in-time recovery of player state to at least the
previous day, with a restore path that has actually been executed once.

**Acceptance.** Delete a character's save, run the documented restore,
and log in as that character.

---

### P1-1 — Logs grow without bound

**Problem.** Docker's log driver is `json-file` with **no** options set —
no `max-size`, no `max-file`. One boot writes ~326 KB, largely the
prewarm error dump (P1-3). Separately `work/log/log` is already 8.9 MB
and nothing truncates it.

**Outcome.** Disk use is bounded and predictable over months.

**Acceptance.** Simulate a month of boots; total log growth stays under a
stated ceiling.

---

### P1-2 — The driver version is not pinned

**Problem.** `docker-compose.yml` sets `FLUFFOS_REF: master`, directly
contradicting its own adjacent comment ("Pin to the commit you've
verified locally rather than tracking upstream master"). A rebuild later
silently gets a different driver.

**Outcome.** A rebuild at any future date produces the same driver.

**Acceptance.** The ref is a SHA or tag, and the built driver reports the
expected version.

---

### P1-3 — Boot-time prewarm never completes

**Problem.** `adm/daemons/prewarmd.lpc:70` self-chains
`call_out("prewarm_batch", 0)`. At 4938 files / 5 per batch that is ~988
nested `call_out(0)` levels against the driver's limit of 1000, and it
aborts:

```
执行时段错误：*Nesting call_out(0) level limit exceeded: 1000.
程序：/adm/daemons/prewarmd.lpc 第 70 行
```

`work/log/PREWARM` last recorded `prewarm done` on **Aug 16 18:14**; all
15 boots since have failed, natively *and* under Docker — so this is not
a container regression.

**Why it matters.** ~4900 files are left uncompiled until first use
(first visit to an area pays the cost), and every boot emits a large
error dump that dominates the container log.

**Note.** This is also why `feature/alias.lpc` now caps a whole `;`/`#N`
batch at `MAX_BATCH 100` — the queue uses the same self-nesting
`call_out(0)` pattern and would hit the same wall.

**Outcome.** Prewarm completes on every boot, or is deliberately removed.

**Acceptance.** `work/log/PREWARM` shows `prewarm done` after every boot
across 5 consecutive boots.

---

### P1-4 — The bot proxy has no lifecycle

**Problem.** `tools/xyjbot/botproxy.py` is started by hand and dies with
its terminal. It hard-codes its target (`botproxy.py:42`:
`MUD_HOST, MUD_PORT = "127.0.0.1", 40012`) and its listen port
(`LISTEN_PORT = 40099`). "The server is up" and "bots can connect" are
therefore two separate facts, and only one of them survives a reboot.

**Outcome.** Bot access is up whenever the MUD is up, across reboots.

**Acceptance.** Reboot the host; `nc 127.0.0.1 40099` reaches the MUD
with no manual step.

---

### P2-1 — Most of the map cannot route home

**Problem.** Only **967 of 2505** mapped rooms can compute a route back
to 天监台. Whole quest-spawn areas are cut off: `d/qujing/lingshan`,
`d/qujing/pansi`, `d/sky`, `d/death`, `d/xueshan`, `d/dntg/hgs` and ~20
more return 0/40 on a sampled reachability check.

**Why it matters.** The 灭妖 bot can be handed a quest in one of those
areas. It already degrades honestly (says it cannot get there and waits),
but it cannot work them, so those quests are dead time.

**Cause is unproven.** Likely a mix of genuinely command-gated
transitions the static map cannot express (`dive`, teleports, sect
gates — `SPECIAL_EXITS` already handles four such cases) and real gaps in
`build_map.py`'s exit extraction. **Which of the two dominates is not yet
known and should be measured before anything is built.**

**Outcome.** Either the bot can reach these areas, or it declines those
quests immediately instead of burning the 30-minute timer.

**Acceptance.** For each unreachable spawn area, a recorded decision:
routable (with the transition encoded) or explicitly declined.

## Non-goals

- **A database.** `docs/../docker/README.md` argues this at length and is
  right: the mudlib persists everything as flat `.o` files, and the
  driver's object model assumes it. Not in scope.
- **Public/internet hosting.** Local and LAN only. Anything else changes
  the security model entirely.
- **Rewriting the mudlib.** Fix what blocks hosting; leave the game alone.

## Open questions

1. **Is the live-edit workflow a requirement, or a convenience?** The
   answer decides P0-1's shape. If `.lpc` edits must be live in the
   hosted instance, code and state cannot be cleanly separated.
2. **Who is this hosted for?** Just you, or others on the LAN? Decides
   whether P0-2/P0-3 need alerting or just recovery, and whether the
   listener should stay on `0.0.0.0` (currently it is, so anyone on the
   wifi can reach it — `docker-compose.yml` flags this itself).
3. **Is prewarm worth keeping at all?** Deleting the daemon is a valid
   answer to P1-3 and costs only first-visit latency.
