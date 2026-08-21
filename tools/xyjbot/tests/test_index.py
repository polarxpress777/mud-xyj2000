"""Tests for the game index — the searchable database of the mudlib.

Today, answering "what is 火云洞 and who heads it" takes six greps. This
builds the answer once into SQLite, so it takes one query.

Chinese has no spaces, so FTS5's default tokenizer would swallow a whole
sentence as one token and substring search would fail. The index uses the
trigram tokenizer, which is what makes 火云洞 findable inside 枯松涧火云洞.

Run with: python3 test_index.py
"""
import importlib.util, sqlite3, sys, tempfile
from pathlib import Path

# tools/xyjbot -- every path below is relative to it, so this
# stayed correct when the tests moved down into tests/.
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("bi", HERE / "build_index.py")
bi = importlib.util.module_from_spec(spec); spec.loader.exec_module(bi)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


def fixture():
    """A miniature mudlib: one cave, one demon who can induct you."""
    root = Path(tempfile.mkdtemp()) / "work"
    (root / "d/qujing/kusong/npc").mkdir(parents=True)
    (root / "d/qujing/kusong/huoyun.lpc").write_text('''
inherit ROOM;
void create() {
  set("short", "火云堂");
  set("long", @LONG
枯松涧火云洞的正堂，红孩儿在此坐镇。
LONG);
  set("exits", ([ "out": __DIR__ "kusongjian" ]));
  set("no_fight", 1);
  setup();
}
''', encoding="utf-8")
    (root / "d/qujing/kusong/npc/honghaier.lpc").write_text('''
inherit NPC;
void create() {
  set_name("红孩儿", ({ "honghai er", "er" }));
  set("title", "圣婴大王");
  set("combat_exp", 400000);
  create_family("火云洞", 2, "蓝");
  set_skill("spells", 120);
  setup();
}
int recruit_apprentice(object ob) { return 1; }
''', encoding="utf-8")
    return root


print("one query answers what six greps answered")
root = fixture()
db = Path(tempfile.mkdtemp()) / "game.db"
bi.build_index(root, db)

hits = bi.search(db, "火云洞")
kinds = sorted({h["kind"] for h in hits})
check("finds both the NPC and the room", kinds, ["npc", "room"])

npc = next((h for h in hits if h["kind"] == "npc"), None)
check("names him", npc and npc["name"], "红孩儿")
check("with his title", npc and npc["title"], "圣婴大王")
check("his family", npc and npc["family"], "火云洞")
check("his generation", npc and npc["generation"], 2)
check("and where he lives", npc and npc["path"],
      "d/qujing/kusong/npc/honghaier")
check("flagged as able to induct you", npc and npc["recruits"], 1)

print("\nsubstring search works inside Chinese without spaces")
# 火云洞 appears only INSIDE 枯松涧火云洞的正堂 in the room's long text.
room = next((h for h in hits if h["kind"] == "room"), None)
check("matched mid-sentence", room and room["name"], "火云堂")

print("\ntwo-character terms work — the trigram tokenizer alone would miss them")
# FTS5 trigram indexes 3-character windows, so a 2-character query matches
# NOTHING. That is not an edge case here: 月宫 and 龙宫 are sect names, 拜师
# is the verb for joining one, and 悟空 is the protagonist.
hits = bi.search(db, "火云")
check("finds the two-character term", sorted({h["kind"] for h in hits}),
      ["npc", "room"])
check("and still the longer one", len(bi.search(db, "火云洞")) > 0, True)

print("\nkind filtering lives in one place, not in every caller")
check("npc only", [h["kind"] for h in bi.search(db, "火云洞", kind="npc")],
      ["npc"])

print("\nthe help documentation is indexed too, not just the code")
# The lore lives in doc/help*/ -- the sect guide, the 取经 route, the maps.
# Without it, "who founded 月宫" is answerable only by reading files by hand.
(root / "doc/help").mkdir(parents=True)
(root / "doc/help/menpai").write_text(
    "西游记门派介绍:\n\n五庄观为镇元大仙所创。镇元大仙辈分极高，乃是地仙之祖。\n",
    encoding="utf-8")
db2 = Path(tempfile.mkdtemp()) / "game.db"
bi.build_index(root, db2)

hits = bi.search(db2, "地仙之祖")
doc = next((h for h in hits if h["kind"] == "doc"), None)
check("finds the sect guide by a phrase inside it", bool(doc), True)
check("and says which file", doc and doc["path"], "doc/help/menpai")

# The code is still there alongside it.
both = sorted({h["kind"] for h in bi.search(db2, "火云洞")})
check("code and docs share one index", both, ["npc", "room"])

print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
