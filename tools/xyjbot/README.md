# xyjbot — 西游记 terminal client with a bot builder

A full-screen curses client for the 西游记 mudlib, with reactive triggers
and grinding loops. Pure stdlib for everything except the optional
AI-assisted bot creation.

```
python3 xyjbot.py                 # 127.0.0.1 40012
python3 xyjbot.py <host> <port>
```

| Key | Action |
|---|---|
| F2 / Ctrl-B | open the bot builder |
| F3 / Ctrl-G | toggle all automation on/off |
| PgUp / PgDn | scroll the game pane |
| Ctrl-C | quit |

## Bots

**Triggers** are reactive: when a line from the game matches, commands are
sent back. This is what most bot flows are.

**Timers** are proactive: send commands every N seconds — grinding loops
like 打坐 / 练功.

In the builder: `t` new trigger, `m` new timer, `Enter` edit, `space`
enable/disable, `d` delete, `a` AI-generate, `q` back.

Patterns are plain Chinese by default — paste the line as the game prints
it (`你行功完毕，吸一口气，缓缓站了起来。`). Switch a trigger to regex when
you need to capture a number; `$1` in an action is replaced by the first
capture group. Matching runs against the text with ANSI colour codes
stripped, so patterns never need to account for them.

`cooldown` guards against a trigger that matches its own output and loops.
`quit` is a legal action, so a bot can log itself out.

Bots are stored in `bots.json` next to the code — plain UTF-8 JSON, safe to
hand-edit.

## AI-assisted creation

Press `a` in the builder and describe the bot in Chinese
(「行功完毕就继续打坐」). Requires:

```
pip3 install anthropic
export ANTHROPIC_API_KEY=...      # or an `ant auth login` profile
```

Everything else works without it. AI-generated bots arrive **disabled** —
read what it wrote before letting it drive a live character.

## Design notes

- **CJK widths.** Chinese glyphs occupy two terminal columns, so all layout
  math goes through `ansi.display_width` / `fit_to_width` (stdlib
  `unicodedata.east_asian_width`) rather than `len()`. Using `len()` here
  misaligns every line that contains 中文, which is nearly all of them.
- **Prompts have no trailing newline.** The mud's prompts (`Select GB or
  BIG5`, `请输入相应密码`) arrive unterminated, so they're flushed on a short
  idle and pushed through the trigger engine like any other line — they are
  exactly the lines players most want to trigger on.
- **The engine takes `now` as a parameter** instead of reading the clock, so
  cooldown and interval behaviour is testable without sleeping.

## Tests

```
python3 test_triggers.py
```

Covers the engine (the seam worth testing): Chinese substring and regex
matching, capture-group substitution, cooldowns, once-only, timers, the
master switch, ANSI stripping, CJK width, and config round-tripping. The
curses UI is deliberately not covered.
