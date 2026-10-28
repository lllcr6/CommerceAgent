

const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

function toast(msg, isErr) {
  let t = $("toast");
  if (!t) { t = el("div"); t.id = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = isErr ? "err" : "";
  t.style.display = "block";
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.display = "none"; }, 3600);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || ("HTTP " + r.status));
  return body;
}


const fmtTime = (iso) => window.formatDateTime(iso);

const fmtBytes = (n) => {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
};


function scoreCell(v, redLine) {
  const td = el("td", "num");
  const box = el("div", "cell-bar");
  const val = el("span", "v", v === null || v === undefined ? "—" : v.toFixed(3));
  const track = el("span", "track");
  const fill = el("span", "fill");
  fill.style.width = Math.max(2, Math.round((v || 0) * 100)) + "%";
  if (redLine !== null && redLine !== undefined) fill.classList.add(v >= redLine ? "hi" : "lo");
  track.appendChild(fill);
  box.appendChild(val);
  box.appendChild(track);
  td.appendChild(box);
  return td;
}

const STATUS_LABEL = {
  idle: "Not run yet", running: "Running", ok: "Completed", failed: "Failed", stopped: "Stopped",
};


const JOB_LOGS = {};


function jobButton(spec, logbox, onFinish) {
  const titles = {"roberta-corpus": "Generate or resume the training corpus", "roberta-dataset": "Export and audit dataset partitions"};
  spec = {...spec, title: titles[spec.name] || spec.title};
  const btn = el("button", "btn sm go", spec.actionLabel || "Run " + spec.title);
  btn.title = spec.disabledReason || spec.title;
  if (spec.danger) { btn.classList.remove("go"); btn.classList.add("danger"); }
  const stopText = spec.stopLabel || (/^(eval|bench)|calibrate|threshold|golden/.test(spec.name) ? "Stop evaluation" : "Stop task");
  const stop = el("button", "btn sm", stopText);
  stop.disabled = true;
  const controls = el("span", "job-controls");
  controls.style.cssText = "display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap";
  controls.appendChild(btn); controls.appendChild(stop);
  let timer = null;

  function paint(st) {
    const running = st.status === "running";
    btn.disabled = running || Boolean(spec.disabledReason);
    stop.disabled = !running;
    stop.hidden = Boolean(spec.hideIdleStop) && !running;
    stop.textContent = stopText;
    btn.textContent = running
      ? (spec.runningLabel || "Running… " + spec.title)
      : (spec.actionLabel || (st.status === "idle" ? "Run " : "Run again ") + spec.title);
    if (st.log) {
      const at = st.started_at || st.log_mtime;
      JOB_LOGS[spec.name] = {text: st.log, at};
      showLog(st.log, at);
    }
  }

  function showLog(text, at) {
    if (logbox._caption) {
      logbox._caption.hidden = false;
      logbox._caption.textContent = "Run output: " + (spec.actionLabel || spec.title)
        + (at ? " · " + fmtTime(at) : "");
    }
    logbox.classList.add("on");
    logbox.textContent = text;
    logbox.scrollTop = logbox.scrollHeight;
  }

  async function poll() {
    try {
      const st = await api("/api/jobs/" + spec.name);
      paint(st);
      if (st.status !== "running") {
        clearInterval(timer); timer = null;
        toast(spec.title + "：" + STATUS_LABEL[st.status]
          + (st.returncode !== null ? "(Exit code " + st.returncode + ")" : ""),
          st.status !== "ok");
        if (onFinish) onFinish();
      }
    } catch (e) {
      clearInterval(timer); timer = null;
      toast("Polling failed: " + e.message, true);
    }
  }

  btn.addEventListener("click", async () => {
    if (spec.heavy && !confirm(spec.confirmationMessage ||
      "Start " + spec.title + "? This may take several minutes.")) return;
    btn.disabled = true;
    logbox.classList.add("on");
    logbox.textContent = "Starting…";
    try {
      const st = await api("/api/jobs/" + spec.name, { method: "POST" });
      paint(st);
      timer = setInterval(poll, 1200);
    } catch (e) {
      btn.disabled = Boolean(spec.disabledReason);
      stop.disabled = true;
      logbox.textContent = "Could not start: " + e.message;
      toast("Could not start: " + e.message, true);
    }
  });

  stop.addEventListener("click", async () => {
    stop.disabled = true;
    stop.textContent = "Stopping…";
    try {
      const st = await api("/api/jobs/" + spec.name + "/stop", {method: "POST"});
      if (timer) { clearInterval(timer); timer = null; }
      paint(st);
      toast("Stopped. Completed requests may still be billed.");
      if (onFinish) onFinish();
    } catch (e) {
      toast("Could not stop: " + e.message, true);
      // The server remains authoritative if completion and stop raced.
      await poll();
    }
  });

  paint(spec);
  if (JOB_LOGS[spec.name]) showLog(JOB_LOGS[spec.name].text, JOB_LOGS[spec.name].at);   // Restore logs after rebuilding
  if (spec.status === "running") timer = setInterval(poll, 1200);
  return controls;
}


function jobRow(specs, onFinish, extraNote) {
  const wrap = el("div");
  const row = el("div", "jobrow");
  const caption = el("p", "needs");
  caption.hidden = true;
  const logbox = el("pre", "logbox");
  logbox._caption = caption;
  for (const s of specs) row.appendChild(jobButton(s, logbox, onFinish));
  if (extraNote) row.appendChild(el("span", "needs", extraNote));
  wrap.appendChild(row);
  const details = el("details");
  details.appendChild(el("summary", null, "View run details"));
  details.appendChild(caption);
  details.appendChild(logbox);
  wrap.appendChild(details);
  return wrap;
}


function readNoteHtml(note, fallbackHtml) {
  if (!note || /[\u3400-\u9fff]/.test(String(note))) return fallbackHtml;
  const esc = String(note).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  return esc.replace(/(?<![A-Za-z@_.\-\d])\d+(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z_])/g,
    (n) => "<b>" + n + "</b>");
}


function missingBox(hint) {
  return el("div", "miss", hint || "No results yet. Run this task to get started.");
}
