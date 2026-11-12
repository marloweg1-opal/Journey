"use strict";
(() => {
  const $=id=>document.getElementById(id), api=(route,body={})=>apiPost(`/api/inspect/${route}`,body);
  let audit=null, timer=null, generation=0;
  const job=()=>sessionStorage.getItem('journey-current-inspection');
  const selected=new Set();
  async function status() {
    const scope=job(); if(!scope)return;
    const version=++generation, value=await api('duplicates-status',{job:scope});
    if(scope!==job() || version!==generation)return;
    const changed=audit?.id!==value.audit?.id;audit=value.audit;if(changed)selected.clear();
    $('duplicate-status').textContent=`${value.running?'Auditing':value.current?'Checkpoint ready':'Audit needed or stale'} · ${value.audited} files hashed · removal ${value.permission.enabled?'enabled for this scope':'locked'} · monitor ${value.monitor?'on':'off'}. ${value.error || value.monitor_error || ''}`;
    if(audit) {
      $('duplicate-report').innerHTML=`<p>${audit.proposed_removals} exact copies proposed; ${(audit.projected_recoverable_bytes/1048576).toFixed(2)} MiB potentially recoverable. ${audit.hashes_reused} hashes reused. ${audit.hash_errors.length} files could not be hashed.</p>
        <p>Every removal uses a verified, temporary recovery checkpoint for seven days. Its storage cost means these bytes are not immediately guaranteed free. Maximum 16 MiB per file, 256 MiB recovery quota. Different-byte variations are preserved.</p>
        <p>Reference check: ${esc(audit.references.state)}. No scan proves absence of external dependencies.</p>
        ${audit.exact_groups.map(g=>`<details><summary>Keep ${esc(g.keep.name)} · ${g.remove.length} proposed removals · ${g.held.length} held</summary><p>Retain: ${esc(g.keep.path)}</p>
          ${g.remove.map(i=>`<label class="inspection-entry"><input type="checkbox" data-duplicate-asset="${i.id}"${selected.has(i.id)?' checked':''}>Remove ${esc(i.path)} · ${i.size} bytes${i.automatic_candidate?' · copy-suffix rule candidate':''}</label>`).join('')}
          ${g.held.map(i=>`<p>Keep ${esc(i.path)}: ${esc(i.hold)}</p>`).join('')}</details>`).join('')}
        <details><summary>${audit.near_duplicates.length} perceptual variation pairs · review only</summary>${audit.near_duplicates.map(p=>`<p>Prefer for quality review: ${esc(p.preferred.name)} ↔ ${esc(p.variation.name)}. ${esc(p.reason)}</p>`).join('')}
        <p>${audit.near_coverage_limited?'Comparison budget reached; coverage is partial.':'Within the configured comparison budget.'}</p></details>
        <details><summary>Broad organization preview · ${audit.broad_groups.length} groups</summary>${audit.broad_groups.map(g=>`<p>${esc(g.label)} · ${g.assets.length} assets</p>`).join('')}<p>Virtual proposals only. Secondary relationships remain in searchable image evidence.</p></details>`;
    } else $('duplicate-report').textContent='Run an audit for a current preview. Source files remain unchanged.';
    $('duplicate-recovery').innerHTML=`<h4>Recovery checkpoints</h4>${value.recovery.map(r=>`<p>${esc(r.source)} · ${esc(r.state)} · expires ${new Date(r.expires*1000).toLocaleString()} ${r.state==='removed'?`<button type="button" data-duplicate-restore="${esc(r.id)}">Review restore</button>`:''}</p>`).join('') || '<p>No files removed in this scope.</p>'}`;
    clearTimeout(timer);if(value.running || value.monitor)timer=setTimeout(()=>status().catch(failure),2500);
  }
  function failure(error){$('duplicate-status').textContent=`Stopped: ${error.message}`;}
  async function review(result){window.dispatchEvent(new CustomEvent('journey-duplicate-batch',{detail:result}));}
  document.addEventListener('change',event=>{const id=event.target.dataset.duplicateAsset;if(id){if(event.target.checked)selected.add(Number(id));else selected.delete(Number(id));}});
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-duplicate],[data-duplicate-restore]');if(!button)return;
    const scope=job();if(!scope){failure(new Error('Select a checkpoint collection first.'));return;}
    button.disabled=true;
    try {
      const body={job:scope,read_references:$('duplicate-read-references').checked};
      if(button.dataset.duplicateRestore)await review(await api('duplicates-restore',{job:scope,recovery:button.dataset.duplicateRestore}));
      else switch(button.dataset.duplicate){
        case 'audit':await api('duplicates-audit',body);break;
        case 'permission':await api('duplicates-permission',{job:scope,automatic:$('duplicate-automatic').checked});$('duplicate-status').textContent='Complete or cancel the scoped permission dialog in Windows, then refresh this report.';return;
        case 'watch':await api('duplicates-watch',{...body,enabled:true});break;
        case 'stop':await api('duplicates-watch',{...body,enabled:false});await api('duplicates-revoke',{job:scope});break;
        case 'prepare':if(!audit)throw new Error('Audit the collection first.');await review(await api('duplicates-prepare',{job:scope,audit:audit.id,assets:[...selected]}));break;
      }
      await status();
    } catch(error){failure(error);}finally{button.disabled=false;}
  });
  $('inspect-duplicates').addEventListener('toggle',()=>{if($('inspect-duplicates').open)status().catch(failure);});
  $('history-text-search').addEventListener('submit',async event=>{
    event.preventDefault();try{const result=await api('history-text-search',{job:job(),query:new FormData(event.target).get('query')});
      $('history-text-results').innerHTML=result.items.map(r=>`<div class="inspection-entry"><strong>${esc(r.title)}</strong><p>${esc(r.excerpt)}</p><p>Conversation timestamp: ${esc(String(r.authored))}. Imported: ${esc(r.imported)}. Source: ${esc(r.name)} · message ${esc(r.message)} · ${esc(r.role)}</p></div>`).join('') || '<p>No completed imported messages matched.</p>';
    }catch(error){$('history-text-results').textContent=error.message;}
  });
})();
