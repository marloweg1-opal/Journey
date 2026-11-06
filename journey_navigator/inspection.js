"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const panel = $("inspection");
  const api = (route, body = {}) => apiPost(`/api/inspect/${route}`, body);
  const pathField = $("inspect-path");
  const approval = $("inspect-approval");
  const browser = $("inspect-browser");
  const results = $("inspect-results");
  const manage = document.querySelector('[data-panel="manage"]');
  const notice = (message) => { $("inspect-notice").textContent = message; };
  const action = (name, label, value = "") => `<button type="button" data-inspect="${name}" data-value="${esc(value)}">${esc(label)}</button>`;
  const label = (value) => String(value || "").replaceAll("_", " ");
  const views = {images: "images", groups: "groups", links: "links", issues: "skipped entries"};
  let job = "", view = "images", series = "", query = "", offset = 0, running = false, sequence = 0;

  function failure(error) {
    notice(error.error || error.message || String(error));
  }

  function provenance(row) {
    const trail = (row.hops || []).map(hop => `<p>${esc(hop.kind)} · ${esc(hop.link)} → ${esc(hop.declared_target)}</p>`).join("");
    return `<dl><dt>Selected path</dt><dd>${esc(row.selected)}</dd><dt>Destination</dt><dd>${esc(row.target || "Unavailable")}</dd></dl>${trail}`;
  }

  async function browse(path = "", page = 0) {
    browser.hidden = false;
    if (!path) {
      const {items} = await api("drives");
      browser.innerHTML = `<p>Choose a local drive to browse.</p>${items.map(item => action("folder", item, item)).join("")}`;
      return;
    }
    const data = await api("browse", {path, offset: page});
    browser.innerHTML = `<p><strong>${esc(data.folder)}</strong></p><div class="inspection-bar">
      ${action("choose", "Inspect this folder", data.folder)}
      ${data.parent !== data.folder ? action("folder", "Up one folder", data.parent) : ""}
      ${action("drives", "Local drives")}</div>` + data.entries.map(item => `<div class="inspection-entry">
        <strong>${esc(item.name)}</strong> <small>${esc(item.kind)}</small>
        ${item.kind === "folder" ? action("folder", `Browse ${item.name}`, item.path) : action("choose", `Review ${item.name}`, item.path)}</div>`).join("") +
      `<div class="inspection-bar">${page ? action("browse-page", "Previous folders", JSON.stringify([path, Math.max(0, page - 100)])) : ""}
        ${data.more ? action("browse-page", "More folders", JSON.stringify([path, page + 100])) : ""}</div>`;
  }

  async function showJobs() {
    const {items} = await api("jobs");
    manage.innerHTML = `<div class="inspection-card"><h2>Saved inspections</h2><p>Journey saves progress, thumbnails, and review decisions as you work.</p>
      ${items.map(item => `<div class="inspection-entry"><p>${esc(item.root)}</p>${action("saved", "Open saved inspection", item.id)}</div>`).join("") || "<p>Choose a folder to begin.</p>"}
      ${action("exit", "Close Navigator")}</div>`;
  }

  function coverage(data) {
    const names = [["files", "Files found"], ["analyzed", "Images examined"], ["pending", "Images waiting"], ["pending_folders", "Folders waiting"],
      ["unsupported", "Other file types"], ["skipped", "Skipped"], ["reused", "Cached analyses reused"], ["link_attention", "Links needing attention"]];
    $("inspect-counts").innerHTML = names.map(([key, title]) => `<div><strong data-count="${key}">${data[key].toLocaleString()}</strong><span>${title}</span></div>`).join("");
    const waiting = data.pending || data.pending_folders;
    $("inspect-progress").textContent = running ? "Inspecting in the background. Each batch saves its progress." :
      waiting ? "Inspection paused. Resume to continue from saved progress." : "Finished inspecting the available scope. See links and skipped entries for coverage gaps.";
    panel.querySelector('[data-inspect="resume"]').disabled = running || !waiting;
    panel.querySelector('[data-inspect="pause"]').disabled = !running;
    panel.querySelector('[data-inspect="refresh"]').disabled = running;
    panel.querySelector('[data-inspect="export"]').disabled = running;
  }

  function showImages(items) {
    const questions = new Map();
    for (const image of items) {
      const question = image.identity.state === "proposed_identity" ? `Which images in this series depict ${image.identity.label}?` :
        image.purpose.state === "unknown" ? "What purpose does this visual series serve?" : "";
      if (question) questions.set(`${image.series}:${question}`, {question, series: image.series});
    }
    $("inspect-questions").innerHTML = questions.size ? `<div class="inspection-entry"><strong>Review questions in this view</strong>
      ${[...questions.values()].slice(0, 6).map(item => `<p>${esc(item.question)} ${action("group", "Show series", item.series)}</p>`).join("")}</div>` : "";
    results.innerHTML = `<div class="inspection-gallery">${items.map(image => {
      const identity = image.identity;
      const rejected = (identity.rejections || identity.suppressed || []).map(item => item.label).join(", ");
      const name = image.name;
      return `<article class="inspection-entry" data-image="${image.id}">
        <img src="data:image/webp;base64,${esc(image.thumbnail)}" alt="Thumbnail of ${esc(image.filename)}">
        <h3>${esc(image.filename)}</h3><small>${esc(image.path)}</small>
        <p><strong>${esc(image.purpose.label || "Purpose open")}</strong> · ${esc(label(image.purpose.state))}</p>
        <p>${esc(identity.label || "Identity open")} · ${esc(label(identity.state))}</p>
        <p><small>${image.memberships.map(esc).join(" · ")}</small></p>
        <details><summary>Evidence and naming preview</summary><p>${esc(image.purpose.reason)}</p><p>${esc(identity.reason)}</p>
        ${rejected ? `<p>Rejected association · ${esc(rejected)}</p>` : ""}
        <p><strong>${esc(name.destination || "Name needs identification")}</strong></p><p>${esc(name.reason)} ${esc(name.blocker || "")}</p></details>
        <details><summary>Record a correction</summary><form data-image-review="${image.id}">
          <label>Decision <select name="decision"><option value="confirm">Confirm identity</option><option value="reject">Reject identity</option><option value="purpose">Record purpose</option></select></label>
          <label>Identity <input name="label" value="${esc(identity.label)}"></label>
          <label>Purpose <input name="purpose"></label>
          <button type="submit">Save correction</button></form></details></article>`;
    }).join("")}</div>`;
  }

  async function loadView() {
    if (!job) return;
    const request = {job, offset, series, query};
    const requestedView = view;
    const data = await api(view, request);
    if (job !== request.job || view !== requestedView || offset !== request.offset || series !== request.series || query !== request.query) return;
    $("inspect-filter").hidden = view !== "images";
    $("inspect-questions").innerHTML = "";
    if (!data.items.length) {
      results.textContent = `No ${views[view]} in this view yet.`;
    } else if (view === "images") {
      showImages(data.items);
    } else if (view === "groups") {
      results.innerHTML = data.items.map(row => `<div class="inspection-entry"><strong>Visual series ${esc(row.series.slice(0, 8))}</strong>
        <p>${row.members.toLocaleString()} similar images. Visual membership is separate from confirmed identity.</p>${action("group", "Browse series", row.series)}</div>`).join("");
    } else if (view === "links") {
      results.innerHTML = data.items.map(row => `<div class="inspection-entry" data-link-row><strong>${esc(row.kind)} · ${esc(label(row.status))}</strong>
        ${provenance(row)}<p>${esc(row.reason)}</p>${row.status === "approval_required" ? action("link", "Review destination", row.id) : ""}</div>`).join("");
    } else {
      results.innerHTML = data.items.map(row => `<div class="inspection-entry"><strong>${esc(row.path)}</strong><p>${esc(row.reason)}</p></div>`).join("");
    }
    $("inspect-page").textContent = `Page ${Math.floor(offset / 24) + 1}`;
    panel.querySelector('[data-inspect="previous"]').disabled = offset === 0;
    panel.querySelector('[data-inspect="next"]').disabled = !data.more;
  }

  async function openJob(id) {
    job = id;
    sessionStorage.setItem("journey-current-inspection", job);
    setMode("inspect");
    $("inspect-review").hidden = false;
    const data = await api("summary", {job});
    $("inspect-root").textContent = data.root;
    const form = $("inspect-rule");
    for (const name of ["project", "filename", "folder"]) form.elements[name].value = data.rule[name];
    coverage(data);
    await loadView();
  }

  async function run() {
    if (running || !job) return;
    running = true;
    $("inspect-progress").textContent = "Starting inspection. Each batch saves its progress.";
    panel.querySelector('[data-inspect="resume"]').disabled = true;
    panel.querySelector('[data-inspect="pause"]').disabled = false;
    panel.querySelector('[data-inspect="refresh"]').disabled = true;
    panel.querySelector('[data-inspect="export"]').disabled = true;
    const id = ++sequence;
    const selected = job;
    let data;
    try {
      do {
        data = await api("step", {job: selected});
        if (!running || id !== sequence) return;
        coverage(data);
        await new Promise(resolve => setTimeout(resolve, 15));
      } while (running && id === sequence && (data.pending || data.pending_folders));
    } finally {
      if (id === sequence) {
        running = false;
        if (data) coverage(data);
        else coverage(await api("summary", {job}));
        await loadView();
      }
    }
  }

  async function pause() {
    if (!job) return;
    running = false;
    sequence++;
    coverage(await api("pause", {job}));
    await loadView();
  }

  async function selected(result) {
    approval.hidden = result.status !== "approval_required";
    if (result.status === "approval_required") {
      approval.innerHTML = `<h3>Allow read-only inspection?</h3>${provenance(result)}<p>${esc(result.reason)}</p>
        ${action("approve", "Authorize this destination", result.ticket)} ${action("cancel-approval", "Keep current scope")}`;
      approval.querySelector("button").focus();
    } else if (result.status === "ready") {
      browser.hidden = true;
      notice(result.hops.length ? `Resolved ${result.selected}\nInspecting ${result.target}` : `Selected ${result.target}`);
      await openJob(result.job);
      await run();
    } else {
      notice(`${label(result.status)} · ${result.reason}`);
      if (job && view === "links") {
        coverage(await api("summary", {job}));
        await loadView();
      }
    }
  }

  async function choose(path) {
    await pause();
    pathField.value = path;
    series = query = "";
    $("inspect-filter").reset();
    offset = 0;
    view = "images";
    panel.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
    await selected(await api("select", {path: path.trim().replace(/^"|"$/g, "")}));
  }

  $("inspect-selection").addEventListener("submit", (event) => {
    event.preventDefault();
    choose(pathField.value).catch(failure);
  });
  panel.addEventListener("submit", async (event) => {
    if (event.target.id === "inspect-selection") return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target));
    try {
      if (event.target.id === "inspect-filter") {
        query = data.query.trim();
        offset = 0;
      } else if (event.target.id === "inspect-rule") {
        await api("rule", {job, ...data});
        notice("Naming convention saved.");
      } else if (event.target.dataset.imageReview) {
        await api("review", {job, asset: Number(event.target.dataset.imageReview), ...data});
        notice("Correction saved. Related image suggestions have been updated.");
      }
      await loadView();
    } catch (error) { failure(error); }
  });

  const commands = {
    browse: () => browse(pathField.value ? pathField.value.trim().replace(/^"|"$/g, "") : ""),
    drives: () => browse(), folder: (path) => browse(path), "browse-page": (value) => browse(...JSON.parse(value)), choose,
    link: async (value) => selected(await api("select", {job, link: Number(value)})),
    approve: async (ticket) => {
      approval.querySelectorAll("button").forEach(button => { button.disabled = true; });
      notice("Checking the destination and its permissions…");
      try { await selected(await api("approve", {ticket})); }
      catch (error) { approval.hidden = true; throw error; }
    },
    "cancel-approval": () => { approval.hidden = true; notice("Current inspection scope retained."); },
    resume: run, pause,
    refresh: async () => { coverage(await api("refresh", {job})); await run(); },
    export: async () => { const output = await api("export", {job}); notice(`Plan saved to ${output.path}`); },
    previous: async () => { offset = Math.max(0, offset - 24); await loadView(); },
    next: async () => { offset += 24; await loadView(); },
    group: async (value) => {
      series = value; query = ""; view = "images"; offset = 0;
      $("inspect-filter").reset();
      panel.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
      await loadView();
    },
    saved: async (value) => { await pause(); view = "images"; series = query = ""; offset = 0; $("inspect-filter").reset(); await openJob(value); },
    exit: async () => { await pause(); await api("exit"); manage.innerHTML = '<p>Navigator is closed. Your review is saved.</p>'; }
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-inspect]");
    const tab = event.target.closest("[data-view]");
    try {
      if (button) await commands[button.dataset.inspect](button.dataset.value);
      else if (tab) {
        view = tab.dataset.view; offset = 0; series = "";
        panel.querySelectorAll("[data-view]").forEach(item => item.setAttribute("aria-pressed", String(item === tab)));
        await loadView();
      } else if (event.target.closest('[data-select="manage"]')) await showJobs();
      else if (event.target.closest('[data-select="find"]')) document.getElementById("command").focus();
    } catch (error) { failure(error); }
  });

  document.querySelector(".titlebar .subtitle").textContent = "Read-only folder and image stewardship";
  document.querySelector('[data-panel="home"]').innerHTML = `<div class="inspection-card"><h2>Navigator inspection</h2><p>Open Inspect to choose a folder or shortcut. Manage reopens saved inspections.</p></div>`;
  document.querySelector('[data-panel="find"]').innerHTML = `<div class="inspection-card"><h2>Find inspected files</h2><p>Search file names and paths in the current inspection.</p></div>`;
  document.querySelector('[data-panel="guide"]').innerHTML = `<div class="inspection-card"><h2>Inspect and review</h2>
    <p>Browse to the folder or select an existing shortcut. Navigator shows the link and destination separately. Approve a destination when it falls outside the current scope.</p>
    <p>Pause at any time and reopen from Manage. Review images, grouped questions, and proposed names. Save plan records previews in Journey's local review storage.</p></div>`;
  setMode("inspect");
})();
