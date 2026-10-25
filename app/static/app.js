// Loop Builder editor: loop tabs, a drag-and-drop slide strip, an editor per slide type with a live
// preview drawn by the export renderer, autosave, checks and export.
"use strict";

const seconds = (v) => String(v ?? "").split(":").reduce((t, p) => t * 60 + Number(p || 0), 0);
const TYPES = {
  board: { name: "Board", hint: "A DisplayLink Plus template", icon: '<rect x="3" y="6" width="22" height="14" rx="2"/><path d="M10 24h8M14 20v4"/>' },
  card: { name: "Card", hint: "Text in a fixed layout", icon: '<rect x="3" y="5" width="22" height="18" rx="2"/><path d="M9 11h10M7 15h14M10 19h8"/>' },
  qr: { name: "QR", hint: "Full-height code + text", icon: '<rect x="5" y="5" width="7" height="7"/><rect x="16" y="5" width="7" height="7"/><rect x="5" y="16" width="7" height="7"/><path d="M16 16h3v3M23 16v7h-7"/>' },
  image: { name: "Image", hint: "A picture, framed to fit", icon: '<rect x="3" y="5" width="22" height="18" rx="2"/><path d="M5 21l6-7 5 5 3-3 5 5"/><circle cx="19" cy="10" r="2"/>' },
  countdown: { name: "Countdown", hint: "A running clock", icon: '<circle cx="14" cy="15" r="9"/><path d="M14 10v5l3 2M11 3h6"/>' },
  lanes: { name: "Lanes", hint: "Guest lane assignments", icon: '<rect x="3" y="5" width="22" height="18" rx="2"/><path d="M3 12h22M10 5v18M17 5v18"/>' },
  crawl: { name: "Crawl", hint: "Scrolling message", icon: '<rect x="3" y="9" width="22" height="10" rx="2"/><path d="M21 14H9M12 11l-3 3 3 3"/>' },
};
const icon = (type) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "28"); svg.setAttribute("height", "28"); svg.setAttribute("viewBox", "0 0 28 28");
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "#C4CAD1");
  svg.setAttribute("stroke-width", "1.8"); svg.setAttribute("stroke-linecap", "round");
  svg.innerHTML = TYPES[type].icon; // fixed markup from TYPES above, never user content
  return svg;
};

const state = { event: null, loop: 0, n: 0, draft: null, templates: [], templateDetails: [], teams: [], settings: {}, issues: [], teamsAdded: [], stamp: Date.now() };
const kindOf = (raw) => Object.keys(raw)[0];
const propsOf = (raw) => raw[kindOf(raw)];
const currentLoop = () => state.event.loops[state.loop];
const rawSlides = () => currentLoop().slides.map((s) => structuredClone(s.raw));

function defaultSlide(type) {
  switch (type) {
    case "board": return null; // made once a template is picked
    case "card": return { card: { layout: "logo-center", lines: [
      { text: "Welcome", size: "M", style: "outlined" }, { text: "TEAM NAME", size: "L", style: "outlined" },
      { text: "Thanks for swimming with us!", size: "S" }] } };
    case "qr": return { qr: { url: "https://", heading: ["SCAN", "FOR INFO"] } };
    case "countdown": return { countdown: { label: "WARM-UP", length: "10:00", hold_at_zero: 5 } };
    case "crawl": return { crawl: { length: "3:00", speed: "medium", segments: [
      { text: "The meet will " }, { text: "RESUME", style: "outlined" }, { text: " shortly", style: "accent" }] } };
    case "lanes": {
      const first = state.settings.first_lane ?? 1;
      return { lanes: { title: "Welcome!", first, last: first + (state.settings.pool_lanes ?? 8) - 1, lanes: [] } };
    }
    default: return null; // image: made once a picture is picked
  }
}

// ---------- loading ----------

async function loadEvent(keepEditor = false) {
  state.event = await api("/api/event");
  if (state.templatesFor !== templatesKey()) await loadTemplates(); // the folder changed, or went missing or came back
  $("#event-name").replaceChildren(el("a", { href: "/" }, "Events"), " / ",
    el("button", { class: "crumb-edit", type: "button", title: "Rename the event, change its date or its visiting team", on: { click: openDetails } },
      `${state.event.name}${state.event.date ? " · " + niceDate(state.event.date) : ""}`));
  renderTabs();
  renderLoop();
  $("#undo").disabled = !state.event.can_undo;
  $("#redo").disabled = !state.event.can_redo;
  $("#theme-offer").hidden = !state.event.offer_team_theme;
  if (!keepEditor) selectSlide(Math.min(state.n, currentLoop().slides.length - 1));
  else markCurrent();
  loadChecks();
}

function renderTabs() {
  $("#tabs").replaceChildren(...state.event.loops.map((lp, i) =>
    el("button", { class: "tab", role: "tab", type: "button", "aria-selected": String(i === state.loop),
      on: { click: () => { state.loop = i; state.n = 0; loadEvent(); } } }, lp.name, el("span", { class: "mono" }, clock(lp.length)))));
  markIssues();
}

const slideUrl = (loop, n, scale) => `/api/slide.png?loop=${loop}&n=${n}&scale=${scale}&t=${state.stamp}`;

function renderLoop() {
  const lp = currentLoop();
  $("#loop-name").textContent = lp.name;
  $("#loop-length").textContent = `${clock(lp.length)} total`;
  $("#loop-hold").value = lp.hold;
  $("#loop-fade").value = lp.fade;
  $("#slides").replaceChildren(...lp.slides.map((sl, j) =>
    el("li", { "data-n": j },
      el("button", { class: "thumb", type: "button", draggable: "true", "aria-current": String(j === state.n),
        on: { click: () => selectSlide(j), dragstart: (e) => e.dataTransfer.setData("text/plain", `move:${j}`) } },
      el("img", { src: slideUrl(state.loop, j, 1), alt: `${TYPES[sl.type].name}: ${sl.label}`, draggable: "false",
        on: { error: async (e) => {
          const img = e.target;
          let why = "Can't draw this slide";
          try { const res = await fetch(img.src); why = `Can't draw: ${await failure(res)}`; } catch (err) { /* keep the generic text */ }
          img.replaceWith(el("span", { class: "thumb-error" }, why));
        } } }),
      el("span", { class: "meta" }, el("span", {}, `${j + 1}  ${TYPES[sl.type].name} · ${sl.label}`),
        sl.linked ? el("span", { class: "badge", title: "Shown in more than one place; an edit changes all of them" }, `Linked · ${sl.linked}`)
          : el("span", { class: "mono" }, sl.timed ? "timed" : `${sl.hold ?? lp.hold} s${pagesLabel(sl)}`))))),
    el("li", { class: "drop-zone", "data-n": lp.slides.length }, "Drop a slide here"));
  markIssues();
}

// The preview stays at the top while the fields scroll under it, so a field the browser scrolls to (Tab, a
// focus) must land below it, not behind it: scroll-padding follows the preview's height.
new ResizeObserver(([entry]) => {
  document.documentElement.style.scrollPaddingTop = `${Math.round(entry.target.getBoundingClientRect().height) + 12}px`;
}).observe(document.querySelector(".preview"));

function markCurrent() {
  document.querySelectorAll("#slides .thumb").forEach((b, j) => b.setAttribute("aria-current", String(j === state.n)));
  markIssues();
}

// A slide a check stops from exporting is marked in the strip, and its reason shows under its preview, so a
// problem is seen where it is, not only in the list at the bottom.
function markIssues() {
  const name = currentLoop().name;
  const errors = (j) => state.issues.filter((i) => i.level === "error" && i.loop === name && i.slide === j + 1);
  document.querySelectorAll("#slides .thumb").forEach((b, j) => {
    const found = errors(j);
    b.classList.toggle("has-error", found.length > 0);
    b.title = found.map((i) => i.message).join("\n");
  });
  document.querySelectorAll("#tabs .tab").forEach((tab, i) => { // a loop with a slide to fix, on another tab too
    const loop = state.event.loops[i];
    tab.classList.toggle("has-error", !!loop && state.issues.some((x) => x.level === "error" && x.loop === loop.name));
  });
  const said = (i) => /^QR/.test(i.message); // the scan check line beside it already says what's wrong with a QR
  $("#slide-errors").textContent = errors(state.n).filter((i) => !said(i))
    .map((i) => `✗ ${i.message[0].toUpperCase()}${i.message.slice(1)}`).join("  ");
}

// ---------- strip editing: add, move, duplicate, delete ----------

async function saveLoop(slides, select) {
  const lp = currentLoop();
  try {
    await api(`/api/loops/${state.loop}`, "PUT", { name: lp.name, hold: Number($("#loop-hold").value) || lp.hold,
      fade: Number($("#loop-fade").value), slides });
  } catch (err) { flash(`Not saved: ${err.message}`); return; }
  state.stamp = Date.now();
  state.n = select ?? state.n;
  await loadEvent();
  flash("Saved");
}

async function insertSlide(type, at) {
  let raw = defaultSlide(type);
  if (type === "image") raw = await pickPicture((file) => ({ image: { file } }));
  if (type === "board") {
    if (!staticTemplates().length) await setTemplateFolder(folderProblem());
    const name = staticTemplates().length ? await pickTemplate() : null;
    raw = name ? { board: { template: name } } : null;
  }
  if (!raw) return;
  const slides = rawSlides();
  slides.splice(at, 0, raw);
  saveLoop(slides, at);
}

function moveSlide(from, to) {
  const slides = rawSlides();
  const [raw] = slides.splice(from, 1);
  const at = to > from ? to - 1 : to;
  slides.splice(at, 0, raw);
  saveLoop(slides, at);
}

$("#move-up").addEventListener("click", () => state.n > 0 && moveSlide(state.n, state.n - 1));
$("#move-down").addEventListener("click", () => state.n < currentLoop().slides.length - 1 && moveSlide(state.n, state.n + 2));
$("#duplicate").addEventListener("click", () => {
  const slides = rawSlides();
  const copy = structuredClone(slides[state.n]);
  delete propsOf(copy).id; // a duplicate is independent; linking is separate
  slides.splice(state.n + 1, 0, copy);
  saveLoop(slides, state.n + 1);
});
$("#delete").addEventListener("click", () => {
  const slides = rawSlides();
  if (slides.length === 1) { flash("A loop keeps at least one slide"); return; }
  slides.splice(state.n, 1);
  saveLoop(slides, Math.max(0, state.n - 1));
});
["#loop-hold", "#loop-fade"].forEach((id) => $(id).addEventListener("change", () => saveLoop(rawSlides())));

$("#new-loop").addEventListener("click", async () => {
  try {
    const { index } = await api("/api/loops", "POST", { name: `New loop ${state.event.loops.length + 1}`,
      hold: 10, fade: 0.5, slides: [defaultSlide("card")] });
    state.loop = index; state.n = 0; await loadEvent();
  } catch (err) { flash(`Not added: ${err.message}`); }
});

