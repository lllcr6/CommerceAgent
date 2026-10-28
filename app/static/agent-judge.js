/* Render model judgments without interpreting untrusted text as markup. */
(() => {
  const node = (tag, cls, text) => {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (text != null) element.textContent = String(text);
    return element;
  };
  const labels = {pass:'Passed', fail:'Failed', uncertain:'Uncertain', error:'Call failed', not_evaluated:'Not evaluated'};
  const displayStatus = item => labels[item.overall] ? item.overall : (labels[item.status] ? item.status : 'not_evaluated');
  const badge = value => node('span', 'judge-badge ' + (labels[value] ? value : 'not_evaluated'), labels[value] || 'Not evaluated');
  const titleCase = value => String(value || 'Scenario').replace(/[_-]+/g, ' ').replace(/\b\w/g, char => char.toUpperCase());

  function metric(label, value, sub, primary = false) {
    const box = node('div', 'judge-metric' + (primary ? ' primary' : ''));
    box.append(node('span', 'judge-metric-label', label), node('strong', 'judge-metric-value', value), node('span', 'judge-metric-sub', sub));
    return box;
  }

  function caseCard(item) {
    const state = displayStatus(item), details = node('details', 'judge-case');
    const heading = node('summary');
    const name = node('span', 'judge-case-title', titleCase(item.scenario));
    name.appendChild(node('span', 'judge-case-meta', `Run ${Number(item.repeat ?? 0) + 1} · ${(item.turns || []).length} turns`));
    heading.append(name, badge(state)); details.appendChild(heading);
    const body = node('div', 'judge-case-body');
    if (item.error) body.appendChild(node('p', 'judge-note', `Judge call failed: ${item.error}`));
    const dimensions = Object.entries(item.dimensions || {});
    if (dimensions.length) {
      const grid = node('div', 'judge-dimensions');
      for (const [name, result] of dimensions) {
        const card = node('div', 'judge-dimension'), top = node('div', 'judge-dimension-head');
        top.append(node('span', null, titleCase(name)), badge(result.verdict));
        card.append(top, node('p', null, result.reason || 'No explanation provided.')); grid.appendChild(card);
      }
      body.appendChild(grid);
    }
    if ((item.turns || []).length) body.appendChild(node('div', 'judge-conversation-title', 'Conversation'));
    for (const turn of item.turns || []) {
      const row = node('div', 'judge-turn');
      row.appendChild(node('div', 'judge-turn-header', `TURN ${turn.turn}`));
      for (const [role, text] of [['Customer', turn.prompt], ['Assistant', turn.answer]]) {
        const message = node('div', 'judge-message');
        message.append(node('span', 'judge-message-label', role), node('span', 'judge-message-text', text || '—'));
        row.appendChild(message);
      }
      if ((turn.tools || []).length) row.appendChild(node('p', 'judge-tools', `Tools observed: ${turn.tools.join(', ')}`));
      if ((turn.actions || []).length) row.appendChild(node('p', 'judge-tools', `Proposed actions: ${JSON.stringify(turn.actions)}`));
      body.appendChild(row);
    }
    details.appendChild(body); return details;
  }

  window.renderAgentJudge = judge => {
    const section = node('section', 'judge-section');
    const header = node('div', 'judge-header'), copy = node('div');
    copy.append(node('h3', null, 'Conversation quality'), node('p', null, 'LLM judge · synthetic Agent conversations'));
    header.appendChild(copy);
    if (judge?.model) header.appendChild(node('span', 'judge-model', judge.model));
    section.appendChild(header);
    if (!judge) {
      section.appendChild(node('p', 'judge-note', 'No judge results yet. Run an Agent evaluation to assess conversation quality.'));
      return section;
    }
    const rate = judge.pass_rate == null ? '—' : (judge.pass_rate * 100).toFixed(1) + '%';
    const metrics = node('div', 'judge-metrics');
    metrics.append(metric('Pass rate', rate, `${judge.pass ?? 0} of ${judge.assessed ?? 0} assessed`, true),
      metric('Failed', judge.fail ?? 0, 'Needs review'),
      metric('Uncertain', judge.uncertain ?? 0, 'Not included in pass rate'),
      metric('Judged', `${judge.judged ?? 0} / ${judge.planned ?? 0}`, `${judge.failed_calls ?? 0} judge calls failed`));
    section.appendChild(metrics);
    section.appendChild(node('p', 'judge-note', 'The pass rate excludes uncertain cases and failed judge calls.'));
    const about = node('details', 'judge-about'), aboutTitle = node('summary', null, 'About this evaluation');
    about.append(aboutTitle, node('p', null, (judge.scope || 'Synthetic conversations only.') + ' Model judgments are not human-reviewed resolution rates. Tool results and backend side effects are not verified. Continue retries failed judge calls. Judge calls use additional provider credits and are not included in Agent token averages.'));
    section.appendChild(about);
    const cases = judge.cases || [], controls = node('div', 'judge-cases-head'), heading = node('div');
    heading.append(node('h4', null, 'Case review'), node('p', null, `${cases.length} conversations · select a case to inspect`));
    controls.appendChild(heading);
    const filters = node('div', 'judge-filters'), list = node('div', 'judge-list');
    filters.setAttribute('role', 'group'); filters.setAttribute('aria-label', 'Filter judgments');
    const order = {fail:0, error:1, uncertain:2, not_evaluated:3, pass:4};
    const sorted = [...cases].sort((a,b) => order[displayStatus(a)] - order[displayStatus(b)]);
    let filter = 'all', visible = 6;
    const more = node('button', 'judge-more'); more.type = 'button';
    const buttons = [];
    function render() {
      const shown = sorted.filter(item => filter === 'all' || (filter === 'review' ? displayStatus(item) !== 'pass' : displayStatus(item) === filter));
      list.replaceChildren(...shown.slice(0, visible).map(caseCard));
      if (!shown.length) list.appendChild(node('p', 'judge-empty', 'No cases in this view.'));
      more.hidden = shown.length <= visible;
      more.textContent = `Show more (${Math.max(0, shown.length - visible)} remaining)`;
      buttons.forEach(([button, key]) => button.setAttribute('aria-pressed', String(key === filter)));
    }
    for (const [label, key] of [['All', 'all'], ['Needs review', 'review'], ['Passed', 'pass'], ['Uncertain', 'uncertain']]) {
      const button = node('button', 'judge-filter', label); button.type = 'button';
      button.addEventListener('click', () => { filter = key; visible = 6; render(); });
      filters.appendChild(button); buttons.push([button, key]);
    }
    more.addEventListener('click', () => { visible += 6; render(); });
    controls.appendChild(filters); section.append(controls, list, more); render();
    return section;
  };
})();
