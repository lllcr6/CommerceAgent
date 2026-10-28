/* Show timestamps with explicit offsets in local time; preserve unzoned wall time. */
(() => {
  const dateOptions = {year: 'numeric', month: 'short', day: 'numeric'};
  const timeOptions = {hour: 'numeric', minute: '2-digit', hour12: true};
  window.formatDateTime = (value) => {
    if (value == null || value === '') return '—';
    const text = String(value).trim();
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$/);
    let date, options;
    if (match) {
      const [, year, month, day, hour, minute, second] = match;
      date = new Date(Date.UTC(+year, +month - 1, +day, +(hour || 0), +(minute || 0), +(second || 0)));
      if (date.getUTCFullYear() !== +year || date.getUTCMonth() !== +month - 1 ||
          date.getUTCDate() !== +day || date.getUTCHours() !== +(hour || 0) ||
          date.getUTCMinutes() !== +(minute || 0) || date.getUTCSeconds() !== +(second || 0)) return '—';
      options = {...dateOptions, ...(hour == null ? {} : timeOptions), timeZone: 'UTC'};
    } else {
      // Require a zone on non-naive strings instead of guessing the server timezone.
      if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) return '—';
      date = new Date(text.replace(" ", "T"));
      if (Number.isNaN(date.getTime())) return '—';
      options = {...dateOptions, ...timeOptions};
    }
    return new Intl.DateTimeFormat('en-US', options).format(date);
  };
})();