$("#palette").replaceChildren(...Object.entries(TYPES).map(([type, t]) =>
  el("button", { class: "pal", type: "button", draggable: "true",
    on: { click: () => insertSlide(type, state.n + 1), dragstart: (e) => e.dataTransfer.setData("text/plain", `new:${type}`) } },
  icon(type), el("span", {}, t.name, el("small", {}, t.hint)))));

// Drop targets: before a slide (upper half), after it (lower half), or the zone at the end.
const strip = $("#slides");
const dropIndex = (e) => {
  const li = e.target.closest("li");
  if (!li) return currentLoop().slides.length;
  const n = Number(li.dataset.n);
  if (li.classList.contains("drop-zone")) return n;
  const r = li.getBoundingClientRect();
  return e.clientY < r.top + r.height / 2 ? n : n + 1;
};
const clearDrop = () => strip.querySelectorAll(".drop-before,.drop-after").forEach((li) => li.classList.remove("drop-before", "drop-after"));
strip.addEventListener("dragover", (e) => {
  e.preventDefault();
  clearDrop();
  const at = dropIndex(e);
  const items = strip.querySelectorAll("li:not(.drop-zone)");
  if (at < items.length) items[at].classList.add("drop-before");
  else if (items.length) items[items.length - 1].classList.add("drop-after");
});
strip.addEventListener("dragleave", (e) => { if (!strip.contains(e.relatedTarget)) clearDrop(); });
strip.addEventListener("drop", (e) => {
  e.preventDefault();
  clearDrop();
  const [what, arg] = e.dataTransfer.getData("text/plain").split(":");
  const at = dropIndex(e);
  if (what === "new") insertSlide(arg, at);
  else if (what === "move" && Number(arg) !== at && Number(arg) + 1 !== at) moveSlide(Number(arg), at);
});

// ---------- the selected slide ----------

function selectSlide(n) {
  state.n = n;
  markCurrent();
  const sl = currentLoop().slides[n];
  state.draft = structuredClone(sl.raw);
  $("#slide-kind").textContent = `Slide ${n + 1} · ${TYPES[sl.type].name}`;
  $("#slide-title").textContent = sl.label;
  $("#move-up").disabled = n === 0;
  $("#move-down").disabled = n === currentLoop().slides.length - 1;
  $("#issues").textContent = "";
  setupScrub(sl);
  draw(slideUrl(state.loop, n, 3));
  renderEditor();
}

async function draw(url, options) {
  const start = performance.now();
  const res = await fetch(url, options);
  if (!res.ok) { $("#issues").textContent = await failure(res); return; }
  const img = $("#preview");
  if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
  img.src = URL.createObjectURL(await res.blob());
  document.querySelectorAll(".crop-preview").forEach((m) => { m.src = img.src; });
  $("#render-ms").textContent = `320 × 176 · drawn by the export renderer in ${res.headers.get("X-Render-Ms")} ms, on screen in ${Math.round(performance.now() - start)} ms`;
  $("#issues").textContent = decodeURIComponent(res.headers.get("X-Issues") || "");
  const qr = res.headers.get("X-QR");
  $("#qr-check").className = qr === "ok" ? "qr-ok" : qr ? "qr-fail" : "";
  $("#qr-check").textContent = qr === "ok" ? "✓ Scan check: the code reads back this exact link"
    : qr === "fail" ? "✗ Scan check: the code doesn't read back the link"
    : qr === "incomplete" ? "✗ Enter a full web address, like https://yourteam.com or https://yourteam.com/page" : "";
}

function setupScrub(sl, keepPlace = false) {
  const p = propsOf(sl.raw);
  const panning = sl.type === "image" && !!p.pan;
  const pages = sl.type === "lanes" ? (([first, last, per]) => Math.ceil((last - first + 1) / per))(laneRange(p)) : 1;
  const timed = sl.type === "countdown" || sl.type === "crawl" || panning || pages > 1;
  $("#scrub").hidden = !timed;
  if (!timed) return;
  const hold = Number(p.hold ?? currentLoop().hold);
  const total = panning ? hold : pages > 1 ? pages * hold + (pages - 1) * 0.5
    : seconds(p.length || (sl.type === "crawl" ? "3:00" : "10:00")) + (sl.type === "countdown" ? Number(p.hold_at_zero ?? 5) : 0);
  const at = keepPlace ? Math.min(Number($("#scrub-at").value) || 0, total) : 0;
  $("#scrub-at").max = total;
  $("#scrub-at").value = at;
  $("#scrub-label").textContent = `${clock(at)} of ${clock(total)}`;
}
$("#scrub-at").addEventListener("input", (e) => {
  $("#scrub-label").textContent = `${clock(Number(e.target.value))} of ${clock(Number(e.target.max))}`;
  previewDraft(false);
});

// Live preview while editing, then autosave once typing pauses.
let previewTimer, saveTimer;
function previewDraft(save = true) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => draw("/api/render", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loop: state.loop, n: state.n, slide: state.draft, at: $("#scrub").hidden ? null : Number($("#scrub-at").value) }) }), 120);
  if (!save) return;
  $("#saved").textContent = "Editing…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveSlide, 700);
}

async function saveSlide() {
  try {
    await api("/api/slide", "PUT", { loop: state.loop, n: state.n, slide: state.draft });
  } catch (err) { flash(`Not saved: ${err.message}`); return; }
  state.stamp = Date.now();
  await loadEvent(true);
  $("#slide-title").textContent = currentLoop().slides[state.n].label;
  flash("Saved");
}

function flash(text) { $("#saved").textContent = text; }

// ---------- editors ----------

const P = () => propsOf(state.draft);
const set = (key, value) => { if (value === "" || value == null) delete P()[key]; else P()[key] = value; previewDraft(); };

function seg(label, options, current, onPick) {
  return el("span", { class: "seg", role: "group", "aria-label": label }, options.map(([value, text]) =>
    el("button", { type: "button", "aria-pressed": String(value === current), on: { click: (e) => {
      e.currentTarget.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      e.currentTarget.setAttribute("aria-pressed", "true");
      onPick(value);
    } } }, text)));
}
const opts = (...names) => names.map((n) => [n, n[0].toUpperCase() + n.slice(1)]);
const text = (label, value, onInput, attrs = {}) => el("label", { class: "lbl" }, label,
  el("input", { class: "field", value: value ?? "", ...attrs, on: { input: (e) => onInput(e.target.value) } }));
const group = (legend, ...kids) => el("fieldset", { class: "group" }, el("legend", { class: "label" }, legend), ...kids);
const holdField = () => text("Hold (s, empty = loop default)", P().hold, (v) => {
  set("hold", v === "" ? "" : Number(v));
  setupScrub({ type: kindOf(state.draft), raw: state.draft }, true); // the "Preview at" timeline follows the new length
  document.dispatchEvent(new Event("holdchange")); // and so does a pan playing in "On the board"
}, { type: "number", min: "1", step: "0.5", placeholder: String(currentLoop().hold) });
async function loadTemplates() {
  const found = await api("/api/templates");
  state.templates = found.templates;
  state.templateDetails = found.details || [];
  state.templatesFor = templatesKey();
}
const templatesKey = () => `${state.event.templates_folder}|${state.event.templates_found}`;
const staticTemplates = () => state.templateDetails.filter((t) => !t.live && !t.broken).map((t) => t.name);
const templateUrl = (name) => `/api/template.png?name=${encodeURIComponent(name)}`;

// Why this event has no board templates to pick from, or "" when it has some.
function folderProblem() {
  const ev = state.event;
  if (!ev.templates_set) return "This event has no DisplayLink Plus template folder yet, so there are no board templates to choose from.";
  if (!ev.templates_found) return `The DisplayLink Plus template folder ${ev.templates_folder} isn't on this computer. Choose where the templates are here.`;
  if (!state.templateDetails.length) return `There are no DisplayLink Plus templates (.tpl) in ${ev.templates_folder}.`;
  if (!staticTemplates().length) return `None of the templates in ${ev.templates_folder} can go in a video: they show live meet data or can't be drawn.`;
  return "";
}

// Where this event's board templates come from, with a way to change it (for the whole event).
function folderStatus(value) {
  const ev = state.event;
  const name = value ? value.split("/").pop() : "";
  const missing = value && value !== "blank" && !state.templates.some((t) => t === value || t.split("/").pop() === name);
  const where = ev.templates_source === "event" ? "this event's folder" : ev.templates_source === "override" ? "set at launch" : "the default for new events";
  const problem = folderProblem() || (missing ? `“${value.replace(/\.tpl$/, "")}” isn't in the DisplayLink Plus template folder.` : "");
  return el("div", { class: problem ? "folder-status warn-box" : "folder-status" },
    problem && el("p", { class: "warn" }, problem),
    el("p", { class: "muted" }, ev.templates_found ? `Templates from ${ev.templates_folder} (${where}).` : ""),
    el("button", { class: problem ? "btn btn-primary" : "btn", type: "button", on: { click: () => setTemplateFolder() } },
      "Set DisplayLink Plus template folder…"));
}

function setTemplateFolder(why = "") {
  const dialog = $("#folder-dialog");
  $("#folder-path").value = state.event.templates_found ? state.event.templates_folder : "";
  $("#folder-status").textContent = why;
  $("#folder-default").checked = state.event.templates_source !== "event";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", resolve, { once: true }));
}
$("#folder-pick").addEventListener("click", () => pickFolder($("#folder-path")));
$("#folder-save").addEventListener("click", async () => {
  try {
    const { templates } = await api("/api/event/templates", "PUT", { folder: $("#folder-path").value.trim(), make_default: $("#folder-default").checked });
    state.templatesFor = null; // the same folder may hold new templates
    state.stamp = Date.now();
    await loadEvent(true);
    renderEditor();
    draw(slideUrl(state.loop, state.n, 3));
    $("#folder-dialog").close();
    flash(`Folder set · ${templates} templates`);
  } catch (err) { $("#folder-status").textContent = err.message; }
});

// A template field: the chosen template's thumbnail and a button that opens the picker.
const templateSelect = (label, value, onPick, allowBlank) => {
  const blank = !value || value === "blank";
  const live = state.templateDetails.find((t) => t.name === value && t.live);
  return group(label, el("div", { class: "tpl-field" },
    blank ? el("span", { class: "tpl-blank" }, "Blank background")
      : el("img", { src: templateUrl(value), alt: "", class: "tpl-thumb",
        on: { error: (e) => e.target.replaceWith(el("span", { class: "tpl-blank" }, "Not found")) } }),
    el("span", { class: "tpl-name" }, blank ? "" : value.replace(/\.tpl$/, ""),
      live && el("small", { class: "warn", style: "display:block" }, `Has live data (${live.about}): pick another`)),
    el("button", { class: "btn", type: "button", disabled: !staticTemplates().length, on: { click: async () => {
      const picked = await pickTemplate({ allowBlank, current: value });
      if (picked !== null) onPick(picked);
    } } }, "Choose template…")), folderStatus(blank ? "" : value));
};

