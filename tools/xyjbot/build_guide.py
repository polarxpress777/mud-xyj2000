#!/usr/bin/env python3
"""Generate the training guide from the index.

    python3 build_index.py        # first, if game.db is stale
    python3 build_guide.py        # -> guide/training-guide.html (+ md table)

Who is worth sparring is a question about DATA -- every NPC's skills, 道行
and whereabouts -- so it is answered from game.db rather than by hand. The
prose that explains WHY lives in guide/training-guide.md and is not
generated.

Two filters, both from the mudlib:
  * `friendly` NPCs refuse `fight` outright (std/char/npc.lpc:36-71), so
    they are dropped -- 店小二 is not a training target.
  * an NPC with no skills at all teaches nothing, so it is dropped too.
"""
import json
import re
import sqlite3
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "game.db"
MUDLIB = HERE.parent.parent / "libs/xyj2000f/work"
OUT_HTML = HERE.parent.parent / "guide/training-guide.html"


def regions():
    out = {}
    for line in (MUDLIB / "adm/daemons/find.map").read_text(
            encoding="utf-8").splitlines():
        p = line.split(None, 1)
        if len(p) == 2 and p[1].strip():
            out[p[0]] = p[1].replace(" ", "").strip()
    return out


def region_of(path, maps):
    parts = path.strip("/").split("/")
    for cut in range(len(parts) - 1, 0, -1):
        label = maps.get("/".join(parts[:cut]))
        if label:
            return label
    return "（未命名区域）"


def collect():
    maps = regions()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    # where each NPC stands: reverse of the rooms' own object lists
    where = {}
    for r in db.execute("SELECT path, name, objects FROM entities "
                        "WHERE kind='room' AND objects != ''"):
        for op in json.loads(r["objects"]):
            where.setdefault(op, (r["path"], r["name"]))

    rows = []
    for n in db.execute("SELECT path, name, title, skills, daoxing, "
                        "combat_exp, attitude FROM entities WHERE kind='npc'"):
        if not n["skills"] or n["attitude"] == "friendly":
            continue
        levels = [v for v in json.loads(n["skills"]).values() if v]
        if not levels:
            continue
        room_path, room_name = where.get(n["path"], ("", ""))
        rows.append({
            "name": n["name"] or Path(n["path"]).name,
            "title": n["title"] or "",
            "avg": round(statistics.mean(levels)),
            "top": max(levels),
            "daoxing": n["daoxing"] or 0,
            "exp": n["combat_exp"] or 0,
            "region": region_of(room_path or n["path"], maps),
            "room": room_name or "（未放置）",
            "path": n["path"],
            "attitude": n["attitude"] or "peaceful",
        })
    db.close()
    rows.sort(key=lambda r: (r["avg"], r["exp"]))
    return rows


