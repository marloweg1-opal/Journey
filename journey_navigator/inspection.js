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
  const notice = (message) => { $("inspect-notice").textContent = message; const alert=document.getElementById("journey-alert"); if (alert) alert.textContent=message; };
  const action = (name, label, value = "") => `<button type="button" data-inspect="${name}" data-value="${esc(value)}">${esc(label)}</button>`;
  const label = (value) => String(value || "").replaceAll("_", " ");
  const views = {images: "images", groups: "groups", links: "links", issues: "skipped entries"};
  let job = "", view = "images", series = "", query = "", offset = 0, running = false, sequence = 0;
  let profileDraft = null, registryOffset = 0, auditRows = [];
  let flowCoverage = null, flowProfile = null, flowHistory = null, flowTarget = "images", flowReviewed = false, flowSkip = false;

  function collectionFlow() {
    if (!flowCoverage || !job) return;
    const pending = flowCoverage.pending || flowCoverage.pending_folders;
    let message, title, disabled = false;
    $("collection-flow-skip").hidden = true;
    if (pending || running) {
      flowTarget = "resume";
      message = `Inspection · ${flowCoverage.files.toLocaleString()} entries found, ${flowCoverage.analyzed.toLocaleString()} images examined. ${running ? "Continuing in bounded batches." : "Saved at a checkpoint. Resume when ready."}`;
      title = "Resume inspection"; disabled = running;
    } else if (!flowCoverage.retains) {
      flowTarget = "images"; title = "Review interpretations";
      message = "Temporary inspection is ready. To retain project context and decisions, select this folder with a local checkpoint enabled.";
    } else if (!flowProfile) {
      flowTarget = "profile"; title = "Add project context";
      message = "Inspection finished. Preview a project pack to establish which project's evidence and naming rules apply to this collection.";
    } else if (flowHistory?.files.some(file => file.status === "queued")) {
      flowTarget = "history"; title = "View import progress";
      message = `${flowProfile.project} · Importing the reviewed historical selection. Completed sources will update relevant interpretations.`;
    } else if (!flowHistory?.files.some(file => file.status === "complete") && !flowSkip) {
      flowTarget = "history"; title = "Add historical context";
      message = `${flowProfile.project} · Project context is active. Import reviewed local exports, or continue with the evidence already available.`;
      $("collection-flow-skip").hidden = false;
    } else if (!flowReviewed) {
      flowTarget = "images"; title = "Review interpretations";
      message = `${flowProfile.project} · Context is ready for review. Inspect identity, purpose, source citations and open questions before organization.`;
    } else {
      flowTarget = "destination"; title = "Preview organization";
      message = `${flowProfile.project} · Describe the result you want, then review Journey's evidence-linked virtual groups. Saving a preview preserves the source files.`;
    }
    $("collection-flow-status").textContent = message;
    $("collection-flow-next").textContent = title;
    $("collection-flow-next").disabled = disabled;
  }

  async function collectionNext() {
    if (flowTarget === "resume") return run();
    if (flowTarget === "profile" || flowTarget === "history") {
      const section = $(flowTarget === "profile" ? "inspect-registry" : "inspect-history");
      section.open = true;
      section.scrollIntoView({block: "start"});
      section.querySelector('input').focus();
    } else if (flowTarget === "destination") {
      document.querySelector('.journey-tools [data-select="destination"]').click();
      $("destination-form").elements.why.focus();
    } else {
      flowReviewed = true;
      view = "images"; offset = 0; series = ""; query = "";
      $("inspect-filter").reset();
      panel.querySelectorAll('[data-view]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.view === view)));
      await loadView();
      results.scrollIntoView({block: "start"});
      collectionFlow();
    }
  }

  window.addEventListener('journey-history-status', event => {
    if (event.detail.job !== job) return;
    const data = event.detail.data;
    if (flowHistory && (flowHistory.incremental?.[0]?.sequence || 0) !== (data.incremental?.[0]?.sequence || 0)) flowReviewed = false;
    flowHistory = data;
    collectionFlow();
  });

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
    manage.innerHTML = `<div class="inspection-card"><h2>Saved inspections</h2><p>Reviews appear here when you choose to keep a local checkpoint.</p>
      ${items.map(item => `<div class="inspection-entry"><p>${esc(item.root)}</p>${item.active ?
        action("saved", "Open saved inspection", item.id) : action("reauthorize", "Review access settings", item.id)}</div>`).join("") || "<p>Choose a folder to begin.</p>"}
      ${action("exit", "Close Navigator")}</div>`;
    window.dispatchEvent(new Event('journey-manage'));
  }

  function coverage(data) {
    const names = [["files", "Files found"], ["analyzed", "Images examined"], ["pending", "Images waiting"], ["pending_folders", "Folders waiting"],
      ["unsupported", "Other file types"], ["skipped", "Skipped"], ["reused", "Cached analyses reused"],
      ["text_count", "Images with readable text"], ["link_attention", "Links needing attention"]];
    $("inspect-counts").innerHTML = names.map(([key, title]) => `<div><strong data-count="${key}">${data[key].toLocaleString()}</strong><span>${title}</span></div>`).join("");
    const waiting = data.pending || data.pending_folders;
    $("inspect-progress").textContent = running ? "Inspecting in batches. You can pause after the current batch." :
      waiting ? "Inspection paused. Resume to continue." : "Finished inspecting the available scope. See links and skipped entries for coverage gaps.";
    $("inspect-mode").textContent = (data.retains ? "Local checkpoint enabled." : "Temporary review for this session.") +
      (data.ocr_available ? " Image text reading is available." : " Image text reading is unavailable. Filename, folder, and visual evidence are available.");
    $("inspect-naming").hidden = !data.proposals;
    $("inspect-registry").hidden = !data.retains;
    $("inspect-naming-audit").hidden = !data.retains;
    $("inspect-history").hidden = !data.retains;
    $("inspect-watch").hidden = !data.retains;
    panel.querySelector('[data-inspect="resume"]').disabled = running || !waiting;
    panel.querySelector('[data-inspect="pause"]').disabled = !running;
    panel.querySelector('[data-inspect="refresh"]').disabled = running;
    panel.querySelector('[data-inspect="export"]').disabled = running || !data.retains || !data.proposals;
    flowCoverage = data;
    collectionFlow();
  }

  function sourceLabel(source) {
    if (typeof source === "string") return source;
    return [source.role, source.archive, source.title, source.authored, source.conversation, source.message, source.locator].filter(Boolean).join(" · ");
  }

  function claimText(item) {
    const value = item.kind === "relationship" ? `${item.value.relation} ${item.value.asset}` : item.value;
    return `${label(item.kind)}${value ? ` · ${value}` : ""} · ${item.decision}`;
  }

  function imageMetadata(image) {
    const data = image.metadata;
    const date = data.date;
    const short = data.filename_date;
    const applicable = Boolean(image.naming_profile.project);
    const dateLabel = date ? date.date : data.date_state === "conflicted" ? "Evidence disagrees" : "Unknown";
    const modified = new Date(Math.trunc(data.filesystem_modified_ns / 1_000_000)).toLocaleString();
    return `<details><summary>Image details · created ${esc(dateLabel)}</summary>
      <dl><dt>Original filename</dt><dd>${esc(data.original_filename)}</dd><dt>Current filename</dt><dd>${esc(data.current_filename)}</dd>
      <dt>Full creation date</dt><dd>${esc(dateLabel)}${date ? ` · ${esc(sourceLabel(date.source))}` : ""}</dd>
      <dt>Filesystem modification time</dt><dd>${esc(modified)}</dd></dl>
      ${data.lifecycle !== "unestablished" ? `<p>Reviewed lifecycle · ${esc(data.lifecycle)}</p>` : ""}
      ${data.retirements.map(item => `<p>Retired from active use · ${esc(item.family)} · ${esc(item.reason)}
        ${item.replacement ? ` · Replacement ${esc(item.replacement)}` : ""}</p>`).join("")}
      ${short && short.state !== "undated" ? `<p>Filename date fields · ${short.state === "placeholder" ? "00_00 date placeholder" :
        `day ${short.day}, month ${short.month}${short.year ? `, year ${short.year}` : ""}
          · ${short.state === "invalid" ? "invalid date fields" : "filename evidence"}`}</p>` : ""}
      ${image.naming_profile.rule_source ? `<p>Naming rule source · ${esc(image.naming_profile.rule_source)}</p>` : ""}
      ${data.embedded_dates.map(item => `<p>${esc(item.source)} · ${esc(item.date)}</p>`).join("")}
      ${data.path_history.map(item => `<p>${esc(item.from_path)} → ${esc(item.to_path)} · receipt ${esc(item.receipt)}</p>`).join("")}
      ${data.registry_evidence.map(item => `<p>${esc(claimText(item))}<br><small>${esc(sourceLabel(item.source))}</small>
        ${item.kind === "creation_date" && item.decision !== "rejected" ?
          action("use-date", `Confirm ${item.value} for this image`, JSON.stringify([image.id, item.id])) : ""}</p>`).join("")}
      ${data.source_fingerprint_matches.map(item => `<p>Matches an attributed source fingerprint · ${esc(item.filename)}<br><small>${esc(sourceLabel(item.source))}</small></p>`).join("")}
      ${data.local_history.length ? `<details><summary>Local archive references (${data.local_history.length})</summary>
        ${data.local_history.map(item => `<p>${esc(item.name)} · ${esc(item.match || item.value.relation || item.kind)}
          ${item.kind === "attachment" ? " · Attachment bytes unavailable" : ""}
          ${item.kind === "relationship" ? ` · ${esc(item.value.relation)} ${esc(item.value.asset)}` : ""}
          ${item.kind === "lifecycle" ? ` · Historical claim: ${esc(item.value)}` : ""}
          <br><small>${esc(sourceLabel(item.source))}</small></p>`).join("")}</details>` : ""}
      ${applicable ? `<form data-image-date="${image.id}" class="inspection-bar">
        <label>Verified creation date <input name="date" type="date" value="${esc(date?.date || "")}" required></label>
        <label>Date source <input name="source" maxlength="300" required></label>
        <button type="submit">Record creation date</button></form>` : ""}</details>`;
  }

  async function loadRegistry() {
    if (!job || $("inspect-registry").hidden) return;
    const selected = job, page = registryOffset;
    const data = await api("registry", {job: selected, offset: page});
    if (selected !== job || page !== registryOffset) return;
    flowProfile = data.profile;
    collectionFlow();
    $("registry-import").hidden = !data.profile;
    $("registry-status").textContent = data.profile ?
      `${data.profile.project} · ${data.profile.rules.length} validated naming rules · ${data.claims} evidence records · ${data.archives} imported files` :
      "Choose a project profile to start a registry in this folder.";
    $("registry-results").innerHTML = data.profile ?
      data.profile.rules.map(rule => `<p>${esc(rule.subject)} · ${esc(rule.purpose)} · ${esc(rule.example.filename)}</p>`).join("") +
      action("registry-deactivate", "Deactivate this profile") +
      data.items.map(item => `<details class="inspection-entry"><summary>${esc(item.name)} · ${esc(label(item.state))}</summary>
        ${item.lifecycle !== "unestablished" ? `<p>Reviewed lifecycle · ${esc(item.lifecycle)}</p>` : ""}
        ${item.paths.map(path => `<p>${esc(path)}</p>`).join("")}
        ${item.evidence.map(claim => `<p>${esc(claimText(claim))}<br><small>${esc(sourceLabel(claim.source))}</small><br>
          ${action("registry-review", "Accept this evidence", JSON.stringify([claim.id, "accepted"]))}
          ${action("registry-review", "Reject this evidence", JSON.stringify([claim.id, "rejected"]))}</p>`).join("")}</details>`).join("") +
      `<div class="inspection-bar">${page ? action("registry-page", "Previous records", page - 16) : ""}
        ${data.more ? action("registry-page", "Next records", page + 16) : ""}</div>` : "";
  }

  async function loadNamingAudit() {
    if (!job || $("inspect-naming-audit").hidden) return;
    const requested = job;
    const audit = await api("naming-audit", {job});
    if (job !== requested) return;
    const counts = new Map();
    for (const item of audit.items) counts.set(item.state, (counts.get(item.state) || 0) + 1);
    $("naming-audit-status").textContent = audit.state === "NO_AUDIT" ? "Choose a project evidence file to audit coverage." :
      audit.reason || `${audit.project} · ${audit.items.length} subject and asset-family combinations · ${audit.active_rule_count} active rules · ` +
      [...counts].map(([state, count]) => `${count} ${label(state).toLowerCase()}`).join(" · ") +
      (audit.scan_limited ? " · File coverage is incomplete." : "");
    auditRows = audit.items;
    const subjects = [...new Set(auditRows.map(row => row.subject))];
    const families = [...new Set(auditRows.map(row => row.family))];
    const compact = {VERIFIED_FILENAME_EXEMPLAR: "File", RULE_ONLY: "Rule", CONFLICTED: "Conflict", CANDIDATE: "Evidence", UNKNOWN: "Open"};
    $("naming-audit-results").innerHTML = !subjects.length ? "" : `<div class="audit-scroll"><table class="audit-matrix">
      <caption>Project naming coverage. Choose a cell to see its sources.</caption><thead><tr><th scope="col">Subject</th>
      ${families.map(name => `<th scope="col">${esc(name)}</th>`).join("")}</tr></thead><tbody>
      ${subjects.map(subject => `<tr><th scope="row">${esc(subject)}</th>
        ${auditRows.map((row, index) => row.subject !== subject ? "" : `<td><button type="button" data-inspect="audit-row" data-value="${index}">
          <span class="journey-sr-only">${esc(row.subject)} · ${esc(row.family)} · ${esc(label(row.state).toLowerCase())}</span>
          <span aria-hidden="true">${esc(compact[row.state] || label(row.state))}</span></button></td>`).join("")}</tr>`).join("")}
      </tbody></table></div><div id="audit-row-proof" tabindex="-1"></div>`;
  }

  function auditProof(index) {
    const row = auditRows[Number(index)];
    if (!row) return;
    const target = $("audit-row-proof");
    target.innerHTML = `<details open class="inspection-entry">
      <summary>${esc(row.subject)} · ${esc(row.family)} · ${esc(label(row.state).toLowerCase())}</summary>
      <p>${row.observed_count} filename candidates in the current inspected scope.</p>
      ${row.active_rules.map(rule => `<p>Active rule · ${esc(rule.example.filename)} · ${esc(rule.source)}</p>`).join("")}
      ${row.files.map(file => `<p>${esc(label(file.state))} · ${esc(file.path)} ${file.sha256 ? ` · ${esc(file.sha256)}` : ""}</p>`).join("")}
      ${row.examples.map(file => `<p>${file.sha256 ? "Direct-file sample" : "Archive filename reference"} · ${esc(file.filename)}
        <br><small>${esc(file.source.locator)}${file.sha256 ? ` · ${esc(file.sha256)}` : ""}</small></p>`).join("")}
      <dl>${Object.entries(row.fields).map(([name, field]) => `<dt>${esc(label(name))}</dt>
        <dd>${esc(label(field.state).toLowerCase())}${field.value ? ` · ${esc(field.value)}` : ""}
          ${field.proof.length ? `<ul>${field.proof.map(claim => `<li>Tier ${esc(claim.tier)} · ${esc(claim.value)}
            ${claim.superseded ? " · superseded" : ""}<br><small>${esc(claim.source.locator)}</small></li>`).join("")}</ul>` : ""}</dd>`).join("")}</dl>
      </details>`;
    target.focus();
  }

  function showImages(items) {
    const questions = new Map();
    for (const image of items) {
      const question = image.identity.state === "conflicting_evidence" ?
        `Which subject fits this series? The evidence points to ${image.identity.conflicts.join(" or ")}.` :
        image.purpose.state === "conflicting_evidence" ? "What purpose fits this series? Its labels disagree." : "";
      if (question) questions.set(`${image.series}:${question}`, {question, series: image.series});
    }
    $("inspect-questions").innerHTML = questions.size ? `<div class="inspection-entry"><strong>Review questions in this view</strong>
      ${[...questions.values()].slice(0, 6).map(item => `<p>${esc(item.question)} ${action("group", "Show series", item.series)}</p>`).join("")}</div>` : "";
    results.innerHTML = `<div class="inspection-gallery">${items.map(image => {
      const identity = image.identity;
      const rejected = (identity.rejections || []).map(item => item.label).join(", ");
      const name = image.name;
      const ocr = image.ocr;
      const reasons = image.signals.slice(0, 24).map(signal => `<li><strong>${esc(signal.source)}</strong> · ${esc(signal.text)}
        ${signal.subjects.length ? ` · ${esc(signal.subjects.join(", "))}` : ""}
        ${signal.purposes.length ? ` · ${esc(signal.purposes.join(", "))}` : ""}
        ${(signal.ambiguous_references || []).map(item => ` · Possible relationship: ${esc(item.possible_subject)} and ${esc(item.related_to)}. ${esc(item.reason)}`).join('')}
        ${signal.provenance ? `<br><small>${esc(sourceLabel(signal.provenance))}</small>` : ""}
        ${signal.source === "Image text" ? ` · ${esc(signal.strength)}` : ""}</li>`).join("");
      return `<article class="inspection-entry" data-image="${image.id}">
        <img src="data:image/webp;base64,${esc(image.thumbnail)}" alt="Thumbnail of ${esc(image.filename)}">
        <h3>${esc(image.filename)}</h3>
        <p><strong>${esc(image.purpose.label || "Purpose open")}</strong> · ${esc(label(image.purpose.state))}</p>
        <p>${esc(identity.label || "Identity open")} · ${esc(label(identity.state))}</p>
        ${image.metadata.local_history.length ? `<p><small>${image.metadata.local_history.length} local history records</small></p>` : ""}
        <details><summary>Evidence and naming preview</summary><p>${esc(image.purpose.reason)}</p><p>${esc(identity.reason)}</p>
        ${reasons ? `<ul>${reasons}</ul>` : ""}
        ${identity.visual ? `<p>Visual match · ${esc(identity.visual.label)} · ${esc(identity.visual.reason)}</p>` : ""}
        ${rejected ? `<p>Rejected association · ${esc(rejected)}</p>` : ""}
        ${image.suggestion && !image.naming_profile.project ? `<p><strong>Preliminary filename · ${esc(image.suggestion.filename)}</strong></p><p>${esc(image.suggestion.reason)}</p>` : ""}
        ${name.destination ? `<p><strong>Destination preview · ${esc(name.destination)}</strong></p>` : ""}
        ${name.candidate_destination ? `<p><strong>Trial format only · ${esc(name.candidate_destination)}</strong></p>` : ""}
        <p>${esc(name.reason)} ${esc(name.blocker || "")}</p>
        <details><summary>Path and original filename structure</summary><p>${esc(image.path)}</p><p>${esc(image.observed_name.original)}</p>
          <p>Exact extension · ${esc(image.observed_name.extension)}</p>
          <p>Observed Unicode sequences · ${esc(image.observed_name.unicode_sequences.join(' · ') || 'None')}</p>
          <p>Observed numeric fields · ${esc(image.observed_name.numeric_fields.map(item => item.text).join(' · ') || 'None')}</p>
        </details>
        <details><summary>Text read from the image · ${esc(label(ocr.status))}</summary>
          ${ocr.provider ? `<p>${esc(ocr.provider)} · ${esc(ocr.language || "eng")} · local</p>` : ""}
          ${ocr.lines ? `<ul>${ocr.lines.map(line => `<li>${esc(line.text)}</li>`).join("")}</ul>` : ""}
          ${ocr.refresh_available || ocr.status === "retry" || ocr.status === "pending_refresh" ? "<p>Refresh source to run the current text reader.</p>" : ""}
        </details></details>
        ${imageMetadata(image)}
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
    const data = await api("summary", {job: id});
    job = id;
    flowCoverage = null; flowProfile = null; flowHistory = null; flowReviewed = false; flowSkip = false;
    sessionStorage.setItem("journey-current-inspection", job);
    setMode("inspect");
    $("inspect-review").hidden = false;
    $("inspect-root").textContent = data.root;
    const form = $("inspect-rule");
    for (const name of ["project", "filename", "folder"]) form.elements[name].value = data.rule[name];
    coverage(data);
    profileDraft = null;
    registryOffset = 0;
    $("registry-profile").reset();
    $("registry-import").reset();
    $("registry-activate").disabled = true;
    $("registry-file-preview").textContent = "";
    $("naming-audit-load").reset();
    $("naming-audit-results").replaceChildren();
    $("naming-audit-status").textContent = "";
    await showAccess();
    await loadView();
    await loadRegistry();
    if ($("inspect-naming-audit").open) await loadNamingAudit();
    window.dispatchEvent(new Event("journey-project-ready"));
  }

  async function showAccess() {
    const data = await api("permissions", {job});
    $("inspect-scopes").innerHTML = `<p>Reuse in another scope and physical changes require separate authority. This review grants neither.</p>
      ${data.scopes.map(scope => `<div class="inspection-entry"><p><strong>${esc(scope.path)}</strong></p>
      <p>${scope.inspect ? "Inspection allowed" : "Inspection inactive"} · ${scope.retain ? "Local checkpoint" : "Temporary data"} ·
        ${scope.propose ? "Suggestions enabled" : "Suggestions off"}</p><div class="inspection-bar">
      ${scope.inspect ? action("allow-plans", scope.propose ? "Turn off suggestions" : "Allow suggestions",
        JSON.stringify([scope.path, !scope.propose])) : ""}
      ${scope.inspect ? action("revoke-read", "Revoke inspection", scope.path) : ""}
      ${action("forget", scope.retain ? "Forget checkpoint for this scope" : "Clear temporary results", scope.path)}</div></div>`).join("")}`;
  }

  async function revoke(scope, permission) {
    if (permission === "retain" && !confirm("Remove this scope's results and corrections from Navigator? Exported plan files are separate.")) return;
    await pause();
    const data = await api("revoke", {job, scope, permission});
    if (data.closed) {
      job = "";
      sessionStorage.removeItem("journey-current-inspection");
      results.replaceChildren();
      $("inspect-scopes").replaceChildren();
      $("inspect-review").hidden = true;
    } else {
      offset = 0;
      coverage(await api("summary", {job}));
      await showAccess();
      await loadView();
    }
    notice(permission === "retain" ? "Review data cleared for this scope." : "Inspection permission revoked.");
  }

  async function run() {
    if (running || !job) return;
    running = true;
    $("inspect-progress").textContent = "Starting inspection.";
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
        if ($("inspect-registry").open) await loadRegistry();
        if ($("inspect-naming-audit").open) await loadNamingAudit();
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
        <p>${result.retains ? "Authorizing this destination will also keep its image text and corrections in the local checkpoint." :
          "Results for this destination stay in this temporary review."}</p>
        <label><input type="checkbox" id="inspect-link-plans" ${result.proposals ? "checked" : ""}> Suggest names and draft a plan for this destination</label>
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
    await selected(await api("select", {path: path.trim().replace(/^"|"$/g, ""),
      retain: $("inspect-retain").checked, proposals: $("inspect-propose").checked}));
  }

  $("inspect-selection").addEventListener("submit", (event) => {
    event.preventDefault();
    choose(pathField.value).catch(failure);
  });
  $("registry-file").addEventListener("change", async (event) => {
    const file = event.target.files[0], selected = job;
    profileDraft = null;
    $("registry-activate").disabled = true;
    $("registry-file-preview").textContent = "";
    if (!file) return;
    try {
      if (file.size > 62 * 1024) throw new Error("Choose a project profile JSON under 62 KiB.");
      const data = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
      if (job !== selected || event.target.files[0] !== file) return;
      if (!["journey-project-naming-1", "journey-project-naming-2"].includes(data?.format) || !Array.isArray(data.rules)) throw new Error("Choose a Journey project naming profile.");
      profileDraft = data;
      $("registry-file-preview").textContent = `${data.project} · ${data.rules.map(rule => rule.example?.filename).join(" · ")}`;
      $("registry-activate").disabled = false;
    } catch (error) { failure(error); }
  });
  $("inspect-registry").addEventListener("toggle", () => {
    if ($("inspect-registry").open) loadRegistry().catch(failure);
  });
  $("inspect-naming-audit").addEventListener("toggle", () => {
    if ($("inspect-naming-audit").open) loadNamingAudit().catch(failure);
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
        notice("Trial naming format saved.");
      } else if (event.target.id === "registry-profile") {
        if (!profileDraft) throw new Error("Choose a project profile first.");
        await api("registry-profile", {job, profile: profileDraft});
        registryOffset = 0;
        await loadRegistry();
        if ($("inspect-naming-audit").open) await loadNamingAudit();
        window.dispatchEvent(new Event("journey-project-ready"));
        notice("Project profile active for this inspection.");
      } else if (event.target.id === "naming-audit-load") {
        const file = $("naming-audit-file").files[0], selected = job;
        if (!file || file.size > 62 * 1024) throw new Error("Choose a naming audit JSON under 62 KiB.");
        const audit = JSON.parse((await file.text()).replace(/^\uFEFF/, ""));
        if (job !== selected) return;
        await api("naming-audit-load", {job, audit});
        await loadNamingAudit();
      } else if (event.target.id === "registry-import") {
        $("registry-status").textContent = "Reading the selected file for project evidence.";
        const result = await api("registry-import", {job, path: data.path.trim().replace(/^"|"$/g, "")});
        registryOffset = 0;
        await loadRegistry();
        notice(result.already_imported ? "This file was already imported for the active profile." : `Retained ${result.added} new source-linked records.`);
      } else if (event.target.dataset.imageDate) {
        await api("asset-creation-date", {job, asset: Number(event.target.dataset.imageDate), ...data});
        notice("Creation date recorded for this image.");
      } else if (event.target.dataset.imageReview) {
        await api("review", {job, asset: Number(event.target.dataset.imageReview), ...data});
        notice("Correction recorded. Related suggestions within this scope have been updated.");
      }
      await loadView();
    } catch (error) { failure(error); }
  });

  const commands = {
    "workflow-next": collectionNext,
    "workflow-skip": async () => { flowSkip = true; flowTarget = "images"; await collectionNext(); },
    "audit-row": auditProof,
    layout: () => {
      const compact = results.classList.toggle("compact-layout");
      $("inspect-layout").setAttribute("aria-pressed", String(compact));
      $("inspect-layout").textContent = compact ? "Show gallery" : "Compact list";
    },
    browse: () => browse(pathField.value ? pathField.value.trim().replace(/^"|"$/g, "") : ""),
    drives: () => browse(), folder: (path) => browse(path), "browse-page": (value) => browse(...JSON.parse(value)), choose,
    link: async (value) => selected(await api("select", {job, link: Number(value)})),
    approve: async (ticket) => {
      approval.querySelectorAll("button").forEach(button => { button.disabled = true; });
      notice("Checking the destination and its permissions…");
      try { await selected(await api("approve", {ticket, proposals: $("inspect-link-plans").checked})); }
      catch (error) { approval.hidden = true; throw error; }
    },
    "cancel-approval": () => { approval.hidden = true; notice("Current inspection scope retained."); },
    resume: run, pause,
    refresh: async () => { coverage(await api("refresh", {job})); await run(); },
    export: async () => {
      const result=$("inspect-export-result"); result.textContent="Saving inspection snapshot…";
      try { const output=await api("export",{job}); result.textContent=`Saved inspection snapshot: ${output.path}. This preserves review state; execution requires a separately approved batch.`; notice(result.textContent); }
      catch(error) { result.textContent=`Save failed: ${error.message}`; throw error; }
    },
    "allow-plans": async (value) => {
      const [scope, allowed] = JSON.parse(value);
      await api("proposals", {job, scope, allowed});
      coverage(await api("summary", {job}));
      await showAccess();
      await loadView();
    },
    "revoke-read": (scope) => revoke(scope, "inspect"),
    forget: (scope) => revoke(scope, "retain"),
    "registry-page": async (page) => { registryOffset = Number(page); await loadRegistry(); },
    "registry-deactivate": async () => {
      await api("registry-deactivate", {job});
      await loadRegistry();
      await loadView();
      window.dispatchEvent(new Event("journey-project-ready"));
      notice("Project profile deactivated for this inspection.");
    },
    "registry-review": async (value) => {
      const [claim, decision] = JSON.parse(value);
      await api("registry-review", {job, claim, decision});
      await loadRegistry();
      await loadView();
      notice("Evidence review recorded.");
    },
    "use-date": async (value) => {
      const [asset, claim] = JSON.parse(value);
      await api("asset-creation-date", {job, asset, claim});
      await loadView();
      notice("Archive date confirmed for this image.");
    },
    reauthorize: async (id) => {
      const data = await api("permissions", {job: id});
      pathField.value = data.root;
      $("inspect-retain").checked = true;
      setMode("inspect");
      notice("Choose your permissions and inspect this folder to reopen the checkpoint.");
    },
    previous: async () => { offset = Math.max(0, offset - 24); await loadView(); },
    next: async () => { offset += 24; await loadView(); },
    group: async (value) => {
      series = value; query = ""; view = "images"; offset = 0;
      $("inspect-filter").reset();
      panel.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
      await loadView();
    },
    saved: async (value) => { await pause(); view = "images"; series = query = ""; offset = 0; $("inspect-filter").reset(); await openJob(value); },
    exit: async () => { await pause(); await api("exit"); manage.innerHTML = '<p>Navigator is closed.</p>'; }
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

  document.querySelector(".titlebar .subtitle").textContent = "Local image stewardship · Guided changes require your account";
  document.querySelector('[data-panel="home"]').innerHTML = `<div class="inspection-card"><h2>Navigator inspection</h2><p>Open Inspect to choose a folder or shortcut. Manage reopens saved inspections.</p></div>`;
  document.querySelector('[data-panel="find"]').innerHTML = `<div class="inspection-card"><h2>Find inspected files</h2><p>Search filenames, paths, and text read from images in the current inspection.</p></div>`;
  window.addEventListener("journey-evidence-change", () => {
    if (!job) return;
    Promise.all([loadView(), loadRegistry(), $("inspect-naming-audit").open ? loadNamingAudit() : Promise.resolve()]).catch(failure);
  });
  document.querySelector('[data-panel="guide"]').innerHTML = `<div class="inspection-card"><h2>Inspect and review</h2>
    <p>Browse to the folder or select an existing shortcut. Navigator shows the link and destination separately. Approve a destination when it falls outside the current scope.</p>
    <p>Pause at any time. Turn on a local checkpoint to reopen from Manage. Name suggestions are optional, and a saved plan records previews in Journey's local review storage.</p></div>`;
  setMode("inspect");
})();
