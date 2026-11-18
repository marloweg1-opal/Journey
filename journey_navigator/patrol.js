"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const api = (name, body = {}) => apiPost(`/api/inspect/${name}`, body);
  const notify = value => { $("inspect-notice").textContent = value; const alert=$("journey-alert"); if (alert) alert.textContent=value; };
  let destination = "", current = null, offset = 0, polling = false, collection = "", questionMembers = null, batchId = "";
  let imageRequest=0, statusRequest=0, renderedSnapshot='', pollAgain=false;
  let stewardshipScope = null, stewardshipReview = null, retirementDecision = "", talkRequest = null;
  let evidenceScope = null;
  const destinationJobs = new Map();
  const selections={'.patrol-asset':new Set(),'.patrol-name':new Set()};
  const clearSelections=()=>Object.values(selections).forEach(values=>values.clear());
  const client = crypto.randomUUID();
  const toolbar = document.createElement("nav");
  toolbar.className = "inspection-bar journey-tools";
  toolbar.setAttribute("aria-label", "Journey tools");
  toolbar.innerHTML = ["Talk", "Destination", "Inspect", "Patrol", "Find", "Review", "Manage"].map(name =>
    `<button type="button" data-select="${name.toLowerCase()}">${name}</button>`).join("");
  document.querySelector(".quick").after(toolbar);
  const alert=document.createElement('p'); alert.id='journey-alert'; alert.setAttribute('role','status'); alert.setAttribute('aria-live','polite'); toolbar.after(alert);
  const build = document.createElement("div");
  build.className = "inspection-card journey-build";
  document.querySelector(".titlebar").after(build);
  api("build").then(info => {
    build.innerHTML = `<strong>Journey ${esc(info.version)}</strong> · ${esc(info.installation)} · Build ${esc(info.commit)} / ${esc(info.build)}
      <details><summary>Running application</summary><p>${esc(info.location)}</p><p>${esc(info.executable)}</p><p>Session ${esc(info.session)}</p></details>`;
  }).catch(error => notify(error.message || String(error)));
  const heartbeat = () => api("attach", {client}).catch(() => {});
  heartbeat();
  const windowLease = setInterval(heartbeat, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) heartbeat(); });
  window.addEventListener("pagehide", () => {
    clearInterval(windowLease);
    fetch('/api/inspect/detach', {method:'POST', keepalive:true, headers:{'Content-Type':'application/json',
      'X-Journey-Session':sessionStorage.getItem('journey-inspection-session') || ''},body:JSON.stringify({client})}).catch(() => {});
  });
  const selected = selector => [...selections[selector]];
  document.addEventListener('change',event=>{
    for (const [selector,values] of Object.entries(selections)) {
      if (event.target.matches(selector)) {
        const id=Number(event.target.value);
        if (event.target.checked) values.add(id); else values.delete(id);
      }
    }
  });
  const failure = error => notify(error.error || error.message || String(error));
  const talkForm = $("stewardship-plan");
  const talkSubmit = talkForm.querySelector('button[type="submit"]');
  const stewardshipStatus = value => { $("stewardship-status").textContent = value; };
  const readable = value => String(value ?? "").replaceAll("_", " ").toLowerCase();
  const retirementAssets = () => [...document.querySelectorAll(".stewardship-asset:checked")].map(input => Number(input.value));
  const selectedJob = () => sessionStorage.getItem("journey-current-inspection") || null;
  const talkDestination = job => job && destinationJobs.get(destination) === job ? destination : null;
  const matchesTalkSelection = scope => scope.job === selectedJob() && scope.destination === talkDestination(scope.job);
  const isTalkCurrent = scope => scope === stewardshipScope && matchesTalkSelection(scope);

  function resetStewardship(message = "") {
    stewardshipScope = null;
    stewardshipReview = null;
    retirementDecision = "";
    talkRequest = null;
    talkSubmit.disabled = false;
    $("stewardship-results").replaceChildren();
    stewardshipStatus(message);
  }

  function clearStaleTalk() {
    if (evidenceScope && !matchesTalkSelection(evidenceScope)) {
      evidenceScope = null;
      talkForm.elements.share_evidence.checked = false;
    }
    if (stewardshipScope && !isTalkCurrent(stewardshipScope)) {
      resetStewardship("Selection changed. Ask Journey again for the current scope.");
    }
  }

  function chooseDestination(id) {
    if (destination === id) return;
    destination = id;
    evidenceScope = null;
    talkForm.elements.share_evidence.checked = false;
    if (stewardshipScope) resetStewardship("Selection changed. Ask Journey again for the current scope.");
  }

  function addTalkText(parent, tag, value) {
    const element = document.createElement(tag);
    if (value != null) element.textContent = value;
    parent.append(element);
    return element;
  }

  function addTalkValue(parent, value) {
    if (Array.isArray(value)) {
      const items = addTalkText(parent, "ul");
      for (const item of value) addTalkValue(addTalkText(items, "li"), item);
    } else if (value && typeof value === "object") {
      const fields = addTalkText(parent, "dl");
      for (const [label, item] of Object.entries(value)) {
        addTalkText(fields, "dt", readable(label));
        addTalkValue(addTalkText(fields, "dd"), item);
      }
    } else {
      parent.append(document.createTextNode(value == null ? "—" : String(value)));
    }
  }

  function addTalkSection(parent, heading, value, collapsed = false) {
    if (value == null || (typeof value === "object" && !Object.keys(value).length)) return;
    const section = addTalkText(parent, collapsed ? "details" : "div");
    section.className = "inspection-entry";
    addTalkText(section, collapsed ? "summary" : "h3", heading);
    addTalkValue(section, value);
  }

  function showStewardship(result, scope) {
    const slot = $("stewardship-results");
    const state = readable(result.state);
    stewardshipStatus(state === "complete" || state === "completed" ? "Completed." :
      state.charAt(0).toUpperCase() + state.slice(1) + ".");
    if (result.message) addTalkText(slot, "p", result.message);
    if (result.reason && result.reason !== result.message) addTalkText(slot, "p", result.reason);
    addTalkSection(slot, "Identity", result.identity);
    addTalkSection(slot, "Authority", result.authority);
    addTalkSection(slot, "Knowledge", result.knowledge);
    addTalkSection(slot, "Inspection coverage", result.summary, true);
    addTalkSection(slot, "History coverage", result.history, true);
    addTalkSection(slot, "Duplicate audit", result.audit, true);
    addTalkSection(slot, "Local models", result.models);
    if (result.provider && typeof result.provider === "object") addTalkSection(slot, "Local interpretation", result.provider);
    if (result.capabilities?.length) {
      addTalkText(slot, "h3", "Capabilities");
      for (const {id, ...capability} of result.capabilities) addTalkSection(slot, readable(id), capability);
    }
    if (result.results?.length) {
      addTalkText(slot, "h3", "Matches");
      for (const item of result.results) {
        const match = addTalkText(slot, "div");
        match.className = "inspection-entry";
        addTalkText(match, "strong", item.title || item.name || "History excerpt");
        if (item.excerpt != null) {
          addTalkText(match, "p", item.excerpt);
          addTalkValue(match, {source: item.name, role: item.role, conversation: item.conversation, message: item.message,
            conversation_timestamp: item.authored, imported: item.imported, truncated: Boolean(item.truncated)});
        } else {
          if (item.group) addTalkText(match, "p", item.group);
          addTalkText(match, "p", item.details || item.summary);
        }
      }
    }
    if (result.evidence?.length) {
      const evidence = addTalkText(slot, "details");
      addTalkText(evidence, "summary", `Evidence (${result.evidence.length})`);
      for (const {id, kind, value} of result.evidence) addTalkSection(evidence, `${id} · ${readable(kind)}`, value);
    }
    if (result.council) {
      addTalkText(slot, "h3", "Council");
      if (result.council.state) addTalkText(slot, "p", readable(result.council.state));
      for (const {member, ...consultation} of result.council.members || []) addTalkSection(slot, member, consultation);
      addTalkSection(slot, "Council assessment", result.council.assessment);
      addTalkSection(slot, "Council metrics", result.council.metrics, true);
    }
    addTalkSection(slot, "Request metrics", result.metrics, true);

    if (result.binding) {
      const review = addTalkText(slot, "div");
      showRetirementReview(review, result);
    } else if (result.intent === "organize" && result.state === "AWAITING_REVIEW" && scope.destination && result.steps?.length) {
      addTalkText(slot, "h3", "Organization plan");
      if (result.scope) addTalkText(slot, "p", result.scope);
      const steps = addTalkText(slot, "ol");
      for (const step of result.steps) addTalkText(steps, "li", step);
      addTalkText(slot, "p", "Patrol will update virtual groups and report review decisions. Physical changes use a separate exact batch.");
      const begin = addTalkText(slot, "button", "Start this scoped plan");
      begin.type = "button";
      begin.id = "start-goal-patrol";
      begin.onclick = async () => {
        if (!isTalkCurrent(scope)) { clearStaleTalk(); return; }
        begin.disabled = true;
        try {
          const started = await api("patrol-begin", {destination: scope.destination});
          if (started.error) throw started;
          if (isTalkCurrent(scope)) { setMode("patrol"); poll(); }
        } catch (error) { if (isTalkCurrent(scope)) stewardshipStatus(`Plan failed. ${error.error || error.message || error}`); }
        finally { begin.disabled = !isTalkCurrent(scope); }
      };
    }
  }

  function showRetirementReview(slot, result) {
    const {entries, dependencies} = result;
    const candidates = entries.filter(item => item.group === "asset_candidate");
    const rest = entries.filter(item => item.group !== "asset_candidate");
    const sources = entry => entry.evidence.map(item => `<p><small>${esc(item.source.role)} · ${esc(item.source.archive)} · ${esc(item.source.message)}</small></p>`).join("");
    slot.innerHTML = `<h3>Retirement review for ${esc(result.family)}</h3><p><strong>Review scope</strong> · ${esc(result.scope)}</p>
      <p>${esc(result.withheld_or_changed)} matches withheld or changed. ${esc(dependencies.files_checked)} reference files checked · ${esc(readable(dependencies.state))}.</p>
      <details><summary>What Journey checked</summary><dl>${Object.entries(result.questions).map(([question, state]) =>
        `<dt>${esc(readable(question))}</dt><dd>${esc(readable(state))}</dd>`).join("")}</dl></details>
      <h4>Asset candidates</h4>${candidates.map(item => `<div class="inspection-entry">
        <label><input class="stewardship-asset" type="checkbox" value="${esc(item.id)}"> ${esc(item.path)}</label>
        ${item.physical_blocker ? `<p>Archive hold · ${esc(item.physical_blocker)}</p>` : ""}
        ${item.copy_paths.map(path => `<p>Identical content at a separate path · ${esc(path)}</p>`).join("")}
        ${sources(item)}</div>`).join("") || "<p>Review references and scope before recording a retirement.</p>"}
      <h4>Historical references and unresolved entries</h4>
      ${rest.map(item => `<div class="inspection-entry"><p>${esc(item.path)} · ${esc(readable(item.group))}</p>${sources(item)}</div>`).join("")}
      ${result.archive_evidence.map(item => `<p>${esc(item.name)} · ${esc(item.decision)} · ${esc(item.source.archive)} · ${esc(item.source.message)}</p>`).join("")}
      <h4>Dependency evidence</h4>
      ${dependencies.references.map(item => `<p>${esc(item.reference)} → ${esc(item.target)} · ${esc(readable(item.role))}</p>`).join("")}
      ${candidates.length ? `<form id="stewardship-confirm" class="inspection-bar">
        <label>Reason for retirement <input name="reason" maxlength="300" required></label>
        <label>Replacement, if known <input name="replacement" maxlength="180"></label>
        <button type="submit">Record selected retirements</button></form>
      <form id="stewardship-archive" class="inspection-bar" hidden>
        <label>Existing archive folder in this scope <input name="folder" required></label>
        <button type="submit">Prepare exact archive batch</button></form>` : ""}`;
  }

  async function list() {
    const {items} = await api("destinations");
    for (const row of items) destinationJobs.set(row.id, row.job);
    $("destination-list").innerHTML = items.map(row => `<div class="inspection-entry"><strong>${esc(row.objective)}</strong>
      <p>${esc(row.coverage.root)} · ${esc(row.state)}</p><button type="button" data-destination="${esc(row.id)}">Open Destination</button></div>`).join("");
    const job = sessionStorage.getItem("journey-current-inspection");
    $("destination-scope").textContent = job ? "The current Inspect selection supplies the scope and its granted permissions." : "Select a project in Inspect first.";
    if (!destination && items.length) destination = items[0].id;
    clearStaleTalk();
  }

  async function images() {
    if (!current) return;
    const request=++imageRequest, requestedDestination=destination, snapshot=current.outcome_binding;
    $("patrol-naming-batch").disabled=true;
    $("patrol-answer").querySelector('button[type="submit"]').disabled=true;
    const page = await api("destination-images", {destination:requestedDestination, offset, collection, assets:questionMembers});
    if (request !== imageRequest || requestedDestination !== destination) return;
    if (page.reason) throw new Error(page.reason);
    const available=new Set(page.items.map(image=>image.id));
    for (const values of Object.values(selections)) for (const id of values) if (!available.has(id)) values.delete(id);
    $("patrol-review-images").innerHTML = page.items.map(image => `<label class="inspection-entry"><input type="checkbox" class="patrol-asset" value="${image.id}"${selections['.patrol-asset'].has(image.id) ? ' checked' : ''}>
      <img src="data:image/webp;base64,${esc(image.thumbnail)}" alt="${esc(image.filename)}"><strong>${esc(image.filename)}</strong>
      <span>${esc(image.identity.label || 'Subject open')} · ${esc(image.identity.state.replaceAll('_',' '))}</span>
      <span>${esc(image.identity.reason)}</span></label>`).join("");
    $("patrol-names").innerHTML = page.items.filter(image => image.name.state === 'proposed').map(image => `<label class="inspection-entry">
      <input type="checkbox" class="patrol-name" value="${image.id}"${selections['.patrol-name'].has(image.id) ? ' checked' : ''}><strong>${esc(image.filename)}</strong> → ${esc(image.name.destination)}
      <p>${esc(image.name.reason)}</p></label>`).join("") || (page.items.some(image => image.naming_profile.state === 'validated') ?
        '<p>No eligible naming proposals in this view. Check the naming evidence and date details in Inspect.</p>' :
        '<p>Preliminary naming evidence is available in Inspect. Source filename changes are held because no validated project naming profile is active.</p>');
    $("review-page").textContent = `Page ${Math.floor(offset / 24)+1}`;
    $("review-previous").disabled = offset === 0;
    $("review-next").disabled = !page.more;
    $("patrol-naming-batch").disabled=!page.items.some(image => image.name.state === 'proposed');
    $("patrol-answer").querySelector('button[type="submit"]').disabled=false;
    renderedSnapshot=snapshot;
  }

  async function viewBatch(id) {
    const requestedDestination=destination;
    batchId=id;
    const batch = await api('batch-view', {destination:requestedDestination, batch:id});
    if (batchId !== id || destination !== requestedDestination) return;
    $("patrol-batch-details").innerHTML = `<div class="inspection-entry"><h3>Exact batch · ${esc(batch.status)}</h3>
      <p>Scope ${esc(batch.scope)}</p><p>Review binding ${esc(batch.binding)}</p>
      ${batch.operations.map(op => `<p><strong>${esc(op.kind)}</strong> · ${esc(op.source || 'New folder')} → ${esc(op.destination)}</p><p>${esc(op.reason)}</p>`).join('')}
      <p>${esc(batch.reason)}</p>${batch.approval ? `<p>Approved by ${esc(batch.approval.account)} · ${esc(batch.approval.method)}</p>` : ''}
      ${['review_required','blocked','partially_completed'].includes(batch.status) ? `<button type="button" data-authorize-batch="${esc(id)}">Authorize exact batch with my Windows account</button>` : ''}
      <p>File changes require your assessment of these paths and their external dependencies. The Windows account prompt completes attribution.</p></div>`;
  }

  async function status() {
    if (!destination) return;
    const request=++statusRequest, requestedDestination=destination;
    const value=await api("patrol-status", {destination:requestedDestination});
    if (request !== statusRequest || requestedDestination !== destination) return current;
    if (current && current.id === value.id && current.inspection_epoch !== value.inspection_epoch) {
      clearSelections(); questionMembers=null; offset=0; imageRequest++; renderedSnapshot='';
      $("patrol-review-images").innerHTML='<p>The source inventory is refreshing. Select current images after assessment.</p>';
      $("patrol-names").innerHTML='';
    }
    current=value;
    destinationJobs.set(value.id, value.job);
    clearStaleTalk();
    const approving=current.batches.some(batch => batch.status === 'authorizing');
    const pill=document.querySelector('.status-pill');
    pill.innerHTML=`<span class="status-dot"></span>${esc(current.state)}`;
    pill.title=current.reason;
    if (!approving && $("journey-alert").textContent === 'Complete account verification in the Journey Windows dialog.') notify('');
    $("patrol-objective").textContent = current.objective;
    $("patrol-intent").textContent = `${current.why} Success looks like ${current.success} ${current.objective_outcome}`;
    $("patrol-state").textContent = current.state;
    $("patrol-reason").textContent = current.reason;
    $("patrol-authority").textContent = `Scope ${current.authority.scope} · Active authority ${current.authority.active} · Ceiling ${current.authority.ceiling}`;
    const metrics = {"Files inspected":current.coverage.files,"Images analyzed":current.coverage.analyzed,
      "Images with text":current.coverage.text_count,"Proposed identities":current.metrics.proposed,
      "Confirmed identities":current.metrics.confirmed,"Virtual collections":current.metrics.collections,
      "Unresolved assets":current.metrics.unresolved,"Verified operations":current.metrics.physical_verified,
      "Coverage gaps":current.coverage.skipped+current.coverage.link_attention,"Batches awaiting approval":current.batches_waiting};
    $("patrol-metrics").innerHTML = Object.entries(metrics).map(([label,count]) => `<div><strong>${count.toLocaleString()}</strong><span>${esc(label)}</span></div>`).join('');
    $("patrol-collections").innerHTML = current.collections.map(value => `<button type="button" data-collection="${esc(value.name)}">${esc(value.name)} · ${value.members}</button>`).join('') || '<p>Collections will appear as evidence is assessed.</p>';
    $("patrol-questions").innerHTML = current.questions.map(question => `<div class="inspection-entry"><strong>${esc(question.prompt)}</strong>
      <p>${question.members.length} images share this review question.</p><button type="button" data-question="${esc(JSON.stringify(question.members))}">Select these images</button></div>`).join('') ||
      (['Inspecting','Assessing','Working','Verifying'].includes(current.state) ? '<p>Assessment is continuing. Review questions update at the next checkpoint.</p>' : '<p>No material conflicts have been queued for this view.</p>');
    $("patrol-batches").innerHTML = current.batches.map(batch => `<div class="inspection-entry">${esc(batch.status)} · ${esc(batch.reason)}
      <button type="button" data-batch="${esc(batch.id)}">Review exact batch</button></div>`).join('');
    $("patrol-history").innerHTML = current.history.map(receipt => `<div class="inspection-entry"><strong>OP-${String(receipt.id).padStart(6,'0')} · ${esc(receipt.status)}</strong>
      <p>${esc(receipt.action_type)} · ${esc(receipt.target_path)}</p><details><summary>Verification receipt</summary><pre>${esc(JSON.stringify(JSON.parse(receipt.new_state || '{}'),null,2))}</pre></details>
      ${receipt.action_type === 'file_move' && receipt.status === 'applied' ? `<button type="button" data-undo="${receipt.id}">Review safe reversal</button>` : ''}</div>`).join('') || '<p>Account-approved operations will appear here with their verification evidence.</p>';
    $("patrol-work").textContent = current.report;
    if (batchId) await viewBatch(batchId);
    if (document.querySelector('[data-panel="review"]').classList.contains('active') &&
        !['Inspecting','Assessing','Working','Verifying'].includes(current.state) && renderedSnapshot !== current.outcome_binding) await images();
    return current;
  }

  async function poll() {
    if (polling) { pollAgain=true; return; }
    polling = true;
    try {
      while (destination) {
        const value = await status();
        if (!value || (!['Inspecting','Assessing','Working','Verifying'].includes(value.state) && !value.batches.some(batch => batch.status === 'authorizing'))) break;
        await new Promise(resolve => setTimeout(resolve, 800));
      }
    } catch (error) { failure(error); }
    finally { polling = false; if (pollAgain) { pollAgain=false; poll(); } }
  }

  $("destination-form").addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const data = Object.fromEntries(new FormData(event.target));
      const result = await api('destination-create', {...data,job:sessionStorage.getItem('journey-current-inspection'),max_files:Number(data.max_files),max_seconds:Number(data.max_seconds)});
      destinationJobs.set(result.id, result.job);
      chooseDestination(result.id); clearSelections(); renderedSnapshot=''; batchId=''; collection=''; questionMembers=null; offset=0; setMode('patrol'); await status();
    } catch (error) { failure(error); }
  });
  $("patrol-save-preview").onclick = async () => {
    try {
      if (!current) throw new Error('Choose a saved Destination first.');
      const saved = await api('export', {job:current.job});
      $("patrol-preview-result").textContent = 'Organization preview saved to ' + saved.path + '. Saving this preview does not change source files. Physical changes require separate exact-batch approval.';
    } catch(error) { failure(error); }
  };
  $("patrol-start").onclick = async () => { try { await api('patrol-begin',{destination}); poll(); } catch(error) { failure(error); } };
  $("patrol-refresh").onclick = async () => { try { resetStewardship(); await api('patrol-begin',{destination,refresh:true}); poll(); } catch(error) { failure(error); } };
  $("patrol-pause").onclick = async () => { try { await api('patrol-pause',{destination}); await status(); } catch(error) { failure(error); } };
  $("patrol-accept-outcome").onclick = async () => {
    try { await api('destination-outcome',{destination,binding:current.outcome_binding}); await status(); }
    catch(error) { failure(error); }
  };
  $("patrol-review").onclick = async () => { setMode('review'); await status(); await images(); };
  $("patrol-answer").onsubmit = async event => {
    event.preventDefault();
    try { await api('patrol-answer',{destination,assets:selected('.patrol-asset'),...Object.fromEntries(new FormData(event.target))}); await status(); await images(); poll(); }
    catch(error) { failure(error); }
  };
  $("patrol-naming-batch").onclick = async () => {
    try { const batch = await api('batch-suggestions',{destination,assets:selected('.patrol-name')}); batchId=batch.id; await status(); }
    catch(error) { failure(error); }
  };
  $("patrol-operation").onsubmit = async event => {
    event.preventDefault();
    try {
      const operation = Object.fromEntries(new FormData(event.target));
      if (operation.kind !== 'mkdir') {
        const assets = selected('.patrol-asset');
        if (assets.length !== 1) throw new Error('Select one image above for this exact operation.');
        operation.asset = assets[0];
      }
      const batch = await api('batch-prepare',{destination,operations:[operation]});
      await status(); await viewBatch(batch.id);
    } catch(error) { failure(error); }
  };
  talkForm.elements.use_model.onchange = () => {
    const share = talkForm.elements.share_evidence;
    share.disabled = !talkForm.elements.use_model.checked;
    if (share.disabled) {
      share.checked = false;
      evidenceScope = null;
    }
  };
  talkForm.elements.share_evidence.onchange = () => {
    const job = selectedJob();
    evidenceScope = talkForm.elements.share_evidence.checked ? {job, destination: talkDestination(job)} : null;
  };
  for (const example of document.querySelectorAll("[data-talk-example]")) {
    example.onclick = () => {
      talkForm.elements.instruction.value = example.textContent;
      talkForm.elements.instruction.focus();
    };
  }
  talkForm.onsubmit = async event => {
    event.preventDefault();
    clearStaleTalk();
    if (talkRequest) return;
    const job = selectedJob();
    const scope = {job, destination: talkDestination(job)};
    const {instruction, use_model, share_evidence, read_references} = talkForm.elements;
    const body = {job, instruction: instruction.value, use_model: use_model.checked,
      share_evidence: use_model.checked && share_evidence.checked, read_references: read_references.checked};
    if (scope.destination) body.destination = scope.destination;
    share_evidence.checked = false;
    evidenceScope = null;
    resetStewardship();
    stewardshipScope = talkRequest = scope;
    talkSubmit.disabled = true;
    stewardshipStatus("Request started.");
    const waiting = setTimeout(() => {
      if (!isTalkCurrent(scope)) return;
      stewardshipStatus(body.use_model ? "Waiting for Journey. Local consultation can take up to two and a half minutes." : "Waiting for Journey’s reply.");
    }, 500);
    try {
      const result = await api("conversation", body);
      if (!isTalkCurrent(scope)) { clearStaleTalk(); return; }
      if (!result?.state) throw new Error(result?.error || "Journey returned no request status.");
      stewardshipReview = result.binding ? result : null;
      showStewardship(result, scope);
    } catch (error) {
      if (isTalkCurrent(scope)) resetStewardship(`Request failed. ${error.error || error.message || error}`);
      else clearStaleTalk();
    } finally {
      clearTimeout(waiting);
      if (talkRequest === scope) {
        talkRequest = null;
        talkSubmit.disabled = false;
      }
    }
  };
  $("stewardship-results").addEventListener("submit", async event => {
    event.preventDefault();
    clearStaleTalk();
    if (!stewardshipReview || !stewardshipScope?.destination) return;
    const scope = stewardshipScope;
    const request = {destination: scope.destination, binding: stewardshipReview.binding, assets: retirementAssets()};
    const data = Object.fromEntries(new FormData(event.target));
    try {
      if (event.target.id === "stewardship-confirm") {
        const result = await api("stewardship-confirm", {...request, ...data});
        if (!isTalkCurrent(scope) || stewardshipReview?.binding !== request.binding) return;
        retirementDecision = result.decision;
        $("stewardship-archive").hidden = stewardshipReview.dependencies.state !== "CHECKED_WITHIN_SCOPE";
        stewardshipStatus(`Recorded ${result.recorded} selected retirements in the registry.`);
        await status();
      } else {
        const batch = await api("stewardship-archive", {...request, ...data, decision: retirementDecision});
        if (!isTalkCurrent(scope) || stewardshipReview?.binding !== request.binding) return;
        await viewBatch(batch.id);
        if (!isTalkCurrent(scope)) return;
        stewardshipStatus("Exact archive batch prepared for account review.");
        setMode("review");
        $("patrol-batch-details").scrollIntoView({block:"center"});
      }
    } catch (error) {
      if (isTalkCurrent(scope)) stewardshipStatus(error.error || error.message || String(error));
    }
  });
  $("review-previous").onclick = async () => { clearSelections(); offset=Math.max(0,offset-24); await images(); };
  $("review-next").onclick = async () => { clearSelections(); offset+=24; await images(); };
  document.addEventListener('click', async event => {
    const button=event.target.closest('button');
    if (!button) return;
    try {
      if (button.dataset.destination) { chooseDestination(button.dataset.destination); clearSelections(); renderedSnapshot=''; batchId=''; collection=''; questionMembers=null; offset=0; setMode('patrol'); await status(); poll(); }
      else if (button.dataset.collection) { clearSelections(); collection=button.dataset.collection; questionMembers=null; offset=0; setMode('review'); await images(); }
      else if (button.dataset.batch) await viewBatch(button.dataset.batch);
      else if (button.dataset.authorizeBatch) { await api('batch-authorize',{destination,batch:button.dataset.authorizeBatch}); notify('Complete account verification in the Journey Windows dialog.'); poll(); }
      else if (button.dataset.undo) { const batch=await api('batch-undo',{destination,receipt:Number(button.dataset.undo)}); await viewBatch(batch.id); }
      else if (button.dataset.question) {
        const members=JSON.parse(button.dataset.question);
        clearSelections();
        members.forEach(id=>selections['.patrol-asset'].add(id));
        questionMembers=members; collection=''; offset=0;
        await images();
        $('patrol-review-images').closest('details').open=true;
      } else if (button.dataset.select === 'talk') clearStaleTalk();
      else if (button.dataset.select === 'destination') await list();
      else if (button.dataset.select === 'patrol') { await list(); await status(); poll(); }
      else if (button.dataset.select === 'review') { await list(); await status(); await images(); }
    } catch(error) { failure(error); }
  });
  window.addEventListener('journey-project-ready', clearStaleTalk);
  window.addEventListener('journey-duplicate-batch', async event => {
    try { chooseDestination(event.detail.destination); await list(); chooseDestination(event.detail.destination);
      await status(); await viewBatch(event.detail.batch); document.querySelector('[data-select="review"]')?.click(); poll();
      $("patrol-batch-details").scrollIntoView({block:'center'});
    } catch(error) { failure(error); }
  });
  window.addEventListener('journey-manage', async () => {
    try {
      const [{items}, builds]=await Promise.all([api('checkpoints'), api('managed-builds')]);
      const panel=document.querySelector('[data-panel="manage"]');
      panel.querySelector('#journey-recovery')?.remove();
      const section=document.createElement('div'); section.id='journey-recovery'; section.className='inspection-card';
      section.innerHTML=`<h2>Work, permissions and recovery</h2><p>Inspect contains scope controls. Review contains exact batches, account approvals and operation receipts.</p>
        <button type="button" data-select="destination">Open saved Destinations</button> <button type="button" data-select="review">Review operations and recovery</button>
        <p>Inspection recovery snapshots restore reviewed data with scope access inactive. Action receipts stay current. Forgetting retained observations also clears old inspection recovery snapshots.</p>
        ${items.map(item=>`<div class="inspection-entry"><p>${esc(item.created)} · ${esc(item.backup)}</p>
          <button type="button" data-restore="${item.version}">Restore inspection checkpoint</button>
          <button type="button" data-restore="${item.version}" data-close-for-rollback>Restore and close for build rollback</button></div>`).join('')}
        <details><summary>Managed candidate builds</summary>
          <p>Use the running build for current work. Prior builds are retained for review and rollback.</p>
          ${builds.items.map(item=>`<p>${item.running ? 'Running' : 'Prior candidate'} · ${esc(item.commit)} · ${esc(item.path)}</p>`).join('') || '<p>No managed candidate builds were found for this account.</p>'}</details>`;
      panel.append(section);
    } catch(error) { failure(error); }
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-restore]');
    if (!button || !confirm('Restore this inspection checkpoint? Current inspection data is backed up, scope access needs reselection, and action receipts stay current.')) return;
    try {
      const reopen=!button.hasAttribute('data-close-for-rollback');
      await api('restore-checkpoint',{version:Number(button.dataset.restore),reopen});
      notify(reopen ? 'Restoring the inspection checkpoint. Navigator will reopen.' : 'Restoring the checkpoint and closing for build rollback.');
    }
    catch(error) { failure(error); }
  });
  list().catch(failure);
})();
