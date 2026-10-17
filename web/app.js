const providersEl = document.getElementById("providers-list");
const providersStatus = document.getElementById("providers-status");
const settingsStatus = document.getElementById("settings-status");
const statusLine = document.getElementById("status-line");
const chatLog = document.getElementById("chat-log");
const agentLog = document.getElementById("agent-log");
const consoleState = document.getElementById("console-state");
const toolsList = document.getElementById("tools-list");
const toolParams = document.getElementById("tool-params");
const toolConfirm = document.getElementById("tool-confirm");
const toolResult = document.getElementById("tool-result");
const toolRun = document.getElementById("tool-run");
const toolRunnerName = document.getElementById("tool-runner-name");
const checklistEl = document.getElementById("setup-checklist");
const serviceKeysEl = document.getElementById("service-keys-list");
const enginesEl = document.getElementById("engines-list");
const enginesStatus = document.getElementById("engines-status");
const ondeviceInfoEl = document.getElementById("ondevice-info");
const ondeviceListEl = document.getElementById("ondevice-list");
const ondeviceStatusEl = document.getElementById("ondevice-status");

let selectedTool = null;
let stream = null; // active EventSource

/* data for the setup checklist (loaded by the fetches below) */
let statusData = null;
let providersData = [];
let serviceKeysData = [];
let enginesData = null;
let ondeviceData = null;
let odPollTimer = null;

/* ---------------------------------------------------------------- tabs */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
  });
});

/* -------------------------------------------------------------- status */
async function loadStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    statusData = s;
    const tts = s.voice && s.voice.tts && s.voice.tts.available ? "tts" : "no-tts";
    const stt = s.voice && s.voice.stt && s.voice.stt.available ? "stt" : "no-stt";
    statusLine.textContent = `${s.tools} tools - ${s.has_provider ? "AI ready" : "offline"} - ${tts} - ${stt}`;
  } catch {
    statusLine.textContent = "offline";
  }
  renderSetup();
}

/* --------------------------------------------------------------- agent */
function setConsoleState(text, cls) {
  consoleState.textContent = text;
  consoleState.className = "console-state" + (cls ? " " + cls : "");
}

function consoleLine(kind, text, meta) {
  const line = document.createElement("div");
  line.className = `cline ${kind}`;
  const tag = document.createElement("span");
  tag.className = "ctag";
  tag.textContent = kind;
  const body = document.createElement("span");
  body.className = "cbody";
  body.textContent = text;
  line.append(tag, body);
  if (meta) {
    const m = document.createElement("span");
    m.className = "cmeta";
    m.textContent = meta;
    line.appendChild(m);
  }
  agentLog.appendChild(line);
  agentLog.scrollTop = agentLog.scrollHeight;
}

