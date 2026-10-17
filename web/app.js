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
const voiceInfoEl = document.getElementById("voice-info");
const voiceStatusEl = document.getElementById("voice-status");
const memQueryEl = document.getElementById("mem-query");
const memTagEl = document.getElementById("mem-tag");
const memSourceEl = document.getElementById("mem-source");
const memListEl = document.getElementById("mem-list");
const memFacetsEl = document.getElementById("mem-facets");
const memStatusEl = document.getElementById("mem-status");
const memSummaryEl = document.getElementById("mem-summary");
const memAutoEl = document.getElementById("mem-auto");

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

  const v = voiceData;
  if (v) {
    const ttsOk = !!(v.tts && v.tts.available);
    setupItem(
      ttsOk,
      "Voice output",
      ttsOk
        ? `${v.tts.provider} - press SAY to hear replies, MIC to speak`
        : "No text-to-speech backend available.",
      "#voice"
    );
  }

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

/* --------------------------------------------------------------- voice */
let voiceData = null;
const CHAT_PLACEHOLDER = document.getElementById("chat-input").placeholder;

function renderVoice(data) {
  voiceData = data;
  if (!voiceInfoEl) return;
  const tts = data.tts || {};
  const stt = data.stt || {};
  const wake = data.wake || {};
  const lines = [];
  lines.push(
    tts.available
      ? `Speak aloud: ${tts.provider || "ready"}`
      : "Speak aloud: no voice output available"
  );
  lines.push(
    stt.available
      ? `Transcribe: ${stt.provider} (engine: ${data.stt_engine})`
      : data.android
        ? `Transcribe: ready (engine: ${data.stt_engine})`
        : "Transcribe: needs the Android app or a desktop STT backend"
  );
  if (!wake.supported) {
    lines.push("Wake word: available in the Android app");
  } else if (wake.error) {
    lines.push(`Wake word: ${wake.error}`);
  } else if (wake.running) {
    lines.push(`Wake word: listening for "${wake.keyword}"`);
  } else {
    lines.push("Wake word: stopped");
  }
  voiceInfoEl.innerHTML = lines.join("<br>");
}

async function loadVoice() {
  try {
    const data = await (await fetch("/api/voice/status")).json();
    renderVoice(data);
  } catch {
    if (voiceInfoEl) voiceInfoEl.textContent = "Could not load voice status.";
  }
  renderSetup();
}

