# Browser + Mudlet dual access

**Status:** designed, accepted, not started.
**Scope:** a new bridge service, `docker/docker-compose.yml`. No mudlib
changes, no bot changes, no changes to `botproxy.py`.

## The decision

Run this as an open-source public server with **two front doors onto one
game**:

| Door | Audience | Gets | Install |
|---|---|---|---|
| Browser | casual / mobile | play only, no automation | none |
| Telnet | power players | play **and** bots, via Mudlet's own editor | Mudlet |

Automation is deliberately a desktop-only, power-user feature. The browser
client is a terminal and nothing more.

## Why this is nearly free

Mudlet speaks telnet, so the Mudlet door costs **zero code** — it is the
port that already exists. Only the browser door needs building, and three
things already in the tree do most of it:

- The mud emits **UTF-8** (the tools decode it directly and it works), so
  there is no GBK transcoding step and `xterm.js` renders it natively.
- `ansi.py:21` `strip_iac()` already drops telnet negotiation from a raw
  byte chunk — the one non-obvious piece a browser bridge needs.
- `botproxy.py` is already this service's shape: it accepts a client
  socket, opens `127.0.0.1:40012` (`botproxy.py:48`) and relays both ways.
  The bridge is that, with a WebSocket front end and the bot manager
  deleted.

## Shape of the change

| Piece | What it does | Size |
|---|---|---|
| WS↔telnet bridge | accept WebSocket, open TCP to the mud, relay both ways, `strip_iac` outbound, **keep** ANSI so colours survive | ~100 lines |
| Static page | `xterm.js` + a connect box | ~50 lines |
| Reverse proxy | auto-TLS, serves the page, proxies the WebSocket (Caddy or Traefik) | config only |
| compose entry | one more service | small |

Seams crossed: packaging/deploy only. It touches no mudlib file, no bot,
and no existing tool. That is what makes it a small item despite adding a
network-facing service.

**`docker-compose.yml:29` currently publishes `127.0.0.1:40012:40012`** —
the mud is bound to localhost. Going public means changing that line, and
that is the moment the security posture changes, not when the bridge is
written.

## Rejected alternatives

- **In-browser bot editor.** Rejected as disproportionate: it needs a
  script sandbox, a `SharedWorker` to own the connection so an editor
  window can pop out without dropping the session, script persistence, and
  an editor UI — all to rebuild something Mudlet already does well. It is
  the right call *only* if automation must reach mobile users, or if this
  ever became a paid product (see below).
- **Server-side hosted bots** (a multi-tenant `botproxy`). Rejected:
  running strangers' code needs real isolation (Wasm, V8 isolates,
  per-user containers), CPU/memory limits and command rate limiting, and
  it makes bots run while players are offline — a game-economy decision,
  not just a technical one.
- **Selling on Steam.** Rejected. Steam needs a native executable, which
  means wrapping the web client — and once you ship a client, telling a
  paying customer to install *Mudlet* for the headline feature is a
  review-killer, so the in-browser editor comes back. Independently
  blocked by provenance: **11,076 files under `libs/` carry
  `// cracked by vikee 2/09/2002`**. The repo `LICENSE` (MIT) covers
  FluffOS, the driver — not the mudlib. 西游记 itself is public domain;
  this code is not.
- **`websockify` instead of a custom bridge.** Rejected: it relays raw
  bytes, so telnet IAC negotiation reaches the browser as garbage.
  `strip_iac()` already exists here.
- **Mudlet only.** Rejected: install friction loses casual and mobile
  players entirely.
- **Browser only.** Rejected: it forces the in-browser editor back in.

## Done test

Stated before implementation starts:

1. A player with **nothing installed** opens the URL, logs in, walks a few
   rooms, and Chinese text and ANSI colours both render correctly.
2. A player with **Mudlet** connects to the same server on the telnet
   port, plays the same world, and can write a trigger that fires.
3. Killing the bridge does not affect telnet players, and restarting it
   does not require touching the mud container.

Note on (1) and (2): they cannot be the **same account at the same time**.
This mudlib replaces an existing session on re-login —
`有人从别处( ... )连线取代你所控制的人物` — so the test needs two accounts.
See `verify-live-before-shipping` in the agent memory; this rule has
already invalidated one test run.

## Verify while building, not after

- **CJK width in `xterm.js`** against real room descriptions. Alignment
  assumptions live in `ansi.py:26` `char_width()` / `display_width()`.
- **Chinese IME input** in a browser terminal — fine until it isn't.
- **TLS is not optional**: a page on `https://` can only open `wss://`.
  Caddy does Let's Encrypt automatically, but it is the step people skip.
- **A public telnet port attracts scanners.** Rate limiting, and the
  mud's own login is the only other gate.

## Bot portability principle

Bots should stay **Mudlet-shaped** so one can be re-created there cheaply:
same pattern types (substring, regex, begin-of-line, exact), multi-line
triggers with line deltas, timers, aliases. If bot scripting is ever
rewritten, **Lua is the choice that makes bots portable rather than merely
similar** — Mudlet is Lua, and today's Python bots do not port at all.

This is the same conclusion [`BOT-EVENT-STREAM.md`](BOT-EVENT-STREAM.md)
reaches from the other direction: observation must be continuous and
non-destructive, which is exactly what a trigger model is.

## Optional later, not part of this item

- **GMCP** in the mudlib. The highest-value follow-up: structured
  out-of-band JSON for room, vitals and combat means triggers match on
  data instead of Chinese prose, and Mudlet has first-class support. The
  mudlib currently negotiates no GMCP, MSDP, MSSP or ATCP at all.
- **MSSP**, so listing sites (The Mud Connector, Grapevine, MudStats) can
  poll server status automatically.
- A starter `.mpackage` of aliases for Mudlet players — goodwill, not a
  requirement.
