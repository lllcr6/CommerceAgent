/* Local pricing assumptions. No model requests or server writes. */
(function () {
  function estimate(inputTokens, outputTokens, inputRate, outputRate) {
    if (![inputTokens, outputTokens, inputRate, outputRate].every(v => typeof v === 'number' && Number.isFinite(v) && v >= 0)) return null;
    return (inputTokens * inputRate + outputTokens * outputRate) / 1000000;
  }
  window.agentCostEstimate = estimate;
  window.agentCostEditor = function (summary, model) {
    const box = el('section', 'price-editor');
    box.setAttribute('aria-label', 'Agent cost estimate');
    box.appendChild(el('h3', null, 'Estimate model cost'));
    const fields = el('div', 'price-fields'), key = 'paw-model-prices-v1:' + (model || 'unknown');
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(key)) || {}; } catch (_) {}
    const inputs = ['Input', 'Output'].map((name, i) => {
      const label = el('label', 'price-field', name + ' · USD / 1M tokens');
      const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.step = 'any'; input.placeholder = i ? 'e.g. 2.00' : 'e.g. 0.50';
      input.inputMode = 'decimal'; input.value = saved[name.toLowerCase()] ?? '';
      label.appendChild(input); fields.appendChild(label); return input;
    });
    const result = el('div', 'price-result'); result.setAttribute('aria-live', 'polite');
    const value = el('strong', null, '—'), note = el('p', 'price-note');
    result.append(el('span', null, 'Avg. cost / 3-turn conversation'), value);
    fields.appendChild(result);
    box.append(fields, note);
    function update() {
      const rates = inputs.map(input => input.value.trim() === '' ? NaN : Number(input.value));
      const count = summary.token_complete_sessions ?? summary.usage_complete_sessions ?? 0;
      const cost = count ? estimate(summary.session_input_tokens?.mean, summary.session_output_tokens?.mean, ...rates) : null;
      const valid = rates.every(n => Number.isFinite(n) && n >= 0);
      inputs.forEach((input, i) => input.setAttribute('aria-invalid', input.value !== '' && !(Number.isFinite(rates[i]) && rates[i] >= 0) ? 'true' : 'false'));
      value.textContent = cost === null ? '—' : new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',minimumFractionDigits:4,maximumFractionDigits:6}).format(cost);
      note.textContent = !count ? 'Token usage unavailable. Run an Agent evaluation to estimate cost.'
        : !valid ? 'Enter input and output prices to estimate cost.'
        : 'Estimate based on ' + count + ' measured conversations.';
      try {localStorage.setItem(key, JSON.stringify({input:inputs[0].value,output:inputs[1].value}));} catch (_) {}
    }
    inputs.forEach(input => input.addEventListener('input', update)); update(); return box;
  };
})();