function pretty(value) {
  try {
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function truncate(text, n) {
  text = text == null ? "" : String(text);
  return text.length > n ? text.slice(0, n) + "…" : text;
}

function addChat(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function attachTrace(bubble, steps) {
  if (!steps.length) return;
  const details = document.createElement("details");
  details.className = "trace";
  const summary = document.createElement("summary");
  summary.textContent = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  details.appendChild(summary);
  const list = document.createElement("div");
  list.className = "trace-steps";
  for (const s of steps) {
    const row = document.createElement("div");
    row.className = "trace-step" + (s.success ? "" : " failed");
    row.textContent = `${s.tool}(${truncate(pretty(s.args), 80)}) → ${
      s.success ? truncate(pretty(s.result), 120) : s.error
    }`;
    list.appendChild(row);
  }
  details.appendChild(list);
  bubble.appendChild(details);
}

function finishStream() {
  if (stream) {
    stream.close();
    stream = null;
  }
  setConsoleState("done", "ok");
}

function runAgent(message) {
  const mode = document.getElementById("chat-mode").value;
  if (!message) return;
  if (stream) stream.close();

  addChat("user", message);
  consoleLine("user", message);
  setConsoleState("running", "busy");

  const bubble = addChat("assistant", "…");
  const steps = [];
  let gotFinal = false;
  let sawAny = false;

  const url =
    "/api/agent/stream?message=" +
    encodeURIComponent(message) +
    "&mode=" +
    encodeURIComponent(mode);

  stream = new EventSource(url);

  stream.onmessage = (evt) => {
    sawAny = true;
    let ev;
    try {
      ev = JSON.parse(evt.data);
    } catch {
      return;
    }
    switch (ev.type) {
      case "start":
        consoleLine("start", `session ${ev.session || "?"} · mode ${ev.mode || "auto"}`);
        break;
      case "thought":
        consoleLine("thought", ev.text || "");
        break;
      case "confirmation":
        consoleLine("confirm", `${ev.tool} needs confirmation`, (ev.permissions || []).join(", "));
        break;
      case "tool_call":
        consoleLine("call", `${ev.tool}(${truncate(pretty(ev.args), 100)})`);
        break;
      case "tool_result": {
        const step = {
          tool: ev.tool,
          args: (steps[steps.length - 1] && steps[steps.length - 1].args) || {},
          success: ev.success,
          result: ev.result,
          error: ev.error,
        };
        steps.push(step);
        const tag = ev.needs_confirmation
          ? "needs confirmation"
          : ev.success
          ? "ok"
          : "error";
        consoleLine(
          "result",
          `${ev.tool} → ${tag}${ev.error ? ": " + ev.error : ""}`,
          ev.duration_ms != null ? `${ev.duration_ms} ms` : ""
        );
        break;
      }
      case "message":
        gotFinal = true;
        bubble.textContent = ev.text || "(no response)";
        if (ev.provider) bubble.dataset.provider = ev.provider;
        attachTrace(bubble, steps);
        consoleLine("reply", truncate(ev.text, 200), ev.provider || "");
        break;
      case "error":
        consoleLine("error", ev.error || "unknown error");
        if (!gotFinal) bubble.textContent = "Error: " + (ev.error || "unknown");
        break;
      case "done":
        finishStream();
        break;
      default:
        break;
    }
  };

  stream.onerror = () => {
    // If the stream failed before producing anything, fall back to the
    // non-streaming endpoint so the user still gets an answer.
    if (!sawAny && !gotFinal) {
      stream.close();
      stream = null;
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, mode }),
      })
        .then((r) => r.json())
        .then((body) => {
          bubble.textContent = body.text || "(no response)";
          if (body.provider) bubble.dataset.provider = body.provider;
          consoleLine("reply", truncate(body.text, 200), body.provider || "");
          setConsoleState("done", "ok");
        })
        .catch((err) => {
          bubble.textContent = `Error: ${err.message}`;
          setConsoleState("error", "err");
        });
    } else {
      finishStream();
    }
  };
}

/* ---------------------------------------------------------------- chat */
function sendChat() {
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  runAgent(message);
}

