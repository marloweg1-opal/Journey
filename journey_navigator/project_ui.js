"use strict";

(() => {
  const $ = id => document.getElementById(id);
  const api = (name, body = {}) => apiPost("/api/inspect/" + name, body);
  const selected = () => sessionStorage.getItem("journey-current-inspection");
  const pathValue = form => new FormData(form).get("path").trim().replace(/^"|"$/g, "");
  const status = (id, value) => {
    const item = $(id);
    if (item.textContent !== value) item.textContent = value;
  };
  const button = (text, callback) => {
    const item = document.createElement("button");
    item.type = "button";
    item.textContent = text;
    item.onclick = callback;
    return item;
  };
  const paragraph = (text, tag = "p") => {
    const item = document.createElement(tag);
    item.textContent = text;
    return item;
  };
  const errorText = error => error.error || error.message || String(error);
  const errorHandler = (id, task) => async event => {
    event?.preventDefault();
    event?.stopPropagation();
    try { await task(event); } catch (error) { status(id, errorText(error)); }
  };
  let historyTimer, watchTimer, historyPending = false;
  let ownerJob = null;

  async function loadPack() {
    const job = selected();
    if (!job || job.startsWith("session-")) return;
    const data = await api("pack-status", {job});
    if (selected() !== job) return;
    $("history-preview").querySelector("button").disabled = !data.project;
    $("pack-results").replaceChildren(paragraph(data.project ?
      data.project + " · " + data.rules + " reviewed rename rules · " + (data.audit ? "Naming audit active" : "Naming audit open") :
      "No project pack active in this inspection."));
    if (data.rollback) {
      $("pack-results").append(button("Restore prior pack", errorHandler("pack-status-message", async () => {
        await api("pack-rollback", {job});
        window.dispatchEvent(new Event("journey-evidence-change"));
        await sync();
      })));
    }
    if (!data.project) {
      status("history-status", "Activate a project profile to import project history.");
      $("history-files").replaceChildren();
    } else {
      await history();
    }
  }

  $("pack-preview").onsubmit = errorHandler("pack-status-message", async event => {
    const job = selected();
    const plan = await api("pack-preview", {job, path: pathValue(event.currentTarget)});
    if (selected() !== job) return;
    const target = $("pack-results");
    target.replaceChildren(paragraph(plan.name + " · pack preview"));
    for (const item of plan.choices) {
      target.append(paragraph(item.project + " · " + item.rules + " rules · " + item.rules_added +
        " added, " + item.rules_removed + " replaced or removed" + (item.includes_audit ? " · Includes audit" : "")));
      if (item.compatible) target.append(button("Activate " + item.project + " for this scope",
        errorHandler("pack-status-message", async () => {
          if (selected() !== job) return;
          await api("pack-apply", {job, project: item.key, ticket: plan.ticket});
          status("pack-status-message", "Pack saved for this inspection.");
          window.dispatchEvent(new Event("journey-evidence-change"));
          await sync();
        })));
      else target.append(paragraph("Use an independent inspection for this project."));
    }
  });

  let evidenceSequence = null;
  function renderHistory(data, job) {
    window.dispatchEvent(new CustomEvent('journey-history-status', {detail: {job, data}}));
    const sequence = (data.incremental || [])[0]?.sequence || 0;
    if (evidenceSequence !== null && evidenceSequence !== sequence) window.dispatchEvent(new Event("journey-evidence-change"));
    evidenceSequence = sequence;
    clearTimeout(historyTimer);
    const complete = data.files.filter(item => item.status === "complete").length;
    const queued = data.files.filter(item => item.status === "queued").length;
    const scanned = data.files.reduce((sum, item) => sum + item.offset, 0);
    const failed = data.files.filter(item => item.status === "failed").length;
    const message = complete + " exports indexed · " + data.unique_messages.toLocaleString() + " distinct messages · " +
      data.referenced_assets.toLocaleString() + " named assets · " + data.attachment_records.toLocaleString() +
      " attachment references · " + (data.text_index?.indexed_messages || 0).toLocaleString() + " searchable messages · " + queued + " queued · " + failed + " failed";
    status("history-status", data.files.length ? message + (queued ? " · " + Math.round(scanned / 1048576) + " MiB examined" : "") :
      "No local conversation archive has been indexed for this inspection.");
    const details = $("history-files");
    let summary = details.querySelector("details");
    if (!summary) {
      summary = document.createElement("details");
      summary.append(paragraph("Archive coverage and gaps", "summary"), paragraph("", "div"));
      details.append(summary);
    }
    const recap = data.reconciliation;
    const body = summary.querySelector("div");
    body.replaceChildren();
    if (recap) {
      body.append(paragraph(recap.name_candidates + " filename candidates · " + recap.not_located_in_scope +
        " reference names unlocated in this scope · " + recap.ambiguous_names + " ambiguous names · " +
        recap.byte_verified_exemplars + " matching project-pack fingerprints. Export attachment pointers have no accessible bytes." +
        (recap.current ? "" : " Refresh reconciliation after the inventory or evidence changes.")));
    }
    for (const change of data.incremental || []) {
      body.append(paragraph(change.export + " · " + change.new_claims + " new assertions · " + change.changed_claims +
        " changed claims · " + change.overlapping_claims + " overlapping assertions reused · " + change.affected_assets + " affected assets"));
      const proof = document.createElement("details");
      proof.append(paragraph("Trace new conclusions to their sources", "summary"));
      for (const claim of change.changes) proof.append(paragraph(claim.name + " · " + claim.kind + " · " +
        JSON.stringify(claim.value) + " · " + claim.source.role + " · conversation " + claim.source.conversation + " · message " + claim.source.message));
      body.append(proof);
    }
    const monitor = data.monitor;
    if (monitor) {
      body.append(paragraph("Export monitoring · " + monitor.state + " · " + monitor.checked + " entries checked · " +
        monitor.queued + " new exports queued · " + monitor.gaps + " gaps. Monitoring stops when Navigator closes or import is paused."));
      if (monitor.enabled) body.append(button("Stop export monitoring", errorHandler("history-status", async () => {
        await api("history-monitor-stop", {job}); await history();
      })));
      else if (monitor.available_folder) body.append(paragraph("Allow new conversations*.json exports in " + monitor.available_folder +
        " to enrich this project's retained knowledge and refresh affected saved virtual groups this session. Every 60 seconds, at most 24 folder entries and 24 asset reassessments, with a soft 150 ms folder scan. Import budgets still apply."),
        button("Monitor this reviewed export folder", errorHandler("history-status", async () => {
          await api("history-monitor-enable", {job}); await history();
        })));
    }
    for (const file of data.files) {
      body.append(paragraph(file.name + " · " + file.status + " · " + file.records + " conversations" +
        (file.gaps ? " · " + file.gaps + " excluded by export privacy flag" : "") + (file.error ? " · " + file.error : "")));
    }
    if (queued || (data.monitor && data.monitor.enabled)) {
      historyPending = historyPending || queued > 0;
      historyTimer = setTimeout(() => history().catch(error => status("history-status", errorText(error))), 1300);
    } else if (historyPending && selected() === job) {
      historyPending = false;
      window.dispatchEvent(new Event("journey-evidence-change"));
    }
  }

  async function history() {
    const job = selected();
    if (!job || job.startsWith("session-")) return;
    const data = await api("history-status", {job});
    if (selected() === job) renderHistory(data, job);
  }

  $("history-preview").onsubmit = errorHandler("history-status", async event => {
    const job = selected();
    const plan = await api("history-preview", {job, path: pathValue(event.currentTarget)});
    if (selected() !== job) return;
    const target = $("history-selection");
    const files = document.createElement("details");
    files.append(paragraph("Files in this reference grant", "summary"));
    for (const file of plan.files) files.append(paragraph(file.name + " · " + file.size.toLocaleString() + " bytes"));
    target.replaceChildren(paragraph(plan.files.length + " export files · " + (plan.bytes / 1048576).toFixed(1) +
      " MiB · " + plan.project + " · " + plan.other_entries + " other entries ignored. Read these exports and keep only the scoped index?"), files,
      button("Import these reviewed exports", errorHandler("history-status", async () => {
        if (selected() !== job) return;
        const data = await api("history-enqueue", {job, ticket: plan.ticket});
        target.replaceChildren();
        renderHistory(data, job);
      })));
  });

  async function showWatch(value = null) {
    clearTimeout(watchTimer);
    const job = selected();
    if (!job || job.startsWith("session-")) return;
    const data = value || await api("watch-status", {job});
    if (selected() !== job) return;
    status("watch-status", data.state + " · " + data.checked + " metadata checks · " + data.gaps + " gaps" +
      (data.last_check ? " · Last check " + new Date(data.last_check).toLocaleTimeString() : "") +
      (data.changes.length ? " · Refresh source to review changes in " + data.changes.join(", ") : ""));
    if (data.enabled) watchTimer = setTimeout(() => showWatch().catch(error => status("watch-status", errorText(error))), 10000);
  }

  const commands = {
    "history-status": history,
    "history-pause": async () => renderHistory(await api("history-pause", {job: selected()}), selected()),
    "history-reconcile": async () => { await api("history-reconcile", {job: selected()}); await history(); },
    "history-forget": async () => {
      if (!window.confirm("Forget local conversation indexes for this inspection and clear its recovery snapshots?")) return;
      await api("history-forget", {job: selected()});
      window.dispatchEvent(new Event("journey-evidence-change"));
      await history();
    },
    "watch-status": () => showWatch(),
    "watch-enable": async () => showWatch(await api("watch-enable", {job: selected()})),
    "watch-stop": async () => showWatch(await api("watch-stop", {job: selected()})),
  };

  document.querySelectorAll("[data-project]").forEach(item => {
    const name = item.dataset.project;
    item.onclick = errorHandler(name.startsWith("watch") ? "watch-status" : "history-status", commands[name]);
  });

  async function sync() {
    const job = selected();
    if (ownerJob !== job) {
      ownerJob = job;
      historyPending = false;
      clearTimeout(historyTimer);
      clearTimeout(watchTimer);
      $("history-selection").replaceChildren();
      $("history-preview").reset();
      $("pack-preview").reset();
    }
    await loadPack();
    await showWatch();
  }

  window.addEventListener("journey-project-ready", () => sync().catch(error => status("history-status", errorText(error))));
})();
