"""The live carousel editor.

Everything it saves goes to data/overrides.json, never back to settings.yaml
-- see config.apply_overlay for why. Plain HTML and vanilla JS: this is a page
for editing four lists on a home server, not an application.
"""

from __future__ import annotations

EDITOR_CSS = """
:root { color-scheme: dark; }
body { background:#101014; color:#c8c8d0; margin:0; padding:22px 26px 80px;
       font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }
h1 { font-size:15px; letter-spacing:.14em; text-transform:uppercase; color:#fff; margin:0 0 2px; }
h2 { font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:#7f8; margin:26px 0 8px; }
p.meta { color:#6a6a78; margin:0 0 16px; }
a { color:#7cf; }
code { color:#fd8; }
.bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
select, input, textarea, button {
  background:#1a1a22; color:#dfe; border:1px solid #33333f; border-radius:3px;
  padding:5px 7px; font:12px ui-monospace,Menlo,monospace; }
input[type=number] { width:74px; }
button { cursor:pointer; }
button:hover { border-color:#5a5a70; }
button.primary { background:#1d3a2a; border-color:#2f6b4a; color:#9f9; }
button.danger  { background:#3a1d1d; border-color:#6b2f2f; color:#f99; }
button.ghost   { background:transparent; }
.row { display:grid; grid-template-columns:26px 150px 1fr 78px 70px 92px;
       gap:10px; align-items:start; padding:10px; border:1px solid #26262e;
       border-radius:4px; margin-bottom:8px; background:#15151c; }
.row.off { opacity:.42; }
.row img { image-rendering:pixelated; width:100%; background:#000;
           border:1px solid #2a2a34; display:block; }
.row textarea { width:100%; min-height:44px; resize:vertical; }
.lbl { color:#6a6a78; font-size:10px; text-transform:uppercase;
       letter-spacing:.08em; display:block; margin-bottom:3px; }
.handles { display:flex; flex-direction:column; gap:3px; }
.handles button { padding:1px 5px; line-height:1.1; }
.err { color:#f77; margin-left:8px; }
.ok  { color:#7f7; margin-left:8px; }
.hint { color:#5a5a68; font-size:11px; margin:6px 0 0; }
"""