function sendConsole() {
  const input = document.getElementById("console-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  runAgent(message);
}

document.getElementById("chat-send").addEventListener("click", sendChat);
document.getElementById("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});
document.getElementById("console-send").addEventListener("click", sendConsole);
document.getElementById("console-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendConsole();
});
document.getElementById("console-clear").addEventListener("click", () => {
  agentLog.innerHTML = "";
  setConsoleState("idle");
});

/* --------------------------------------------------------------- tools */
async function loadTools() {
  try {
    const data = await (await fetch("/api/tools")).json();
    toolsList.innerHTML = "";
    for (const t of data.tools) {
      const item = document.createElement("div");
      item.className = "tool-item";
      item.dataset.name = t.name;
      const name = document.createElement("strong");
      name.textContent = t.name;
      const desc = document.createElement("span");
      desc.className = "tool-desc";
      desc.textContent = t.description || "";
      const perms = document.createElement("span");
      perms.className = "tool-perms";
      perms.textContent = (t.permissions || []).join(", ") || "no permissions";
      item.append(name, desc, perms);
      item.addEventListener("click", () => selectTool(t));
      toolsList.appendChild(item);
    }
  } catch {
    toolsList.textContent = "Could not load tools.";
  }
}

function selectTool(t) {
  selectedTool = t;
  toolRunnerName.textContent = t.name;
  document.querySelectorAll(".tool-item").forEach((el) => {
    el.classList.toggle("selected", el.dataset.name === t.name);
  });
  toolResult.textContent = "";
  toolRun.disabled = false;
}

async function runTool() {
  if (!selectedTool) return;
  let params = {};
  const raw = toolParams.value.trim();
  if (raw) {
    try {
      params = JSON.parse(raw);
    } catch (err) {
      toolResult.textContent = `Invalid JSON: ${err.message}`;
      return;
    }
  }
  toolResult.textContent = "Running...";
  try {
    const res = await fetch(`/api/tools/${encodeURIComponent(selectedTool.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params, confirm: toolConfirm.checked }),
    });
    const body = await res.json();
    toolResult.textContent = JSON.stringify(body, null, 2);
  } catch (err) {
    toolResult.textContent = `Error: ${err.message}`;
  }
}

toolRun.addEventListener("click", runTool);

/* ------------------------------------------------------------ providers */
function badge(state) {
  const b = document.createElement("span");
  b.className = "pbadge";
  b.dataset.role = "badge";
  if (state === "ready") b.classList.add("pok");
  else if (state === "error") b.classList.add("pbad");
  else if (state === "off") b.classList.add("poff");
  b.textContent =
    state === "ready" ? "READY" : state === "error" ? "ERROR" : state === "off" ? "OFF" : "UNKNOWN";
  return b;
}

function setBadge(card, state, text) {
  const b = card.querySelector('[data-role="badge"]');
  if (!b) return;
  b.className = "pbadge " + (state === "ready" ? "pok" : state === "error" ? "pbad" : state === "off" ? "poff" : "");
  b.textContent = text || (state === "ready" ? "READY" : state === "error" ? "ERROR" : state === "off" ? "OFF" : "UNKNOWN");
}

function renderProvider(p) {
  const card = document.createElement("div");
  card.className = "pcard";
  card.dataset.name = p.name;
  const off = p.enabled === false;

  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = p.label || p.name;
  const b = badge(off ? "off" : p.ready ? "ready" : p.error ? "error" : "unknown");
  const toggle = document.createElement("button");
  toggle.className = "ptoggle";
  toggle.textContent = off ? "TURN ON" : "TURN OFF";
  toggle.addEventListener("click", async () => {
    await fetch(`/api/providers/${p.name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: off }),
    });
    loadProviders();
  });
  head.append(title, b, toggle);
  card.appendChild(head);

  const mkRow = (labelText, role, value, placeholder, type) => {
    const row = document.createElement("label");
    row.textContent = labelText;
    const input = document.createElement("input");
    input.type = type || "text";
    input.dataset.role = role;
    if (type === "password") input.autocomplete = "off";
    if (value != null) input.value = value;
    if (placeholder) input.placeholder = placeholder;
    row.appendChild(input);
    card.appendChild(row);
  };

  mkRow("API key", "key", "", p.key_set ? `saved (${p.key_hint}) - type to replace` : "paste key", "password");
  mkRow("Model", "model", p.model || "", "");
  if (p.name === "ollama") mkRow("URL", "url", p.url || "", "");

  const actions = document.createElement("div");
  actions.className = "form-actions";
  const save = document.createElement("button");
  save.textContent = "SAVE";
  const test = document.createElement("button");
  test.textContent = "TEST";
  actions.append(save, test);
  if (p.name !== "ollama") {
    const clear = document.createElement("button");
    clear.textContent = "CLEAR KEY";
    clear.addEventListener("click", () => saveProvider(card, true));
    actions.appendChild(clear);
  }
  card.appendChild(actions);

  const note = document.createElement("div");
  note.className = "pnote";
  note.dataset.role = "note";
  card.appendChild(note);

  save.addEventListener("click", () => saveProvider(card, false));
  test.addEventListener("click", () => testProvider(card));
  return card;
}

