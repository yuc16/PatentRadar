// PatentRadar Dashboard frontend.
// Talks to /api/run, /api/status, /api/stream (SSE), /api/log, /api/runs.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
  form: $("#run-form"),
  input: $("#pub-input"),
  btn: $("#run-btn"),
  history: $("#history-select"),
  streamToggle: $("#stream-toggle"),
  pipelineStatus: $("#pipeline-status"),
};

const state = {
  pub: null,
  eventSource: null,
  pollHandle: null,
  showStream: true,
};

const MODULE_LABELS = {
  1: "拆解",
  2: "竞品搜索",
  3: "全 claim 扩展",
  4: "生成报告",
};

// ---------- module rendering ----------

function setModuleStatus(n, status, elapsed) {
  const card = document.querySelector(`.module[data-module="${n}"]`);
  if (!card) return;
  card.dataset.status = status;
  const dot = card.querySelector(".status-dot");
  dot.classList.remove("pending", "running", "done", "error");
  dot.classList.add(status);
  card.querySelector(".elapsed").textContent =
    elapsed != null ? `${elapsed}s` : "";
}

function renderSummary(n, summary) {
  const el = document.getElementById(`summary-${n}`);
  if (!el || !summary || Object.keys(summary).length === 0) return;
  if (summary.error) {
    el.innerHTML = `<p class="placeholder" style="color:#c44a4a">${escape(summary.error)}</p>`;
    return;
  }
  if (n === 1) {
    el.innerHTML = `
      <dl>
        <dt>专利标题</dt><dd>${escape(summary.title || "—")}</dd>
        <dt>申请人</dt><dd>${escape((summary.applicants || []).join("、") || "—")}</dd>
        <dt>申请日</dt><dd>${escape(summary.application_date || "—")}</dd>
        <dt>技术领域</dt><dd><span class="pill">${escape(summary.technology_tag || "—")}</span></dd>
        <dt>权 1 特征</dt><dd>${summary.claim1_features ?? 0}</dd>
        <dt>总 claim 数</dt><dd>${summary.claims ?? 0}</dd>
      </dl>
    `;
  } else if (n === 2) {
    const tops = summary.top || [];
    el.innerHTML = `
      <dl>
        <dt>TOP 候选</dt><dd><span class="pill">${summary.top_count ?? 0}</span></dd>
        <dt>失效</dt><dd>${summary.excluded_count ?? 0}</dd>
      </dl>
      ${tops.length ? `<ul>${tops.map(c => `
        <li>
          <span>${escape(c.company || "")} / ${escape(c.product_name || "")}</span>
          <span class="score">${c.total_score ?? "—"}</span>
        </li>`).join("")}</ul>` : ""}
    `;
  } else if (n === 3) {
    const cs = summary.candidates || [];
    el.innerHTML = `
      <dl>
        <dt>处理候选</dt><dd><span class="pill">${summary.candidate_count ?? 0}</span></dd>
      </dl>
      ${cs.length ? `<ul>${cs.map(c => `
        <li>
          <span>${escape(c.company || "")} · ${c.candidate_id || ""}</span>
          <span class="score">${c.total_score ?? "—"}</span>
        </li>`).join("")}</ul>` : ""}
    `;
  } else if (n === 4) {
    const md = summary.report_md;
    const pdf = summary.report_pdf;
    el.innerHTML = `
      <dl>
        <dt>报告大小</dt><dd>${kb(summary.size_bytes || 0)}</dd>
      </dl>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        ${md ? `<a href="/api/output/${state.pub}/report.md" target="_blank">📄 Markdown</a>` : ""}
        ${pdf ? `<a href="/api/output/${state.pub}/report.pdf" target="_blank">📕 PDF</a>` : ""}
      </div>
    `;
  }
}

function appendStream(n, delta) {
  if (!state.showStream) return;
  const pre = document.querySelector(`.stream-text[data-stream="${n}"]`);
  if (!pre) return;
  pre.textContent += delta;
  // autoscroll
  const panel = pre.closest("details");
  if (panel && !panel.open) panel.open = true;
  pre.scrollTop = pre.scrollHeight;
}