EDITOR_JS = r"""
const TOKEN = window.__GLANCE_TOKEN__ || "";
const q = (u) => TOKEN ? u + (u.includes("?") ? "&" : "?") + "k=" + encodeURIComponent(TOKEN) : u;
const api = async (path, opts) => {
  const r = await fetch(q(path), Object.assign({headers:{"Content-Type":"application/json"}}, opts));
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};

let SCENES = [], CHANNEL = null, ENTRIES = [];

function say(msg, cls) {
  const el = document.getElementById("status");
  el.className = cls || "";
  el.textContent = msg;
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
}

function previewUrl(entry) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(entry.params || {})) p.set(k, v);
  const ref = entry.ref.includes(":") ? entry.ref : entry.ref;
  return q("/s/" + encodeURIComponent(ref) + ".png?" + p.toString() + "&_=" + Date.now());
}

function render() {
  const host = document.getElementById("entries");
  host.innerHTML = "";
  ENTRIES.forEach((e, i) => {
    const row = document.createElement("div");
    row.className = "row" + (e.enabled ? "" : " off");
    row.innerHTML = `
      <div class="handles">
        <button ${i === 0 ? "disabled" : ""} data-act="up"   data-i="${i}">&#9650;</button>
        <button ${i === ENTRIES.length-1 ? "disabled" : ""} data-act="down" data-i="${i}">&#9660;</button>
      </div>
      <div>
        <span class="lbl">scene</span>
        <select data-act="ref" data-i="${i}">
          ${SCENES.map(s => `<option value="${s}" ${s === e.ref ? "selected" : ""}>${s}</option>`).join("")}
          ${SCENES.includes(e.ref) ? "" : `<option value="${e.ref}" selected>${e.ref}</option>`}
        </select>
        <label class="hint"><input type="checkbox" data-act="enabled" data-i="${i}"
          ${e.enabled ? "checked" : ""}> enabled</label>
        <label class="hint"><input type="checkbox" data-act="takeover" data-i="${i}"
          ${e.takeover ? "checked" : ""}> takeover</label>
      </div>
      <div>
        <span class="lbl">params (json)</span>
        <textarea data-act="params" data-i="${i}">${JSON.stringify(e.params || {}, null, 0)}</textarea>
      </div>
      <div>
        <span class="lbl">dwell s</span>
        <input type="number" min="0" step="10" data-act="dwell" data-i="${i}" value="${e.dwell || 0}">
      </div>
      <div>
        <span class="lbl">&nbsp;</span>
        <button class="danger" data-act="del" data-i="${i}">remove</button>
      </div>
      <div>
        <span class="lbl">preview</span>
        <img src="${previewUrl(e)}" alt="">
      </div>`;
    host.appendChild(row);
  });
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-act]");
  if (!b || b.tagName !== "BUTTON") return;
  const i = +b.dataset.i;
  if (b.dataset.act === "up")   { [ENTRIES[i-1], ENTRIES[i]] = [ENTRIES[i], ENTRIES[i-1]]; render(); }
  if (b.dataset.act === "down") { [ENTRIES[i+1], ENTRIES[i]] = [ENTRIES[i], ENTRIES[i+1]]; render(); }
  if (b.dataset.act === "del")  { ENTRIES.splice(i, 1); render(); }
});

document.addEventListener("change", (ev) => {
  const el = ev.target.closest("[data-act]");
  if (!el || el.tagName === "BUTTON") return;
  const i = +el.dataset.i, act = el.dataset.act;
  if (act === "ref")      { ENTRIES[i].ref = el.value; render(); }
  if (act === "enabled")  { ENTRIES[i].enabled = el.checked; render(); }
  if (act === "takeover") { ENTRIES[i].takeover = el.checked; }
  if (act === "dwell")    { ENTRIES[i].dwell = +el.value || 0; }
  if (act === "params") {
    try { ENTRIES[i].params = JSON.parse(el.value || "{}"); el.style.borderColor = "#33333f"; render(); }
    catch { el.style.borderColor = "#a44"; say("params must be valid JSON", "err"); }
  }
});

async function loadChannel(name) {
  CHANNEL = name;
  const data = await api("/api/channels/" + encodeURIComponent(name));
  ENTRIES = data.entries;
  document.getElementById("overridden").textContent =
    data.overridden ? "edited (settings.yaml overridden)" : "straight from settings.yaml";
  render();
}

async function boot() {
  const meta = await api("/api/channels");
  SCENES = meta.scenes;
  const sel = document.getElementById("channel");
  sel.innerHTML = meta.channels.map(c => `<option value="${c}">${c}</option>`).join("");
  sel.onchange = () => loadChannel(sel.value);

  const car = meta.carousel;
  document.getElementById("mode").value = car.mode;
  document.getElementById("dwell").value = car.dwell;
  document.getElementById("minadv").value = car.min_advance_interval;

  document.getElementById("add").onclick = () => {
    ENTRIES.push({ref: SCENES[0], params: {}, enabled: true, takeover: false, dwell: 0});
    render();
  };
  document.getElementById("save").onclick = async () => {
    try {
      await api("/api/channels/" + encodeURIComponent(CHANNEL),
                {method: "PUT", body: JSON.stringify({entries: ENTRIES})});
      say("saved - live on the panel's next fetch", "ok");
      loadChannel(CHANNEL);
    } catch (e) { say("save failed: " + e.message, "err"); }
  };
  document.getElementById("reset").onclick = async () => {
    if (!confirm("Discard edits to '" + CHANNEL + "' and go back to settings.yaml?")) return;
    await api("/api/channels/" + encodeURIComponent(CHANNEL) + "/reset", {method: "POST"});
    say("reset to settings.yaml", "ok");
    loadChannel(CHANNEL);
  };
  document.getElementById("savecar").onclick = async () => {
    await api("/api/carousel", {method: "PUT", body: JSON.stringify({
      mode: document.getElementById("mode").value,
      dwell: +document.getElementById("dwell").value,
      min_advance_interval: +document.getElementById("minadv").value,
    })});
    say("carousel settings saved", "ok");
  };

  await loadChannel(meta.channels[0]);
}
boot().catch(e => say("failed to load: " + e.message, "err"));
"""

EDITOR_HTML = """<!doctype html><meta charset="utf-8">
<title>Glance editor</title>
<style>__CSS__</style>
<h1>Carousel editor</h1>
<p class="meta">Saves to <code>data/overrides.json</code>, never to
 <code>settings.yaml</code>. Changes are live on the panel's next fetch.
 &middot; <a href="/preview">preview</a> &middot; <a href="/api/status">status</a></p>

<div class="bar">
  <label class="lbl" style="margin:0">channel</label>
  <select id="channel"></select>
  <span id="overridden" class="hint"></span>
  <span style="flex:1"></span>
  <button id="add">add scene</button>
  <button id="reset" class="ghost">reset to file</button>
  <button id="save" class="primary">save</button>
  <span id="status"></span>
</div>

<div id="entries"></div>

<p class="hint">Order is rotation order. <b>dwell</b> holds an entry for that
 many seconds before moving on &mdash; the device decides how often it fetches,
 so dwell is the only way to control pace. 0 means advance every fetch.
 <b>takeover</b> makes an entry pre-empt the whole rotation whenever it has
 something to show.</p>

<h2>Carousel</h2>
<div class="bar">
  <label class="lbl" style="margin:0">mode</label>
  <select id="mode"><option value="advance">advance</option><option value="clock">clock</option></select>
  <label class="lbl" style="margin:0">clock dwell s</label>
  <input id="dwell" type="number" min="1">
  <label class="lbl" style="margin:0">min advance s</label>
  <input id="minadv" type="number" min="0">
  <button id="savecar" class="primary">save carousel</button>
</div>
<p class="hint"><b>advance</b> steps on each fetch (respecting dwell).
 <b>clock</b> picks purely from wall-clock time. <b>min advance</b> stops a
 double fetch burning two slots.</p>

<script>window.__GLANCE_TOKEN__ = "__TOKEN__";</script>
<script>__JS__</script>
"""


def editor_page(token: str = "") -> str:
    return (
        EDITOR_HTML
        .replace("__CSS__", EDITOR_CSS)
        .replace("__JS__", EDITOR_JS)
        .replace("__TOKEN__", token.replace('"', '\\"'))
    )
