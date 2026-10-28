const $ = id => document.getElementById(id);
const make = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
let me, scope = 'mine', current = null, selected = null, listSignature = '', detailSignature = '', fetching = false, pending = false, targets = [];
const edits = new Map();
const time = value => window.formatDateTime(value);
const LABEL = {pending:'Awaiting support',processing:'In progress',completed:'Completed'};
const RETURN = {NONE:'No request',AUDITING:'Under review',RETURNING:'Return in progress',REFUNDED:'Refunded'};
const LOGISTICS = {'':'No new event',PICKED_UP:'Picked up',IN_TRANSIT:'In transit',DELIVERING:'Out for delivery',DELIVERED:'Delivered'};
async function api(path, method='GET', body) {
  const r = await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  const d = await r.json().catch(()=>({}));
  if(r.status===401){location.href='/login';throw Error('Please sign in');}
  if(!r.ok){const e=Error(typeof d.detail==='string'?d.detail:'Check the form');e.status=r.status;throw e;}
  return d;
}
function toast(text,error=false){$('notice').textContent=text;$('notice').className=error?'error':'';$('notice').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('notice').hidden=true,4000);}
function cache(){if(!edits.has(current))edits.set(current,new Map());return edits.get(current);}
function field(parent,label,key,value='',options=null){
  const wrap=make('label',null,label), input=make(options?'select':key.includes('content')||key==='resolution'?'textarea':'input');
  if(options)for(const [v,text]of Object.entries(options)){const o=make('option',null,text);o.value=v;input.append(o);}
  input.value=cache().has(key)?cache().get(key):value;input.dataset.key=key;
  input.oninput=()=>cache().set(key,input.value);input.onchange=input.oninput;
  if(!options)input.maxLength=8000;
  wrap.append(input);parent.append(wrap);return input;
}
function section(title){const box=make('section','ticket-section');box.append(make('h2',null,title));return box;}
function button(parent,text,fn,cls=''){const b=make('button','btn '+cls,text);b.type='button';b.onclick=async()=>{if(pending)return;pending=true;b.disabled=true;try{await fn();}catch(e){toast(e.message,true);}finally{pending=false;if(b.isConnected)b.disabled=false;}};parent.append(b);return b;}
async function mutate(path,body,clearKeys=[]){
  const number=current;await api('/api/tickets/'+encodeURIComponent(number)+path,'POST',body);
  const draft=edits.get(number);clearKeys.forEach(k=>draft?.delete(k));
  if(current===number)await loadDetail(true);
  await loadList();toast('Saved');
}
function closeList(focus=true){const was=$('ticket-sidebar').classList.contains('open');$('ticket-sidebar').classList.remove('open');$('ticket-sidebar').removeAttribute('role');$('ticket-sidebar').removeAttribute('aria-modal');$('ticket-backdrop').hidden=true;document.querySelector('.workspace').inert=false;$('list-open').setAttribute('aria-expanded','false');if(was&&focus)$('list-open').focus();}
$('list-open').onclick=()=>{$('ticket-sidebar').classList.add('open');$('ticket-sidebar').setAttribute('role','dialog');$('ticket-sidebar').setAttribute('aria-modal','true');$('ticket-backdrop').hidden=false;document.querySelector('.workspace').inert=true;$('list-open').setAttribute('aria-expanded','true');$('list-close').focus();};
$('list-close').onclick=$('ticket-backdrop').onclick=()=>closeList();
matchMedia('(max-width:779px)').addEventListener('change',()=>closeList(false));
document.addEventListener('keydown',e=>{if(!$('ticket-sidebar').classList.contains('open'))return;if(e.key==='Escape'){e.preventDefault();closeList();}if(e.key==='Tab'){const controls=[...$('ticket-sidebar').querySelectorAll('button:not(:disabled),a[href],select')].filter(n=>n.getClientRects().length),first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
async function loadList(){
  const requestScope=scope,requestState=$('state-filter').value;const params=new URLSearchParams({scope});if($('state-filter').value)params.set('state',$('state-filter').value);
  const data=await api('/api/tickets?'+params);if(requestScope!==scope||requestState!==$('state-filter').value)return;const signature=JSON.stringify([data.items,current]);if(signature===listSignature)return;listSignature=signature;
  $('ticket-list').replaceChildren();
  for(const t of data.items){const b=make('button','session-card session-pick'+(t.ticket_no===current?' selected':'')),top=make('div','session-top');b.type='button';
    top.append(make('strong',null,me.role==='user'?window.petLabel(t.ticket_type)+' ticket':t.user_id+' · '+window.petLabel(t.ticket_type)),make('span','badge '+(t.state==='pending'?'waiting':t.state==='processing'?'active':''),t.status));
    b.append(top,make('p',null,t.description.slice(0,80)),make('time',null,time(t.updated_at)));b.onclick=()=>{closeList(false);choose(t.ticket_no).catch(e=>toast(e.message,true));};$('ticket-list').append(b);
  }
  if(!data.items.length)$('ticket-list').append(make('p','empty-note',scope==='pending'?'No unassigned tickets':'No tickets'));
}
async function choose(number){current=number;selected=null;detailSignature='';$('ticket-detail').replaceChildren(make('p','empty-note','Loading ticket…'));await loadDetail(true);document.querySelector('.ticket-content').scrollTop=0;await loadList();history.replaceState(null,'','/tickets?ticket='+encodeURIComponent(number));}
function render(d){
  selected=d;const root=$('ticket-detail');root.replaceChildren();$('stale').hidden=true;
  $('page-title').textContent=(me.role==='user'?'':d.user_id+' · ')+window.petLabel(d.ticket_type)+' ticket';$('ticket-number').textContent=d.ticket_no;
  const info=make('section','ticket-info'),line=make('div','summary-line');line.append(make('span','badge '+(d.state==='pending'?'waiting':d.state==='processing'?'active':''),d.status),make('span','ticket-meta','Created '+time(d.created_at)));info.append(line,make('p','ticket-description',d.description));
  if(me.role!=='user')info.append(make('p','ticket-meta','Owner: '+(d.assignee_id||'Unassigned')));
  if(d.resolution){info.append(make('h2',null,'Resolution'),make('p','ticket-result',d.resolution));}
  if(d.can_claim){const actions=make('div','ticket-actions');button(actions,'Claim ticket',()=>mutate('/claim',{version:d.version}),'primary');info.append(actions);}
  root.append(info);
  if(d.can_assign){const box=section(d.assignee_id?'Reassign owner':'Assign owner'),form=make('form');const options={'':'Choose an owner',...Object.fromEntries(targets.map(a=>[a.id,a.id]))};const who=field(form,'Owner','assignee',d.assignee_id||'',options),reason=field(form,'Assignment note (internal)','assignment_reason');who.required=true;
    button(form,d.assignee_id?'Confirm reassignment':'Confirm assignment',async()=>{if(!form.reportValidity())return;await mutate('/assign',{version:d.version,assignee_id:who.value,reason:reason.value},['assignee','assignment_reason']);});form.onsubmit=e=>e.preventDefault();box.append(form);root.append(box);}
  const records=section('Activity');
  const ACTION={created:'Create ticket',claimed:'Accepted',assigned:'Assigned',reassigned:'Reassigned',assignment_detail:'Assignment details',update:'Progress update',note:'Internal note',completed:'Final resolution',order_linked:'Linked order',order_updated:'Order update'};
  for(const r of d.records){const row=make('article','ticket-record'+(r.visibility==='internal'?' internal':'')),head=make('div','ticket-record-head');head.append(make('strong',null,ACTION[r.action]||'Activity'),make('small',null,time(r.created_at)+' · '+r.actor_id));if(r.visibility==='internal')head.append(make('span','badge','Internal'));row.append(head);if(r.action!=='completed'||!d.resolution)row.append(make('p',null,r.content));records.append(row);}
  if(!d.records.length)records.append(make('p','empty-note','No detailed activity yet'));root.append(records);
  if(d.can_manage){
    const box=section('Add activity note'),form=make('form'),content=field(form,'Note content','record_content'),visibility=field(form,'Visibility','record_visibility','internal',{internal:'Internal note',public:'Visible to customer'});content.required=true;
    button(form,'Save note',async()=>{if(!form.reportValidity())return;await mutate('/records',{version:d.version,content:content.value,visibility:visibility.value},['record_content','record_visibility']);});form.onsubmit=e=>e.preventDefault();box.append(form);root.append(box);
  }
  if(d.order||d.can_manage){const box=section('Linked order');
    if(d.order){const o=d.order;box.append(make('p','ticket-description',o.product+' · '+window.petMoney(o.amount,o.currency)),make('p','ticket-meta',o.order_id+' · '+window.petLabel(o.status)+' · '+(RETURN[o.return_code]||o.return_code)));
      if(d.can_manage){const form=make('form'),grid=make('div','ticket-order-grid');form.append(grid);const status=field(grid,'Order status','order_status',o.status,Object.fromEntries(['awaiting_payment','paid','shipped','delivered','cancelled'].map(v=>[v,window.petLabel(v)]))),ret=field(grid,'Return status','order_return',o.return_code,RETURN),log=field(grid,'Tracking event','order_log','',LOGISTICS),city=field(grid,'Tracking city','city','Los Angeles'),desc=field(form,'Tracking details','order_description');
        button(form,'Save order changes',async()=>{await api('/api/tickets/'+encodeURIComponent(d.ticket_no)+'/orders/'+encodeURIComponent(o.order_id),'PATCH',{version:o.version,status:status.value,return_code:ret.value,status_code:log.value||null,city:city.value||'Los Angeles',description:desc.value||'Ticket support updated tracking'});['order_status','order_return','order_log','city','order_description'].forEach(k=>cache().delete(k));await loadDetail(true);await loadList();toast('Order updated');});form.onsubmit=e=>e.preventDefault();const editor=make('details'),summary=make('summary',null,'Edit order and tracking');editor.append(summary,form);box.append(editor);}
    }else box.append(make('p','ticket-meta','No order linked. Only this customer’s orders can be linked.'));
    if(d.can_manage){const form=make('form'),oid=field(form,'Linked order number','link_order',d.order_id||'');oid.required=true;oid.maxLength=96;button(form,d.order_id?'Change linked order':'Linked order',async()=>{if(!form.reportValidity())return;await api('/api/tickets/'+encodeURIComponent(d.ticket_no)+'/order','PATCH',{version:d.version,order_id:oid.value});cache().delete('link_order');await loadDetail(true);toast('Order linked');});form.onsubmit=e=>e.preventDefault();const linker=make('details'),summary=make('summary',null,d.order_id?'Change linked order':'Link customer order');linker.append(summary,form);box.append(linker);}root.append(box);
  }
  if(d.messages.length&&me.role!=='user'){const box=section('Conversation context'),details=make('details'),summary=make('summary',null,'View linked conversation');details.append(summary);for(const m of d.messages)details.append(make('p',null,(m.role==='user'?'Customer: ':'Support / AI：')+m.content));details.className='ticket-context';box.append(details);root.append(box);}
  if(d.can_manage){const box=section('Complete ticket'),form=make('form'),resolution=field(form,'Resolution (visible to customer, required)','resolution');resolution.required=true;button(form,'Complete and notify customer',async()=>{if(!form.reportValidity())return;await mutate('/complete',{version:d.version,resolution:resolution.value},['resolution']);},'primary');form.onsubmit=e=>e.preventDefault();box.append(form);root.append(box);}
}
async function loadDetail(force=false){if(!current)return;const number=current;let d;try{d=await api('/api/tickets/'+encodeURIComponent(number));}catch(e){if(e.status===404&&number===current){selected=null;$('ticket-detail').replaceChildren(make('p','empty-note','Ticket reassigned or inaccessible. Select another ticket.'));}throw e;}if(number!==current)return;const signature=JSON.stringify(d);if(!force&&signature===detailSignature)return;if(!force&&edits.get(number)?.size){$('stale').hidden=d.version===selected?.version;return;}detailSignature=signature;render(d);}
async function refresh(force=false){if(fetching)return;fetching=true;try{await loadList();await loadDetail(force);}catch(e){toast(e.message,true);}finally{fetching=false;}}
$('refresh').onclick=()=>refresh(true);$('state-filter').onchange=()=>loadList().catch(e=>toast(e.message,true));
document.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>{scope=b.dataset.scope;document.querySelectorAll('[data-scope]').forEach(n=>n.setAttribute('aria-selected',String(n===b)));loadList().catch(e=>toast(e.message,true));});
$('logout').onclick=async()=>{try{await api('/api/auth/logout','POST');localStorage.removeItem('commerceagent_conversation_id');location.href='/login';}catch(e){toast(e.message,true);}};
try{me=await api('/api/auth/me');const worker=['support','admin'].includes(me.role);$('account-name').textContent=me.username;$('avatar').textContent=Array.from(me.username)[0].toUpperCase();$('desk-label').textContent=me.role==='admin'?'Manage tickets':worker?'Ticket queue':'My tickets';$('page-title').textContent=$('desk-label').textContent;document.querySelector('[data-scope=mine]').hidden=me.role==='admin';$('support-link').hidden=me.role!=='support';$('orders-link').hidden=me.role!=='user';$('chat-link').hidden=me.role!=='user';$('admin-link').hidden=me.role!=='admin';document.querySelector('[data-scope=pending]').hidden=!worker;document.querySelector('[data-scope=pending]').textContent=me.role==='admin'?'Awaiting assignment':'Unassigned';document.querySelector('[data-scope=all]').hidden=me.role!=='admin';scope=me.role==='admin'?'all':worker?'pending':'mine';document.querySelectorAll('[data-scope]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.scope===scope)));if(me.role==='admin')targets=(await api('/api/tickets/assignees')).items;await loadList();const number=new URLSearchParams(location.search).get('ticket');if(number)await choose(number);setInterval(()=>{if(!document.hidden&&!pending)refresh();},5000);}catch(e){toast(e.message,true);}