// The template picker: static templates can be picked; ones with live data are dimmed, with the reason.
function pickTemplate({ allowBlank = false, current = "" } = {}) {
  const dialog = $("#tpl-picker");
  return new Promise((resolve) => {
    let picked = null;
    const choose = (name) => { picked = name; dialog.close(); };
    const groups = {};
    state.templateDetails.forEach((t) => {
      const folder = t.name.includes("/") ? t.name.slice(0, t.name.lastIndexOf("/")) : "Templates";
      (groups[folder] = groups[folder] || []).push(t);
    });
    const card = (t) => {
      const disabled = t.live || !!t.broken;
      return el("button", { type: "button", class: `tpl-card${disabled ? " tpl-disabled" : ""}`, disabled,
        "aria-current": String(t.name === current),
        title: t.live ? `Live data: ${t.about}` : t.broken ? `Can't draw: ${t.broken}` : t.name,
        on: { click: () => choose(t.name) } },
        el("img", { src: templateUrl(t.name), alt: "", loading: "lazy" }),
        el("span", { class: "tpl-card-name" }, t.name.split("/").pop().replace(/\.tpl$/, "")),
        t.live && el("small", { class: "tpl-why" }, `Live data: ${t.about}`),
        t.broken && el("small", { class: "tpl-why" }, "Can't be drawn"));
    };
    const live = state.templateDetails.filter((t) => t.live).length;
    const order = Object.keys(groups).sort((x, y) => (x === "Templates" ? -1 : y === "Templates" ? 1 : x.localeCompare(y)));
    const usableFirst = (list) => [...list].sort((x, y) => Number(x.live || !!x.broken) - Number(y.live || !!y.broken));
    $("#tpl-grid").replaceChildren(
      ...(allowBlank ? [el("section", { class: "tpl-group" }, el("div", { class: "tpl-cards" },
        el("button", { type: "button", class: "tpl-card", "aria-current": String(!current || current === "blank"), on: { click: () => choose("blank") } },
          el("span", { class: "tpl-blank" }, "Blank"), el("span", { class: "tpl-card-name" }, "No board, just the slide"))))] : []),
      ...order.map((folder) => el("section", { class: "tpl-group" },
        el("p", { class: "label" }, folder), el("div", { class: "tpl-cards" }, usableFirst(groups[folder]).map(card)))));
    $("#tpl-note").textContent = live
      ? `${live} template${live === 1 ? " shows" : "s show"} live meet data (swimmer names, events, times) that DisplayLink Plus fills in as the meet runs. A Loop Builder video would freeze those fields, so they're dimmed. Use them directly in DisplayLink Plus instead.`
      : "";
    dialog.onclose = () => resolve(picked);
    dialog.showModal();
  });
}

function lineRows(lines, max, withSize, shown = Infinity, layoutName = "") {
  const box = el("div", {});
  const redraw = () => box.replaceChildren(...lines.map((line, i) => el("div", { class: i >= shown ? "line hidden-line" : "line", title: i >= shown ? `Hidden in ${layoutName}` : null },
    el("span", { class: "n mono" }, i >= shown ? `${i + 1}·` : String(i + 1)),
    el("input", { class: "field", value: line.text ?? "", "aria-label": `Line ${i + 1} text${i >= shown ? ` (hidden in ${layoutName})` : ""}`, on: { input: (e) => { line.text = e.target.value; previewDraft(); } } }),
    withSize && seg(`Line ${i + 1} size`, opts("S", "M", "L").map(([v]) => [v, v]), line.size || "S", (v) => { line.size = v; previewDraft(); }),
    seg(`Line ${i + 1} style`, opts(...(withSize ? ["regular", "bold", "outlined", "accent"] : ["regular", "outlined", "accent"])),
      line.style || "regular", (v) => { line.style = v; previewDraft(); }),
    el("button", { class: "btn remove", type: "button", "aria-label": `Remove line ${i + 1}`, disabled: lines.length === 1,
      on: { click: () => { lines.splice(i, 1); redraw(); previewDraft(); } } }, "✕"))),
    ...(lines.length < Math.min(max, shown) ? [el("button", { class: "btn", type: "button", on: { click: () => {
      lines.push(withSize ? { text: "", size: "S" } : { text: "" }); redraw(); previewDraft(); } } }, withSize ? "+ Add a line" : "+ Add a piece")] : []));
  redraw();
  return box;
}

const LAYOUTS = [["stack", "Stack"], ["logo-center", "Logo center"], ["text-qr", "Text + QR"], ["text-picture", "Text + picture"], ["banner", "Banner"]];
const LAYOUT_INFO = {
  "stack": { max: 4, holds: "1–4 lines" },
  "logo-center": { max: 4, holds: "Lines + team logo" },
  "text-qr": { max: 4, holds: "Lines + a QR code" },
  "text-picture": { max: 4, holds: "Lines + a picture beside them" },
  "banner": { max: 2, holds: "2 lines, thick bars" },
};
// QR links are kept exactly as typed (some links only work with their capitals); no autocapitalise or autocorrect.
const linkField = (label, value, key, attrs = {}) => el("label", { class: "lbl" }, label,
  el("input", { class: "field mono", value: value ?? "", placeholder: "https://yourteam.com", inputmode: "url",
    autocapitalize: "off", autocorrect: "off", spellcheck: "false", ...attrs, on: { input: (e) => set(key, e.target.value.trim()) } }));
// Pick one of the theme's colour roles for part of a slide, shown with the event's own colours.
const ROLES = [["muted", "Muted"], ["text", "Text"], ["accent", "Accent"], ["primary", "Primary"]];
const roleColour = (label, key, fallback) => {
  const theme = { ...DEFAULTS, ...(state.event.theme || {}) };
  return group(label, seg(label, ROLES, P()[key] || fallback, (v) => set(key, v === fallback ? "" : v)),
    el("span", { class: "swatches", "aria-hidden": "true" }, ROLES.map(([k]) => el("i", { style: `background:${theme[k]}`, title: k }))));
};
const linkColour = () => roleColour("Link colour", "link_color", "muted");
// Separators between a crawl's repeats: only symbols the board font (Arial / Arimo) draws.
const SEPARATORS = [["•", "Dot"], ["●", "Big dot"], ["■", "Square"], ["♦", "Diamond"], ["♥", "Heart"], ["|", "Bar"],
  ["—", "Dash"], ["/", "Slash"], ["", "Spaces only"]];
const separatorPicker = (p) => group("Separator between repeats", el("span", { class: "seg", role: "group", "aria-label": "Separator" },
  SEPARATORS.map(([sym, name]) => el("button", { type: "button", title: name, "aria-label": name,
    "aria-pressed": String((p.separator === undefined ? "•" : String(p.separator).trim()) === sym), class: "sep-btn",
    on: { click: (e) => {
      e.currentTarget.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      e.currentTarget.setAttribute("aria-pressed", "true");
      set("separator", sym === "•" ? "" : sym || " ");
      renderEditor(); // the separator colour only applies when there's a symbol
    } } }, sym || "␣"))));
const isFullUrl = (u) => /^https?:\/\/[^\s/.]+(\.[^\s/.]+)+(\/\S*)?$/i.test(u || "");

// What the chosen layout does with this card's lines, so a switch never leaves the user guessing.
function layoutNote(p) {
  const layout = p.layout || "stack";
  const n = (p.lines || []).length;
  if (layout === "text-qr" && !isFullUrl(p.qr)) return ["warn", "Text + QR needs a link. Enter it in “QR link” below; until then the code's place shows “ADD QR LINK”."];
  if (layout === "banner" && n > 2) return ["warn", `A banner shows 2 lines. ${n === 3 ? "Line 3 is" : `Lines 3–${n} are`} kept but hidden; pick another layout to show them again.`];
  if (layout === "logo-center") return ["muted", "The team logo sits under the big (L) line. Set the logo in Theme if the card shows none."];
  if (layout === "text-qr") return ["muted", "Lines sit on the left and shrink to fit beside the code; keep them short."];
  if (layout === "text-picture" && (!p.picture || p.picture === "none")) return ["warn", "Text + picture needs a picture. Pick one under “Picture” below."];
  if (layout === "text-picture") return ["muted", "Lines sit beside the picture and shrink to fit; keep them short."];
  return ["muted", ""];
}
const miniLayout = (layout) => {
  const bar = (w, h, c = "#8A9099") => el("i", { style: `width:${w}px;height:${h}px;background:${c}` });
  const primary = (state.event.theme || {}).primary || DEFAULTS.primary; // the event's own colour, as on its slides
  if (layout === "logo-center") return el("span", { class: "mini" }, bar(30, 3), bar(52, 7, "#ECEEF0"), bar(12, 12, primary), bar(44, 3));
  if (layout === "text-qr") return el("span", { class: "mini", style: "flex-direction:row;gap:5px" }, el("span", { style: "display:flex;flex-direction:column;gap:3px;align-items:center" }, bar(34, 3), bar(40, 7, "#ECEEF0"), bar(30, 3)), bar(26, 26, "#FFFFFF"));
  if (layout === "text-picture") return el("span", { class: "mini", style: "flex-direction:row;gap:5px" }, el("span", { style: "display:flex;flex-direction:column;gap:3px;align-items:center" }, bar(34, 3), bar(40, 7, "#ECEEF0"), bar(30, 3)), bar(22, 22, primary));
  if (layout === "banner") return el("span", { class: "mini", style: "padding:0;gap:4px" }, bar(84, 4, primary), bar(60, 9, "#ECEEF0"), bar(38, 3), bar(84, 4, primary));
  return el("span", { class: "mini" }, bar(34, 3), bar(56, 8, "#ECEEF0"), bar(42, 3));
};

// A countdown or crawl drawn on a board needs the board's panel: the area it may cover.
function panelEditor(template) {
  if (!template || template === "blank") return null;
  const name = template.split("/").pop();
  const panel = state.event.panels[name];
  const values = panel ? [...panel] : [0, 0, Math.round(state.event.width * 0.55), Math.round(state.event.height * 0.82)];
  const fields = ["Left", "Top", "Width", "Height"].map((label, i) => text(label, values[i], (v) => { values[i] = Number(v); },
    { type: "number", min: "0", class: "field mono" }));
  return group(panel ? `Panel on ${name.replace(/\.tpl$/, "")}` : `${name.replace(/\.tpl$/, "")} has no panel yet`,
    el("p", { class: panel ? "muted" : "warn" }, panel ? "The area of the board this slide draws in; the rest of the board stays visible."
      : "Set the area of the board this slide may draw in (board pixels), so the rest stays visible."),
    el("div", { class: "grid" }, fields),
    el("button", { class: "btn", type: "button", style: "align-self:flex-start", on: { click: async () => {
      try { await api("/api/panels", "PUT", { template: name, panel: values }); }
      catch (err) { flash(`Panel not saved: ${err.message}`); return; }
      state.stamp = Date.now(); await loadEvent(true); renderEditor(); previewDraft(false); flash("Panel saved");
    } } }, panel ? "Update panel" : "Save panel"));
}

