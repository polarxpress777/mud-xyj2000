#!/usr/bin/env python3
"""Build a searchable index of the mudlib.

    python3 build_index.py                 # index libs/xyj2000f/work -> game.db
    python3 build_index.py search 火云洞     # ask it something
    python3 build_index.py family 将军府     # list a sect

Why this exists: answering "what is 火云洞, who heads it, where is it" took
six greps across two lineages. The facts are all in the .lpc files; they are
just not searchable together. This reads them once into SQLite.

**Chinese needs the trigram tokenizer.** FTS5's default tokenizer splits on
spaces, and Chinese has none, so 枯松涧火云洞的正堂 becomes a single token and
searching 火云洞 finds nothing. `tokenize='trigram'` indexes every 3-character
window instead, which gives substring matching. Requires SQLite 3.34+.

The parser is deliberately regex-shallow: it reads what `create()` sets, not
what the code computes at runtime. That is the same trade build_map.py makes,
and the same caveat applies -- anything assembled dynamically is invisible.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MUDLIB = HERE.parent.parent / "libs/xyj2000f/work"
DEFAULT_DB = HERE / "game.db"

# --- what a file is -------------------------------------------------------
ROOM_RE = re.compile(r"^\s*inherit\s+(?:ROOM|__DIR__|\"?/std/room)", re.M)
NPC_RE = re.compile(r"^\s*inherit\s+(?:NPC|F_NPC)", re.M)

# --- what create() sets ---------------------------------------------------
SHORT_RE = re.compile(r'set\s*\(\s*"short"\s*,\s*"([^"]+)"')
TITLE_RE = re.compile(r'set\s*\(\s*"title"\s*,\s*"([^"]+)"')
NAME_RE = re.compile(r'set_name\s*\(\s*"([^"]+)"\s*,\s*\(\{([^}]*)\}\)')
ID_RE = re.compile(r'"([^"]+)"')
INT_RE = {
    "combat_exp": re.compile(r'set\s*\(\s*"combat_exp"\s*,\s*(\d+)'),
    "daoxing": re.compile(r'set\s*\(\s*"daoxing"\s*,\s*(\d+)'),
    "age": re.compile(r'set\s*\(\s*"age"\s*,\s*(\d+)'),
}
# feature/attack.lpc:244 -- an NPC whose attitude is "aggressive" calls
# COMBAT_D->auto_fight() on any player who walks in. That is the difference
# between a monster you can walk past and one that kills you for entering.
ATTITUDE_RE = re.compile(r'set\s*\(\s*"attitude"\s*,\s*"([a-z_]+)"')
# Which NPCs a room places: set("objects", ([ __DIR__"npc/head" : 1 ]))
OBJECTS_RE = re.compile(r'set\s*\(\s*"objects"\s*,\s*\(\[(.*?)\]\)', re.S)
OBJECT_ENTRY_RE = re.compile(r'(__DIR__\s*)?"([^"]+)"\s*:\s*(\d+)')
FAMILY_RE = re.compile(r'create_family\s*\(\s*"([^"]+)"\s*,\s*(\d+)\s*,\s*"([^"]*)"')
RECRUIT_RE = re.compile(r"\b(?:recruit_apprentice|recognize_apprentice)\b")
SKILL_RE = re.compile(r'set_skill\s*\(\s*"([a-z0-9_-]+)"\s*,\s*(\d+)')
FLAG_RE = re.compile(r'set\s*\(\s*"(no_fight|no_magic|no_mieyao|sleep_room'
                     r'|if_bed|outdoors|no_flee|no_look)"\s*,\s*"?([^",)]*)')
EXITS_RE = re.compile(r'set\s*\(\s*"exits"\s*,\s*\(\[(.*?)\]\)\s*\)', re.S)
EXIT_ENTRY_RE = re.compile(r'"([a-z]+)"\s*:\s*(?:__DIR__\s*)?"([^"]*)"')
# @LONG … LONG);  — the terminator must start its own line (see AGENTS.md)
HEREDOC_RE = re.compile(r'set\s*\(\s*"long"\s*,\s*@([A-Z_]+)\s*\n(.*?)\n\1',
                        re.S)
LONG_STR_RE = re.compile(r'set\s*\(\s*"long"\s*,\s*"((?:[^"\\]|\\.)*)"', re.S)

LINE_COMMENT = re.compile(r"//[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(text):
    return LINE_COMMENT.sub("", BLOCK_COMMENT.sub("", text))


def long_text(src):
    m = HEREDOC_RE.search(src)
    if m:
        return m.group(2).strip()
    m = LONG_STR_RE.search(src)
    return m.group(1).replace("\\n", " ").strip() if m else ""


def parse_file(rel, src):
    """One .lpc file -> a record, or None if it is neither room nor NPC."""
    code = strip_comments(src)
    is_npc = bool(NPC_RE.search(code))
    is_room = bool(ROOM_RE.search(code)) and not is_npc
    if not (is_npc or is_room):
        return None

    name_m = NAME_RE.search(code)
    short_m = SHORT_RE.search(code)
    fam_m = FAMILY_RE.search(code)
    title_m = TITLE_RE.search(code)

    rec = {
        "kind": "npc" if is_npc else "room",
        "path": rel,
        "area": str(Path(rel).parent),
        "name": (name_m.group(1) if name_m else
                 short_m.group(1) if short_m else ""),
        "ids": " ".join(ID_RE.findall(name_m.group(2))) if name_m else "",
        "title": title_m.group(1) if title_m else "",
        "family": fam_m.group(1) if fam_m else "",
        "generation": int(fam_m.group(2)) if fam_m else None,
        "rank": fam_m.group(3) if fam_m else "",
        "recruits": 1 if RECRUIT_RE.search(code) else 0,
        "attitude": (ATTITUDE_RE.search(code).group(1)
                     if ATTITUDE_RE.search(code) else ""),
        "long": long_text(code),
    }
    for key, rx in INT_RE.items():
        m = rx.search(code)
        rec[key] = int(m.group(1)) if m else None

    skills = {k: int(v) for k, v in SKILL_RE.findall(code)}
    rec["skills"] = json.dumps(skills, ensure_ascii=False) if skills else ""

    flags = {}
    for k, v in FLAG_RE.findall(code):
        flags[k] = v if v and not v.isdigit() else int(v or 1)
    rec["flags"] = json.dumps(flags, ensure_ascii=False) if flags else ""

    exits = {}
    m = EXITS_RE.search(code)
    if m:
        for d, target in EXIT_ENTRY_RE.findall(m.group(1)):
            exits[d] = target
    rec["exits"] = json.dumps(exits, ensure_ascii=False) if exits else ""

    # Who lives here. Paths are resolved the same way exits are: __DIR__
    # means "this room's directory", otherwise it is already absolute.
    here = str(Path(rel).parent)
    placed = []
    m = OBJECTS_RE.search(code)
    if m:
        for dirmacro, target, _n in OBJECT_ENTRY_RE.findall(m.group(1)):
            t = target.lstrip("/")
            placed.append(f"{here}/{t}" if dirmacro else t)
    rec["objects"] = json.dumps(placed, ensure_ascii=False) if placed else ""
    return rec


SCHEMA = """
CREATE TABLE entities (
    kind TEXT, path TEXT PRIMARY KEY, area TEXT, name TEXT, ids TEXT,
    title TEXT, family TEXT, generation INTEGER, rank TEXT, recruits INTEGER,
    combat_exp INTEGER, daoxing INTEGER, age INTEGER,
    skills TEXT, flags TEXT, exits TEXT, objects TEXT, attitude TEXT,
    long TEXT
);
CREATE INDEX entities_attitude ON entities(attitude);
CREATE INDEX entities_family ON entities(family);
CREATE INDEX entities_area ON entities(area);
CREATE INDEX entities_kind ON entities(kind);
CREATE VIRTUAL TABLE search USING fts5(
    path UNINDEXED, kind UNINDEXED, name, ids, title, family, body,
    tokenize='trigram'
);
"""

COLUMNS = ["kind", "path", "area", "name", "ids", "title", "family",
           "generation", "rank", "recruits", "combat_exp", "daoxing", "age",
           "skills", "flags", "exits", "objects", "attitude", "long"]


def build_index(mudlib_root, db_path, verbose=False):
    """Read every .lpc under `mudlib_root` into a fresh SQLite index."""
    mudlib_root, db_path = Path(mudlib_root), Path(db_path)
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)

    n = 0
    for f in sorted((mudlib_root / "d").rglob("*.lpc")):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(mudlib_root))[:-4]
        rec = parse_file(rel, src)
        if not rec:
            continue
        db.execute(
            f"INSERT OR REPLACE INTO entities ({','.join(COLUMNS)}) "
            f"VALUES ({','.join('?' * len(COLUMNS))})",
            [rec[c] for c in COLUMNS])
        db.execute(
            "INSERT INTO search (path, kind, name, ids, title, family, body) "
            "VALUES (?,?,?,?,?,?,?)",
            (rec["path"], rec["kind"], rec["name"], rec["ids"], rec["title"],
             rec["family"], rec["long"]))
        n += 1
        if verbose and n % 500 == 0:
            print(f"  {n} entities…")

    n += index_docs(mudlib_root, db, verbose)
    db.commit()
    db.close()
    return n


# The lore is not in the code. doc/ carries the sect guide, the 取经 route
# with its 破迷要领 puzzle outlines, and ~40 area maps -- the answers to
# "who founded 月宫" and "how do I get into 波月洞", which no .lpc states.
DOC_MAX_BYTES = 400_000


def index_docs(mudlib_root, db, verbose=False):
    """Index doc/ as kind='doc'. These files have no extension and no
    structure worth parsing -- the whole text is the useful part."""
    docs = mudlib_root / "doc"
    if not docs.is_dir():
        return 0
    n = 0
    for f in sorted(docs.rglob("*")):
        if not f.is_file() or f.stat().st_size > DOC_MAX_BYTES:
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not body.strip() or "\x00" in body[:2000]:
            continue
        rel = str(f.relative_to(mudlib_root))
        db.execute(
            "INSERT OR REPLACE INTO entities (kind, path, area, name, long) "
            "VALUES ('doc', ?, ?, ?, ?)",
            (rel, str(f.parent.relative_to(mudlib_root)), f.name, body))
        db.execute(
            "INSERT INTO search (path, kind, name, ids, title, family, body) "
            "VALUES (?, 'doc', ?, '', '', '', ?)", (rel, f.name, body))
        n += 1
    if verbose:
        print(f"  {n} docs")
    return n


# FTS5's trigram tokenizer indexes 3-character windows, so a query shorter
# than that matches NOTHING -- not "few results", none. That is fatal here:
# 月宫 and 龙宫 are sect names, 拜师 is how you join one, 悟空 is the
# protagonist. Short terms fall back to a LIKE scan, which is slower but
# correct, and the tables are small enough that nobody notices.
TRIGRAM_MIN = 3
LIKE_COLUMNS = ("name", "ids", "title", "family", "long")


def search(db_path, term, kind=None, limit=50):
    """Rows matching `term` anywhere — name, id, title, family or body.

    `kind` restricts to 'npc', 'room' or 'doc'. Callers should use this
    rather than writing their own SQL: the short-term fallback below is
    easy to forget, and forgetting it silently loses 月宫.
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    params = []

    if len(term) < TRIGRAM_MIN:
        where = " OR ".join(f"{c} LIKE ?" for c in LIKE_COLUMNS)
        sql = f"SELECT * FROM entities WHERE ({where})"
        params += [f"%{term}%"] * len(LIKE_COLUMNS)
        order = " ORDER BY kind, name"
    else:
        sql = ("SELECT e.* FROM search s JOIN entities e ON e.path = s.path "
               "WHERE search MATCH ?")
        params.append('"' + term.replace('"', '""') + '"')
        order = " ORDER BY rank"

    if kind:
        sql += " AND kind = ?" if len(term) < TRIGRAM_MIN else " AND e.kind = ?"
        params.append(kind)
    rows = db.execute(sql + order + " LIMIT ?", params + [limit]).fetchall()
    db.close()
    return [dict(r) for r in rows]


