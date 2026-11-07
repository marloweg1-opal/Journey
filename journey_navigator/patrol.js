"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const api = (name, body = {}) => apiPost(`/api/inspect/${name}`, body);
  const notify = value => { $("inspect-notice").textContent = value; const alert=$("journey-alert"); if (alert) alert.textContent=value; };
  let destination = "", current = null, offset = 0, polling = false, collection = "", questionMembers = null, batchId = "";
  const client = sessionStorage.getItem("journey-window") || crypto.randomUUID();
  sessionStorage.setItem("journey-window", client);
  const toolbar = document.createElement("nav");
  toolbar.className = "inspection-bar journey-tools";
  toolbar.setAttribute("aria-label", "Journey tools");
  toolbar.innerHTML = ["Destination", "Inspect", "Patrol", "Find", "Review", "Manage"].map(name =>
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
  api("attach", {client}).catch(() => {});
  window.addEventListener("pagehide", () => {
    fetch('/api/inspect/detach', {method:'POST', keepalive:true, headers:{'Content-Type':'application/json',
      'X-Journey-Session':sessionStorage.getItem('journey-inspection-session') || ''},body:JSON.stringify({client})}).catch(() => {});
  });
  const selected = selector => [...document.querySelectorAll(selector + ':checked')].map(input => Number(input.value));
  const failure = error => notify(error.error || error.message || String(error));

  async function list() {
    const {items} = await api("destinations");
    $("destination-list").innerHTML = items.map(row => `<div class="inspection-entry"><strong>${esc(row.objective)}</strong>
      <p>${esc(row.coverage.root)} · ${esc(row.state)}</p><button type="button" data-destination="${esc(row.id)}">Open Destination</button></div>`).join("");
    const job = sessionStorage.getItem("journey-current-inspection");
    $("destination-scope").textContent = job ? "The current Inspect selection supplies the scope and its granted permissions." : "Select a project in Inspect first.";
    if (!destination && items.length) destination = items[0].id;
  }

  async function images() {
    if (!current) return;
    const page = await api("destination-images", {destination, offset, collection, assets:questionMembers});
    if (page.reason) throw new Error(page.reason);
    $("patrol-review-images").innerHTML = page.items.map(image => `<label class="inspection-entry"><input type="checkbox" class="patrol-asset" value="${image.id}">
      <img src="data:image/webp;base64,${esc(image.thumbnail)}" alt="${esc(image.filename)}"><strong>${esc(image.filename)}</strong>
      <span>${esc(image.identity.label || 'Subject open')} · ${esc(image.identity.state.replaceAll('_',' '))}</span>
      <span>${esc(image.identity.reason)}</span></label>`).join("");
    $("patrol-names").innerHTML = page.items.filter(image => image.name.state === 'proposed').map(image => `<label class="inspection-entry">
      <input type="checkbox" class="patrol-name" value="${image.id}"><strong>${esc(image.filename)}</strong> → ${esc(image.name.destination)}
      <p>${esc(image.name.reason)}</p></label>`).join("") || '<p>Confirmed subject and purpose can support physical naming proposals. Preliminary suggestions are available in Inspect.</p>';
    $("review-page").textContent = `Page ${Math.floor(offset / 24)+1}`;
    $("review-previous").disabled = offset === 0;
    $("review-next").disabled = !page.more;
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
    current = await api("patrol-status", {destination});
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
    $("patrol-work").textContent = `${current.coverage.pending} images and ${current.coverage.pending_folders} folders waiting. ${current.metrics.unresolved} assets remain unresolved. ` + current.tasks.map(task => `${task.kind}: ${task.status}${task.reason ? " · " + task.reason : ""}`).join(". ");
    if (batchId) await viewBatch(batchId);
    return current;
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      while (destination) {
        const value = await status();
        if (!value || (!['Inspecting','Assessing','Working','Verifying'].includes(value.state) && !value.batches.some(batch => batch.status === 'authorizing'))) break;
        await new Promise(resolve => setTimeout(resolve, 800));
      }
    } catch (error) { failure(error); }
    finally { polling = false; }
  }

  $("destination-form").addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const data = Object.fromEntries(new FormData(event.target));
      const result = await api('destination-create', {...data,job:sessionStorage.getItem('journey-current-inspection'),max_files:Number(data.max_files),max_seconds:Number(data.max_seconds)});
      destination = result.id; batchId=''; collection=''; questionMembers=null; offset=0; setMode('patrol'); await status();
    } catch (error) { failure(error); }
  });
  $("patrol-start").onclick = async () => { try { await api('patrol-begin',{destination}); poll(); } catch(error) { failure(error); } };
  $("patrol-refresh").onclick = async () => { try { await api('patrol-begin',{destination,refresh:true}); poll(); } catch(error) { failure(error); } };
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
  $("review-previous").onclick = async () => { offset=Math.max(0,offset-24); await images(); };
  $("review-next").onclick = async () => { offset+=24; await images(); };
  document.addEventListener('click', async event => {
    const button=event.target.closest('button');
    if (!button) return;
    try {
      if (button.dataset.destination) { destination=button.dataset.destination; batchId=''; collection=''; questionMembers=null; offset=0; setMode('patrol'); await status(); poll(); }
      else if (button.dataset.collection) { collection=button.dataset.collection; questionMembers=null; offset=0; setMode('review'); await images(); }
      else if (button.dataset.batch) await viewBatch(button.dataset.batch);
      else if (button.dataset.authorizeBatch) { await api('batch-authorize',{destination,batch:button.dataset.authorizeBatch}); notify('Complete account verification in the Journey Windows dialog.'); poll(); }
      else if (button.dataset.undo) { const batch=await api('batch-undo',{destination,receipt:Number(button.dataset.undo)}); await viewBatch(batch.id); }
      else if (button.dataset.question) {
        const members=JSON.parse(button.dataset.question);
        questionMembers=members; collection=''; offset=0;
        await images(); document.querySelectorAll('.patrol-asset').forEach(input => { input.checked=members.includes(Number(input.value)); });
        $('patrol-review-images').closest('details').open=true;
      } else if (button.dataset.select === 'destination') await list();
      else if (button.dataset.select === 'patrol') { await list(); await status(); poll(); }
      else if (button.dataset.select === 'review') { await list(); await status(); await images(); }
    } catch(error) { failure(error); }
  });
  window.addEventListener('journey-manage', async () => {
    try {
      const {items}=await api('checkpoints');
      const panel=document.querySelector('[data-panel="manage"]');
      panel.querySelector('#journey-recovery')?.remove();
      const section=document.createElement('div'); section.id='journey-recovery'; section.className='inspection-card';
      section.innerHTML=`<h2>Work, permissions and recovery</h2><p>Inspect contains scope controls. Review contains exact batches, account approvals and operation receipts.</p>
        <button type="button" data-select="destination">Open saved Destinations</button> <button type="button" data-select="review">Review operations and recovery</button>
        <p>Inspection recovery snapshots restore reviewed data with scope access inactive. Action receipts stay current. Forgetting retained observations also clears old inspection recovery snapshots.</p>
        ${items.map(item=>`<div class="inspection-entry"><p>${esc(item.created)} · ${esc(item.backup)}</p><button type="button" data-restore="${item.version}">Restore inspection checkpoint</button></div>`).join('')}`;
      panel.append(section);
    } catch(error) { failure(error); }
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-restore]');
    if (!button || !confirm('Restore this inspection checkpoint? Current inspection data is backed up, scope access needs reselection, and action receipts stay current.')) return;
    try { await api('restore-checkpoint',{version:Number(button.dataset.restore)}); notify('Restoring the inspection checkpoint. Navigator will reopen.'); }
    catch(error) { failure(error); }
  });
  list().catch(failure);
})();