// ---------- the crop box: draw what shows on the board ----------
// The box keeps the board's shape. It maps to the slide's focus (its centre, 0-1) and zoom (how much
// smaller than the largest board-shaped box), exactly as the renderer crops.
const MAX_LANES = 10; // lane numbers and lanes on a page (loopgen/slides.py MAX_LANES)
const MAX_ZOOM = 3; // closer than this and the board shows the picture's pixels

function cropBox(p) {
  const fit = (p.fit || "fill") === "fit"; // Fill: a board-shaped box. Fit: any shape, fitted with the background around it.
  const bw = state.event.width, bh = state.event.height, board = bw / bh;
  const wrap = el("div", { class: "crop-wrap" });
  const img = el("img", { class: "crop-src", alt: "The picture, with the part the board shows outlined", draggable: "false",
    src: `/api/asset?path=${encodeURIComponent(p.file)}&t=${state.stamp}` });
  const box = el("div", { class: "crop-box", tabindex: "0", role: "group",
    "aria-label": fit ? "Crop box, any shape. Drag to move, drag a corner to resize; arrow keys move it, plus and minus resize it."
      : "Crop box in the board's shape. Drag to move, drag a corner to zoom; arrow keys move it, plus and minus zoom." },
    ...["nw", "ne", "sw", "se"].map((c) => el("span", { class: `crop-handle ${c}`, "data-corner": c, "aria-hidden": "true" })));
  const readout = el("span", { class: "muted mono" });
  const shades = ["top", "bottom", "left", "right"].map((side) => el("span", { class: `crop-shade ${side}`, "aria-hidden": "true" }));
  const mirror = el("img", { class: "crop-preview", alt: "What the board shows now", src: $("#preview").src });
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "pan-arrow");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<defs><marker id="pan-head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#5AA2FF"/></marker></defs><rect class="pan-end" x="0" y="0" width="0" height="0" fill="none" stroke="#5AA2FF" stroke-width="2" stroke-dasharray="6 4"/><line x1="0" y1="0" x2="0" y2="0" stroke="#5AA2FF" stroke-width="4" stroke-linecap="round" marker-end="url(#pan-head)"/>'; // fixed markup
  const line = svg.querySelector("line");
  const endBox = svg.querySelector("rect"); // where the camera stops: the box at the end of the pan
  const head = el("span", { class: "pan-handle", tabindex: "0", role: "group",
    "aria-label": "End of the pan. Drag it, or use the arrow keys, to set where the view travels to." });
  const anim = el("canvas", { class: "crop-preview", width: state.event.width, height: state.event.height, hidden: true,
    "aria-label": "The pan, playing on a loop as the board will show it" });
  wrap.append(img, ...shades, box, svg, head);
  // Older events stored a pan as start and end framings: carry its end over as the arrow's target.
  if (P().pan && !P().pan.to) {
    const end = P().pan.end || {};
    P().pan = { to: [end.x ?? (P().focus || [0.5, 0.5])[0], end.y ?? (P().focus || [0.5, 0.5])[1]] };
  }
  let iw = 0, ih = 0, full = { w: 0, h: 0 }, r = { x: 0, y: 0, w: 0, h: 0 }; // r = the box in picture pixels
  const MIN = 20; // smallest Fit box side, in picture pixels

  const whole = () => (fit ? { x: 0, y: 0, w: iw, h: ih } : { x: (iw - full.w) / 2, y: (ih - full.h) / 2, w: full.w, h: full.h });
  const fromSlide = () => {
    if (fit) {
      const c = P().crop;
      r = c ? { x: c[0] * iw, y: c[1] * ih, w: (c[2] - c[0]) * iw, h: (c[3] - c[1]) * ih } : whole();
      return;
    }
    const f = P().focus || [0.5, 0.5], zoom = Math.min(MAX_ZOOM, Math.max(1, Number(P().zoom ?? 1)));
    r.w = full.w / zoom; r.h = full.h / zoom;
    r.x = Math.min(Math.max(f[0] * iw - r.w / 2, 0), iw - r.w);
    r.y = Math.min(Math.max(f[1] * ih - r.h / 2, 0), ih - r.h);
  };
  const panEnd = (pan) => [Math.min(Math.max(pan.to[0] * iw - r.w / 2, 0), iw - r.w), Math.min(Math.max(pan.to[1] * ih - r.h / 2, 0), ih - r.h)];
  const show = () => {
    const sx = img.clientWidth / iw, sy = img.clientHeight / ih;
    const [L, T, W, H] = [r.x * sx, r.y * sy, r.w * sx, r.h * sy];
    Object.assign(box.style, { left: `${L}px`, top: `${T}px`, width: `${W}px`, height: `${H}px` });
    const [top, bottom, left, right] = shades; // darken everything the board won't show
    Object.assign(top.style, { left: "0", top: "0", width: "100%", height: `${T}px` });
    Object.assign(bottom.style, { left: "0", top: `${T + H}px`, width: "100%", bottom: "0" });
    Object.assign(left.style, { left: "0", top: `${T}px`, width: `${L}px`, height: `${H}px` });
    Object.assign(right.style, { left: `${L + W}px`, top: `${T}px`, right: "0", height: `${H}px` });
    const pan = P().pan;
    svg.style.display = head.style.display = pan ? "" : "none";
    if (pan) {
      const [cx, cy] = [L + W / 2, T + H / 2], [hx, hy] = [pan.to[0] * img.clientWidth, pan.to[1] * img.clientHeight];
      svg.setAttribute("viewBox", `0 0 ${img.clientWidth} ${img.clientHeight}`);
      Object.assign(svg.style, { width: `${img.clientWidth}px`, height: `${img.clientHeight}px` });
      line.setAttribute("x1", cx); line.setAttribute("y1", cy); line.setAttribute("x2", hx); line.setAttribute("y2", hy);
      Object.assign(head.style, { left: `${hx}px`, top: `${hy}px` });
      const [ex, ey] = panEnd(pan); // kept inside the picture, as the renderer does
      endBox.setAttribute("x", ex * sx); endBox.setAttribute("y", ey * sy);
      endBox.setAttribute("width", W); endBox.setAttribute("height", H);
    }
    const scale = fit ? Math.min(bw / r.w, bh / r.h) : full.w / r.w;
    readout.textContent = fit
      ? `showing ${Math.round(r.w)} × ${Math.round(r.h)} px of ${iw} × ${ih}, fitted at ${scale.toFixed(2)}×${scale > MAX_ZOOM ? " (blocky: draw a bigger box)" : ""}`
      : `${scale.toFixed(2)}× · showing ${Math.round(r.w)} × ${Math.round(r.h)} px of ${iw} × ${ih}`;
  };
  const save = () => {
    if (fit) {
      const all = r.x < 0.5 && r.y < 0.5 && r.w > iw - 1 && r.h > ih - 1;
      if (all) delete P().crop;
      else P().crop = [r.x / iw, r.y / ih, (r.x + r.w) / iw, (r.y + r.h) / ih].map((v) => +v.toFixed(4));
    } else {
      P().focus = [+((r.x + r.w / 2) / iw).toFixed(4), +((r.y + r.h / 2) / ih).toFixed(4)];
      P().zoom = +(full.w / r.w).toFixed(3);
      if (P().zoom <= 1.0005) delete P().zoom;
    }
    previewDraft();
  };
  const clampMove = () => { r.x = Math.min(Math.max(r.x, 0), iw - r.w); r.y = Math.min(Math.max(r.y, 0), ih - r.h); };
  // Resize from a corner, keeping the opposite corner (anchor) fixed.
  const resizeTo = (w, h, anchorX, anchorY, corner) => {
    if (fit) {
      w = Math.max(MIN, Math.min(w, corner.includes("w") ? anchorX : iw - anchorX));
      h = Math.max(MIN, Math.min(h, corner.includes("n") ? anchorY : ih - anchorY));
    } else {
      w = Math.min(full.w, Math.max(full.w / MAX_ZOOM, w));
      h = w / board;
    }
    r.x = corner.includes("w") ? anchorX - w : anchorX;
    r.y = corner.includes("n") ? anchorY - h : anchorY;
    r.w = w; r.h = h;
    clampMove();
  };

  img.addEventListener("load", () => {
    iw = img.naturalWidth; ih = img.naturalHeight;
    full = iw / ih > board ? { w: ih * board, h: ih } : { w: iw, h: iw / board };
    fromSlide(); show();
  });
  new ResizeObserver(() => iw && show()).observe(img);

  box.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    box.setPointerCapture(e.pointerId);
    const scale = iw / img.clientWidth;
    const corner = e.target.dataset.corner;
    const start = { px: e.clientX, py: e.clientY, ...r };
    const anchor = corner && { x: corner.includes("w") ? start.x + start.w : start.x, y: corner.includes("n") ? start.y + start.h : start.y };
    const move = (ev) => {
      const dx = (ev.clientX - start.px) * scale, dy = (ev.clientY - start.py) * scale;
      if (!corner) { r.x = start.x + dx; r.y = start.y + dy; clampMove(); }
      else resizeTo(start.w + (corner.includes("w") ? -dx : dx), start.h + (corner.includes("n") ? -dy : dy), anchor.x, anchor.y, corner);
      show(); save();
    };
    const up = () => { box.removeEventListener("pointermove", move); box.removeEventListener("pointerup", up); };
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up);
  });
  box.addEventListener("keydown", (e) => {
    const step = (e.shiftKey ? 0.1 : 0.02) * Math.max(iw, ih);
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) { r.x += moves[e.key][0]; r.y += moves[e.key][1]; clampMove(); }
    else if (["+", "=", "-", "_"].includes(e.key)) {
      const k = e.key === "+" || e.key === "=" ? 0.92 : 1.08, cx = r.x + r.w / 2, cy = r.y + r.h / 2;
      let w = r.w * k, h = r.h * k;
      if (fit) { w = Math.max(MIN, Math.min(iw, w)); h = Math.max(MIN, Math.min(ih, h)); }
      else { w = Math.min(full.w, Math.max(full.w / MAX_ZOOM, w)); h = w / board; }
      r = { x: cx - w / 2, y: cy - h / 2, w, h }; clampMove();
    } else return;
    e.preventDefault(); show(); save();
  });

  head.addEventListener("pointerdown", (e) => {
    e.preventDefault(); e.stopPropagation();
    head.setPointerCapture(e.pointerId);
    const rect = img.getBoundingClientRect();
    const move = (ev) => {
      P().pan.to = [Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width)), Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))]
        .map((v) => +v.toFixed(4));
      show(); previewDraft();
    };
    const up = () => { head.removeEventListener("pointermove", move); head.removeEventListener("pointerup", up); };
    head.addEventListener("pointermove", move);
    head.addEventListener("pointerup", up);
  });
  head.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.05 : 0.01;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (!moves[e.key]) return;
    e.preventDefault();
    P().pan.to = P().pan.to.map((v, k) => +Math.min(1, Math.max(0, v + moves[e.key][k])).toFixed(4));
    show(); previewDraft();
  });

  // "On the board", playing the pan on a loop from the arrow's start, drawn the way the renderer does it.
  let raf = 0;
  const play = () => {
    cancelAnimationFrame(raf);
    const pan = P().pan;
    mirror.hidden = !!pan; anim.hidden = !pan;
    if (!pan || !iw) return;
    const ctx = anim.getContext("2d");
    const seconds = Number(P().hold ?? currentLoop().hold) || 10, began = performance.now();
    const tick = (now) => {
      if (!anim.isConnected) return; // the editor moved on
      const t = ((now - began) / 1000 % (seconds + 0.6)) / seconds; // a short rest at the end, then from the start again
      const u = Math.min(1, t), ease = 0.7 * u + 0.3 * u * u * (3 - 2 * u);
      const [tx, ty] = panEnd(pan);
      const x = r.x + (tx - r.x) * ease, y = r.y + (ty - r.y) * ease;
      ctx.fillStyle = (state.event.theme || {}).background || "#000000";
      ctx.fillRect(0, 0, bw, bh);
      if (fit) { const k = Math.min(bw / r.w, bh / r.h), w = r.w * k, h = r.h * k; ctx.drawImage(img, x, y, r.w, r.h, (bw - w) / 2, (bh - h) / 2, w, h); }
      else ctx.drawImage(img, x, y, r.w, r.h, 0, 0, bw, bh);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  };
  img.addEventListener("load", play);
  const onHold = () => { if (!anim.isConnected) document.removeEventListener("holdchange", onHold); else if (P().pan) play(); };
  document.addEventListener("holdchange", onHold);
  const panToggle = seg("Pan", [["still", "Hold still"], ["pan", "Pan"]], P().pan ? "pan" : "still", (v) => {
    if (v === "pan") {
      const cx = (r.x + r.w / 2) / iw, cy = (r.y + r.h / 2) / ih;
      P().pan = { to: [+Math.min(1, cx + 0.3).toFixed(4), +cy.toFixed(4)] };
    } else delete P().pan;
    show(); play(); previewDraft(); setupScrub({ type: "image", raw: state.draft }); renderEditorHint();
  });
  const hint = el("p", { class: "muted" });
  const renderEditorHint = () => { hint.textContent = P().pan
    ? "The box is where the camera starts. Drag the arrowhead to where it should end: the view, same size, travels along the arrow over the slide's hold. “On the board” plays it on a loop."
    : fit ? "Draw a box of any shape around the part to show: it's fitted on the board whole, with the background colour around it. Drag a corner to reshape it."
      : "Drag the box to choose what fills the board; drag a corner to zoom in or out. The box keeps the board's shape so nothing is stretched."; };
  renderEditorHint();
  const replay = () => P().pan && play(); // restart the loop after the box or arrow changes
  box.addEventListener("pointerup", replay); head.addEventListener("pointerup", replay);
  box.addEventListener("keyup", replay); head.addEventListener("keyup", replay);

  return group("What the board shows", el("div", { class: "crop-row" }, wrap,
      el("figure", { class: "crop-mirror" }, mirror, anim, el("figcaption", { class: "muted" }, "On the board"))),
    el("div", { class: "row" }, panToggle),
    el("div", { class: "row" }, readout,
      el("button", { class: "btn", type: "button", on: { click: () => { r = whole(); show(); save(); } } }, "Whole picture")),
    hint);
}

