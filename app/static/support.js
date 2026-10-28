const $ = id => document.getElementById(id);
const CAT = '<img src="/static/paws.svg" alt="" aria-hidden="true">';
document.querySelectorAll('[data-cat]').forEach(el => { el.innerHTML = CAT; });
let cid = null, selectedState = null, signature = '', listSignature = '', historySequence = 0;
let queueItems = [], mineItems = [], refreshing = false, sending = false, closing = false;
const drafts = new Map();
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text != null) node.textContent = text; return node; }
function notify(message, isError = false) {
  const notice = $('notice'); notice.textContent = message; notice.className = isError ? 'error' : ''; notice.setAttribute('role', isError ? 'alert' : 'status'); notice.hidden = false;
  clearTimeout(notice.timer); notice.timer = setTimeout(() => { notice.hidden = true; }, 4000);
}
async function api(url, method = 'GET', body) {
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { location.href = '/login'; throw Error('Please sign in'); }
  if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Action failed. Please try again');
  return data;
}
function action(parent, text, fn, cls = '') {
  const button = el('button', 'btn ' + cls, text); button.type = 'button';
  button.onclick = async () => { button.disabled = true; try { await fn(); } catch (error) { notify(error.message, true); } finally { if (button.isConnected) button.disabled = false; } };
  parent.append(button); return button;
}
function shortTime(time) { return window.formatDateTime(time); }
function customer(id) { return mineItems.find(h => h.conversation_id === id)?.user_id || queueItems.find(h => h.conversation_id === id)?.user_id || 'Customer conversations'; }
function tabs(first, second, firstPanel, secondPanel) {
  function activate(which) {
    first.setAttribute('aria-selected', String(which === first)); second.setAttribute('aria-selected', String(which === second));
    first.tabIndex = which === first ? 0 : -1; second.tabIndex = which === second ? 0 : -1;
    firstPanel.hidden = which !== first; secondPanel.hidden = which !== second;
  }
  first.onclick = () => activate(first); second.onclick = () => activate(second);
  for (const button of [first, second]) button.onkeydown = event => { if (['ArrowLeft', 'ArrowRight'].includes(event.key)) { event.preventDefault(); const next = button === first ? second : first; activate(next); next.focus(); } };
  activate(first); return activate;
}
const showSessions = tabs($('queue-tab'), $('mine-tab'), $('queue'), $('mine'));
tabs($('orders-tab'), $('tickets-tab'), $('orders'), $('tickets'));
let drawer = null, drawerTrigger = null;
function closeDrawer(focus = true) {
  if (!drawer) return;
  drawer.classList.remove('open'); drawer.removeAttribute('role'); drawer.removeAttribute('aria-modal');
  $('drawer-backdrop').hidden = true;
  document.querySelectorAll('.desk > *').forEach(part => { part.inert = false; });
  drawerTrigger?.setAttribute('aria-expanded', 'false');
  if (focus && drawerTrigger?.getClientRects().length) drawerTrigger.focus();
  drawer = null;
}
function openDrawer(id, trigger) {
  closeDrawer(false); drawer = $(id); drawerTrigger = trigger;
  drawer.classList.add('open'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true');
  $('drawer-backdrop').hidden = false; trigger.setAttribute('aria-expanded', 'true');
  document.querySelectorAll('.desk > *').forEach(part => { part.inert = part !== drawer; });
  drawer.querySelector('.drawer-close').focus();
}
$('sessions-open').onclick = () => openDrawer('sessions', $('sessions-open'));
$('business-open').onclick = () => openDrawer('business', $('business-open'));
$('sessions-close').onclick = $('business-close').onclick = () => closeDrawer();
$('drawer-backdrop').onclick = () => closeDrawer();
for (const query of ['(max-width:779px)', '(max-width:1200px)']) matchMedia(query).addEventListener('change', () => closeDrawer(false));
document.addEventListener('keydown', event => {
  if (!drawer) return;
  if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); }
  if (event.key === 'Tab' && drawer) {
    const buttons = [...drawer.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),summary')].filter(node => node.getClientRects().length), first = buttons[0], last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
function renderLists() {
  const next = JSON.stringify([queueItems, mineItems, cid]); if (next === listSignature) return; listSignature = next;
  $('queue-count').textContent = queueItems.length; $('mine-count').textContent = mineItems.length;
  $('queue').replaceChildren(); $('mine').replaceChildren();
  for (const item of queueItems) {
    const card = el('article', 'session-card'), top = el('div', 'session-top');
    top.append(el('strong', null, item.user_id || 'Waiting customers'), el('span', 'badge waiting', 'Queued'));
    card.append(top, el('p', null, item.reason || 'Customer requested human support'), el('time', null, shortTime(item.created_at)));
    action(card, 'Conversation', async () => {
      await api(`/api/support/${item.conversation_id}/claim`, 'POST');
      await refresh(false); showSessions($('mine-tab')); await selectConversation(item.conversation_id); closeDrawer(false);
    }, 'primary'); $('queue').append(card);
  }
  for (const item of [...mineItems].sort((a, b) => (a.state === 'active' ? 0 : 1) - (b.state === 'active' ? 0 : 1))) {
    const card = el('button', 'session-card session-pick' + (item.conversation_id === cid ? ' selected' : '')), top = el('div', 'session-top'); card.type = 'button';
    if (item.conversation_id === cid) card.setAttribute('aria-current', 'true');
    top.append(el('strong', null, item.user_id || 'Customer conversations'), el('span', 'badge' + (item.state === 'active' ? ' active' : ''), item.state === 'active' ? 'Active conversation' : 'Completed'));
    card.append(top, el('p', null, item.reason || 'Human support'), el('time', null, shortTime(item.created_at)));
    card.onclick = () => { closeDrawer(false); selectConversation(item.conversation_id).catch(error => notify(error.message, true)); }; $('mine').append(card);
  }
  if (!queueItems.length) $('queue').append(el('p', 'empty-note', 'No waiting customers'));
  if (!mineItems.length) $('mine').append(el('p', 'empty-note', 'No support history yet'));
}
function renderService(state) {
  selectedState = state.state; const active = state.state === 'active';
  $('service-state').hidden = !active; $('close').hidden = !active; $('close').disabled = sending || closing;
  $('reply-area').hidden = !active; $('closed-state').hidden = state.state !== 'closed';
  $('reply').disabled = !active || sending; $('send').disabled = !active || sending || !$('reply').value.trim();
  $('rating').textContent = state.rating ? `Customer rating: ${state.rating}` : 'Awaiting customer feedback';
  $('business-open').disabled = false;
  document.querySelectorAll('#orders fieldset').forEach(fieldset => { fieldset.disabled = !active; });
}
async function history() {
  if (!cid) return;
  const id = cid, request = ++historySequence;
  const [data, state] = await Promise.all([api(`/api/conversations/${id}/messages`), api(`/api/conversations/${id}/service`)]);
  if (id !== cid || request !== historySequence) return;
  const next = JSON.stringify(data.items);
  if (signature !== next) {
    const box = $('history'), nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80 || !signature;
    signature = next; box.replaceChildren();
    for (const message of data.items) {
      if (!message.content) continue;
      const own = message.role !== 'user', row = el('article', 'message' + (own ? ' own' : ''));
      row.append(el('p', 'message-label', (own ? 'Support' : customer(id)) + (message.created_at ? ' · ' + shortTime(message.created_at) : '')), el('div', 'message-bubble', message.content)); box.append(row);
    }
    if (!data.items.length) box.append(el('p', 'empty-note', 'Customer has not sent a message yet'));
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }
  renderService(state);
}
async function refresh(withHistory = true) {
  if (refreshing) return;
  refreshing = true;
  try {
    const [queue, mine, pendingTickets] = await Promise.all([api('/api/support/queue'), api('/api/support/mine'), api('/api/tickets?scope=pending')]);
    $('pending-tickets').textContent = pendingTickets.items.length;
    queueItems = queue.items; mineItems = mine.items; renderLists();
    if (cid) $('title').textContent = customer(cid);
    if (withHistory && cid) await history();
  } catch (error) { notify(error.message, true); }
  finally { refreshing = false; }
}
async function selectConversation(id) {
  if (id === cid && selectedState) return;
  if (cid) drafts.set(cid, $('reply').value);
  cid = id; signature = ''; selectedState = null;
  $('reply').value = drafts.get(id) || ''; $('title').textContent = customer(id); $('conversation-meta').textContent = `Conversation ID ${id}`;
  $('reply-area').hidden = true; $('closed-state').hidden = true; $('close').hidden = true; $('service-state').hidden = true;
  $('history').replaceChildren(el('p', 'empty-note', 'Loading conversation…')); $('orders').replaceChildren(el('p', 'empty-note', 'Loading order…')); $('tickets').replaceChildren();
  renderLists();
  await history();
  await Promise.all([orders(id), tickets(id)]);
}
const RETURN = { NONE: 'No request', AUDITING: 'Under review', RETURNING: 'Return in progress', REFUNDED: 'Refunded' };
const LOGISTICS = { '': 'No new event', PICKED_UP: 'Picked up', IN_TRANSIT: 'In transit', DELIVERING: 'Out for delivery', DELIVERED: 'Delivered' };
function selectField(parent, label, values, value) {
  const wrap = el('label', null, label), select = el('select');
  for (const [key, text] of Object.entries(values)) { const option = el('option', null, text); option.value = key; option.selected = key === value; select.append(option); }
  wrap.append(select); parent.append(wrap); return select;
}
function inputField(parent, label, value = '', maxLength = 500) {
  const wrap = el('label', null, label), input = el('input'); input.value = value; input.maxLength = maxLength; wrap.append(input); parent.append(wrap); return input;
}
async function orders(id = cid) {
  const data = await api(`/api/support/${id}/orders`); if (id !== cid) return;
  $('orders').replaceChildren();
  for (const order of data.items) {
    const card = el('details', 'order-card'), summary = el('summary'); card.open = data.items.length === 1;
    summary.append(el('strong', null, order.product), document.createTextNode(' · ' + window.petMoney(order.amount,order.currency)), el('span', 'order-meta', order.order_id + ' · ' + window.petLabel(order.status))); card.append(summary);
    const form = el('form', 'order-form'), fieldset = el('fieldset'); fieldset.disabled = selectedState !== 'active'; form.append(fieldset);
    const status = selectField(fieldset, 'Order status', Object.fromEntries(['awaiting_payment', 'paid', 'shipped', 'delivered', 'cancelled'].map(value => [value, window.petLabel(value)])), order.status);
    const ret = selectField(fieldset, 'Return status', RETURN, order.return_code), log = selectField(fieldset, 'Add tracking event', LOGISTICS, '');
    const logistics = el('div', 'logistics-fields'); logistics.hidden = true;
    const city = inputField(logistics, 'City', 'Los Angeles', 64), description = inputField(logistics, 'Event details'); fieldset.append(logistics);
    log.onchange = () => { logistics.hidden = !log.value; };
    const save = el('button', 'btn', 'Save changes'); save.type = 'submit'; fieldset.append(save);
    form.onsubmit = async event => {
      event.preventDefault(); save.disabled = true;
      try {
        await api(`/api/support/${id}/orders/${encodeURIComponent(order.order_id)}`, 'PATCH', { version: order.version, status: status.value, return_code: ret.value, status_code: log.value || null, city: city.value || 'Los Angeles', description: description.value || 'Support updated tracking' });
        notify('Changes saved'); await orders(id);
      } catch (error) { notify(error.message, true); }
      finally { if (save.isConnected) save.disabled = false; }
    };
    card.append(form); $('orders').append(card);
  }
  if (!data.items.length) $('orders').append(el('p', 'empty-note', 'No orders for this customer'));
}
async function tickets(id = cid) {
  const data = await api('/api/tickets?conversation_id=' + id); if (id !== cid) return;
  const items = data.items.filter(ticket => ticket.conversation_id === id); $('ticket-count').textContent = items.length; $('tickets').replaceChildren();
  for (const ticket of items) {
    const card = el('article', 'ticket-card'), top = el('div', 'ticket-top');
    top.append(el('span', 'ticket-id', ticket.ticket_no), el('span', 'badge' + (ticket.status === 'pending' ? ' waiting' : ''), window.petLabel(ticket.status))); card.append(top, el('p', null, ticket.description));
    const link = el('a', 'btn', 'Open ticket'); link.href = '/tickets?ticket=' + encodeURIComponent(ticket.ticket_no); card.append(link);
    $('tickets').append(card);
  }
  if (!items.length) $('tickets').append(el('p', 'empty-note', 'No tickets for this conversation'));
}
$('reply').oninput = () => { if (cid) drafts.set(cid, $('reply').value); $('send').disabled = selectedState !== 'active' || sending || !$('reply').value.trim(); };
$('reply').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$('send').disabled) $('send').click(); } };
$('send').onclick = async () => {
  if (!cid || selectedState !== 'active' || sending || !$('reply').value.trim()) return;
  const id = cid, text = $('reply').value; sending = true; renderService({ state: selectedState });
  try {
    await api(`/api/support/${id}/reply`, 'POST', { message: text });
    if (drafts.get(id) === text) drafts.delete(id);
    if (id === cid) { $('reply').value = ''; await history(); }
  } catch (error) { notify(error.message, true); }
  finally { sending = false; if (cid) await history().catch(error => notify(error.message, true)); }
};
$('close').onclick = async () => {
  if (!cid || selectedState !== 'active' || closing || sending) return;
  const id = cid; closing = true; $('close').disabled = true;
  try { await api(`/api/support/${id}/close`, 'POST'); if (id !== cid) notify('Conversation closed'); await refresh(); }
  catch (error) { notify(error.message, true); }
  finally { closing = false; if (cid) await history().catch(error => notify(error.message, true)); }
};
$('logout').onclick = async () => {
  $('logout').disabled = true;
  try { await api('/api/auth/logout', 'POST'); localStorage.removeItem('commerceagent_conversation_id'); location.href = '/login'; }
  catch (error) { $('logout').disabled = false; notify(error.message, true); }
};
try {
  const me = await api('/api/auth/me');
  if (me.role !== 'support') { location.href = me.role === 'admin' ? '/admin' : '/'; throw Error('Support access required'); }
  $('identity').textContent = me.username; $('account-avatar').textContent = Array.from(me.username)[0].toUpperCase();
  await refresh();
  if (!queueItems.length && mineItems.length) showSessions($('mine-tab'));
  setInterval(() => { if (!document.hidden) refresh(); }, 3000);
} catch (error) { notify(error.message, true); }
