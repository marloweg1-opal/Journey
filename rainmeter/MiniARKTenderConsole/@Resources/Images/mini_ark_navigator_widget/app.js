
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const homeView = $('#homeView'), modeShell = $('#modeShell'), modeContent = $('#modeContent');
const modeTitle = $('#modeTitle'), modeKicker = $('#modeKicker'), toast = $('#toast');

const memories = [
  {title:'Case Drift Incident', text:'Drive event history and recovery context.'},
  {title:'USB Recovery', text:'PhotoRec recovery, media targets, corruption and duplicates.'},
  {title:'R:\\ migration planning', text:'Profile-source migration, quarantine, and staging decisions.'},
  {title:'Attribution canon', text:'Prominent, elegant, searchable provenance and credit architecture.'},
  {title:'Project Profiles', text:'External projects can extend Journey without redefining its core.'},
];

const tools = [
  {name:'Cockpit', desc:'Start the local cockpit.', cmd:'powershell -ExecutionPolicy Bypass -File .\\start_mini_ark.ps1'},
  {name:'Doctor', desc:'Run core integrity checks.', cmd:'.\\ark.cmd doctor'},
  {name:'Brief', desc:'Show current ARK brief.', cmd:'.\\ark.cmd brief'},
  {name:'Conversation Ingest', desc:'Ingest a conversation export for review candidates.', cmd:'.\\ark.cmd ingest <export-file>'},
  {name:'Inventory R:', desc:'Classify scanned files under R: read-only.', cmd:'.\\ark.cmd inventory --under R:\\'},
  {name:'Scan Path', desc:'Scan a path into the ledger.', cmd:'.\\ark.cmd scan <path>'},
  {name:'Tests', desc:'Run the validation suite.', cmd:'python -m unittest discover -s tests'},
  {name:'Project Folder', desc:'Open C:\\mini_ark.', cmd:'explorer C:\\mini_ark'},
  {name:'GitHub', desc:'Open the remote repository.', url:'https://github.com/marloweg1-opal/mini_ark'},
];

const guides = [
  {name:'Add a conversation', what:'Ingest a conversation export into mini_ark and extract review candidates without automatically promoting them to canon.', touches:['ARK ledger/database','derived context candidates','original export remains source material'], cmd:'.\\ark.cmd ingest <export-file>'},
  {name:'Find something ARK remembers', what:'Search ARK memory and project context. The static prototype uses seeded results until connected to the local search bridge.', touches:['read-only ARK memory','project context'], cmd:'[bridge] search'},
  {name:'Check what ARK thinks is canon', what:'Review durable canon and candidate state before promotion or correction.', touches:['canon records','review candidates'], cmd:'.\\ark.cmd brief'},
  {name:'Scan my files', what:'Scan a selected path into the ledger. This records inventory data; it does not move the files.', touches:['filesystem metadata','ARK ledger'], cmd:'.\\ark.cmd scan <path>'},
  {name:'Review duplicates', what:'Review duplicate candidates and their evidence before any move or deletion workflow.', touches:['inventory','duplicate candidates'], cmd:'.\\ark.cmd brief'},
  {name:'Move / quarantine files', what:'Use the project’s approval-gated migration or quarantine workflow. Review exact paths and reversibility first.', touches:['approved source files','quarantine destination','undo/audit history'], cmd:'powershell -ExecutionPolicy Bypass -File .\\migrate_r_user_profiles.ps1'},
  {name:'Undo something', what:'Review prior reversible actions and invoke the project undo path rather than manually reversing filesystem state.', touches:['action history','affected paths'], cmd:'.\\ark.cmd brief'},
  {name:'Run diagnostics', what:'Run the Mini ARK doctor checks and review warnings in plain language.', touches:['read-only system state','ledger integrity'], cmd:'.\\ark.cmd doctor'},
];

const manage = [
  ['ARK Status','Health and current state','.\\ark.cmd doctor'],
  ['Database / Ledgers','Inspect durable local records','.\\ark.cmd brief'],
  ['Config','Open project configuration','notepad config.json'],
  ['Approvals','Review gated actions','.\\ark.cmd brief'],
  ['Undo History','Review reversible actions','.\\ark.cmd brief'],
  ['Logs','Open local logs folder','explorer C:\\mini_ark\\logs'],
  ['Test Suite','Run validation','python -m unittest discover -s tests'],
  ['Git Status','Inspect repository state','git status'],
  ['Documentation','Open user guide','start docs\\USER_GUIDE.md'],
];