function payload(card) {
  const get = (role) => card.querySelector(`[data-role="${role}"]`);
  const out = {};
  const key = get("key");
  if (key && key.value.trim()) out.api_key = key.value.trim();
  const model = get("model");
  if (model) out.model = model.value;
  const url = get("url");
  if (url) out.url = url.value;
  return out;
}

async function saveProvider(card, clear) {
  const name = card.dataset.name;
  const note = card.querySelector('[data-role="note"]');
  note.textContent = clear ? "Clearing..." : "Saving...";
  const body = clear ? { clear_key: true } : payload(card);
  try {
    const res = await fetch(`/api/providers/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error || "failed");
    note.textContent = clear ? "Key cleared." : "Saved.";
    const key = card.querySelector('[data-role="key"]');
    if (key) key.value = "";
    loadProviders();
  } catch (err) {
    note.textContent = `Failed: ${err.message}`;
  }
}

async function testProvider(card) {
  const note = card.querySelector('[data-role="note"]');
  const name = card.dataset.name;
  note.textContent = "Testing...";
  setBadge(card, "unknown", "...");
  try {
    const res = await fetch(`/api/providers/${name}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload(card)),
    });
    const body = await res.json();
    if (body.ready) {
      setBadge(card, "ready");
      note.textContent = `OK - ${body.model} - ${body.latency_ms} ms`;
    } else {
      setBadge(card, "error");
      note.textContent = body.error || "not ready";
    }
  } catch (err) {
    setBadge(card, "error");
    note.textContent = err.message;
  }
}

async function loadProviders() {
  try {
    const data = await (await fetch("/api/providers")).json();
    providersData = data.providers || [];
    providersEl.innerHTML = "";
    for (const p of data.providers) providersEl.appendChild(renderProvider(p));
  } catch {
    providersEl.textContent = "Could not load providers.";
  }
  renderSetup();
}

document.getElementById("test-all-providers").addEventListener("click", async () => {
  providersStatus.textContent = "Testing all providers...";
  try {
    const data = await (await fetch("/api/providers/test", { method: "POST" })).json();
    let ready = 0;
    for (const r of data.results || []) {
      const card = providersEl.querySelector(`[data-name="${r.provider}"]`);
      if (card) {
        setBadge(card, r.ready ? "ready" : "error");
        const note = card.querySelector('[data-role="note"]');
        if (note) note.textContent = r.ready ? `OK - ${r.model} - ${r.latency_ms} ms` : r.error || "not ready";
      }
      if (r.ready) ready += 1;
    }
    providersStatus.textContent = `${ready} of ${(data.results || []).length} providers ready.`;
  } catch (err) {
    providersStatus.textContent = `Test failed: ${err.message}`;
  }
});

/* ----------------------------------------------------- setup checklist */
function setupItem(ok, text, hint, target) {
  const li = document.createElement("li");
  li.className = "ck-item " + (ok ? "ok" : "todo");
  const mark = document.createElement("span");
  mark.className = "ck-mark";
  mark.textContent = ok ? "✓" : "○";
  const body = document.createElement("div");
  body.className = "ck-body";
  const strong = document.createElement("strong");
  strong.textContent = text;
  const small = document.createElement("small");
  small.textContent = hint;
  body.append(strong, small);
  li.append(mark, body);
  if (!ok && target) {
    li.classList.add("clickable");
    li.addEventListener("click", () => {
      const el = document.querySelector(target);
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        try { el.focus({ preventScroll: true }); } catch { el.focus(); }
      }
    });
  }
  checklistEl.appendChild(li);
}