// ---------- lanes: guest lane assignments ----------
const teamLogo = (id) => `/api/teams/${encodeURIComponent(id)}/logo?t=${state.stamp}`;

// (first, last, per page) for a lanes slide, as the renderer works it out (loopgen/slides.py lane_range).
function laneRange(p) {
  const first = Math.max(0, Math.min(Number(p.first ?? 1), MAX_LANES));
  let last = p.last != null ? Number(p.last) : first + Number(p.count || (p.lanes || []).length || 8) - 1;
  last = Math.max(first, Math.min(last, MAX_LANES, first + MAX_LANES - 1));
  const perPage = Math.max(1, Math.min(Number(p.per_page) || last - first + 1, last - first + 1));
  return [first, last, perPage];
}
const pagesLabel = (sl) => {
  if (sl.type !== "lanes") return "";
  const [first, last, per] = laneRange(propsOf(sl.raw)), pages = Math.ceil((last - first + 1) / per);
  return pages > 1 ? ` × ${pages}` : "";
};

// One team in a run of lanes at once (a dual meet's visitors in 5–8), instead of a pick per lane. It starts on the
// visiting team and the second half of the lanes when the event has one, else on your team and every lane.
function fillLanes(first, last) {
  if (!state.teams.length) return null;
  const visitor = visitorTeam(), lanes = Array.from({ length: last - first + 1 }, (_, k) => first + k);
  const from = visitor ? first + Math.ceil(lanes.length / 2) : first;
  const pick = (label, value) => el("select", { class: "field", "aria-label": label },
    lanes.map((n) => el("option", { value: n, selected: n === value }, String(n))));
  const fromPick = pick("Fill from lane", from), toPick = pick("Fill to lane", last);
  const teamPick = el("select", { class: "field", "aria-label": "Team for those lanes" },
    state.teams.map((t) => el("option", { value: t.id, selected: visitor ? t.id === visitor.id : !!t.home }, t.name)));
  return el("div", { class: "row fill-lanes" }, el("span", {}, "Fill lanes"), fromPick, el("span", {}, "to"), toPick,
    el("span", {}, "with"), teamPick, el("button", { class: "btn", type: "button", on: { click: async () => {
      const a = Number(fromPick.value), b = Number(toPick.value);
      if (b < a) { flash("The first lane comes before the last one."); return; }
      let lane;
      try { lane = await api(`/api/teams/${encodeURIComponent(teamPick.value)}/use`, "POST"); }
      catch (err) { flash(err.message); return; }
      for (let n = a; n <= b; n++) P().lanes[n - first] = { ...lane };
      previewDraft(); renderEditor();
      flash(`${lane.name} in lanes ${a}–${b}`);
    } } }, "Fill"));
}

function lanesEditor(p) {
  p.lanes = p.lanes || [];
  if (p.count != null && p.last == null) { // older slides kept a count: store the lane range instead
    p.last = laneRange(p)[1];
    delete p.count;
  }
  const [first, last, perPage] = laneRange(p), count = last - first + 1, pages = Math.ceil(count / perPage);
  while (p.lanes.length < count) p.lanes.push({});
  const numbers = (from, to) => Array.from({ length: to - from + 1 }, (_, k) => from + k);
  const numberPick = (label, value, options, key) => el("label", { class: "lbl" }, label, el("select", { class: "field",
    on: { change: (e) => { set(key, Number(e.target.value)); renderEditor(); setupScrub({ type: "lanes", raw: state.draft }); } } },
    options.map(([v, name]) => el("option", { value: v, selected: v === value }, name))));
  const rows = Array.from({ length: count }, (_, i) => {
    const lane = P().lanes[i];
    const match = state.teams.find((t) => lane.logo && lane.logo.endsWith(`/${t.logo}`));
    const pick = el("select", { class: "field", "aria-label": `Team for lane ${first + i}`, on: { change: async (e) => {
      const id = e.target.value;
      if (id === "__manage") { // a team added from this lane's list goes in this lane, if it's still empty
        e.target.value = match ? match.id : "";
        manageTeams(afterAdding(async (team) => {
          if (P().lanes[i] && P().lanes[i].name) return;
          try { P().lanes[i] = await api(`/api/teams/${encodeURIComponent(team.id)}/use`, "POST"); }
          catch (err) { flash(err.message); return; }
          previewDraft(); renderEditor();
        }));
        return;
      }
      if (!id) { P().lanes[i] = {}; previewDraft(); renderEditor(); return; }
      try { P().lanes[i] = await api(`/api/teams/${encodeURIComponent(id)}/use`, "POST"); }
      catch (err) { flash(err.message); return; }
      previewDraft(); renderEditor();
    } } },
      el("option", { value: "" }, "— empty lane —"),
      state.teams.map((t) => el("option", { value: t.id, selected: match && match.id === t.id }, t.name)),
      el("option", { value: "__manage" }, "Add or manage teams…"));
    return el("div", { class: "line" },
      el("span", { class: "mono lane-n" }, `${p.label ?? "LANE"} ${first + i}`.trim()),
      lane.logo ? el("img", { class: "lane-logo", alt: "", src: `/api/asset?path=${encodeURIComponent(lane.logo)}&t=${state.stamp}` }) : el("span", { class: "lane-logo" }),
      pick,
      el("input", { class: "field", value: lane.name ?? "", placeholder: "Name on the board", "aria-label": `Name shown for lane ${first + i}`,
        on: { input: (e) => { P().lanes[i].name = e.target.value; previewDraft(); } } }));
  });
  return [
    text("Title", p.title, (v) => set("title", v)),
    el("div", { class: "grid" },
      numberPick("First lane", first, numbers(0, MAX_LANES).map((v) => [v, String(v)]), "first"),
      numberPick("Last lane", last, numbers(first, Math.min(MAX_LANES, first + MAX_LANES - 1)).map((v) => [v, String(v)]), "last"),
      numberPick("Lanes per page", perPage, numbers(1, count).reverse().map((v) => [v, v === count ? `All ${count}` : String(v)]), "per_page"),
      text("Label", p.label ?? "LANE", (v) => { set("label", v === "LANE" ? "" : v); }),
      holdField()),
    roleColour("Lane label colour", "label_color", "accent"),
    pages > 1 && el("p", { class: "muted" }, `Shows ${pages} pages, ${perPage} lanes at a time, each for the hold time.`),
    group(`Teams by lane · ${count} lanes`, fillLanes(first, last), ...rows,
      el("p", { class: "muted" }, "Pick a team from your library (its logo is copied into this event), then adjust the name if needed. Put a | where a long name should break onto two lines."),
      el("button", { class: "btn", type: "button", style: "align-self:flex-start", on: { click: () => manageTeams() } }, "Add or manage teams…")),
  ];
}

// After the Teams dialog closes: hand the team added there to `use` (the lane, card or visitor it was opened from).
// With several added in one visit, the last one added and still there, a team added again (a new logo) included;
// teams are listed by name, so the dialog notes the order.
function afterAdding(use) {
  state.teamsAdded = [];
  return () => {
    const last = [...state.teamsAdded].reverse().map((id) => state.teams.find((t) => t.id === id)).find(Boolean);
    if (last) use(last);
  };
}

$("#team-pick").addEventListener("click", () => $("#team-file").click()); // the app's own button for the file picker
$("#team-file").addEventListener("change", (e) => { $("#team-file-name").textContent = e.target.files[0]?.name || "No logo chosen"; });