async function wakeAction(action) {
  if (!voiceStatusEl) return;
  if (action === "start" && voiceData && !voiceData.wake_key_set) {
    voiceStatusEl.textContent =
      "Add your Picovoice access key first (Service API keys above).";
    return;
  }
  voiceStatusEl.textContent = action === "start" ? "Starting..." : "Stopping...";
  try {
    const res = await fetch(`/api/wake/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: "jarvis" }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false)
      throw new Error(data.error || `HTTP ${res.status}`);
    voiceStatusEl.textContent =
      action === "start" ? `Listening for "${data.keyword || "jarvis"}".` : "Stopped.";
  } catch (err) {
    voiceStatusEl.textContent = `Failed: ${err.message}`;
  }
  await loadVoice();
}

async function ensureMicPermission() {
  const bridge = window.JarvisAndroid;
  if (!bridge || !bridge.micPermissionGranted) return true; // desktop answers honestly
  if (bridge.micPermissionGranted()) return true;
  bridge.requestMicPermission();
  for (let i = 0; i < 12; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (bridge.micPermissionGranted()) return true;
  }
  return false;
}

function noteVoiceProblem(message) {
  const input = document.getElementById("chat-input");
  input.placeholder = message;
  setTimeout(() => {
    input.placeholder = CHAT_PLACEHOLDER;
  }, 6000);
}

async function micTranscribe() {
  const btn = document.getElementById("chat-mic");
  const input = document.getElementById("chat-input");
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = "REC";
  btn.classList.add("rec");
  input.placeholder = "Listening...";
  try {
    if (!(await ensureMicPermission())) {
      noteVoiceProblem("Microphone permission denied");
      return;
    }
    const res = await fetch("/api/voice/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds: 8 }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false)
      throw new Error(data.error || `HTTP ${res.status}`);
    input.value = (input.value ? input.value + " " : "") + data.transcript;
    input.focus();
    input.placeholder = CHAT_PLACEHOLDER;
  } catch (err) {
    noteVoiceProblem(err.message || "voice input failed");
  } finally {
    btn.disabled = false;
    btn.textContent = "MIC";
    btn.classList.remove("rec");
    if (input.placeholder === "Listening...") input.placeholder = CHAT_PLACEHOLDER;
  }
}

async function speakLast() {
  const msgs = chatLog.querySelectorAll(".msg.assistant");
  const last = msgs[msgs.length - 1];
  const text = last ? last.textContent.trim() : "";
  if (!text) return;
  try {
    const res = await fetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false)
      throw new Error(data.error || `HTTP ${res.status}`);
  } catch (err) {
    addChat("system", `Could not speak: ${err.message}`);
  }
}

window.onJarvisWake = function (keyword) {
  addChat("system", `Woke up on "${keyword}" - speak your command.`);
  micTranscribe();
};

document.getElementById("chat-mic").addEventListener("click", micTranscribe);
document.getElementById("chat-speak").addEventListener("click", speakLast);
if (document.getElementById("wake-start")) {
  document.getElementById("wake-start").addEventListener("click", () => wakeAction("start"));
  document.getElementById("wake-stop").addEventListener("click", () => wakeAction("stop"));
}

/* ------------------------------------------------------------- memory */
let memData = null;

function memParams() {
  const p = new URLSearchParams();
  const q = memQueryEl.value.trim();
  if (q) p.set("query", q);
  const tag = memTagEl.value.trim();
  if (tag) p.set("tag", tag);
  if (memSourceEl.value) p.set("source", memSourceEl.value);
  p.set("limit", "100");
  return p;
}

function memItemCard(item) {
  const card = document.createElement("div");
  card.className = "mem-card";
  const head = document.createElement("div");
  head.className = "mem-head";
  const text = document.createElement("div");
  text.className = "mem-text";
  text.textContent = item.text;
  const del = document.createElement("button");
  del.className = "mem-del";
  del.textContent = "FORGET";
  del.addEventListener("click", () => deleteMemoryItem(item.item_id));
  head.append(text, del);

  const meta = document.createElement("div");
  meta.className = "mem-meta";
  const bits = [];
  if (item.kind) bits.push(item.kind);
  if (item.source) bits.push(`source: ${item.source}`);
  (item.tags || []).forEach((t) => bits.push(`#${t}`));
  if (item.created_at) bits.push(item.created_at);
  meta.textContent = bits.join("  ·  ");

  card.append(head, meta);
  return card;
}

function fillMemSources(sources) {
  if (!memSourceEl) return;
  const current = memSourceEl.value;
  memSourceEl.innerHTML = '<option value="">any source</option>';
  (sources || []).forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.source;
    opt.textContent = `${s.source} (${s.count})`;
    memSourceEl.appendChild(opt);
  });
  memSourceEl.value = current;
}

function renderMemory(data) {
  memData = data;
  const items = data.items || [];
  const stats = data.stats || {};
  if (memSummaryEl) {
    memSummaryEl.textContent = `Long-term memory: ${stats.total || 0} items, ` +
      `${(stats.sources || []).length} sources, ${(stats.tags || []).length} tags.`;
  }
  if (memAutoEl) memAutoEl.checked = !!stats.auto_ingest;

  if (memFacetsEl) {
    memFacetsEl.innerHTML = "";
    (stats.sources || []).forEach((s) => {
      const chip = document.createElement("span");
      chip.className = "mem-chip";
      chip.textContent = `${s.source}: ${s.count} ×`;
      chip.title = "Click to delete everything from this source";
      chip.addEventListener("click", () => deleteMemorySource(s.source));
      memFacetsEl.appendChild(chip);
    });
    (stats.tags || []).slice(0, 12).forEach((t) => {
      const chip = document.createElement("span");
      chip.className = "mem-chip tag";
      chip.textContent = `#${t.tag} (${t.count})`;
      chip.addEventListener("click", () => {
        memTagEl.value = t.tag;
        loadMemory();
      });
      memFacetsEl.appendChild(chip);
    });
  }

  if (!memListEl) return;
  memListEl.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "No memory items yet.";
    memListEl.appendChild(empty);
    return;
  }
  items.forEach((it) => memListEl.appendChild(memItemCard(it)));
  fillMemSources(stats.sources);
}

async function loadMemory() {
  try {
    const data = await (await fetch("/api/memory?" + memParams())).json();
    renderMemory(data);
  } catch {
    if (memStatusEl) memStatusEl.textContent = "Could not load memory.";
  }
}