function renderSetup() {
  if (!checklistEl) return;
  checklistEl.innerHTML = "";

  const chatOk = !!(statusData && statusData.has_provider);
  setupItem(
    chatOk,
    "Chat provider",
    chatOk
      ? "configured - Jarvis can answer with AI"
      : "Add a key under Chat models (Groq / OpenRouter / Gemini) or configure Ollama.",
    "#providers-list input"
  );

  const hf = serviceKeysData.find((k) => k.name === "hf") || {};
  setupItem(
    !!hf.key_set,
    "Hugging Face token",
    hf.key_set ? `saved (${hf.key_hint})` : "Paste a token - image generation and model downloads.",
    '[data-key-card="hf"] input'
  );

  const pv = serviceKeysData.find((k) => k.name === "picovoice") || {};
  setupItem(
    !!pv.key_set,
    "Picovoice access key",
    pv.key_set ? `saved (${pv.key_hint})` : "Paste your access key - wake-word detection.",
    '[data-key-card="picovoice"] input'
  );

  const e = enginesData && enginesData.engines;
  if (e) {
    const allDefault =
      e.llm.value === e.llm.default &&
      e.stt.value === e.stt.default &&
      e.image.value === e.image.default;
    setupItem(
      true,
      "Engine choices",
      `chat ${e.llm.value} - voice ${e.stt.value} - image ${e.image.value}` +
        (allDefault ? " (defaults)" : ""),
      null
    );
  }

  const od = ondeviceData;
  if (od) {
    const supported = !!(od.device && od.device.supported);
    const forced = od.engine_mode === "on_device";
    if (supported || forced) {
      setupItem(
        !!od.ready,
        "Offline chat (on-device)",
        od.ready
          ? `${od.loaded} loaded - private, offline answers`
          : forced
            ? "Engine is on-device but no model is loaded - download one below."
            : "Optional: download a model below for private offline chat.",
        "#ondevice"
      );
    }
  }
}

/* ---------------------------------------------------- service API keys */
function renderServiceKey(k) {
  const card = document.createElement("div");
  card.className = "pcard";
  card.dataset.keyCard = k.name;

  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = k.label;
  const b = document.createElement("span");
  b.className = "pbadge" + (k.key_set ? " pok" : "");
  b.textContent = k.key_set ? "SET" : "NOT SET";
  head.append(title, b);
  card.appendChild(head);

  const note = document.createElement("div");
  note.className = "pnote";
  note.textContent = (k.hint || "") + (k.used_for ? ` - ${k.used_for}` : "");
  card.appendChild(note);

  const row = document.createElement("label");
  row.textContent = "API key";
  const input = document.createElement("input");
  input.type = "password";
  input.autocomplete = "off";
  input.dataset.role = "key";
  input.placeholder = k.key_set ? `saved (${k.key_hint}) - type to replace` : "paste key";
  row.appendChild(input);
  card.appendChild(row);

  const actions = document.createElement("div");
  actions.className = "form-actions";
  const save = document.createElement("button");
  save.textContent = "SAVE";
  const clear = document.createElement("button");
  clear.textContent = "CLEAR";
  actions.append(save, clear);
  card.appendChild(actions);

  const msg = document.createElement("div");
  msg.className = "pnote";
  msg.dataset.role = "note";
  card.appendChild(msg);

  save.addEventListener("click", () => saveServiceKey(card, false));
  clear.addEventListener("click", () => saveServiceKey(card, true));
  return card;
}

async function loadServiceKeys() {
  try {
    const data = await (await fetch("/api/keys")).json();
    serviceKeysData = data.keys || [];
    serviceKeysEl.innerHTML = "";
    for (const k of serviceKeysData) serviceKeysEl.appendChild(renderServiceKey(k));
  } catch {
    serviceKeysEl.textContent = "Could not load service keys.";
  }
  renderSetup();
}

