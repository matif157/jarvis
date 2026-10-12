const providersEl = document.getElementById("providers-list");
const providersStatus = document.getElementById("providers-status");
const settingsStatus = document.getElementById("settings-status");

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
    providersEl.innerHTML = "";
    for (const p of data.providers) providersEl.appendChild(renderProvider(p));
  } catch {
    providersEl.textContent = "Could not load providers.";
  }
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

loadProviders();
loadSettings();