// The team library: logos kept for every event.
async function manageTeams(after) {
  const dialog = $("#teams-dialog");
  const render = async () => {
    state.teams = await api("/api/teams");
    $("#teams-list").replaceChildren(...(state.teams.length ? state.teams.map((t) => t.home ? el("li", {},
      el("img", { src: teamLogo(t.id), alt: "", class: "lane-logo" }),
      el("span", { class: "grow" }, t.name), el("span", { class: "muted" }, "Your team: its name and logo are in Settings"))
    : el("li", {},
      el("img", { src: teamLogo(t.id), alt: "", class: "lane-logo" }),
      el("input", { class: "field grow", value: t.name, "aria-label": `Name for ${t.name}`,
        on: { change: async (e) => { await api(`/api/teams/${encodeURIComponent(t.id)}`, "PUT", { name: e.target.value }); } } }),
      el("button", { class: "btn", type: "button", on: { click: async () => { await api(`/api/teams/${encodeURIComponent(t.id)}`, "DELETE"); render(); } } }, "Remove")))
      : [el("li", { class: "muted" }, "No teams yet. Add each team once; every event can use them.")]));
  };
  await render();
  $("#team-status").textContent = "";
  dialog.onclose = () => { renderEditor(); if (after) after(); };
  dialog.showModal();
  $("#team-add").onclick = async () => {
    const file = $("#team-file").files[0], name = $("#team-name").value.trim();
    if (!name || !file) { $("#team-status").textContent = "Give the team a name and pick its logo."; return; }
    const form = new FormData();
    form.append("file", file); form.append("name", name); form.append("trim", $("#team-trim").checked ? "true" : "false");
    const res = await fetch("/api/teams", { method: "POST", body: form });
    if (!res.ok) { $("#team-status").textContent = await failure(res); return; }
    state.teamsAdded.push((await res.json()).id); // in the order added, for afterAdding
    $("#team-name").value = ""; $("#team-file").value = ""; $("#team-file-name").textContent = "No logo chosen";
    $("#team-status").textContent = `Added ${name}.`;
    await render(); // so Done straight after hands over the team just added
  };
}

// A logo-center card's picture: the theme logo, a team's logo from Teams (a visitor's welcome card shows theirs,
// not ours), an uploaded picture, or none. A team's logo is copied into the event, as a lane's is.
function cardPicture(p, layout = "logo-center") {
  const logoCenter = layout === "logo-center"; // the one layout whose picture is the theme logo unless changed
  const pic = p.picture || (logoCenter ? "" : "none");
  const team = pic.startsWith("assets/teams/") ? state.teams.find((t) => pic.endsWith(`/${t.logo}`)) : null;
  const choosing = state.teamPickFor === `${state.loop}:${state.n}`; // "A team's logo" pressed, no team picked yet
  const kind = pic.startsWith("assets/teams/") || choosing ? "team" : !pic || pic === "logo" ? "logo" : pic === "none" ? "none" : "upload";
  const shown = kind !== "none";
  const useTeam = async (id) => {
    try { set("picture", (await api(`/api/teams/${encodeURIComponent(id)}/use`, "POST")).logo); }
    catch (err) { flash(err.message); return; }
    state.teamPickFor = null;
    renderEditor();
  };
  const teamPick = kind === "team" && el("select", { class: "field", "aria-label": "Team whose logo the card shows", on: { change: (e) => {
    if (e.target.value === "__manage") { // a team added from here becomes the card's picture
      e.target.value = team ? team.id : "";
      manageTeams(afterAdding((added) => useTeam(added.id)));
      return;
    }
    if (e.target.value) useTeam(e.target.value);
  } } },
    !team && el("option", { value: "" }, "Pick a team…"),
    state.teams.map((t) => el("option", { value: t.id, selected: team && team.id === t.id }, t.name)),
    el("option", { value: "__manage" }, "Add or manage teams…"));
  const own = kind === "upload" && pic; // a picture of this event's own: change it, or keep it for other events
  const ownRow = own && el("div", { class: "row" }, el("span", { class: "mono grow" }, pic.split("/").pop()),
    el("button", { class: "btn", type: "button", on: { click: () => pickPicture((file) => { set("picture", file); renderEditor(); }) } }, "Change…"),
    !pic.startsWith("assets/pictures/") && el("button", { class: "btn", type: "button", on: { click: () => keepPicture(pic) } }, "Keep in Pictures"));
  const box = group("Picture", seg("Picture", [["logo", "Theme logo"], ["team", "A team’s logo"], ["upload", "A picture…"], ["none", "None"]], kind,
    async (v) => {
      state.teamPickFor = null;
      if (v === "upload") await pickPicture((file) => { set("picture", file); renderEditor(); });
      else if (v === "team") { // straight to the only other team; else choose from the list that appears
        const others = state.teams.filter((t) => !t.home);
        if (others.length === 1) await useTeam(others[0].id); else { state.teamPickFor = `${state.loop}:${state.n}`; renderEditor(); }
      } else set("picture", logoCenter ? (v === "logo" ? "" : v) : (v === "none" ? "" : v));
      renderEditor();
    }), teamPick, ownRow,
    shown && layout === "text-picture" && seg("Picture side", [["left", "Left of the lines"], ["right", "Right of the lines"]], p.picture_side || "right",
      (v) => set("picture_side", v === "right" ? "" : v)),
    shown && layout !== "text-picture" && seg("Where the picture sits", [["above", "Above the lines"], ["middle", "Under the big line"], ["below", "Below the lines"]],
      p.picture_place || "middle", (v) => set("picture_place", v === "middle" ? "" : v)));
  box.classList.add("wide"); // four choices: a full row, so their names don't wrap
  return box;
}

const EDITORS = {
  board: (p) => [templateSelect("Template", p.template, (v) => { set("template", v); renderEditor(); }),
    holdField()],
  card: (p) => {
    p.lines = p.lines || [{ text: "", size: "L" }];
    const layout = p.layout || "stack";
    const info = LAYOUT_INFO[layout];
    const [noteKind, note] = layoutNote(p);
    const layoutName = LAYOUTS.find(([v]) => v === layout)[1];
    return [
      group("Layout", el("div", { class: "tiles" }, LAYOUTS.map(([v, name]) => el("button", { class: "tile", type: "button", "aria-pressed": String(v === layout),
        on: { click: () => {
          P().layout = v; previewDraft(); renderEditor();
          if (v === "text-qr" && !isFullUrl(P().qr)) document.querySelector("#qr-link")?.focus();
        } } }, miniLayout(v), name, el("small", { class: "muted" }, LAYOUT_INFO[v].holds)))),
        note && el("p", { class: noteKind, role: "status" }, note)),
      group(p.lines.length > info.max ? `Lines · ${info.max} of ${p.lines.length} shown` : `Lines · up to ${info.max}`,
        lineRows(p.lines, 4, true, info.max, layoutName)),
      el("div", { class: "grid" },
        cardPicture(p, layout),
        layout === "text-qr" && linkField("QR link", p.qr, "qr", { id: "qr-link" }),
        layout === "text-qr" && el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: !!p.show_url,
          on: { change: (e) => { set("show_url", e.target.checked || ""); renderEditor(); } } }), "Show the link under the QR"),
        layout === "text-qr" && p.show_url && linkColour(p),
        group("Accent bars", seg("Accent bars", opts("top", "bottom", "both", "none"), p.bars || "both", (v) => set("bars", v))),
        holdField()),
    ];
  },
  qr: (p) => {
    p.heading = p.heading || [];
    p.caption = p.caption || ["Scan with your", "phone camera"];
    const listField = (key, i, label) => text(label, P()[key][i], (v) => {
      const lines = [...P()[key]];
      lines[i] = v;
      while (lines.length && !lines[lines.length - 1]) lines.pop(); // drop empty trailing lines
      P()[key] = Array.from(lines, (x) => x || "");
      previewDraft();
    });
    return [linkField("Link", p.url, "url"),
      el("div", { class: "grid" }, listField("heading", 0, "Heading line 1"), listField("heading", 1, "Heading line 2"),
        listField("caption", 0, "Caption line 1"), listField("caption", 1, "Caption line 2")),
      el("div", { class: "grid" },
        el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: p.show_url !== false, on: { change: (e) => { set("show_url", e.target.checked ? "" : false); renderEditor(); } } }), "Show the link under the caption"),
        p.show_url !== false && linkColour(p),
        group("QR side", seg("QR side", opts("left", "right"), p.side || "right", (v) => set("side", v))), holdField())];
  },
  image: (p) => [
    el("div", { class: "row" }, el("span", { class: "mono" }, p.file), el("button", { class: "btn", type: "button",
      on: { click: () => pickPicture((file) => { ["focus", "zoom", "crop", "pan"].forEach((k) => delete P()[k]); set("file", file); renderEditor(); setupScrub({ type: "image", raw: state.draft }); }) } }, "Replace picture…"),
      !String(p.file).startsWith("assets/pictures/") && el("button", { class: "btn", type: "button", on: { click: () => keepPicture(p.file) } }, "Keep in Pictures")),
    el("div", { class: "grid" },
      group("Fit", seg("Fit", [["fill", "Fill the board"], ["fit", "Fit a part"]], p.fit || "fill", (v) => { set("fit", v); renderEditor(); })),
      holdField()),
    cropBox(p),
  ],
  countdown: (p) => [el("div", { class: "grid" },
    text("Label", p.label ?? "WARM-UP", (v) => set("label", v), { maxlength: "12" }),
    text("Length (m:ss)", p.length ?? "10:00", (v) => { set("length", v); setupScrub({ type: "countdown", raw: state.draft }); }, { class: "field mono" }),
    text("Sublabel", p.sublabel ?? "time remaining", (v) => set("sublabel", v)),
    text("Hold at 0:00 (s)", p.hold_at_zero ?? 5, (v) => { set("hold_at_zero", Number(v)); setupScrub({ type: "countdown", raw: state.draft }); }, { type: "number", min: "0", max: "60" })),
    templateSelect("Background", p.background || "blank", (v) => { set("background", v === "blank" ? "" : v); renderEditor(); }, true),
    panelEditor(p.background)],
  lanes: (p) => lanesEditor(p),
  crawl: (p) => {
    p.segments = p.segments || [{ text: "" }];
    return [group(`Message · ${p.segments.length} of 4 pieces`, lineRows(p.segments, 4, false)), separatorPicker(p),
      String(p.separator ?? "•").trim() && roleColour("Separator colour", "separator_color", "primary"),
      el("div", { class: "grid" },
        text("Length (m:ss)", p.length ?? "3:00", (v) => { set("length", v); setupScrub({ type: "crawl", raw: state.draft }); }, { class: "field mono" }),
        group("Speed", seg("Speed", opts("slow", "medium", "fast"), p.speed || "medium", (v) => set("speed", v))),
        group("Area", seg("Area", [["full", "Full board"], ["panel", "Board panel"]], p.area || "full", (v) => {
          if (v === "panel" && !P().background) P().background = staticTemplates()[0];
          set("area", v); renderEditor();
        })),
        (p.area === "panel") && templateSelect("Board", p.background, (v) => { set("background", v); renderEditor(); })),
      p.area === "panel" && panelEditor(p.background)];
  },
};

