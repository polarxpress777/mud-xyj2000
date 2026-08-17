#!/usr/bin/env python3
"""boteditor -- browser UI for building bots.

    python3 boteditor.py        then open http://127.0.0.1:8777

A browser form is the right place for this: pasting Chinese trigger text,
copying patterns between people, and testing a regex against sample text
are all awkward in a terminal. Reads and writes the same bots.json the
proxy uses, so /reload in game picks up changes immediately.

Stdlib only.
"""
from __future__ import annotations

import json
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

CONFIG = Path(__file__).with_name("bots.json")
PORT = 8777

PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>西游记 机器人编辑器</title>
<style>
 body{font:14px/1.5 -apple-system,"PingFang SC",sans-serif;margin:0;
      background:#1e1f22;color:#e6e6e6}
 header{background:#2b2d31;padding:12px 20px;font-weight:600}
 main{display:flex;gap:20px;padding:20px;align-items:flex-start}
 .col{background:#2b2d31;border-radius:8px;padding:16px}
 #list{width:340px} #form{flex:1;min-width:420px}
 h2{font-size:13px;text-transform:uppercase;color:#9aa0a6;margin:0 0 10px}
 .item{padding:8px;border-radius:6px;cursor:pointer;margin-bottom:4px}
 .item:hover{background:#3a3d43} .item.sel{background:#3f4d5a}
 .item .n{font-weight:600} .item .d{color:#9aa0a6;font-size:12px}
 label{display:block;margin:10px 0 4px;color:#9aa0a6;font-size:12px}
 input[type=text],textarea,select{width:100%;box-sizing:border-box;
   background:#1e1f22;color:#e6e6e6;border:1px solid #4a4d53;
   border-radius:6px;padding:8px;font:14px/1.4 inherit}
 textarea{min-height:60px;resize:vertical}
 .row{display:flex;gap:12px} .row>*{flex:1}
 button{background:#4a7dbb;color:#fff;border:0;border-radius:6px;
   padding:9px 14px;font-weight:600;cursor:pointer;margin-right:8px}
 button.sec{background:#4a4d53} button.del{background:#a3423c}
 .match{margin-top:8px;padding:8px;border-radius:6px;font-weight:600}
 .yes{background:#1e4620;color:#7ee787} .no{background:#4a2020;color:#ffa198}
 .hint{color:#9aa0a6;font-size:12px;margin-top:4px}
 code{background:#1e1f22;padding:1px 5px;border-radius:4px}
</style></head><body>
<header>西游记 机器人编辑器 &nbsp;<span style="color:#9aa0a6;font-weight:400">
 存到 bots.json — 游戏里打 /reload 生效</span></header>
<main>
 <div class="col" id="list">
   <h2>机器人</h2><div id="items"></div>
   <button onclick="newBot('trigger')">+ 触发</button>
   <button onclick="newBot('timer')" class="sec">+ 循环</button>
 </div>
 <div class="col" id="form">
   <h2 id="ftitle">编辑</h2>
   <label>名称（游戏里用 /名称 执行）</label>
   <input type="text" id="name">
   <div id="trigfields">
     <label>触发文字（贴上游戏里出现的整句）</label>
     <textarea id="pattern"></textarea>
     <div class="row">
       <div><label>比对方式</label>
         <select id="isregex" onchange="test()">
           <option value="0">纯文字（建议）</option>
           <option value="1">正规表示式</option></select></div>
       <div><label>冷却秒数（0 = 不限）</label>
         <input type="text" id="cooldown" value="0"></div>
     </div>
     <label>测试文字（贴一行游戏输出试试）</label>
     <textarea id="sample"></textarea>
     <div id="result" class="match no">尚未比对</div>
     <div class="hint">正规表示式可用 <code>(\d+)</code> 抓数字，
       动作里用 <code>$1</code> 代入。</div>
   </div>
   <div id="timerfields" style="display:none">
     <label>每隔几秒执行</label><input type="text" id="interval" value="10">
   </div>
   <label>要送出的指令（一行一个）</label>
   <textarea id="actions"></textarea>
   <label><input type="checkbox" id="enabled" style="width:auto"> 启用</label>
   <div style="margin-top:14px">
     <button onclick="save()">储存</button>
     <button onclick="del()" class="del">删除</button>
   </div>
 </div>
</main>
<script>
let data={triggers:[],timers:[]}, sel=null;
const $=id=>document.getElementById(id);

async function load(){ data=await (await fetch('/api/bots')).json(); render(); }
function render(){
  const el=$('items'); el.innerHTML='';
  data.triggers.forEach((t,i)=>el.appendChild(row(t,'trigger',i,
    '当「'+t.pattern+'」')));
  data.timers.forEach((t,i)=>el.appendChild(row(t,'timer',i,
    '每 '+t.interval+' 秒')));
}
function row(t,kind,i,desc){
  const d=document.createElement('div');
  d.className='item'+(sel&&sel.kind===kind&&sel.i===i?' sel':'');
  d.innerHTML='<div class="n">'+(t.enabled?'☑':'☐')+' /'+t.name+'</div>'+
              '<div class="d">'+desc+' → '+(t.actions||[]).join(' ; ')+'</div>';
  d.onclick=()=>{sel={kind,i};edit(t,kind);render();};
  return d;
}
function newBot(kind){
  const t=kind==='trigger'
    ?{name:'新触发',pattern:'',is_regex:false,actions:[],cooldown:0,
      once:false,enabled:true}
    :{name:'新循环',interval:10,actions:[],enabled:true};
  (kind==='trigger'?data.triggers:data.timers).push(t);
  sel={kind,i:(kind==='trigger'?data.triggers:data.timers).length-1};
  edit(t,kind); render();
}
function edit(t,kind){
  $('ftitle').textContent=kind==='trigger'?'编辑触发':'编辑循环';
  $('trigfields').style.display=kind==='trigger'?'':'none';
  $('timerfields').style.display=kind==='timer'?'':'none';
  $('name').value=t.name||'';
  $('actions').value=(t.actions||[]).join('\n');
  $('enabled').checked=!!t.enabled;
  if(kind==='trigger'){
    $('pattern').value=t.pattern||''; $('isregex').value=t.is_regex?'1':'0';
    $('cooldown').value=t.cooldown||0; test();
  } else $('interval').value=t.interval||10;
}
function current(){
  if(!sel)return null;
  return (sel.kind==='trigger'?data.triggers:data.timers)[sel.i];
}
async function test(){
  const p=$('pattern').value, s=$('sample').value, r=$('result');
  if(!p||!s){r.className='match no';r.textContent='尚未比对';return;}
  const res=await (await fetch('/api/test',{method:'POST',
    body:JSON.stringify({pattern:p,sample:s,is_regex:$('isregex').value==='1'})
  })).json();
  r.className='match '+(res.ok?'yes':'no');
  r.textContent=res.ok?('比对成功！'+(res.groups.length?
    '  捕获：'+res.groups.map((g,i)=>'$'+(i+1)+'='+g).join('  '):''))
    :(res.error||'不符合');
}
$('pattern').addEventListener('input',test);
$('sample').addEventListener('input',test);
async function save(){
  const t=current(); if(!t)return;
  t.name=$('name').value.trim().replace(/\s+/g,'');
  t.actions=$('actions').value.split('\n').map(s=>s.trim()).filter(Boolean);
  t.enabled=$('enabled').checked;
  if(sel.kind==='trigger'){
    t.pattern=$('pattern').value; t.is_regex=$('isregex').value==='1';
    t.cooldown=parseFloat($('cooldown').value)||0;
  } else t.interval=parseFloat($('interval').value)||10;
  await fetch('/api/bots',{method:'POST',body:JSON.stringify(data)});
  render();
}
async function del(){
  if(!sel)return;
  (sel.kind==='trigger'?data.triggers:data.timers).splice(sel.i,1);
  sel=null;
  await fetch('/api/bots',{method:'POST',body:JSON.stringify(data)});
  render();
}
load();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(PAGE.encode("utf-8"), "text/html")
        if path == "/api/bots":
            if CONFIG.exists():
                return self._send(CONFIG.read_bytes())
            return self._send(b'{"triggers":[],"timers":[]}')
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")

        if path == "/api/bots":
            CONFIG.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8")
            return self._send(b'{"saved":true}')

        if path == "/api/test":
            # Live pattern tester -- the "PATTERN MATCHES!" panel.
            pat, sample = payload.get("pattern", ""), payload.get("sample", "")
            if payload.get("is_regex"):
                try:
                    m = re.search(pat, sample)
                except re.error as e:
                    return self._send(json.dumps(
                        {"ok": False, "error": f"正规表示式错误：{e}"},
                        ensure_ascii=False).encode("utf-8"))
                out = {"ok": bool(m),
                       "groups": list(m.groups()) if m else []}
            else:
                out = {"ok": pat in sample, "groups": []}
            return self._send(json.dumps(out, ensure_ascii=False)
                              .encode("utf-8"))
        self.send_error(404)

    def log_message(self, *a):
        pass          # keep the console quiet


def main():
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"boteditor: {url}   (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nboteditor stopped.")


if __name__ == "__main__":
    main()