DANGER_OUT = HERE / "danger.json"


def dump_danger(db_path, out=DANGER_OUT):
    """Write room path -> strongest attitude-aggressive resident's combat_exp.

    feature/attack.lpc:244 auto_fight()s any player who walks into a room
    holding an "aggressive" NPC, so these are the rooms that kill you for
    entering rather than for fighting. The bot compares each against its own
    武学 and stays out of the ones it cannot survive.

    Keyed by PATH, not by room name: 休息室 exists four times and 海底莽林 ten,
    and only some of them are lethal.

    NOT covered: NPCs that attack on a script rather than an attitude. 马盗
    (d/westway/npc/madao.lpc) is attitude "heroism" and attacks 25 seconds
    after you arrive via call_out -> command("kill"), which no attribute
    reveals. The bot handles him separately, by paying the toll.
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    npcs = {r["path"]: r for r in db.execute(
        "SELECT path, combat_exp, attitude FROM entities WHERE kind='npc'")}
    danger = {}
    for r in db.execute("SELECT path, objects FROM entities "
                        "WHERE kind='room' AND objects != ''"):
        worst = 0
        for op in json.loads(r["objects"]):
            n = npcs.get(op)
            if n and n["attitude"] == "aggressive":
                worst = max(worst, n["combat_exp"] or 0)
        if worst:
            danger[r["path"]] = worst
    db.close()
    Path(out).write_text(json.dumps(danger, ensure_ascii=False, indent=0),
                         encoding="utf-8")
    return danger


KIND_LABEL = {"npc": "NPC", "room": "房间", "doc": "文档"}


def snippet(db, path, term, width=70):
    """The line of body text the match sits in, so a hit explains itself."""
    row = db.execute("SELECT long FROM entities WHERE path = ?",
                     (path,)).fetchone()
    body = (row[0] if row and row[0] else "").replace("\n", " ")
    i = body.find(term)
    if i < 0:
        return body[:width].strip()
    start = max(0, i - width // 3)
    return ("…" if start else "") + body[start:start + width].strip() + "…"


def show_family(db, name):
    rows = db.execute("SELECT * FROM entities WHERE family = ? "
                      "ORDER BY generation, name", (name,)).fetchall()
    if not rows:
        print(f"no family called {name}")
        return 1
    print(f"{name} — {len(rows)} members")
    for r in rows:
        recruits = " 【可拜师】" if r["recruits"] else ""
        print(f"  第{r['generation']}代 {r['name'] or '?':<12}"
              f"{r['title'] or '':<16} {r['path']}{recruits}")
    return 0


def show_search(db, db_path, term, kind, limit):
    rows = search(db_path, term, kind=kind, limit=limit)
    if not rows:
        print(f"nothing matches {term}")
        return 0
    print(f"{len(rows)} hit(s) for {term}\n")
    for r in rows:
        label = KIND_LABEL.get(r["kind"], r["kind"])
        bits = [b for b in (r["title"], r["family"] and f"门派:{r['family']}",
                            r["recruits"] and "可拜师") if b]
        print(f"[{label}] {r['name'] or Path(r['path']).name}  "
              f"{'  '.join(str(b) for b in bits)}")
        print(f"        {r['path']}")
        text = snippet(db, r["path"], term)
        if text:
            print(f"        {text}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build and query the mudlib index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  build_index.py                       rebuild the index (the default)
  build_index.py search 火云洞          anything mentioning it
  build_index.py search 红孩儿 --kind npc
  build_index.py family 将军府          every member, by generation
""")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="rebuild game.db and danger.json")
    b.add_argument("root", nargs="?", default=str(DEFAULT_MUDLIB))
    b.add_argument("out", nargs="?", default=str(DEFAULT_DB))

    se = sub.add_parser("search", help="search names, ids, titles and bodies")
    se.add_argument("term")
    se.add_argument("--kind", choices=["npc", "room", "doc"])
    se.add_argument("-n", "--limit", type=int, default=20)

    fa = sub.add_parser("family", help="list a sect's members")
    fa.add_argument("name")

    for p in (se, fa):
        p.add_argument("--db", default=str(DEFAULT_DB))

    args = ap.parse_args(argv)

    if args.cmd in (None, "build"):
        root = Path(getattr(args, "root", DEFAULT_MUDLIB))
        out = Path(getattr(args, "out", DEFAULT_DB))
        print(f"indexing {root} -> {out}")
        total = build_index(root, out, verbose=True)
        print(f"{total} entities indexed, {out.stat().st_size // 1024} KB")
        danger = dump_danger(out)
        print(f"{len(danger)} rooms with an aggressive resident -> "
              f"{DANGER_OUT.name} (worst {max(danger.values()) if danger else 0})")
        return 0

    if not Path(args.db).exists():
        sys.exit(f"no index at {args.db} — run: python3 build_index.py")
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    if args.cmd == "family":
        return show_family(db, args.name)
    return show_search(db, args.db, args.term, args.kind, args.limit)


if __name__ == "__main__":
    sys.exit(main())