function showToast(message){
  toast.textContent = message; toast.classList.add('show');
  clearTimeout(window.__toast); window.__toast=setTimeout(()=>toast.classList.remove('show'),1800);
}
async function copyText(text){
  try{ await navigator.clipboard.writeText(text); showToast(`Copied: ${text}`); }
  catch{ showToast(text); }
}
function goHome(){
  modeShell.hidden=true; homeView.hidden=false; $('#searchInput').value='';
}
function openMode(mode, query=''){
  homeView.hidden=true; modeShell.hidden=false;
  const names={find:'FIND',launch:'LAUNCH',guide:'GUIDE',manage:'MANAGE'};
  const kick={find:'RESONANCE SEARCH',launch:'SUMMON TOOLS',guide:'ACTION MANIFESTS',manage:'KERNEL STEWARDSHIP'};
  modeTitle.textContent=names[mode]; modeKicker.textContent=kick[mode];
  if(mode==='find') renderFind(query);
  if(mode==='launch') renderLaunch();
  if(mode==='guide') renderGuide(0);
  if(mode==='manage') renderManage();
}
function renderFind(query=''){
  const q=query.trim().toLowerCase();
  const tf=tools.filter(x=>!q || (x.name+' '+x.desc).toLowerCase().includes(q));
  const gf=guides.filter(x=>!q || (x.name+' '+x.what).toLowerCase().includes(q));
  const mf=memories.filter(x=>!q || (x.title+' '+x.text).toLowerCase().includes(q));
  modeContent.innerHTML=`<div class="mode-panel find-results">
    <section><h3>TOOLS · ${tf.length}</h3>${tf.map(x=>`<div class="result-item"><strong>${x.name}</strong><p>${x.desc}</p></div>`).join('')||'<p>No tool matches.</p>'}</section>
    <section><h3>GUIDE · ${gf.length}</h3>${gf.map(x=>`<div class="result-item"><strong>${x.name}</strong><p>${x.what}</p></div>`).join('')||'<p>No guide matches.</p>'}</section>
    <section><h3>ARK MEMORY · ${mf.length}</h3>${mf.map(x=>`<div class="result-item"><strong>${x.title}</strong><p>${x.text}</p></div>`).join('')||'<p>No memory matches.</p>'}</section>
  </div>`;
}
function renderLaunch(){
  modeContent.innerHTML=`<div class="mode-panel"><div class="tool-grid">${
    tools.map((x,i)=>`<article class="tool-card"><h3>${x.name}</h3><p>${x.desc}</p>
      ${x.url?`<button data-open="${x.url}">Open</button>`:`<button data-copy="${x.cmd.replaceAll('"','&quot;')}">Copy launch command</button>`}
    </article>`).join('')
  }</div></div>`;
  wireActions();
}
function renderGuide(index){
  const g=guides[index]||guides[0];
  modeContent.innerHTML=`<div class="mode-panel guide-layout">
    <nav class="guide-list">${guides.map((x,i)=>`<button data-guide="${i}" class="${i===index?'active':''}">${x.name}</button>`).join('')}</nav>
    <article class="guide-detail"><h3>${g.name}</h3><p>${g.what}</p>
      <div class="instrument-label">WHAT IT TOUCHES</div>
      <ul>${g.touches.map(x=>`<li>${x}</li>`).join('')}</ul>
      <button data-copy="${g.cmd.replaceAll('"','&quot;')}">Copy launch action</button>
    </article></div>`;
  $$('[data-guide]').forEach(b=>b.onclick=()=>renderGuide(Number(b.dataset.guide)));
  wireActions();
}
function renderManage(){
  modeContent.innerHTML=`<div class="mode-panel"><div class="manage-grid">${
    manage.map(x=>`<article class="manage-card"><h3>${x[0]}</h3><p>${x[1]}</p><button data-copy="${x[2].replaceAll('"','&quot;')}">Copy action</button></article>`).join('')
  }</div></div>`;
  wireActions();
}
function wireActions(){
  $$('[data-copy]').forEach(b=>b.onclick=()=>copyText(b.dataset.copy));
  $$('[data-open]').forEach(b=>b.onclick=()=>window.open(b.dataset.open,'_blank','noopener'));
}
$$('.command-card').forEach(b=>b.addEventListener('click',()=>openMode(b.dataset.mode)));
$('#backButton').onclick=goHome; $('#homeButton').onclick=goHome;
$('#searchForm').addEventListener('submit',e=>{e.preventDefault();openMode('find',$('#searchInput').value)});
document.addEventListener('keydown',e=>{
  if(e.ctrlKey&&e.altKey&&e.key.toLowerCase()==='a'){e.preventDefault();$('#searchInput').focus();$('#searchInput').select()}
});
$('#statusJewel').onclick=()=>{
  const p=$('#statusPopover'); p.hidden=!p.hidden; $('#statusJewel').setAttribute('aria-expanded',String(!p.hidden));
};
document.addEventListener('click',e=>{
  if(!e.target.closest('#statusJewel')&&!e.target.closest('#statusPopover')) $('#statusPopover').hidden=true;
});
wireActions();
