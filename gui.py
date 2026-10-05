"""Read-only HTML archive for humans. Cases first. Not a prompt dump."""
from __future__ import annotations

import html
import webbrowser
from pathlib import Path
from typing import Any

from . import catalog
from . import managed

TOOLS = [
    {
        "name": "be_gui",
        "description": "Write a read-only HTML archive of history/cards and return its path. For the human, not a model dump.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _all_history() -> list[dict[str, Any]]:
    catalog.init()
    with catalog.connect(write=False) as conn:
        rows = conn.execute(
            "SELECT * FROM case_history ORDER BY closed DESC, gold DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _all_cards() -> list[dict[str, Any]]:
    catalog.init()
    with catalog.connect(write=False) as conn:
        rows = conn.execute("SELECT * FROM schema_card ORDER BY kind, name").fetchall()
    return [dict(r) for r in rows]


def _all_strategy() -> list[dict[str, Any]]:
    catalog.init()
    with catalog.connect(write=False) as conn:
        rows = conn.execute("SELECT * FROM strategy ORDER BY lane, seq").fetchall()
    return [dict(r) for r in rows]


def _case_block(row: dict[str, Any]) -> str:
    gold = "<span class='gold'>金标准</span>" if row.get("gold") else ""
    st = str(row.get("status") or "archived")
    st_cn = {"archived": "已结档", "abandoned": "已废弃"}.get(st, st)
    amounts = _esc(row.get("amounts") or "—")
    q = " ".join(
        str(row.get(k) or "")
        for k in ("ticket_id", "acc_num", "claim", "finding", "amounts", "note")
    )
    return (
        f"<article class='case' data-q='{_esc(q)}'>"
        f"<div class='case-top'>"
        f"<div><div class='tid'>{_esc(row.get('ticket_id'))}</div>"
        f"<div class='meta'>号码 {_esc(row.get('acc_num'))}　账期 {_esc(row.get('months'))}</div></div>"
        f"<div class='amt'>{amounts}</div></div>"
        f"{gold} <span class='st'>{_esc(st_cn)}</span>"
        f"<dl>"
        f"<dt>主张</dt><dd>{_esc(row.get('claim'))}</dd>"
        f"<dt>结论</dt><dd>{_esc(row.get('finding'))}</dd>"
        f"</dl>"
        f"<div class='foot'>{_esc(row.get('note'))}　{_esc(row.get('closed'))}</div>"
        f"</article>"
    )


def _card_block(row: dict[str, Any]) -> str:
    q = f"{row.get('kind')} {row.get('name')} {row.get('body')}"
    return (
        f"<article class='kv' data-q='{_esc(q)}'>"
        f"<div class='k'><span class='kind'>{_esc(row.get('kind'))}</span> {_esc(row.get('name'))}</div>"
        f"<div class='v'>{_esc(row.get('body'))}</div></article>"
    )


def _strat_block(row: dict[str, Any]) -> str:
    q = f"{row.get('lane')} {row.get('name')} {row.get('story')}"
    return (
        f"<article class='kv' data-q='{_esc(q)}'>"
        f"<div class='k'>{_esc(row.get('lane'))}-{_esc(row.get('seq'))}　{_esc(row.get('name'))}</div>"
        f"<div class='v'>{_esc(row.get('story'))}<br>"
        f"<span class='muted'>做：{_esc(row.get('how'))}</span><br>"
        f"<span class='muted'>不做：{_esc(row.get('not_that'))}</span></div></article>"
    )


def _thread_html(cur: dict[str, Any]) -> str:
    thread = cur.get("thread") if isinstance(cur.get("thread"), list) else []
    if not thread:
        return "<p class='empty'>左边是对话。开单后会出现主张、相似旧单、出包提示。</p>"
    bits = []
    for item in thread:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "sys")
        label = {"user": "你", "agent": "取证", "sys": "系统"}.get(role, role)
        bits.append(
            f"<div class='msg { _esc(role) }'><div class='who'>{_esc(label)}</div>"
            f"<div class='bubble'>{_esc(item.get('text'))}</div></div>"
        )
    return "".join(bits)


def _run_panel() -> str:
    from .loop import load_current

    cur = load_current() or {}
    sql = str(cur.get("sql") or "")
    acc = _esc(cur.get("acc_num") or "—")
    tid = _esc(cur.get("ticket_id") or cur.get("id") or "—")
    months = _esc(",".join(cur.get("months") or []))
    claim = _esc((cur.get("claim") or "")[:180])
    mode = str(cur.get("mode") or "")
    mode_cn = "探索" if mode == "explore" else ("复用已验证碎片" if mode == "reuse" else "—")
    remind = _esc((cur.get("reminder") or "")[:220])
    raw_p = str(cur.get("process") or "idle")
    process = _esc(
        {
            "idle": "空闲",
            "active": "已开单",
            "packed": "待跑 SQL",
            "ingested": "已贴回",
            "verified": "已核对",
            "drafted": "草稿待结档",
            "archived": "已结档",
            "abandoned": "已废弃",
        }.get(raw_p, raw_p)
    )
    placeholder = "等待出包。锁定工单后这里会出现可复制的 SQL。"
    ingest = str(cur.get("ingest") or "")
    ingest_html = (
        f"<h3>贴回结果</h3><pre id='ingest-view' class='ingest'>{_esc(ingest)}</pre>"
        if ingest
        else "<h3>贴回结果</h3><pre id='ingest-view' class='ingest'></pre>"
    )
    return (
        f"<section class='run'>"
        f"<div class='run-top'><div>"
        f"<div class='tid'>要跑的 SQL</div>"
        f"<div class='meta' id='run-meta'>工单 {tid}　{process}　模式 {mode_cn}</div>"
        f"<dl class='slots' id='run-slots'>"
        f"<dt>号码</dt><dd id='slot-acc'>{acc}</dd>"
        f"<dt>月份</dt><dd id='slot-months'>{months}</dd>"
        f"<dt>主张</dt><dd id='slot-claim'>{claim}</dd>"
        f"<dt>模式</dt><dd id='slot-mode'>{mode_cn}</dd>"
        f"</dl>"
        f"<div class='claim' id='run-remind'>{remind}</div></div>"
        f"<div class='run-actions'>"
        f"<button type='button' id='copy'>一键复制 SQL</button>"
        f"<span id='copied' class='muted'></span></div></div>"
        f"<pre id='sql'>{_esc(sql or placeholder)}</pre>"
        f"{ingest_html}</section>"
    )


def render(*, live: bool = False) -> str:
    cases = _all_history()
    cards = _all_cards()
    strategies = _all_strategy()
    kinds: dict[str, list[str]] = {}
    for row in cards:
        kinds.setdefault(str(row.get("kind") or ""), []).append(_card_block(row))
    card_sections = "".join(
        f"<h3>{_esc(kind)}</h3>{''.join(blocks)}" for kind, blocks in kinds.items()
    )
    from .loop import load_current

    cur = load_current() or {}
    refresh = "" if live else '<meta http-equiv="refresh" content="4"/>'
    composer = (
        """<form id="chat" class="composer">
  <textarea id="msg" rows="2" placeholder="贴工单或提问，Enter 发送，Shift+Enter 换行"></textarea>
  <div class="composer-row">
    <p id="chat-err" class="empty"></p>
    <button type="submit">发送</button>
  </div>
</form>"""
        if live
        else ""
    )
    ingest_box = (
        """<div class="ingest-box">
  <h3>贴回 SQL 结果</h3>
  <textarea id="ingest-text" rows="6" placeholder="把堡垒机结果贴在这里，交给 AI 继续 loop"></textarea>
  <button type="button" id="ingest-btn">提交结果</button>
</div>"""
        if live
        else ""
    )
    live_js = (
        r"""
async function paint(state) {
  const box = document.getElementById('thread');
  if (box && state.thread) {
    box.innerHTML = (state.thread || []).map((item) => {
      const role = item.role || 'sys';
      const who = {user:'你', agent:'取证', sys:'系统'}[role] || role;
      const text = (item.text || '').replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
      return `<div class="msg ${role}"><div class="who">${who}</div><div class="bubble">${text}</div></div>`;
    }).join('') || '<p class="empty">在下方输入，真实调用 smolagents。</p>';
    box.scrollTop = box.scrollHeight;
  }
  const sql = document.getElementById('sql');
  const sqlEl = document.getElementById('sql');
  if (sqlEl) sqlEl.textContent = state.sql || '等待出包。锁定工单后这里会出现可复制的 SQL。';
  const ing = document.getElementById('ingest-view');
  if (ing) ing.textContent = state.ingest || '';
  const meta = document.getElementById('run-meta');
  const sl = state.slots || {};
  const acc = document.getElementById('slot-acc');
  if (acc) acc.textContent = sl.acc_num || state.acc_num || '—';
  const mo = document.getElementById('slot-months');
  if (mo) mo.textContent = (sl.months || state.months || []).join(',') || '—';
  const cl = document.getElementById('slot-claim');
  if (cl) cl.textContent = sl.claim || state.claim || '—';
  const md = document.getElementById('slot-mode');
  const mode = state.mode === 'explore' ? '探索' : (state.mode === 'reuse' ? '复用已验证碎片' : '—');
  if (md) md.textContent = mode;
  const rm = document.getElementById('run-remind');
  if (rm) rm.textContent = state.reminder || '';
  if (meta) meta.textContent = '工单 ' + (state.ticket_id || '—') + '　' + (state.process || '') + '　模式 ' + mode;
}
async function pull() {
  try {
    const r = await fetch('/api/state');
    paint(await r.json());
  } catch (e) {}
}
setInterval(pull, 2000);
pull();
const form = document.getElementById('chat');
const msgBox = document.getElementById('msg');
if (msgBox) {
  msgBox.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      form.requestSubmit();
    }
  });
}
if (form) {
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const ta = document.getElementById('msg');
    const err = document.getElementById('chat-err');
    const text = (ta.value || '').trim();
    if (!text) return;
    err.textContent = '思考中…';
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text}),
      });
      const data = await r.json();
      if (data.error) err.textContent = data.error;
      else { err.textContent = ''; ta.value = ''; }
      if (data.state) paint(data.state);
      else pull();
    } catch (e) {
      err.textContent = String(e);
    }
  });
}
const nb = document.getElementById('new-chat');
if (nb) {
  nb.addEventListener('click', async () => {
    if (!confirm('清空当前对话并开始新单？未结档的工单不会写入历史。')) return;
    const r = await fetch('/api/new', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    const data = await r.json();
    if (data.state) paint(data.state);
    else pull();
  });
}
const ib = document.getElementById('ingest-btn');
if (ib) {
  ib.addEventListener('click', async () => {
    const ta = document.getElementById('ingest-text');
    const r = await fetch('/api/ingest', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: ta.value || ''}),
    });
    const data = await r.json();
    if (data.error) alert(data.error);
    if (data.state) paint(data.state);
  });
}
"""
        if live
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>计费取证</title>
{refresh}
<style>
:root {{
  --bg:#f4f1ea; --paper:#fffcf7; --ink:#1c1917; --muted:#78716c;
  --line:#e7e0d4; --gold:#b45309; --amt:#9f1239; --chat:#efebe3;
}}
* {{ box-sizing:border-box; }}
html, body {{ height:100%; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 "Segoe UI", "PingFang SC", "Noto Sans SC", sans-serif; }}
.shell {{ display:grid; grid-template-columns:minmax(300px,34%) 1fr; height:100vh; }}
.left {{
  display:flex; flex-direction:column; height:100vh; min-height:0;
  border-right:1px solid var(--line); background:var(--chat);
}}
.left-head {{ flex:0 0 auto; padding:14px 16px 8px; }}
.left-head-row {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
button.ghost {{
  border:1px solid var(--line); background:transparent; color:var(--ink);
  padding:4px 10px; border-radius:999px; cursor:pointer; font:12px inherit; flex-shrink:0;
}}
#thread {{ flex:1 1 auto; min-height:0; overflow:auto; padding:8px 16px 12px; }}
.composer {{
  flex:0 0 auto; padding:10px 16px 14px; border-top:1px solid var(--line);
  background:var(--chat);
}}
.composer-row {{ display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:8px; }}
.composer-row .empty {{ margin:0; flex:1; }}
.right {{ overflow:auto; padding:16px 20px 40px; }}
.left h1, .right h2 {{ margin:0 0 4px; font-size:18px; }}
.sub {{ color:var(--muted); font-size:12px; margin:0; }}
.msg {{ margin:0 0 12px; }}
.who {{ font-size:11px; color:var(--muted); margin-bottom:4px; }}
.bubble {{ background:var(--paper); border:1px solid var(--line); border-radius:10px; padding:8px 10px; white-space:pre-wrap; word-break:break-word; }}
.msg.agent .bubble {{ background:#1c1917; color:#fffcf7; border-color:#1c1917; }}
.msg.sys .bubble {{ background:transparent; border-style:dashed; font-size:13px; color:var(--muted); }}
.wrap {{ max-width:none; margin:0; padding:0; }}
.tabs {{ display:flex; gap:8px; margin-bottom:14px; }}
.tabs {{ display:flex; gap:8px; margin-bottom:14px; }}
.tabs button {{
  border:1px solid var(--line); background:transparent; color:var(--ink);
  padding:6px 12px; border-radius:999px; cursor:pointer; font:inherit;
}}
.tabs button.on {{ background:#1c1917; color:#fffcf7; border-color:#1c1917; }}
#q {{
  width:100%; padding:10px 12px; margin-bottom:16px; font:inherit;
  border:1px solid var(--line); border-radius:8px; background:var(--paper);
}}
.panel {{ display:none; }}
.panel.on {{ display:block; }}
.case {{
  background:var(--paper); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px 12px; margin-bottom:12px;
}}
.case-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
.tid {{ font-size:20px; font-weight:700; letter-spacing:.02em; }}
.meta {{ color:var(--muted); font-size:13px; margin-top:2px; }}
.amt {{ font-size:22px; font-weight:700; color:var(--amt); white-space:nowrap; }}
.gold, .st {{ display:inline-block; margin-top:8px; font-size:12px; color:var(--gold); margin-right:8px; }}
.st {{ color:var(--muted); }}
dl {{ margin:12px 0 0; }}
dt {{ font-size:12px; color:var(--muted); margin-top:8px; }}
dd {{ margin:2px 0 0; }}
.foot {{ margin-top:10px; font-size:12px; color:var(--muted); }}
.kv {{ background:var(--paper); border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; margin-bottom:8px; }}
.k {{ font-weight:650; margin-bottom:4px; }}
.kind {{ font-size:11px; color:var(--muted); font-weight:500; margin-right:6px; }}
.v {{ color:#44403c; font-size:14px; }}
h3 {{ font-size:13px; color:var(--muted); font-weight:600; margin:18px 0 8px; }}
.hidden {{ display:none !important; }}
.empty {{ color:var(--muted); padding:24px 0; }}
.run {{
  background:#1c1917; color:#fffcf7; border-radius:12px; padding:16px 18px; margin-bottom:16px;
}}
.run .tid {{ color:#fffcf7; }}
.run .meta, .run .claim, .run .empty, .run .slots {{ color:#a8a29e; }}
.run .slots {{ display:grid; grid-template-columns:auto 1fr; gap:2px 12px; margin:8px 0 0; }}
.run .slots dt {{ margin:0; font-size:12px; color:#78716c; }}
.run .slots dd {{ margin:0; color:#fffcf7; }}
.run-top {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start; }}
.run-actions {{ display:flex; gap:8px; align-items:center; flex-shrink:0; }}
#copy {{
  background:#fffcf7; color:#1c1917; border:0; padding:8px 12px; border-radius:999px;
  cursor:pointer; font:inherit; font-weight:650; white-space:nowrap;
}}
pre#sql, pre.ingest {{
  margin:12px 0 0; padding:12px; overflow:auto; max-height:360px;
  background:#0c0a09; color:#e7e5e4; border-radius:8px; font:12px/1.45 ui-monospace,Consolas,monospace;
  white-space:pre;
}}
pre.ingest {{ max-height:220px; background:#292524; }}
.composer textarea, .ingest-box textarea {{
  width:100%; font:inherit; padding:8px 10px; border:1px solid var(--line);
  border-radius:8px; background:var(--paper); resize:none;
}}
.composer button, .ingest-box button {{
  padding:8px 16px; border:0; border-radius:999px;
  background:#1c1917; color:#fffcf7; cursor:pointer; font:inherit; flex-shrink:0;
}}
.ingest-box {{ margin:12px 0 18px; }}
</style>
</head>
<body>
<div class="shell">
<aside class="left">
  <div class="left-head">
    <h1>对话</h1>
    <div class="left-head-row">
      <div>
        <h1>对话</h1>
        <p class="sub">{"DeepSeek · 输入固定在底部" if live else "静态快照。实时对话请双击 be-gui.bat"}</p>
      </div>
      {('<button type="button" id="new-chat" class="ghost">新对话</button>' if live else "")}
    </div>
  </div>
  <div id="thread">{_thread_html(cur)}</div>
  {composer}
</aside>
<div class="right">
  {_run_panel()}
  {ingest_box}
  <div class="tabs">
    <button type="button" class="on" data-tab="hist">工单 {len(cases)}</button>
    <button type="button" data-tab="cards">结构卡片 {len(cards)}</button>
    <button type="button" data-tab="strat">闸门 {len(strategies)}</button>
  </div>
  <input id="q" type="search" placeholder="筛工单号、号码、香港、副卡、金额…" />
  <div id="hist" class="panel on">
    {''.join(_case_block(r) for r in cases) or '<p class="empty">还没有结案记录。</p>'}
  </div>
  <div id="cards" class="panel">
    {card_sections or '<p class="empty">没有卡片。</p>'}
  </div>
  <div id="strat" class="panel">
    {''.join(_strat_block(r) for r in strategies)}
  </div>
</div>
</div>
<script>
const q = document.getElementById('q');
document.querySelectorAll('.tabs button').forEach((btn) => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tabs button').forEach((b) => b.classList.remove('on'));
    document.querySelectorAll('.panel').forEach((p) => p.classList.remove('on'));
    btn.classList.add('on');
    document.getElementById(btn.dataset.tab).classList.add('on');
    filter();
  }});
}});
function filter() {{
  const needle = q.value.trim().toLowerCase();
  const panel = document.querySelector('.panel.on');
  panel.querySelectorAll('article').forEach((el) => {{
    const hay = (el.getAttribute('data-q') || '').toLowerCase();
    el.classList.toggle('hidden', needle && !hay.includes(needle));
  }});
}}
q.addEventListener('input', filter);
const copyBtn = document.getElementById('copy');
if (copyBtn) {{
  copyBtn.addEventListener('click', async () => {{
    const sql = document.getElementById('sql');
    const text = sql ? sql.innerText : '';
    try {{
      await navigator.clipboard.writeText(text);
    }} catch (e) {{
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); ta.remove();
    }}
    const ok = document.getElementById('copied');
    if (ok) ok.textContent = '已复制，去新建窗口粘贴执行';
  }});
}}
{live_js}
</script>
</body>
</html>
"""


def render_live() -> str:
    return render(live=True)


def write_archive(*, browse: bool = True) -> Path:
    catalog.init()
    path = managed.be_home() / "archive.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    if browse:
        webbrowser.open(path.as_uri())
    return path


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "be_gui":
        raise RuntimeError(f"unknown tool {name}")
    path = write_archive(browse=False)
    return {"schema": "be.gui.v1", "path": str(path), "note": "HTML is for the human archive, not a model dump."}