const framing = () => { const p = P(); const f = p.focus || [0.5, 0.5]; return { x: f[0], y: f[1], zoom: Number(p.zoom ?? 1) }; };

function renderEditor() {
  const kind = kindOf(state.draft);
  const p = P();
  if (p.ref) {
    $("#editor").replaceChildren(el("p", { class: "muted" }, `This slide is linked to “${p.ref}”. Edit it where it's defined and every loop that uses it changes.`));
    return;
  }
  $("#editor").replaceChildren(...EDITORS[kind](p).flat().filter(Boolean), extraPictures(p));
}

// Extra pictures over any slide: a badge, league logos, the duck in a corner. As many as wanted, each placed
// on a 3×3 grid of the board and sized; drawn in order, so a later one sits on top.
const PLACES = [["top-left", "↖"], ["top", "↑"], ["top-right", "↗"], ["left", "←"], ["center", "•"], ["right", "→"],
  ["bottom-left", "↙"], ["bottom", "↓"], ["bottom-right", "↘"]];
const PLACE_NAMES = { "top-left": "Top left", top: "Top", "top-right": "Top right", left: "Left", center: "Centre",
  right: "Right", "bottom-left": "Bottom left", bottom: "Bottom", "bottom-right": "Bottom right" };
function extraPictures(p) {
  const list = Array.isArray(p.badges) ? p.badges : [];
  const save = (next) => { set("badges", next.length ? next : ""); renderEditor(); };
  const edit = (i, key, value) => save(list.map((b, j) => (j === i ? { ...b, [key]: value } : b)));
  const rows = list.map((b, i) => el("div", { class: "extra-pic" },
    el("img", { class: "lane-logo", alt: "", src: `/api/asset?path=${encodeURIComponent(b.file)}&t=${state.stamp}` }),
    el("span", { class: "place-grid", role: "group", "aria-label": `Where picture ${i + 1} sits` }, PLACES.map(([v, arrow]) =>
      el("button", { type: "button", title: PLACE_NAMES[v], "aria-label": PLACE_NAMES[v], "aria-pressed": String((b.place || "top-right") === v),
        on: { click: () => edit(i, "place", v) } }, arrow))),
    seg(`Size of picture ${i + 1}`, [["S", "S"], ["M", "M"], ["L", "L"], ["XL", "XL"]], b.size || "M", (v) => edit(i, "size", v)),
    el("button", { class: "btn", type: "button", on: { click: () => pickPicture((file) => edit(i, "file", file)) } }, "Change…"),
    el("button", { class: "btn icon", type: "button", "aria-label": `Remove picture ${i + 1}`, title: "Remove",
      on: { click: () => save(list.filter((_, j) => j !== i)) } }, "✕")));
  const taken = new Set(list.map((b) => b.place || "top-right"));
  const nextPlace = ["top-right", "top-left", "bottom-right", "bottom-left"].find((c) => !taken.has(c)) || "top-right";
  return group(`Extra pictures${list.length ? ` · ${list.length}` : ""}`, ...rows,
    el("p", { class: "muted" }, "Small pictures over this slide, like an app badge or league logos. Add as many as you like."),
    el("button", { class: "btn", type: "button", style: "align-self:flex-start",
      on: { click: () => pickPicture((file) => save([...list, { file, place: nextPlace, size: "M" }])) } }, "+ Add a picture"));
}

// A picture for a slide: one kept in Pictures (copied into this event), a new one added to Pictures, or a
// file used just this once. Resolves to make(path in the event), or null when closed without one.
function pickPicture(make) {
  return managePictures({ choose: true }).then((file) => (file ? make(file) : null));
}

async function uploadOnce() {
  const picker = $("#picker");
  picker.value = "";
  const file = await new Promise((resolve) => {
    picker.onchange = () => resolve(picker.files[0]);
    picker.click();
  });
  if (!file) return null;
  const form = new FormData();
  form.append("file", file);
  flash("Adding picture…");
  const res = await fetch("/api/pictures", { method: "POST", body: form });
  if (!res.ok) { flash(`Picture not added: ${await failure(res)}`); return null; }
  const data = await res.json();
  flash(`Picture added (${Math.round(data.bytes / 1024)} KB working copy)`);
  return data.file;
}

const pictureSrc = (id) => `/api/library/pictures/${encodeURIComponent(id)}/image?t=${state.stamp}`;
const usePicture = async (id) => (await api(`/api/library/pictures/${encodeURIComponent(id)}/use`, "POST")).file;

// The Pictures dialog. With choose, a click on a picture uses it; without, it's for naming and removing them.
function managePictures({ choose = false } = {}) {
  const dialog = $("#pictures-dialog"), grid = $("#pictures-grid"), status = $("#picture-status");
  let chosen = null;
  const done = (file) => { chosen = file; dialog.close(); };
  const render = async () => {
    const pictures = await api("/api/library/pictures");
    grid.classList.toggle("choosing", choose);
    grid.replaceChildren(...(pictures.length ? pictures.map((pic) => el("li", {},
      el("button", { class: "thumb", type: "button", disabled: !choose, title: choose ? `Use ${pic.name}` : pic.name,
        "aria-label": choose ? `Use ${pic.name}` : pic.name,
        on: { click: async () => { if (choose) done(await usePicture(pic.id)); } } },
        el("img", { src: pictureSrc(pic.id), alt: "" })),
      el("input", { class: "field", value: pic.name, "aria-label": `Name for ${pic.name}`,
        on: { change: async (e) => { await api(`/api/library/pictures/${encodeURIComponent(pic.id)}`, "PUT", { name: e.target.value }); } } }),
      el("div", { class: "row between" }, el("span", { class: "muted" }, pic.size ? `${pic.size[0]}×${pic.size[1]}` : ""),
        el("button", { class: "btn", type: "button", on: { click: async () => {
          await api(`/api/library/pictures/${encodeURIComponent(pic.id)}`, "DELETE");
          status.textContent = `Removed ${pic.name}. Events that use it keep their copy.`;
          render();
        } } }, "Remove"))))
      : [el("li", { class: "empty" }, "No pictures yet. Add each badge, logo or picture once; every event can use it.")]));
  };
  $("#pictures-intro").textContent = choose
    ? "Pick a picture for this slide, or add one. A picture from here is copied into this event."
    : "Badges, league logos and other pictures, kept for every event. Using one copies it into this event.";
  $("#picture-add").textContent = choose ? "Add and use" : "Add picture";
  $("#picture-once").hidden = !choose;
  $("#pictures-close").textContent = choose ? "Cancel" : "Done";
  status.textContent = "";
  $("#picture-file").onchange = () => { // a name from the file, until one is typed
    const f = $("#picture-file").files[0], name = $("#picture-name");
    if (f && !name.value.trim()) name.value = f.name.replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ");
  };
  $("#picture-add").onclick = async () => {
    const file = $("#picture-file").files[0], name = $("#picture-name").value.trim();
    if (!name || !file) { status.textContent = "Give the picture a name and pick its file."; return; }
    const form = new FormData();
    form.append("file", file); form.append("name", name); form.append("trim", $("#picture-trim").checked ? "true" : "false");
    status.textContent = "Adding…";
    const res = await fetch("/api/library/pictures", { method: "POST", body: form });
    if (!res.ok) { status.textContent = await failure(res); return; }
    const data = await res.json();
    $("#picture-name").value = ""; $("#picture-file").value = ""; $("#picture-trim").checked = false;
    if (choose) { done(await usePicture(data.id)); return; }
    status.textContent = `Added ${name}.`;
    render();
  };
  $("#picture-once").onclick = async () => { const file = await uploadOnce(); if (file) done(file); };
  return new Promise((resolve) => {
    dialog.onclose = () => { if (!choose) renderEditor(); resolve(chosen); };
    render().then(() => dialog.showModal());
  });
}

// Keep a picture this event already has in Pictures, named from its file (renamed in Pictures if need be).
async function keepPicture(path) {
  const name = path.split("/").pop().replace(/\.[^.]+$/, "").replace(/[-_]+/g, " ");
  try {
    const kept = await api("/api/library/pictures/from-event", "POST", { path, name });
    flash(`Kept in Pictures as “${kept.name}”`);
  } catch (err) { flash(`Not kept: ${err.message}`); }
}

async function loadChecks() {
  const issues = await api("/api/checks");
  state.issues = issues;
  markIssues();
  $("#checks").replaceChildren(issues.length
    ? el("ul", {}, issues.map((i) => el("li", { class: i.level }, `${i.level}: ${i.loop}${i.slide ? ", slide " + i.slide : ""}: ${i.message}`)))
    : el("p", {}, "Checks: no problems in any loop."));
}

// ---------- export ----------

$("#open-export").addEventListener("click", () => {
  if ($("#run-export").disabled) { $("#export").showModal(); return; } // still exporting: show it as it was
  replaceAgreed = null;
  exportButton("Export selected");
  $("#export-loops").replaceChildren(...state.event.loops.map((lp, i) => el("label", { class: "job" },
    el("input", { type: "checkbox", checked: true, value: i, "aria-label": `Export ${lp.name}` }),
    el("span", {}, lp.name, " ", el("span", { class: "mono" }, `· ${clock(lp.length)}`)),
    el("span", { class: "muted", id: `job-${i}` }, ""))));
  api("/api/home").then((h) => { // the last folder used, else the app's default (Movies › Loop Builder on a Mac)
    if (!$("#out-dir").value) $("#out-dir").value = h.settings.export_dir || h.exports;
  });
  $("#show-export").hidden = true;
  $("#export-status").textContent = "";
  $("#export").showModal();
});

