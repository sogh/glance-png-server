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
h2 { font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:#7f8; margin:30px 0 8px; }
p.meta { color:#6a6a78; margin:0 0 16px; }
a { color:#7cf; }
code { color:#fd8; }
.bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
select, input, textarea, button {
  background:#1a1a22; color:#dfe; border:1px solid #33333f; border-radius:3px;
  padding:4px 6px; font:12px ui-monospace,Menlo,monospace; }
input[type=number] { width:66px; }
input[type=text]   { width:100%; box-sizing:border-box; }
select             { max-width:150px; }
button { cursor:pointer; }
button:hover { border-color:#5a5a70; }
button.primary { background:#1d3a2a; border-color:#2f6b4a; color:#9f9; }
button.danger  { background:#3a1d1d; border-color:#6b2f2f; color:#f99; }
button.ghost   { background:transparent; }

.card { border:1px solid #26262e; border-radius:5px; margin-bottom:10px;
        background:#15151c; overflow:hidden; }
.card.off { opacity:.45; }
.head { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
        padding:8px 10px; background:#1a1a22; border-bottom:1px solid #26262e; }
.head .scene { font-weight:bold; color:#9df; }
.head .desc { color:#6a6a78; font-size:11px; }
.head .inline { display:flex; gap:4px; align-items:center; color:#8a8a98; font-size:11px; }
.handles { display:flex; flex-direction:column; gap:2px; }
.handles button { padding:0 5px; line-height:1.2; font-size:9px; }

.body { display:grid; grid-template-columns:1fr 230px; gap:14px; padding:10px; }
.params { display:grid; grid-template-columns:repeat(auto-fill,minmax(135px,1fr)); gap:8px 10px; align-content:start; }
.param { min-width:0; }
.side img { image-rendering:pixelated; width:100%; background:#000;
            border:1px solid #2a2a34; display:block; margin-bottom:6px; }
.side textarea { width:100%; box-sizing:border-box; }
details summary { cursor:pointer; color:#6a6a78; }

.artrow { display:grid; grid-template-columns:160px 120px 1fr 92px; gap:12px;
          align-items:start; padding:9px; border:1px solid #26262e;
          border-radius:4px; margin-bottom:8px; background:#15151c; }
.artrow img { image-rendering:pixelated; width:100%; background:#000; border:1px solid #2a2a34; }

.remrow { display:grid; grid-template-columns:1fr 132px 58px 104px 52px 82px; gap:12px;
           align-items:start; padding:9px; border:1px solid #26262e;
           border-radius:4px; margin-bottom:8px; background:#15151c; }
.remrow.done { opacity:.45; }
.remrow input[type=date] { width:100%; box-sizing:border-box; }
.remrow .overdue { color:#f77; }

.lbl { color:#6a6a78; font-size:10px; text-transform:uppercase;
       letter-spacing:.07em; display:block; margin-bottom:2px; }
.err { color:#f77; } .ok { color:#7f7; }
.hint { color:#5a5a68; font-size:11px; margin:5px 0 0; }
"""


EDITOR_JS = r"""
const TOKEN = window.__GLANCE_TOKEN__ || "";
const q = (u) => TOKEN ? u + (u.includes("?") ? "&" : "?") + "k=" + encodeURIComponent(TOKEN) : u;
const api = async (path, opts) => {
  const r = await fetch(q(path), Object.assign({headers:{"Content-Type":"application/json"}}, opts));
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
};
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

let CATALOGUE = {}, SCENES = [], CHANNEL = null, ENTRIES = [];

function say(msg, cls) {
  const el = document.getElementById("status");
  el.className = cls || "";
  el.innerHTML = msg;
  if (msg && cls !== "err") setTimeout(() => { if (el.innerHTML === msg) el.innerHTML = ""; }, 5000);
}

function schemaFor(ref) {
  const base = ref.includes(":") ? ref.split(":")[0] : ref;
  return (CATALOGUE[base] || {}).params || [];
}

function previewUrl(entry) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(entry.params || {})) p.set(k, v);
  p.set("brightness", "1");
  p.set("_", Date.now());
  return q("/s/" + encodeURIComponent(entry.ref) + ".png?" + p.toString());
}

// One control per declared parameter, so the valid values are visible instead
// of being something you have to know.
function field(param, value, i) {
  const id = `p-${i}-${param.name}`;
  const set = `data-param="${param.name}" data-i="${i}"`;
  const title = param.help ? ` title="${esc(param.help)}"` : "";
  let control;

  if (param.type === "bool") {
    const on = value === undefined ? param.default : value;
    control = `<input type="checkbox" id="${id}" ${set} ${on ? "checked" : ""}>`;
  } else if (param.options && param.options.length) {
    const opts = ['<option value=""></option>'].concat(
      param.options.map(o =>
        `<option value="${esc(o)}" ${String(value) === String(o) ? "selected" : ""}>${esc(o)}</option>`));
    control = `<select id="${id}" ${set}>${opts.join("")}</select>`;
  } else if (param.type === "number") {
    const bounds = `${param.min != null ? ` min="${param.min}"` : ""}${param.max != null ? ` max="${param.max}"` : ""}`;
    control = `<input type="number" id="${id}" ${set}${bounds} value="${value ?? ""}"
                 placeholder="${param.default ?? ""}">`;
  } else {
    control = `<input type="text" id="${id}" ${set} value="${esc(value ?? "")}"
                 placeholder="${esc(param.default ?? "")}">`;
  }
  return `<div class="param"${title}><label class="lbl" for="${id}">${esc(param.name)}</label>${control}</div>`;
}

function render() {
  const host = document.getElementById("entries");
  host.innerHTML = "";
  ENTRIES.forEach((e, i) => {
    const schema = schemaFor(e.ref);
    const known = new Set(schema.map(p => p.name));
    const extra = Object.fromEntries(
      Object.entries(e.params || {}).filter(([k]) => !known.has(k)));

    const card = document.createElement("div");
    card.className = "card" + (e.enabled ? "" : " off");
    card.innerHTML = `
      <div class="head">
        <div class="handles">
          <button ${i === 0 ? "disabled" : ""} data-act="up" data-i="${i}">&#9650;</button>
          <button ${i === ENTRIES.length-1 ? "disabled" : ""} data-act="down" data-i="${i}">&#9660;</button>
        </div>
        <select data-act="ref" data-i="${i}" class="scene">
          ${SCENES.map(s => `<option value="${s}" ${s === e.ref ? "selected" : ""}>${s}</option>`).join("")}
          ${SCENES.includes(e.ref) ? "" : `<option value="${esc(e.ref)}" selected>${esc(e.ref)}</option>`}
        </select>
        <span class="desc">${esc((CATALOGUE[e.ref.split(":")[0]] || {}).description || "")}</span>
        <label class="inline"><input type="checkbox" data-act="enabled" data-i="${i}"
          ${e.enabled ? "checked" : ""}> enabled</label>
        <label class="inline" title="Pre-empt the whole rotation while this has something to show">
          <input type="checkbox" data-act="takeover" data-i="${i}" ${e.takeover ? "checked" : ""}> takeover</label>
        <label class="inline" title="Hold this entry for this many seconds before moving on. 0 advances every fetch.">
          dwell <input type="number" min="0" step="10" data-act="dwell" data-i="${i}" value="${e.dwell || 0}"></label>
        <span style="flex:1"></span>
        <button class="danger" data-act="del" data-i="${i}">remove</button>
      </div>
      <div class="body">
        <div class="params">${schema.map(p => field(p, (e.params || {})[p.name], i)).join("")}</div>
        <div class="side">
          <span class="lbl">preview</span>
          <img src="${previewUrl(e)}" alt="">
          <details ${Object.keys(extra).length ? "open" : ""}>
            <summary class="lbl">when / advanced</summary>
            <label class="lbl">when (json)</label>
            <textarea data-act="when" data-i="${i}" rows="2">${esc(JSON.stringify(e.when || {}))}</textarea>
            <div class="hint">e.g. {"months":[10,11,12]} or {"hours":{"from":7,"to":22}}</div>
            ${Object.keys(extra).length ? `<div class="hint" style="color:#d94">
              unrecognised params: ${esc(Object.keys(extra).join(", "))}</div>` : ""}
          </details>
        </div>
      </div>`;
    host.appendChild(card);
  });
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-act]");
  if (!b) return;
  const i = +b.dataset.i;
  if (b.dataset.act === "up")   { [ENTRIES[i-1], ENTRIES[i]] = [ENTRIES[i], ENTRIES[i-1]]; render(); }
  if (b.dataset.act === "down") { [ENTRIES[i+1], ENTRIES[i]] = [ENTRIES[i], ENTRIES[i+1]]; render(); }
  if (b.dataset.act === "del")  { ENTRIES.splice(i, 1); render(); }
});

function onParamChange(el) {
  const i = +el.dataset.i, name = el.dataset.param;
  const schema = schemaFor(ENTRIES[i].ref).find(p => p.name === name) || {};
  ENTRIES[i].params = ENTRIES[i].params || {};
  let value;
  if (schema.type === "bool") value = el.checked;
  else if (schema.type === "number") value = el.value === "" ? undefined : Number(el.value);
  else value = el.value === "" ? undefined : el.value;

  // Only keep what differs from the default, so the overlay stays a short
  // list of decisions rather than a dump of every knob.
  if (value === undefined || value === schema.default) delete ENTRIES[i].params[name];
  else ENTRIES[i].params[name] = value;
  render();
}

document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (el.dataset.param !== undefined) return onParamChange(el);
  if (el.dataset.act === undefined || el.tagName === "BUTTON") return;
  const i = +el.dataset.i;
  if (el.dataset.act === "ref")      { ENTRIES[i].ref = el.value; ENTRIES[i].params = {}; render(); }
  if (el.dataset.act === "enabled")  { ENTRIES[i].enabled = el.checked; render(); }
  if (el.dataset.act === "takeover") { ENTRIES[i].takeover = el.checked; }
  if (el.dataset.act === "dwell")    { ENTRIES[i].dwell = +el.value || 0; }
  if (el.dataset.act === "when") {
    try { ENTRIES[i].when = JSON.parse(el.value || "{}"); el.style.borderColor = "#33333f"; }
    catch { el.style.borderColor = "#a44"; say("when must be valid JSON", "err"); }
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

async function renderReminders() {
  const data = await api("/api/reminders");
  const host = document.getElementById("remlist");
  if (!data.items.length) { host.innerHTML = "<p class='hint'>Nothing yet.</p>"; return; }
  const today = new Date().toISOString().slice(0, 10);
  host.innerHTML = data.items.map(r => {
    const late = r.due && !r.done && r.due < today;
    return `
    <div class="remrow${r.done ? " done" : ""}">
      <div><span class="lbl">text</span>
        <input type="text" value="${esc(r.text)}" maxlength="${data.limits.text}"
               data-rem="${esc(r.id)}" data-field="text"></div>
      <div><span class="lbl${late ? " overdue" : ""}">${late ? "due &mdash; overdue" : "due"}</span>
        <input type="date" value="${esc(r.due)}" data-rem="${esc(r.id)}" data-field="due"></div>
      <div><span class="lbl">pri</span>
        <input type="number" min="1" max="5" value="${r.priority}"
               data-rem="${esc(r.id)}" data-field="priority"></div>
      <div><span class="lbl">tag</span>
        <input type="text" value="${esc(r.tag)}" maxlength="${data.limits.tag}"
               data-rem="${esc(r.id)}" data-field="tag"></div>
      <div><span class="lbl">done</span>
        <input type="checkbox" ${r.done ? "checked" : ""}
               data-rem="${esc(r.id)}" data-field="done"></div>
      <div><span class="lbl">&nbsp;</span>
        <button class="danger" data-remdel="${esc(r.id)}">delete</button></div>
    </div>`;
  }).join("");
}

document.addEventListener("change", async (ev) => {
  const el = ev.target.closest("[data-rem]");
  if (!el) return;
  const field = el.dataset.field;
  const value = field === "done" ? el.checked
              : field === "priority" ? Number(el.value)
              : el.value;
  try {
    await api("/api/reminders/" + encodeURIComponent(el.dataset.rem),
              {method: "PUT", body: JSON.stringify({[field]: value})});
    say("reminder saved", "ok");
    // done and due change how the row is drawn, so redraw; a text edit would
    // lose the caret for no reason.
    if (field === "done" || field === "due") renderReminders();
  } catch (e) {
    say(e.message, "err");
    renderReminders();          // put the refused value back to what is stored
  }
});

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-remdel]");
  if (!b) return;
  const row = b.closest(".remrow").querySelector("[data-field=text]");
  if (!confirm("Delete " + (row ? row.value : "this reminder") + "?")) return;
  try {
    await api("/api/reminders/" + encodeURIComponent(b.dataset.remdel), {method: "DELETE"});
    renderReminders();
  } catch (e) { say(e.message, "err"); }
});

async function renderArt() {
  const data = await api("/api/art");
  const host = document.getElementById("artlist");
  if (!data.files.length) { host.innerHTML = "<p class='hint'>Nothing yet.</p>"; return; }
  host.innerHTML = data.files.map(f => `
    <div class="artrow">
      <div><span class="lbl">name</span><code>static:${esc(f.name)}</code></div>
      <div><span class="lbl">size</span>${f.width}&times;${f.height}
        ${f.fits ? "" : `<div class="hint" style="color:#d94">not ${data.panel.width}&times;${data.panel.height}</div>`}</div>
      <div><span class="lbl">preview</span>
        <img src="${q("/s/static:" + encodeURIComponent(f.name) + ".png?brightness=1&_=" + Date.now())}"></div>
      <div><span class="lbl">&nbsp;</span><button class="danger" data-art="${esc(f.name)}">delete</button></div>
    </div>`).join("");
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-art]");
  if (!b) return;
  if (!confirm("Delete " + b.dataset.art + "?")) return;
  await api("/api/art/" + encodeURIComponent(b.dataset.art), {method: "DELETE"});
  renderArt();
});

async function boot() {
  const meta = await api("/api/channels");
  SCENES = meta.scenes;
  CATALOGUE = Object.fromEntries(meta.catalogue.map(s => [s.id, s]));

  const sel = document.getElementById("channel");
  sel.innerHTML = meta.channels.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  sel.onchange = () => loadChannel(sel.value);

  document.getElementById("mode").value = meta.carousel.mode;
  document.getElementById("dwell").value = meta.carousel.dwell;
  document.getElementById("minadv").value = meta.carousel.min_advance_interval;

  document.getElementById("add").onclick = () => {
    ENTRIES.push({ref: SCENES[0], params: {}, enabled: true, takeover: false, dwell: 0, when: {}});
    render();
  };
  document.getElementById("save").onclick = async () => {
    try {
      const out = await api("/api/channels/" + encodeURIComponent(CHANNEL),
                            {method: "PUT", body: JSON.stringify({entries: ENTRIES})});
      if (out.warnings && out.warnings.length) {
        say("saved, but: <br>" + out.warnings.map(esc).join("<br>"), "err");
      } else {
        say("saved - live on the panel's next fetch", "ok");
      }
      loadChannel(CHANNEL);
    } catch (e) { say("save failed: " + esc(e.message), "err"); }
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
  document.getElementById("remadd").onclick = async () => {
    const text = document.getElementById("remtext");
    const due = document.getElementById("remdue");
    const pri = document.getElementById("rempri");
    const tag = document.getElementById("remtag");
    const el = document.getElementById("remstatus");
    try {
      await api("/api/reminders", {method: "POST", body: JSON.stringify({
        text: text.value, due: due.value,
        priority: Number(pri.value), tag: tag.value,
      })});
      text.value = ""; due.value = ""; tag.value = ""; pri.value = 3;
      el.className = "ok"; el.textContent = "added";
      renderReminders();
    } catch (e) { el.className = "err"; el.textContent = e.message; }
  };
  document.getElementById("remtext").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") document.getElementById("remadd").click();
  });

  document.getElementById("artupload").onclick = async () => {
    const input = document.getElementById("artfile");
    const el = document.getElementById("artstatus");
    if (!input.files.length) { el.className = "err"; el.textContent = "pick a file first"; return; }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const r = await fetch(q("/api/art"), {method: "POST", body});
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || "upload failed");
      el.className = "ok";
      el.textContent = `saved ${out.saved.filename} (${out.saved.width}x${out.saved.height})`;
      input.value = "";
      renderArt();
    } catch (e) { el.className = "err"; el.textContent = e.message; }
  };

  await loadChannel(meta.channels[0]);
  await renderReminders();
  await renderArt();
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

<h2>Reminders</h2>
<div class="bar">
  <input type="text" id="remtext" placeholder="Something to remember" maxlength="120" style="flex:1;min-width:200px">
  <input type="date" id="remdue">
  <label class="lbl" style="margin:0">pri</label>
  <input type="number" id="rempri" min="1" max="5" value="3">
  <input type="text" id="remtag" placeholder="tag" maxlength="32" style="width:90px;flex:none">
  <button id="remadd" class="primary">add</button>
  <span id="remstatus"></span>
</div>
<p class="hint">Rows live in <code>data/reminders.json</code> and reach the panel
 at the next refresh &mdash; no redeploy. Order is worked out for you: overdue
 first, then by date, then priority, so <b>pri</b> is the only lever (1 is
 highest). Ticking <b>done</b> takes a row off the panel but keeps it here.
 Edits save as you leave each field.</p>
<div id="remlist"></div>

<h2>Artwork</h2>
<div class="bar">
  <input type="file" id="artfile" accept="image/png,image/gif,image/bmp,image/webp">
  <button id="artupload" class="primary">upload</button>
  <span id="artstatus"></span>
</div>
<p class="hint">Files land in <code>assets/static/</code> and are usable
 immediately as <code>static:&lt;name&gt;</code> &mdash; no redeploy. Export at
 the panel's exact size; anything else is scaled nearest-neighbour, which is
 honest but blocky.</p>
<div id="artlist"></div>

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