async function saveServiceKey(card, clear) {
  const name = card.dataset.keyCard;
  const note = card.querySelector('[data-role="note"]');
  const input = card.querySelector('[data-role="key"]');
  const value = input ? input.value.trim() : "";
  if (!clear && !value) {
    note.textContent = "Nothing to save - paste a key first.";
    return;
  }
  note.textContent = clear ? "Clearing..." : "Saving...";
  try {
    const res = await fetch(`/api/keys/${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(clear ? { clear_key: true } : { api_key: value }),
    });
    if (!res.ok) throw new Error((await res.json()).error || "failed");
    note.textContent = clear ? "Key cleared." : "Saved.";
    if (input) input.value = "";
    await loadServiceKeys();
  } catch (err) {
    note.textContent = `Failed: ${err.message}`;
  }
}

/* --------------------------------------------------- engine selection */
function renderEngines(data) {
  enginesEl.innerHTML = "";
  for (const [name, spec] of Object.entries(data.engines || {})) {
    const label = document.createElement("label");
    label.textContent = `${spec.label} - ${spec.description}`;
    const select = document.createElement("select");
    select.dataset.engine = name;
    for (const o of spec.options) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.value === spec.value) opt.selected = true;
      select.appendChild(opt);
    }
    label.appendChild(select);
    enginesEl.appendChild(label);
  }
}

async function loadEngines() {
  try {
    const data = await (await fetch("/api/engines")).json();
    enginesData = data;
    renderEngines(data);
  } catch {
    enginesEl.textContent = "Could not load engine options.";
  }
  renderSetup();
}

async function saveEngines() {
  const body = {};
  enginesEl.querySelectorAll("select[data-engine]").forEach((s) => {
    body[s.dataset.engine] = s.value;
  });
  enginesStatus.textContent = "Saving...";
  try {
    const res = await fetch("/api/engines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error || "save failed");
    enginesStatus.textContent = "Saved.";
    await loadEngines();
    await loadOnDevice();
  } catch (err) {
    enginesStatus.textContent = `Failed: ${err.message}`;
  }
}

/* --------------------------------------------------- on-device model mgr */
function fmtBytes(n) {
  n = n || 0;
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
  if (n >= 1048576) return Math.round(n / 1048576) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

function odCard(m) {
  const card = document.createElement("div");
  card.className = "od-card";

  const head = document.createElement("div");
  head.className = "phead";
  const title = document.createElement("strong");
  title.textContent = m.label;
  const badge = document.createElement("span");
  badge.className =
    "pbadge" + (m.loaded ? " pok" : m.state === "error" ? " pbad" : "");
  badge.textContent = m.loaded
    ? "LOADED"
    : m.state === "downloading"
      ? "DOWNLOADING"
      : m.state === "error"
        ? "ERROR"
        : m.installed
          ? "INSTALLED"
          : "NOT DOWNLOADED";
  head.append(title, badge);
  card.appendChild(head);

  const note = document.createElement("div");
  note.className = "pnote";
  note.textContent = `${fmtBytes(m.size)} - needs ${m.min_ram_gb} GB RAM - ${m.description}`;
  card.appendChild(note);

  if (m.state === "downloading") {
    const bar = document.createElement("div");
    bar.className = "od-bar";
    const fill = document.createElement("div");
    fill.className = "od-fill";
    fill.style.width = (m.progress || 0) + "%";
    bar.appendChild(fill);
    const pct = document.createElement("div");
    pct.className = "pnote";
    pct.textContent = `${m.progress || 0}% - ${fmtBytes(m.done_bytes)} of ${fmtBytes(m.size)}`;
    card.append(bar, pct);
  }
  if (m.error) {
    const err = document.createElement("div");
    err.className = "pnote od-err";
    err.textContent = m.error;
    card.appendChild(err);
  }

  const row = document.createElement("div");
  row.className = "form-actions";
  const mk = (label, action) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.dataset.odAction = action;
    b.dataset.odId = m.id;
    return b;
  };
  if (m.state === "downloading") {
    row.appendChild(mk("CANCEL", "cancel"));
  } else if (!m.installed) {
    row.appendChild(mk("DOWNLOAD", "download"));
    if (m.partial_bytes > 0) row.appendChild(mk("DELETE PARTIAL", "delete"));
  } else {
    if (m.loaded) row.appendChild(mk("UNLOAD", "unload"));
    else row.appendChild(mk("LOAD", "load"));
    row.appendChild(mk("DELETE", "delete"));
  }
  card.appendChild(row);
  return card;
}

function renderOnDevice() {
  if (!ondeviceListEl || !ondeviceData) return;
  const dev = ondeviceData.device || {};
  const bits = [];
  if (dev.supported) {
    if (dev.mem_total_bytes)
      bits.push(`${(dev.mem_total_bytes / 1073741824).toFixed(1)} GB RAM`);
    if (dev.abis && dev.abis.length) bits.push(dev.abis[0]);
    bits.push(
      ondeviceData.ready
        ? `engine loaded: ${ondeviceData.loaded}`
        : "engine not loaded"
    );
  } else {
    bits.push(dev.reason || "On-device chat requires the Android app.");
  }
  ondeviceInfoEl.textContent = bits.join(" - ");
  ondeviceListEl.innerHTML = "";
  for (const m of ondeviceData.models || [])
    ondeviceListEl.appendChild(odCard(m));
}

function scheduleOdPoll() {
  const busy = ((ondeviceData && ondeviceData.models) || []).some(
    (m) => m.state === "downloading"
  );
  if (busy && !odPollTimer) {
    odPollTimer = setInterval(loadOnDevice, 1500);
  } else if (!busy && odPollTimer) {
    clearInterval(odPollTimer);
    odPollTimer = null;
  }
}

async function loadOnDevice() {
  if (!ondeviceListEl) return;
  try {
    const [info, models] = await Promise.all([
      fetch("/api/ondevice/info").then((r) => r.json()),
      fetch("/api/ondevice/models").then((r) => r.json()),
    ]);
    ondeviceData = {
      device: info.device,
      ready: info.ready || models.ready,
      loaded: info.loaded || models.loaded,
      engine_mode: info.engine_mode,
      models: models.models || [],
    };
    renderOnDevice();
    scheduleOdPoll();
  } catch {
    ondeviceInfoEl.textContent = "Could not load on-device status.";
  }
  renderSetup();
}

async function onDeviceAction(action, id) {
  if (action === "delete" && !confirm(`Delete ${id}?`)) return;
  ondeviceStatusEl.textContent = `${action.toUpperCase()} ${id}...`;
  try {
    const res = await fetch(`/api/ondevice/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false)
      throw new Error(data.error || `HTTP ${res.status}`);
    ondeviceStatusEl.textContent =
      action === "download"
        ? "Download started - progress appears on the card."
        : action === "delete"
          ? "Deleted."
          : action === "load"
            ? "Model loaded - offline chat is ready."
            : action === "unload"
              ? "Model unloaded."
              : "Download cancelled.";
  } catch (err) {
    ondeviceStatusEl.textContent = `Failed: ${err.message}`;
  }
  await loadOnDevice();
}

if (ondeviceListEl) {
  ondeviceListEl.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-od-action]");
    if (btn) onDeviceAction(btn.dataset.odAction, btn.dataset.odId);
  });
}

async function loadSettings() {
  try {
    const s = await (await fetch("/api/settings")).json();
    const atif = document.getElementById("set-atif-url");
    const mode = document.getElementById("set-mode");
    if (s["atif.url"]) atif.value = s["atif.url"];
    if (s["answer.mode"]) mode.value = s["answer.mode"];
  } catch {
    /* ignore */
  }
}

document.getElementById("save-settings").addEventListener("click", async () => {
  const body = {
    "atif.url": document.getElementById("set-atif-url").value,
    "answer.mode": document.getElementById("set-mode").value,
  };
  settingsStatus.textContent = "Saving...";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("save failed");
    settingsStatus.textContent = "Saved.";
  } catch (err) {
    settingsStatus.textContent = `Failed: ${err.message}`;
  }
});

document.getElementById("save-engines").addEventListener("click", saveEngines);

loadStatus();
loadProviders();
loadSettings();
loadTools();
loadServiceKeys();
loadEngines();
loadOnDevice();