$("#pick-out").addEventListener("click", () => pickFolder($("#out-dir")));
// Files are named by loop, so exporting another meet into the same folder replaces the last one's. Say so first:
// the first click lists what would be replaced, a second click on "Replace and export" goes ahead.
let replaceAgreed = null; // the choices the person agreed to replace files for
const exportButton = (text) => { $("#run-export").textContent = text; };
$("#run-export").addEventListener("click", async () => {
  const outDir = $("#out-dir").value.trim();
  if (!outDir) { $("#export-status").textContent = "Pick an export folder first."; return; }
  api("/api/settings", "PUT", { export_dir: outDir }).catch(() => {}); // remembered for next time
  const loops = [...document.querySelectorAll("#export-loops input:checked")].map((c) => Number(c.value));
  const formats = [$("#fmt-wmv").checked && "wmv", $("#fmt-png").checked && "png"].filter(Boolean);
  if (!formats.length && !$("#mp4").checked) { $("#export-status").textContent = "Pick at least one thing to make."; return; }
  const choice = JSON.stringify([outDir, loops, formats, $("#mp4").checked]);
  if (replaceAgreed !== choice) {
    let existing = [];
    try { existing = (await api("/api/export/existing", "POST", { loops, out_dir: outDir, formats, preview_mp4: $("#mp4").checked })).files; }
    catch (err) { /* the export itself says what's wrong */ }
    if (existing.length) {
      replaceAgreed = choice;
      const when = new Date(Math.max(...existing.map((f) => f.modified)) * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      const names = existing.slice(0, 3).map((f) => f.name).join(", ") + (existing.length > 3 ? ` and ${existing.length - 3} more` : "");
      $("#export-status").textContent = `This folder already has ${existing.length === 1 ? "a file" : `${existing.length} files`} from an earlier export (last made ${when}): ${names}. `
        + "Replace and export writes over them (and clears this loop’s older stills), or choose another folder to keep them.";
      exportButton("Replace and export");
      return;
    }
  }
  const replace = replaceAgreed === choice;
  replaceAgreed = null;
  exportButton("Export selected");
  let job;
  const run = $("#run-export");
  run.disabled = true; // one export at a time: a second would write the same files
  try {
    try { job = await api("/api/export", "POST", { loops, out_dir: outDir, formats, preview_mp4: $("#mp4").checked, replace }); }
    catch (err) { $("#export-status").textContent = err.message; return; }
    while (job.state === "running") {
      const through = job.fraction ? ` · ${Math.floor(job.fraction * 100)}%` : ""; // how far through this loop
    $("#export-status").textContent = `Rendering ${job.current || "…"}${through} (${job.done.length} of ${job.total} done)`;
      await new Promise((r) => setTimeout(r, 500));
      job = await api(`/api/jobs/${job.id}`);
    }
  } finally { run.disabled = false; }
  job.done.forEach((d) => {
    const i = state.event.loops.findIndex((lp) => lp.name === d.loop);
    const skipped = d.skipped && d.skipped.length ? ` · no PNG for slide ${d.skipped.map((x) => x.slide).join(", ")} (moves; in the WMV)` : "";
    if (i >= 0) $(`#job-${i}`).textContent = `Saved ${d.files.length} file${d.files.length === 1 ? "" : "s"} · ${(d.bytes / 1e6).toFixed(1)} MB${skipped}`;
  });
  $("#export-status").textContent = job.state === "done" ? `Done in ${job.seconds} s. Files are in ${outDir}.` : `Export failed: ${job.error}`;
  $("#show-export").hidden = !(job.state === "done" && native() && native().show_folder); // the app window can open it
  $("#show-export").onclick = () => native().show_folder(outDir);
});

// ---------- undo, theme, versions, linking ----------

async function stepHistory(which) {
  try { const { changed } = await api(`/api/${which}`, "POST"); if (!changed) return; }
  catch (err) { flash(err.message); return; }
  state.stamp = Date.now();
  await loadEvent();
  flash(which === "undo" ? "Undone" : "Redone");
}
$("#undo").addEventListener("click", () => stepHistory("undo"));
$("#redo").addEventListener("click", () => stepHistory("redo"));
// The shortcuts as each system names them: Cmd on a Mac; Windows also redoes with Ctrl+Y.
const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
[["#undo", MAC ? "Undo (⌘Z)" : "Undo (Ctrl+Z)"], ["#redo", MAC ? "Redo (⇧⌘Z)" : "Redo (Ctrl+Y)"]].forEach(([sel, tip]) => {
  $(sel).dataset.tip = tip; $(sel).setAttribute("aria-label", tip);
});
document.addEventListener("keydown", (e) => {
  const key = e.key.toLowerCase(), ctrlY = !MAC && e.ctrlKey && !e.shiftKey && key === "y";
  if (!((e.ctrlKey || e.metaKey) && key === "z") && !ctrlY) return;
  if (e.target.matches("input, textarea, select")) return; // let fields undo their own typing
  e.preventDefault();
  stepHistory(e.shiftKey || ctrlY ? "redo" : "undo");
});

// This event's theme: its colours, or the team theme again ("Use team theme"), which lives in Settings.
const showLook = () => {
  const theme = state.event.theme || {};
  $("#theme-colours").replaceChildren(...COLOURS.map(([k, name, hint]) => el("label", { class: "swatch-field" },
    el("input", { type: "color", id: `colour-${k}`, value: theme[k] || DEFAULTS[k], "aria-label": `${name} colour` }),
    el("span", {}, name, hint && el("small", { class: "muted", style: "display:block" }, hint)))));
  const img = $("#theme-logo");
  img.hidden = !theme.logo;
  if (theme.logo) img.src = `/api/theme/logo?t=${Date.now()}`;
  $("#theme-source").textContent = state.event.team_look ? "Using your team theme" : "This event has its own theme";
  $("#theme-reset").hidden = state.event.team_look;
};
$("#open-theme").addEventListener("click", () => {
  showLook();
  $("#theme-status").textContent = "";
  $("#theme").showModal();
});
async function useTeamTheme() {
  await api("/api/theme/reset", "POST");
  state.stamp = Date.now();
  await loadEvent();
  flash("Team theme restored");
}
$("#theme-reset").addEventListener("click", async () => {
  try { await useTeamTheme(); } catch (err) { $("#theme-status").textContent = err.message; return; }
  showLook();
});
// An event that differs from the team theme offers it, until it's used or this event's own theme is kept.
$("#offer-use").addEventListener("click", () => useTeamTheme().catch((err) => flash(err.message)));
$("#offer-keep").addEventListener("click", async () => {
  try { await api("/api/theme/keep", "POST"); } catch (err) { flash(err.message); return; }
  await loadEvent(true);
  flash("Keeping this event's theme");
});

// Settings from the editor: after a save or a new team logo, catch up with them (closing without changes doesn't).
// Whether to offer the team theme comes from the server with the event.
$("#open-pictures").addEventListener("click", () => managePictures());
$("#open-settings").addEventListener("click", () => openSettings(async () => {
  const [teams, home] = await Promise.all([api("/api/teams"), api("/api/home")]);
  state.teams = teams;
  state.settings = home.settings; // pool lanes and first lane for new lane slides
  state.templatesFor = null; // the template folder may have changed
  state.stamp = Date.now();
  await loadEvent(true);
  renderEditor();
  draw(slideUrl(state.loop, state.n, 3));
  flash("Settings saved");
}));
$("#theme-save").addEventListener("click", async () => {
  const theme = Object.fromEntries(COLOURS.map(([k]) => [k, $(`#colour-${k}`).value.toUpperCase()]));
  try { await api("/api/theme", "PUT", { theme }); }
  catch (err) { $("#theme-status").textContent = err.message; return; }
  $("#theme").close();
  state.stamp = Date.now();
  await loadEvent();
  flash("Theme saved");
});

// The event's name and date, from its header: a duplicate starts as "<name> (copy)", dated today.
// The visiting team, from Teams. Its file name in the event (assets/teams/<file>) says which team it is.
const visitorTeam = () => {
  const v = state.event.visitor;
  return v && v.logo ? state.teams.find((t) => !t.home && v.logo.endsWith(`/${t.logo}`)) : null;
};
function fillVisitorPick() {
  const current = visitorTeam();
  $("#details-visitor").replaceChildren(
    el("option", { value: "" }, current ? "" : state.event.visitor ? state.event.visitor.name : "— none yet —"),
    ...state.teams.filter((t) => !t.home).map((t) => el("option", { value: t.id, selected: current && current.id === t.id }, t.name)),
    el("option", { value: "__manage" }, "Add or manage teams…"));
  if (current) $("#details-visitor").firstChild.remove(); // a current team needs no blank choice
}
$("#details-visitor").addEventListener("change", (e) => {
  if (e.target.value !== "__manage") return;
  fillVisitorPick();
  const pickNew = afterAdding((team) => { $("#details-visitor").value = team.id; }); // a team added here is the pick
  manageTeams(() => { fillVisitorPick(); pickNew(); });
});
function openDetails() {
  fillVisitorPick();
  $("#details-name").value = state.event.name;
  $("#details-date").value = state.event.date || "";
  $("#details-status").textContent = "";
  $("#details").showModal();
  $("#details-name").select();
}
async function saveDetails() {
  const name = $("#details-name").value.trim();
  if (!name) { $("#details-status").textContent = "Give the event a name."; $("#details-name").focus(); return; }
  const pick = $("#details-visitor").value, current = visitorTeam();
  let note = "Saved";
  try {
    await api("/api/event/details", "PUT", { name, date: $("#details-date").value });
    if (pick && pick !== "__manage" && (!current || current.id !== pick)) {
      const { visitor, cards } = await api("/api/event/visitor", "PUT", { team: pick });
      note = `Saved · ${visitor.name} ${cards === 1 ? "is on 1 card" : `is on ${cards} cards`}`;
    }
  } catch (err) { $("#details-status").textContent = err.message; return; }
  $("#details").close();
  state.stamp = Date.now();
  await loadEvent(note === "Saved"); // a new visitor changed slides' text: reload the open slide too, not just the strip
  flash(note);
}
$("#details-save").addEventListener("click", saveDetails);
["#details-name", "#details-date"].forEach((sel) => $(sel).addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); saveDetails(); } // not the form's first button, Cancel
}));

$("#open-versions").addEventListener("click", async () => {
  const list = await api("/api/versions");
  $("#version-list").replaceChildren(...(list.length ? list.map((v) => el("li", {},
    el("span", { class: "mono" }, v.name.replace(/(\d{4}-\d\d-\d\d) (\d\d)\.(\d\d)\.(\d\d)/, "$1 $2:$3:$4")),
    el("button", { class: "btn", type: "button", on: { click: async () => {
      try { await api(`/api/versions/${encodeURIComponent(v.name)}/restore`, "POST"); }
      catch (err) { flash(err.message); return; }
      $("#versions").close(); state.stamp = Date.now(); await loadEvent(); flash(`Restored the version from ${v.name}`);
    } } }, "Restore"))) : [el("li", { class: "muted" }, "No versions yet: one is kept each time you export.")]));
  $("#versions").showModal();
});

$("#open-copy").addEventListener("click", () => {
  const others = state.event.loops.map((lp, i) => [i, lp.name]).filter(([i]) => i !== state.loop);
  if (!others.length) { flash("Add another loop first"); return; }
  $("#copy-target").replaceChildren(...others.map(([i, name]) => el("option", { value: i }, name)));
  $("#copy").showModal();
});
$("#copy-go").addEventListener("click", async () => {
  const target = Number($("#copy-target").value);
  try { await api("/api/copy", "POST", { loop: state.loop, n: state.n, target }); }
  catch (err) { flash(`Not copied: ${err.message}`); return; }
  $("#copy").close();
  await loadEvent(true);
  flash(`Copied to the end of ${state.event.loops[target].name}`);
});

(async () => {
  state.settings = (await api("/api/home")).settings;
  state.teams = await api("/api/teams");
  await loadEvent();
})();
