// Events home: setup, new events from starters, the event list, import/duplicate/package, settings.
"use strict";

let home;
const status = (text, detail = text) => { $("#status").textContent = text; $("#status").title = detail; };
const today = () => { // the local date: toISOString is UTC, a day ahead on an evening in the Americas
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const edited = (t) => {
  const mins = Math.round((Date.now() / 1000 - t) / 60);
  if (mins < 1) return "edited just now";
  if (mins < 60) return `edited ${mins} min ago`;
  if (mins < 60 * 24) return `edited ${Math.round(mins / 60)} h ago`;
  return `edited ${new Date(t * 1000).toLocaleDateString()}`;
};

async function load() {
  home = await api("/api/home");
  $("#team").textContent = home.settings.team || "";
  $("#setup").hidden = home.templates_found;
  $("#team-setup").hidden = !!(home.settings.team && home.settings.logo); // a new install: the team first
  if (home.update) {
    $("#update").hidden = false;
    $("#update").replaceChildren(`Loop Builder ${home.update.version} is available (you have ${home.version}). `,
      el("a", { href: home.update.url, target: "_blank", rel: "noopener" }, "Download it"));
  }
  $("#folder").textContent = `Events are saved on this computer in ${home.folder}.`;
  const bad = home.unreadable || []; // left out of the list, so they don't look deleted
  $("#unreadable").hidden = !bad.length;
  const one = bad.length === 1, names = bad.map((b) => `“${b}”`).join(", ");
  $("#unreadable").textContent = !bad.length ? "" : one
    ? `One event couldn’t be read, so it isn’t listed: ${names}. Its folder is still in the Events folder (below), to fix or remove.`
    : `${bad.length} events couldn’t be read, so they aren’t listed: ${names}. Their folders are still in the Events folder (below), to fix or remove.`;
  $("#show-folder").hidden = !(native() && native().show_folder); // the app window can open it
  $("#show-folder").textContent = /Mac/.test(navigator.platform) ? "Show in Finder" : "Show in Explorer";
  $("#documents-offer").hidden = !home.offer_documents;
  // A dual meet's visitor, from the teams saved in Teams: their name and logo go on the starter's cards.
  const visitors = (await api("/api/teams").catch(() => [])).filter((t) => !t.home);
  const keep = $("#new-visitor").value;
  $("#new-visitor").replaceChildren(el("option", { value: "" }, "— choose later —"),
    ...visitors.map((t) => el("option", { value: t.id, selected: t.id === keep }, t.name)));
  $("#visitor-field").hidden = !visitors.length;
  $("#starters").replaceChildren(...home.starters.map((s) => el("button", { class: "starter", type: "button",
    on: { click: () => create(s.id) } }, s.title, el("small", {}, s.about))));
  renderEvents();
}

function renderEvents() {
  const q = $("#search").value.trim().toLowerCase();
  const list = home.events.filter((e) => !q || e.name.toLowerCase().includes(q));
  $("#events").replaceChildren(...(list.length ? list.map((e) => el("li", { class: "ev" },
    el("img", { src: `/api/events/${encodeURIComponent(e.slug)}/thumb.png?t=${e.edited}`, alt: "", loading: "lazy" }),
    el("div", { class: "ev-main" },
      el("a", { href: "#", class: "ev-name", on: { click: (ev) => { ev.preventDefault(); openEvent(e.slug); } } }, e.name),
      el("span", { class: "muted" }, [niceDate(e.date), edited(e.edited)].filter(Boolean).join(" · ")),
      el("span", { class: "row" }, e.loops.map((l) => el("span", { class: "chip" }, `${l.name} · ${l.slides} slide${l.slides === 1 ? "" : "s"}`)))),
    el("div", { class: "row" },
      el("button", { class: "btn btn-primary", type: "button", on: { click: () => openEvent(e.slug) } }, "Open"),
      el("button", { class: "btn", type: "button", on: { click: () => duplicate(e) } }, "Duplicate"),
      el("button", { class: "btn", type: "button", on: { click: () => savePackage(e) } }, "Save as .loopevent…"),
      el("button", { class: "btn", type: "button", on: { click: () => confirmDelete(e) } }, "Delete…"))))
    : [el("li", { class: "muted" }, q ? "No events match." : "No events yet. Start one above.")]));
}

async function openEvent(slug) {
  try { await api(`/api/events/${encodeURIComponent(slug)}/open`, "POST"); location.href = "/edit"; }
  catch (err) { status(`Couldn't open: ${err.message}`); }
}

async function create(starter) {
  const name = $("#new-name").value.trim();
  if (!name) { // said at the field itself, where the name goes
    $("#new-name").setCustomValidity("Give the event a name first.");
    $("#new-name").reportValidity();
    return;
  }
  try {
    const visitor = $("#new-visitor").value || null;
    const { slug } = await api("/api/events", "POST", { name, date: $("#new-date").value || today(), starter, visitor });
    openEvent(slug);
  } catch (err) { status(`Not created: ${err.message}`); }
}

async function duplicate(e) {
  const name = `${e.name} (copy)`;
  try { const { slug } = await api(`/api/events/${encodeURIComponent(e.slug)}/duplicate`, "POST", { name, date: today() });
    status(`Made “${name}”. Open it and click its name to rename it or change the date.`); await load(); return slug;
  } catch (err) { status(`Not copied: ${err.message}`); return null; }
}

let deleting = null; // the event the Delete dialog asks about
function confirmDelete(e) {
  deleting = e;
  $("#delete-what").textContent = [e.name, e.date].filter(Boolean).join(" · ");
  $("#delete-status").textContent = "";
  $("#delete-dialog").showModal();
}
$("#delete-go").addEventListener("click", async () => {
  try { await api(`/api/events/${encodeURIComponent(deleting.slug)}`, "DELETE"); }
  catch (err) { $("#delete-status").textContent = `Not deleted: ${err.message}`; return; }
  $("#delete-dialog").close();
  status(`Deleted “${deleting.name}”.`);
  await load();
});

async function savePackage(e) {
  const fileName = `${e.name}.loopevent`;
  if (native()) {
    const path = await native().save_file(fileName, home.settings.export_dir || home.exports || "");
    if (!path) return;
    try { const { file } = await api(`/api/events/${encodeURIComponent(e.slug)}/package`, "POST", { path }); status(`Saved ${file.split(/[\\/]/).pop()}`, file); }
    catch (err) { status(`Not saved: ${err.message}`); }
  } else {
    location.href = `/api/events/${encodeURIComponent(e.slug)}/package`; // browser tab: a download
  }
}

async function imported(request) {
  try { const { slug } = await request(); status("Imported."); await load(); openEvent(slug); }
  catch (err) { status(err.message); }
}
$("#import-pick").addEventListener("click", async () => { // a button, so Tab reaches it
  if (!native()) { $("#import-file").click(); return; } // browser tab: its own file picker
  const path = await native().open_package(home.settings.export_dir || home.exports || ""); // the app: the system's, which can offer .loopevent files; it starts where Save does
  if (path) await imported(() => api("/api/events/import-file", "POST", { path }));
});
$("#import-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (file) await imported(() => upload("/api/events/import", file));
});
// The Loop Builder folder, which on a Mac is tucked away in Library › Application Support.
$("#show-folder").addEventListener("click", () => native().show_folder(home.folder));
// A Mac that ran 0.1.6 or earlier: its events are in Documents › Loop Builder until brought over.
$("#documents-move").addEventListener("click", async () => {
  $("#documents-status").textContent = "Moving…";
  try {
    const { moved } = await api("/api/library/move-documents", "POST");
    status(`Brought over ${moved} event${moved === 1 ? "" : "s"} from Documents.`);
    await load();
  } catch (err) { // nothing there (the offer goes away), or the move failed (it stays, to try again)
    $("#documents-status").textContent = err.message; status(err.message); await load();
  }
});
$("#documents-skip").addEventListener("click", async () => { await api("/api/library/documents-checked", "POST"); await load(); });
$("#search").addEventListener("input", renderEvents);
$("#new-name").addEventListener("input", (e) => e.target.setCustomValidity(""));
$("#new-date").value = today();

// First run: the template folder
const clearSetupStatus = () => { $("#setup-status").textContent = ""; }; // a new folder: the old reason no longer applies
$("#setup-pick").addEventListener("click", async () => { if (await pickFolder($("#setup-folder"))) clearSetupStatus(); });
$("#setup-folder").addEventListener("input", clearSetupStatus);
$("#setup-save").addEventListener("click", async () => {
  $("#setup-status").textContent = "";
  try { await api("/api/settings", "PUT", { templates: $("#setup-folder").value.trim() }); status("Template folder saved."); load(); }
  catch (err) { $("#setup-status").textContent = `${err.message}. Check the folder, or click Choose… to pick it.`; $("#setup-folder").focus(); }
});

// Settings
$("#open-settings").addEventListener("click", () => { status(""); openSettings(async () => { status("Settings saved."); await load(); }); });
$("#team-setup-go").addEventListener("click", () => $("#open-settings").click());

load();