async function memPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function addMemory(extract) {
  const text = document.getElementById("mem-text").value.trim();
  if (!text) {
    memStatusEl.textContent = "Type something to remember first.";
    return;
  }
  const source = document.getElementById("mem-new-source").value.trim();
  const tags = document.getElementById("mem-new-tags").value.trim();
  memStatusEl.textContent = extract ? "Extracting facts..." : "Saving...";
  try {
    let data;
    if (extract) {
      data = await memPost("/api/memory/ingest", { text, source, tags, mode: "heuristic" });
    } else {
      data = await memPost("/api/memory", { text, source, tags, kind: "fact" });
    }
    memStatusEl.textContent = `Saved ${data.added || 1} item(s), ${data.skipped || 0} duplicate(s).`;
    document.getElementById("mem-text").value = "";
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function importMemoryFile() {
  const path = document.getElementById("mem-path").value.trim();
  if (!path) {
    memStatusEl.textContent = "Enter a file path to import.";
    return;
  }
  memStatusEl.textContent = "Importing...";
  try {
    const data = await memPost("/api/memory/import", { path });
    memStatusEl.textContent = `Imported ${data.added} item(s), ${data.skipped} duplicate(s).`;
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function importMemoryJson() {
  const raw = document.getElementById("mem-json").value.trim();
  if (!raw) {
    memStatusEl.textContent = "Paste JSON to import.";
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    memStatusEl.textContent = `Invalid JSON: ${err.message}`;
    return;
  }
  const items = Array.isArray(parsed) ? parsed : parsed.items;
  if (!Array.isArray(items)) {
    memStatusEl.textContent = "JSON must be a list or an object with an items list.";
    return;
  }
  memStatusEl.textContent = "Importing...";
  try {
    const data = await memPost("/api/memory/import", { items });
    memStatusEl.textContent = `Imported ${data.added} item(s), ${data.skipped} duplicate(s).`;
    document.getElementById("mem-json").value = "";
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function importLegacyMemory() {
  memStatusEl.textContent = "Importing old memory...";
  try {
    const data = await memPost("/api/memory/import", { legacy: true });
    memStatusEl.textContent = `Imported ${data.added} item(s), ${data.skipped} duplicate(s).`;
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function exportMemory() {
  try {
    const data = await (await fetch("/api/memory/export")).json();
    const blob = new Blob([JSON.stringify(data.items || [], null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "jarvis-memory.json";
    a.click();
    URL.revokeObjectURL(url);
    memStatusEl.textContent = `Exported ${data.count || 0} item(s).`;
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function deleteMemoryItem(itemId) {
  try {
    const res = await fetch(`/api/memory/${encodeURIComponent(itemId)}`, { method: "DELETE" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    memStatusEl.textContent = "Forgotten.";
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function deleteMemorySource(source) {
  if (!confirm(`Delete all memory from "${source}"?`)) return;
  try {
    const data = await memPost("/api/memory/delete-source", { source });
    memStatusEl.textContent = `Removed ${data.removed} item(s) from ${source}.`;
    await loadMemory();
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function toggleAutoIngest() {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ "memory.auto_ingest": memAutoEl.checked ? "1" : "0" }),
    });
    memStatusEl.textContent = memAutoEl.checked
      ? "Auto-capture on: new facts from chat will be saved."
      : "Auto-capture off.";
  } catch (err) {
    memStatusEl.textContent = `Failed: ${err.message}`;
  }
}

if (memListEl) {
  document.getElementById("mem-search").addEventListener("click", loadMemory);
  memQueryEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadMemory();
  });
  document.getElementById("mem-add").addEventListener("click", () => addMemory(false));
  document.getElementById("mem-ingest").addEventListener("click", () => addMemory(true));
  document.getElementById("mem-import-file").addEventListener("click", importMemoryFile);
  document.getElementById("mem-import-json").addEventListener("click", importMemoryJson);
  document.getElementById("mem-import-legacy").addEventListener("click", importLegacyMemory);
  document.getElementById("mem-export").addEventListener("click", exportMemory);
  if (memAutoEl) memAutoEl.addEventListener("change", toggleAutoIngest);
}

/* ----------------------------------------------------------- whatsapp */
const waInfoEl = document.getElementById("wa-info");
const waStatusEl = document.getElementById("wa-status");
const waChatsEl = document.getElementById("wa-chats");
const waListenEl = document.getElementById("wa-listen");
const waAutoEl = document.getElementById("wa-auto");
const waCooldownEl = document.getElementById("wa-cooldown");
let waData = null;
let waChatRules = {};

function renderWhatsApp(data) {
  waData = data;
  if (!waInfoEl) return;
  const lines = [];
  if (!data.supported) {
    lines.push("Live reading and replies need the Android app. Chat exports can still be imported here.");
  } else if (data.error) {
    lines.push(data.error);
  } else {
    lines.push(
      data.listener
        ? "Notification listener: active"
        : "Notification listener: not granted - tap OPEN NOTIFICATION ACCESS"
    );
  }
  lines.push(
    `Stored: ${data.messages || 0} messages in ${data.chats || 0} chats` +
      (data.targets && data.targets.length
        ? `  ·  reply targets: ${data.targets.join(", ")}`
        : "")
  );
  waInfoEl.innerHTML = lines.join("<br>");
  if (waListenEl) waListenEl.checked = !!data.listen;
  if (waAutoEl) waAutoEl.checked = !!data.auto_reply;
  if (waCooldownEl && document.activeElement !== waCooldownEl) {
    waCooldownEl.value = data.cooldown;
  }
  waChatRules = data.rules || {};
}

async function loadWhatsApp() {
  try {
    const data = await (await fetch("/api/whatsapp/status")).json();
    renderWhatsApp(data);
  } catch {
    if (waInfoEl) waInfoEl.textContent = "Could not load WhatsApp status.";
  }
  await loadWaChats();
}

function waCard(chat) {
  const card = document.createElement("div");
  card.className = "mem-card";
  const head = document.createElement("div");
  head.className = "mem-head";
  const title = document.createElement("div");
  title.className = "mem-text";
  title.textContent = chat.chat;
  const del = document.createElement("button");
  del.className = "mem-del";
  del.textContent = "DELETE";
  del.title = "Forget every stored message of this chat";
  del.addEventListener("click", () => deleteWaChat(chat.chat));
  head.append(title, del);

  const meta = document.createElement("div");
  meta.className = "mem-meta";
  meta.textContent =
    `${chat.total} messages  ·  ${chat.inbound} in / ${chat.outbound} out` +
    (chat.last_ts ? `  ·  last: ${chat.last_ts}` : "");

  const controls = document.createElement("div");
  controls.className = "actions";
  const rule = document.createElement("select");
  ["off", "suggest", "auto"].forEach((mode) => {
    const opt = document.createElement("option");
    opt.value = mode;
    opt.textContent =
      mode === "off" ? "rule: off" : mode === "suggest" ? "rule: suggest reply" : "rule: auto reply";
    rule.appendChild(opt);
  });
  rule.value = waChatRules[chat.chat] || chat.rule || "off";
  rule.addEventListener("change", () => saveWaRule(chat.chat, rule.value));
  const gen = document.createElement("button");
  gen.textContent = "DRAFT";
  gen.title = "Generate a suggested reply from this chat's history and style";
  gen.addEventListener("click", () => waAction(`/api/whatsapp/generate`, { chat: chat.chat }, "Drafted a reply."));
  const show = document.createElement("button");
  show.textContent = "HISTORY";
  show.addEventListener("click", () => toggleWaHistory(chat.chat, show));
  controls.append(rule, gen, show);

  card.append(head, meta, controls);

  if (chat.suggestion && chat.suggestion.text) {
    const sug = document.createElement("div");
    sug.className = "mem-meta";
    sug.textContent = `suggestion: ${chat.suggestion.text}`;
    const sugActions = document.createElement("div");
    sugActions.className = "actions";
    const send = document.createElement("button");
    send.textContent = "SEND";
    send.addEventListener("click", () =>
      waAction(`/api/whatsapp/suggestion/accept`, { chat: chat.chat }, "Sent.")
    );
    const dismiss = document.createElement("button");
    dismiss.textContent = "DISMISS";
    dismiss.addEventListener("click", () =>
      waAction(`/api/whatsapp/suggestion/dismiss`, { chat: chat.chat }, "Dismissed.")
    );
    sugActions.append(send, dismiss);
    card.append(sug, sugActions);
  }

  const history = document.createElement("pre");
  history.className = "tool-result";
  history.id = `wa-hist-${encodeURIComponent(chat.chat)}`;
  history.style.display = "none";
  card.append(history);
  return card;
}

async function toggleWaHistory(chat, btn) {
  const pre = document.getElementById(`wa-hist-${encodeURIComponent(chat)}`);
  if (!pre) return;
  if (pre.style.display !== "none") {
    pre.style.display = "none";
    btn.textContent = "HISTORY";
    return;
  }
  try {
    const data = await (
      await fetch(`/api/whatsapp/history?chat=${encodeURIComponent(chat)}&limit=60`)
    ).json();
    pre.textContent = (data.messages || [])
      .map((m) => `${m.ts || "?"} ${m.direction === "out" ? "me" : m.sender || "them"}: ${m.text}`)
      .join("\n");
    pre.style.display = "block";
    btn.textContent = "HIDE";
  } catch (err) {
    pre.textContent = `Failed: ${err.message}`;
    pre.style.display = "block";
  }
}

async function loadWaChats() {
  if (!waChatsEl) return;
  try {
    const data = await (await fetch("/api/whatsapp/chats")).json();
    waChatsEl.innerHTML = "";
    if (!(data.chats || []).length) {
      const empty = document.createElement("div");
      empty.className = "hint";
      empty.textContent = "No chats mapped yet - import an export file or grant notification access.";
      waChatsEl.appendChild(empty);
      return;
    }
    data.chats.forEach((c) => waChatsEl.appendChild(waCard(c)));
  } catch {
    /* status line already explains failures */
  }
}

async function waAction(url, body, successMsg) {
  if (!waStatusEl) return;
  waStatusEl.textContent = "Working...";
  try {
    const data = await memPost(url, body);
    waStatusEl.textContent = successMsg || "Done.";
    if (data && data.suggestion) waStatusEl.textContent = `Suggestion: ${data.suggestion}`;
    if (data && data.error) waStatusEl.textContent = data.error;
  } catch (err) {
    waStatusEl.textContent = `Failed: ${err.message}`;
  }
  await loadWhatsApp();
}

async function saveWaRule(chat, mode) {
  const rules = Object.assign({}, waChatRules);
  if (mode === "off") delete rules[chat];
  else rules[chat] = mode;
  await waAction(`/api/whatsapp/settings`, { rules }, `Rule for ${chat}: ${mode}.`);
}

async function saveWaSettings() {
  if (!waStatusEl) return;
  waStatusEl.textContent = "Saving...";
  try {
    await waAction(`/api/whatsapp/settings`, {
      listen: waListenEl.checked,
      auto_reply: waAutoEl.checked,
      cooldown: parseInt(waCooldownEl.value, 10) || 0,
    }, "Saved.");
  } catch (err) {
    waStatusEl.textContent = `Failed: ${err.message}`;
  }
}

async function deleteWaChat(chat) {
  if (!confirm(`Delete every stored message of "${chat}"?`)) return;
  if (!waStatusEl) return;
  try {
    const res = await fetch(`/api/whatsapp/chats/${encodeURIComponent(chat)}`, {
      method: "DELETE",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    waStatusEl.textContent = `Removed ${data.removed} message(s).`;
  } catch (err) {
    waStatusEl.textContent = `Failed: ${err.message}`;
  }
  await loadWhatsApp();
}

async function importWaFile() {
  const path = (document.getElementById("wa-import-path").value || "").trim();
  if (!path) {
    if (waStatusEl) waStatusEl.textContent = "Paste the path of an exported chat file first.";
    return;
  }
  await waAction(`/api/whatsapp/import`, { path }, "Imported.");
}

const waSection = document.getElementById("wa-chats");
if (waSection) {
  document.getElementById("wa-refresh").addEventListener("click", loadWhatsApp);
  document.getElementById("wa-import").addEventListener("click", importWaFile);
  document.getElementById("wa-open-notif").addEventListener("click", () => {
    const bridge = window.JarvisAndroid;
    if (bridge && bridge.openNotificationSettings) {
      bridge.openNotificationSettings();
    } else if (waInfoEl) {
      waInfoEl.textContent =
        "Notification access is an Android setting: Settings > Apps > Jarvis > Notification access (or Special app access).";
    }
  });
  if (waListenEl) waListenEl.addEventListener("change", saveWaSettings);
  if (waAutoEl) waAutoEl.addEventListener("change", saveWaSettings);
  if (waCooldownEl) waCooldownEl.addEventListener("change", saveWaSettings);
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
loadVoice();
loadMemory();
loadWhatsApp();