def md_table(rows, lo, hi, limit=8):
    """A markdown slice for one tier, cheapest targets first."""
    band = [r for r in rows if lo <= r["avg"] <= hi and r["room"] != "（未放置）"]
    out = ["| NPC | 平均技能 | 道行 | 武学 | 区域 | 房间 |",
           "|---|---:|---:|---:|---|---|"]
    for r in band[:limit]:
        out.append(f"| {r['name']}{' ' + r['title'] if r['title'] else ''} "
                   f"| {r['avg']} | {r['daoxing']:,} | {r['exp']:,} "
                   f"| {r['region']} | {r['room']} |")
    return "\n".join(out), len(band)


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>练功目标 — 西游记</title>
<style>
 :root{color-scheme:dark}
 body{font:14px/1.6 -apple-system,"PingFang SC",sans-serif;margin:0;
      background:#1e1f22;color:#e6e6e6}
 header{background:#2b2d31;padding:14px 20px;display:flex;flex-wrap:wrap;
        gap:14px;align-items:center;position:sticky;top:0;z-index:2}
 header h1{font-size:16px;margin:0;font-weight:600}
 header .sub{color:#9aa0a6;font-size:12px}
 input,select{background:#1e1f22;color:#e6e6e6;border:1px solid #4a4d53;
   border-radius:6px;padding:7px 9px;font:13px inherit}
 main{display:flex;gap:18px;padding:18px;align-items:flex-start}
 #regions{width:230px;flex:none;background:#2b2d31;border-radius:8px;
   padding:12px;max-height:80vh;overflow:auto}
 .reg{padding:7px 9px;border-radius:6px;cursor:pointer;display:flex;
   justify-content:space-between;gap:8px}
 .reg:hover{background:#3a3d43} .reg.sel{background:#3f4d5a}
 .reg .n{color:#9aa0a6;font-size:12px}
 #list{flex:1;background:#2b2d31;border-radius:8px;padding:12px;min-width:0}
 table{width:100%;border-collapse:collapse}
 th{text-align:left;color:#9aa0a6;font-size:12px;font-weight:600;
    padding:6px 8px;cursor:pointer;white-space:nowrap}
 th:hover{color:#e6e6e6}
 td{padding:6px 8px;border-top:1px solid #3a3d43;vertical-align:top}
 td.num{text-align:right;font-variant-numeric:tabular-nums}
 tr.fit{background:rgba(126,231,135,.09)}
 tr.fit td:first-child{box-shadow:inset 3px 0 #7ee787}
 .tag{font-size:11px;color:#9aa0a6}
 .empty{color:#9aa0a6;padding:20px;text-align:center}
 .legend{color:#9aa0a6;font-size:12px;padding:6px 8px}
</style></head><body>
<header>
  <h1>练功目标</h1>
  <span class="sub">__COUNT__ 个肯陪练的 NPC — friendly 的不收（std/char/npc.lpc:36-71）</span>
  <label class="sub">我的平均技能
    <input type="number" id="mine" value="20" min="0" max="300" style="width:74px">
  </label>
  <input type="search" id="q" placeholder="搜 NPC / 房间 / 区域…" style="min-width:200px">
  <label class="sub"><input type="checkbox" id="fitonly"> 只看适合我的</label>
</header>
<main>
  <div id="regions"></div>
  <div id="list"></div>
</main>
<script>
const DATA = __DATA__;
const $ = id => document.getElementById(id);
let sel = null, sortKey = 'avg', sortDir = 1;

// 你靠打比自己强的人涨武学（combatd.lpc:491-503 的 ap < dp），
// 但强太多就是送死。取 +1 到 +40% 这一段当作「适合」。
function fits(r, mine){ return r.avg > mine && r.avg <= Math.max(mine + 3, mine * 1.4); }

function regions(){
  const m = new Map();
  for (const r of DATA) m.set(r.region, (m.get(r.region) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}
function renderRegions(){
  const mine = +$('mine').value;
  const el = $('regions'); el.innerHTML = '';
  const all = document.createElement('div');
  all.className = 'reg' + (sel === null ? ' sel' : '');
  all.innerHTML = '<span>全部区域</span><span class="n">' + DATA.length + '</span>';
  all.onclick = () => { sel = null; render(); };
  el.appendChild(all);
  for (const [name, n] of regions()){
    const hits = DATA.filter(r => r.region === name && fits(r, mine)).length;
    const d = document.createElement('div');
    d.className = 'reg' + (sel === name ? ' sel' : '');
    d.innerHTML = '<span>' + name + '</span><span class="n">' +
      (hits ? '<b style="color:#7ee787">' + hits + '</b> / ' : '') + n + '</span>';
    d.onclick = () => { sel = name; render(); };
    el.appendChild(d);
  }
}
function rows(){
  const mine = +$('mine').value, q = $('q').value.trim().toLowerCase();
  let rs = DATA.filter(r => (sel === null || r.region === sel));
  if (q) rs = rs.filter(r => (r.name + r.title + r.room + r.region + r.path)
                              .toLowerCase().includes(q));
  if ($('fitonly').checked) rs = rs.filter(r => fits(r, mine));
  return rs.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sortDir;
  });
}
function render(){
  renderRegions();
  const mine = +$('mine').value, rs = rows();
  const cols = [['name','NPC'],['avg','平均技能'],['top','最高'],
                ['daoxing','道行'],['exp','武学'],['region','区域'],['room','房间']];
  let h = '<table><thead><tr>' + cols.map(([k, label]) =>
      '<th data-k="' + k + '">' + label + (sortKey === k ? (sortDir > 0 ? ' ↑' : ' ↓') : '') + '</th>'
    ).join('') + '</tr></thead><tbody>';
  for (const r of rs.slice(0, 400)){
    h += '<tr class="' + (fits(r, mine) ? 'fit' : '') + '">' +
      '<td>' + r.name + (r.title ? ' <span class="tag">' + r.title + '</span>' : '') + '</td>' +
      '<td class="num">' + r.avg + '</td><td class="num">' + r.top + '</td>' +
      '<td class="num">' + r.daoxing.toLocaleString() + '</td>' +
      '<td class="num">' + r.exp.toLocaleString() + '</td>' +
      '<td>' + r.region + '</td><td>' + r.room + '</td></tr>';
  }
  h += '</tbody></table>';
  if (!rs.length) h = '<div class="empty">没有符合的 NPC</div>';
  else if (rs.length > 400) h += '<div class="legend">只显示前 400 个，共 ' + rs.length + ' 个</div>';
  else h += '<div class="legend">共 ' + rs.length + ' 个 · 绿色 = 比你略强，正好练功</div>';
  $('list').innerHTML = h;
  document.querySelectorAll('th').forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
    render();
  });
}
for (const id of ['mine','q','fitonly']) $(id).addEventListener('input', render);
render();
</script></body></html>
"""


def write_html(rows, out=OUT_HTML):
    """A self-contained page -- data embedded, no network, no assets."""
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    page = HTML.replace("__DATA__", payload).replace("__COUNT__", str(len(rows)))
    Path(out).write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    rows = collect()
    print(f"{len(rows)} sparrable NPCs with skills")
    out = write_html(rows)
    print(f"-> {out} ({out.stat().st_size // 1024} KB, self-contained)")
    for lo, hi in ((1, 20), (21, 40), (41, 70), (71, 110), (111, 999)):
        table, n = md_table(rows, lo, hi)
        print(f"\n### 平均技能 {lo}–{hi if hi < 999 else '+'}  ({n} 个)\n")
        print(table)
