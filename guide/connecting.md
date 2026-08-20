# Connecting to the server

How to join a 西游记 (xyj2000f) server running on someone's machine on
your local network. For hosting/packaging, see [`docker/README.md`](../docker/README.md).

## What you need from the host

| | |
|---|---|
| **Address** | the host machine's LAN IP, e.g. `192.168.20.20` |
| **Port** | **40012** |
| **Network** | you must be on the same wifi |

The host finds their IP with `ipconfig getifaddr en0` (macOS),
`hostname -I` (Linux), or `ipconfig` (Windows). It can change when they
reconnect to wifi, so ask again if it stops working.

> Port **40099** is *not* the game. That's `tools/xyjbot/botproxy.py`, a
> personal automation proxy bound to `127.0.0.1` only — it isn't
> reachable from other machines and isn't meant to be.

## macOS / Linux

```bash
telnet 192.168.20.20 40012
```

`nc` also works but has **no line editing or history** — arrow-up won't
recall your last command, which gets old fast in a MUD:

```bash
nc 192.168.20.20 40012           # works, but no history
rlwrap nc 192.168.20.20 40012    # adds history + arrow keys
```

`rlwrap` is the only reason to prefer `nc` over `telnet`; install it with
`brew install rlwrap` or `apt install rlwrap`.

## Windows

The game is entirely in Chinese and the server sends **UTF-8**, which the
built-in Windows telnet client handles badly. Options, best first:

### Mudlet (recommended)

Cross-platform MUD client, free. New profile → set:

- Address: `192.168.20.20`, port `40012`
- Settings (toolbar button) → **General** → **Server data encoding** →
  **UTF-8** (this is per-profile and saves with it -- set it once)

Then connect. You'll hit the same `gb`/`no`/name prompts as everyone
else -- see [Logging in](#logging-in) below. Type `gb` there even though
Mudlet's own transport encoding is UTF-8; that prompt is the *mudlib*
picking its internal Chinese encoding via `CONVERT_D`, unrelated to
Mudlet's wire encoding.

If Chinese still renders as boxes/`?`, double-check the encoding didn't
revert to "System", and pick a font with full CJK coverage in the same
General settings tab.

Gives proper Chinese rendering, colour, scrollback, and its own Lua
trigger/alias scripting.

### WSL (the real command-line option)

```powershell
wsl
```
then inside WSL:
```bash
telnet 192.168.20.20 40012
```
Windows Terminal + WSL renders UTF-8 correctly, unlike `cmd`.

### Built-in telnet (works, but expect garbled Chinese)

Disabled by default since Vista. Enable it in an **Administrator**
prompt:

```
dism /online /Enable-Feature /FeatureName:TelnetClient
```
or PowerShell:
```powershell
Enable-WindowsOptionalFeature -Online -FeatureName TelnetClient
```
or Settings → Apps → Optional Features → More Windows Features → tick
**Telnet Client**.

Then:
```
telnet 192.168.20.20 40012
```

`telnet.exe` is a legacy client: even after `chcp 65001` you'll likely
get mojibake or misaligned double-width text, and there's no scrollback.
Fine for a quick check, poor for actually playing.

### PuTTY

Connection type **Telnet**, host/port as above, and importantly
Window → Translation → Remote character set = **UTF-8**.

## Logging in

Two prompts come before the game:

```
Select 国标码 GB or BIG5 (gb/big5):     ->  type:  gb
您是否是中小学学生或年龄更小？(yes/no)   ->  type:  no
您的英文名字：（新玩家请键入 new 注册）  ->  your name, or `new` to register
```

Then you're in. Useful first commands: `look` (看), `hp`, `score`,
`skills`, `help`.

## Troubleshooting

**Chinese shows as `???` or mojibake** — your client isn't in UTF-8. Set
the encoding explicitly (Mudlet: Settings → encoding; PuTTY: Remote
character set). Windows `cmd`: try `chcp 65001`, or switch to WSL/Mudlet.

**Arrow-up doesn't recall commands** — you're on raw `nc`. Use `telnet`,
`rlwrap nc`, or a real MUD client.

**"Connection refused"** — server isn't running, or you have the wrong
IP/port. Have the host confirm with `lsof -iTCP:40012 -sTCP:LISTEN`.

**Connects from the host machine but not from others** — the server is
bound to loopback only, or a firewall is blocking. The listener should
show `*:40012`, not `127.0.0.1:40012`.

## Security

Traffic is **unencrypted** and passwords cross the network in the clear.
That's acceptable on trusted home wifi. Do **not** port-forward 40012 to
the public internet — this is a 1990s codebase with no modern hardening.