function clearModuleVisuals() {
  for (const n of [1, 2, 3, 4]) {
    setModuleStatus(n, "pending", null);
    document.querySelector(`.stream-text[data-stream="${n}"]`).textContent = "";
    document.querySelector(`.log-text[data-log="${n}"]`).textContent = "";
    document.getElementById(`summary-${n}`).innerHTML = `<p class="placeholder">${
      n === 1 ? "等待启动…" : `等待模块 ${n - 1} 完成…`
    }</p>`;
  }
}

function setPipelineStatus(status) {
  const el = els.pipelineStatus;
  el.classList.remove("running", "ok", "failed");
  if (status === "running") {
    el.classList.add("running");
    el.textContent = "● 运行中";
  } else if (status === "ok") {
    el.classList.add("ok");
    el.textContent = "✓ 完成";
  } else if (status === "failed") {
    el.classList.add("failed");
    el.textContent = "✕ 失败";
  } else {
    el.textContent = "空闲";
  }
}

// ---------- SSE ----------

function connectStream(pub) {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  const es = new EventSource(`/api/stream/${encodeURIComponent(pub)}`);
  state.eventSource = es;

  es.onmessage = (ev) => {
    let payload;
    try { payload = JSON.parse(ev.data); } catch { return; }
    if (payload.type === "token") {
      appendStream(payload.module, payload.delta || "");
    } else if (payload.type === "progress") {
      handleProgress(payload);
    } else if (payload.type === "status") {
      for (const m of payload.modules || []) {
        setModuleStatus(m.id, m.status || "pending", m.elapsed_s);
      }
    }
  };

  es.onerror = () => {
    // browsers auto-reconnect; nothing else to do here.
  };
}

function handleProgress(ev) {
  const top = ev.event;
  if (top === "pipeline_start") {
    setPipelineStatus("running");
  } else if (top === "pipeline_end") {
    setPipelineStatus(ev.status || "ok");
    els.btn.disabled = false;
    refreshStatus();  // pull final summary
  } else if (ev.module != null) {
    if (ev.event === "start") {
      setModuleStatus(ev.module, "running");
    } else if (ev.event === "done") {
      setModuleStatus(ev.module, "done", ev.elapsed);
      refreshStatus();
    } else if (ev.event === "error") {
      setModuleStatus(ev.module, "error", ev.elapsed);
      refreshStatus();
    }
  }
}

// ---------- polling helpers ----------

async function refreshStatus() {
  if (!state.pub) return;
  try {
    const res = await fetch(`/api/status/${encodeURIComponent(state.pub)}`);
    if (!res.ok) return;
    const data = await res.json();
    for (const m of data.modules || []) {
      setModuleStatus(m.id, m.status || "pending", m.elapsed_s);
      if (m.summary) renderSummary(m.id, m.summary);
    }
    setPipelineStatus(data.pipeline_state);
  } catch {}
}

async function refreshHistory() {
  try {
    const res = await fetch("/api/runs");
    if (!res.ok) return;
    const data = await res.json();
    els.history.innerHTML =
      '<option value="">— 历史 run —</option>' +
      (data.runs || []).map(r => `<option value="${escape(r)}">${escape(r)}</option>`).join("");
  } catch {}
}

// ---------- event handlers ----------

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pub = els.input.value.trim().toUpperCase();
  if (!pub) return;
  state.pub = pub;
  clearModuleVisuals();
  setPipelineStatus("running");
  els.btn.disabled = true;
  try {
    const res = await fetch(`/api/run/${encodeURIComponent(pub)}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.text();
      alert(`启动失败: ${err}`);
      els.btn.disabled = false;
      return;
    }
    connectStream(pub);
    refreshStatus();
  } catch (err) {
    alert(`网络错误: ${err}`);
    els.btn.disabled = false;
  }
});

els.history.addEventListener("change", (e) => {
  const pub = e.target.value;
  if (!pub) return;
  state.pub = pub;
  els.input.value = pub;
  clearModuleVisuals();
  connectStream(pub);
  refreshStatus();
});

els.streamToggle.addEventListener("change", (e) => {
  state.showStream = e.target.checked;
  $$(".stream-panel").forEach(p => {
    if (p.querySelector(".stream-text")) {
      p.style.display = state.showStream ? "" : "none";
    }
  });
});

// initial load
refreshHistory();
setInterval(refreshHistory, 10000);

// ---------- utils ----------

function escape(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function kb(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
