// PatentRadar Dashboard frontend — sidebar + main stage layout.
// SSE-driven, per-module log buffers, auto-follow current module.

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const MODULE_LABELS = {
  1: "模块 1 · 拆解权利要求",
  2: "模块 2 · 竞品搜索 + 权 1 判定",
  3: "模块 3 · 全部权利要求扩展",
  4: "模块 4 · 生成报告",
};

const MAX_LINES_PER_MODULE = 5000;

const els = {
  form: $("#run-form"),
  input: $("#pub-input"),
  btn: $("#run-btn"),
  replayBtn: $("#replay-btn"),
  pipelineStatus: $("#pipeline-status"),
  moduleItems: $$(".module-item"),
  stageTitle: $("#stage-title"),
  stageDot: $("#stage-dot"),
  stageElapsed: $("#stage-elapsed"),
  stageSummary: $("#stage-summary"),
  stageLog: $("#stage-log"),
  emptyState: $("#empty-state"),
  followBtn: $("#follow-btn"),
  outputsSection: $("#outputs-section"),
  outputsList: $("#outputs-list"),
  replayBar: $("#replay-bar"),
  replayToggle: $("#replay-toggle"),
  speedBtns: $$(".speed-btn"),
  progressBar: $("#progress-bar"),
  progressFill: $("#progress-fill"),
  progressThumb: $("#progress-thumb"),
  progressTime: $("#progress-time"),
};

const state = {
  pub: null,
  eventSource: null,
  activeModule: null,         // 当前主屏显示的模块 N
  followCurrent: true,        // 是否自动跟随正在运行的模块
  autoScroll: true,           // 是否自动滚到底
  mode: "idle",               // "idle" | "live" (SSE) | "replay"
  replayer: null,             // Replayer 实例（仅 replay 模式）
  // 每模块独立 buffer：{ lines: [...], status: "...", elapsed: ..., summary: {...} }
  modules: {
    // pendingLLM: { lineIndex: number, msgEl: HTMLElement | null }
    // 当前正在"打字机累加"的 LLM 行；遇到非 token 事件时清掉，下次 token 来时再开新行
    1: { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null },
    2: { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null },
    3: { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null },
    4: { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null },
  },
  llmBuffer: { 1: "", 2: "", 3: "", 4: "" },  // token 流的累计文字（每模块）
};

// ------------------- helpers -------------------

function formatTs(tsSeconds) {
  const d = tsSeconds ? new Date(tsSeconds * 1000) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function appendLine(moduleN, kind, tag, msg, tsSeconds) {
  const buf = state.modules[moduleN];
  if (!buf) return;
  // 非 LLM 事件来 → 关掉当前 LLM 累加段（下次 token 会开新段）
  if (kind !== "llm") buf.pendingLLM = null;
  const line = {
    ts: formatTs(tsSeconds),
    kind, // lifecycle | stdout | llm | error
    tag,
    msg,
  };
  buf.lines.push(line);
  if (buf.lines.length > MAX_LINES_PER_MODULE) {
    buf.lines.splice(0, buf.lines.length - MAX_LINES_PER_MODULE);
  }
  if (state.activeModule === moduleN) {
    renderLine(line);
  }
}

function renderLine(line) {
  if (els.emptyState && !els.emptyState.hidden) els.emptyState.hidden = true;
  const el = document.createElement("div");
  el.className = `log-line ${line.kind}`;
  el.innerHTML =
    `<span class="ts">[${line.ts}]</span>` +
    `<span class="tag">[${line.tag}]</span>` +
    `<span class="msg"></span>`;
  el.querySelector(".msg").textContent = line.msg;
  els.stageLog.appendChild(el);
  if (state.autoScroll) {
    els.stageLog.scrollTop = els.stageLog.scrollHeight;
  }
  return el;
}

// LLM token 专用：持续追加到当前打字机行；没有就开新行。
function appendLLMDelta(moduleN, delta, tsSeconds) {
  if (!delta) return;
  const buf = state.modules[moduleN];
  if (!buf) return;

  // 没有正在累加的 LLM 行 → 开一条新 line
  if (!buf.pendingLLM) {
    const line = {
      ts: formatTs(tsSeconds),
      kind: "llm",
      tag: "LLM",
      msg: "",
    };
    buf.lines.push(line);
    if (buf.lines.length > MAX_LINES_PER_MODULE) {
      buf.lines.splice(0, buf.lines.length - MAX_LINES_PER_MODULE);
    }
    let msgEl = null;
    if (state.activeModule === moduleN) {
      const el = renderLine(line);
      msgEl = el.querySelector(".msg");
    }
    buf.pendingLLM = {
      lineIndex: buf.lines.length - 1,
      msgEl,
    };
  }

  // 追加到 line.msg + DOM 文本
  const line = buf.lines[buf.pendingLLM.lineIndex];
  if (!line || line.kind !== "llm") {
    // buf 被裁过，丢掉 pending
    buf.pendingLLM = null;
    return appendLLMDelta(moduleN, delta, tsSeconds);
  }
  line.msg += delta;
  if (state.activeModule === moduleN && buf.pendingLLM.msgEl) {
    buf.pendingLLM.msgEl.textContent = line.msg;
    if (state.autoScroll) {
      els.stageLog.scrollTop = els.stageLog.scrollHeight;
    }
  }
}

function clearStage() {
  els.stageLog.innerHTML = "";
  if (els.emptyState && els.emptyState.parentElement !== els.stageLog) {
    els.stageLog.appendChild(els.emptyState);
  }
  if (els.emptyState) els.emptyState.hidden = true;
  els.stageSummary.hidden = true;
}

function showActiveModule(moduleN) {
  state.activeModule = moduleN;
  // 高亮 sidebar
  els.moduleItems.forEach((item) => {
    item.classList.toggle(
      "active",
      Number(item.dataset.module) === moduleN
    );
  });
  // 标题
  els.stageTitle.textContent = MODULE_LABELS[moduleN] || "—";
  const buf = state.modules[moduleN];
  els.stageDot.className = `status-dot ${buf.status}`;
  els.stageElapsed.textContent = buf.elapsed != null ? `耗时 ${buf.elapsed}s` : "";
  // 重新渲染该模块所有缓存行
  els.stageLog.innerHTML = "";
  let lastEl = null;
  for (const line of buf.lines) {
    lastEl = renderLine(line);
  }
  // 切换后如果最后一行还是 pending 的 LLM 段，重新挂接 msgEl 指针让 token 能继续追加
  if (buf.pendingLLM && lastEl && buf.lines[buf.pendingLLM.lineIndex]?.kind === "llm") {
    buf.pendingLLM.msgEl = lastEl.querySelector(".msg");
  }
  // summary
  renderSummary(moduleN);
  if (state.autoScroll) {
    els.stageLog.scrollTop = els.stageLog.scrollHeight;
  }
}

function renderSummary(moduleN) {
  const buf = state.modules[moduleN];
  const sm = buf.summary;
  if (!sm || Object.keys(sm).length === 0) {
    els.stageSummary.hidden = true;
    return;
  }
  let html = "";
  if (moduleN === 1) {
    html = `
      <div class="kv"><div class="k">标题</div><div class="v">${escape(sm.title || "—")}</div></div>
      <div class="kv"><div class="k">申请人</div><div class="v">${escape((sm.applicants || []).join("、") || "—")}</div></div>
      <div class="kv"><div class="k">申请日</div><div class="v">${escape(sm.application_date || "—")}</div></div>
      <div class="kv"><div class="k">技术领域</div><div class="v">${escape(sm.technology_tag || "—")}</div></div>
      <div class="kv"><div class="k">权 1 特征</div><div class="v">${sm.claim1_features ?? 0}</div></div>
      <div class="kv"><div class="k">总 claim</div><div class="v">${sm.claims ?? 0}</div></div>
    `;
  } else if (moduleN === 2) {
    html = `
      <div class="kv"><div class="k">TOP 候选</div><div class="v">${sm.top_count ?? 0}</div></div>
      <div class="kv"><div class="k">失效</div><div class="v">${sm.excluded_count ?? 0}</div></div>
    `;
    if (sm.top?.length) {
      html += `<ul class="candidate-list">${sm.top.map((c) => `
        <li>
          <span>${escape(c.company || "")} / ${escape(c.product_name || "")}</span>
          <span class="score">${c.total_score ?? "—"}</span>
        </li>`).join("")}</ul>`;
    }
  } else if (moduleN === 3) {
    html = `<div class="kv"><div class="k">处理候选</div><div class="v">${sm.candidate_count ?? 0}</div></div>`;
    if (sm.candidates?.length) {
      html += `<ul class="candidate-list">${sm.candidates.map((c) => `
        <li>
          <span>${escape(c.company || "")} · ${escape(c.candidate_id || "")}</span>
          <span class="score">${c.total_score ?? "—"}</span>
        </li>`).join("")}</ul>`;
    }
  } else if (moduleN === 4) {
    html = `<div class="kv"><div class="k">报告大小</div><div class="v">${kb(sm.size_bytes || 0)}</div></div>`;
  }
  els.stageSummary.innerHTML = html;
  els.stageSummary.hidden = false;
}

function setModuleStatus(n, status, elapsed) {
  const buf = state.modules[n];
  buf.status = status;
  if (elapsed != null) buf.elapsed = elapsed;
  const item = document.querySelector(`.module-item[data-module="${n}"]`);
  if (item) {
    item.classList.remove("pending", "running", "done", "error");
    item.classList.add(status);
    item.querySelector(".module-elapsed").textContent =
      elapsed != null ? `${elapsed}s` : "";
  }
  if (state.activeModule === n) {
    els.stageDot.className = `status-dot ${status}`;
    els.stageElapsed.textContent = elapsed != null ? `耗时 ${elapsed}s` : "";
  }
  // follow-current 行为：哪个 module 是 running，stage 切到它
  if (status === "running" && state.followCurrent) {
    showActiveModule(n);
  }
  if (status === "done" || status === "error") {
    refreshOutputs();
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

function clearAllBuffers() {
  for (const n of [1, 2, 3, 4]) {
    state.modules[n] = { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null };
    state.llmBuffer[n] = "";
    setModuleStatus(n, "pending", null);
  }
  els.outputsSection.hidden = true;
  els.outputsList.innerHTML = "";
}

// ------------------- SSE handlers -------------------

function connectStream(pub) {
  if (state.eventSource) state.eventSource.close();
  const es = new EventSource(`/api/stream/${encodeURIComponent(pub)}`);
  state.eventSource = es;

  es.onopen = () => {
    setConnectionState("connected");
  };

  es.onmessage = (ev) => {
    let p;
    try { p = JSON.parse(ev.data); } catch { return; }
    if (p.type === "status") {
      handleStatusSnapshot(p);
    } else if (p.type === "progress") {
      handleProgress(p);
    } else if (p.type === "token") {
      handleToken(p);
    } else if (p.type === "stdout") {
      handleStdout(p);
    }
  };

  es.onerror = () => {
    // readyState: 0 connecting, 1 open, 2 closed
    if (es.readyState === EventSource.CLOSED) {
      setConnectionState("closed");
    } else {
      setConnectionState("reconnecting");
    }
  };
}

function setConnectionState(state) {
  const el = els.pipelineStatus;
  if (state === "reconnecting") {
    el.classList.remove("ok");
    el.classList.add("failed");
    el.textContent = "⚠ SSE 重连中（server 是否在跑？）";
  } else if (state === "closed") {
    el.classList.remove("ok", "running");
    el.classList.add("failed");
    el.textContent = "✕ SSE 连接断开";
  }
  // "connected" 不主动改文案——让 progress 事件接管
}

function handleStatusSnapshot(p) {
  for (const m of p.modules || []) {
    state.modules[m.id].status = m.status || "pending";
    state.modules[m.id].elapsed = m.elapsed_s ?? null;
    setModuleStatus(m.id, m.status || "pending", m.elapsed_s);
  }
  // 初次进入页面时，主舞台没固定到任何模块 → 自动定位到"最后一个非 pending"
  // 的模块，让用户能立刻看到已有进度。优先级：running > error > done > pending。
  if (state.activeModule == null) {
    const mods = p.modules || [];
    const running = mods.find((m) => m.status === "running");
    const error   = [...mods].reverse().find((m) => m.status === "error");
    const done    = [...mods].reverse().find((m) => m.status === "done");
    const target  = running || error || done;
    if (target) {
      showActiveModule(target.id);
      backfillModuleFromServer(target.id);
    }
  }
}

async function backfillModuleFromServer(moduleN) {
  // 老的 run（页面刷新后/历史 run 选择后）token 流和 stdout 还没补回前端 buffer。
  // 拉一份 stdout 日志补到 lines，让用户能看到历史内容。
  // 注：token 流不回灌（数据量可能大且渲染压力高），只走实时 SSE。
  if (!state.pub) return;
  try {
    const res = await fetch(`/api/log/${encodeURIComponent(state.pub)}/${moduleN}?tail=500`);
    if (!res.ok) return;
    const data = await res.json();
    const buf = state.modules[moduleN];
    // 只在 buffer 为空时回灌，避免重复
    if (buf.lines.length > 0) return;
    for (const line of data.lines || []) {
      let kind = "stdout";
      let tag = "STDOUT";
      if (/^ERROR\b/.test(line) || /Traceback/.test(line)) { kind = "error"; tag = "STDERR"; }
      else if (/^WARNING\b/.test(line)) { tag = "WARN"; }
      else if (/^INFO\b/.test(line)) { tag = "INFO"; }
      buf.lines.push({ ts: "—", kind, tag, msg: line });
    }
    if (state.activeModule === moduleN) {
      showActiveModule(moduleN);
    }
  } catch {}
}

function handleProgress(ev) {
  const top = ev.event;
  if (top === "pipeline_start") {
    setPipelineStatus("running");
    for (const n of [1, 2, 3, 4]) {
      appendLine(n, "lifecycle", "LIFECYCLE", `pipeline start (${ev.publication_no || ""})`, ev.ts);
    }
    return;
  }
  if (top === "pipeline_end") {
    setPipelineStatus(ev.status || "ok");
    els.btn.disabled = false;
    if (state.mode === "live") {
      refreshStatus();
      // 跑完了，露出"回看本次"按钮
      els.replayBtn.hidden = false;
    }
    return;
  }
  if (ev.module == null) return;
  const n = ev.module;
  if (ev.event === "start") {
    appendLine(n, "lifecycle", "LIFECYCLE", `模块 ${n} (${ev.label}) 启动`, ev.ts);
    setModuleStatus(n, "running");
  } else if (ev.event === "done") {
    appendLine(n, "lifecycle", "LIFECYCLE", `模块 ${n} 完成 · 耗时 ${ev.elapsed}s`, ev.ts);
    setModuleStatus(n, "done", ev.elapsed);
    if (state.mode === "live") refreshStatus();
  } else if (ev.event === "error") {
    const detail = ev.message || `exit_code=${ev.exit_code}`;
    appendLine(n, "error", "ERROR", `模块 ${n} 失败 · ${detail}`, ev.ts);
    setModuleStatus(n, "error", ev.elapsed);
    if (state.mode === "live") refreshStatus();
  }
}

function handleToken(p) {
  const n = p.module;
  if (!n) return;
  // 累加到当前打字机行（连续滚动效果），不再每个 chunk 一行
  appendLLMDelta(n, p.delta || "", p.ts);
}

function handleStdout(p) {
  const n = p.module;
  if (!n) return;
  const line = p.line || "";
  let kind = "stdout";
  let tag = "STDOUT";
  let msg = line;

  // 识别 logging 输出格式: "HH:MM:SS [logger.name] message"
  const m = line.match(/^(\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+(.*)$/);
  if (m) {
    const loggerName = m[2];
    msg = m[3];
    if (loggerName.startsWith("patentradar.modules.")) {
      // patentradar.modules.competitor_search.pipeline → COMPETITOR_SEARCH
      tag = loggerName.split(".")[2].toUpperCase();
    } else if (loggerName.startsWith("patentradar.llm")) {
      tag = "LLM";  // 注意：这里是底层 logger，跟 token 流不冲突（不同 kind）
    } else if (loggerName.startsWith("patentradar.fetcher")) {
      tag = "FETCH";
    } else if (loggerName.startsWith("patentradar.search")) {
      tag = "SEARCH";
    } else if (loggerName === "httpx") {
      tag = "HTTP";
    } else if (loggerName.startsWith("patentradar.")) {
      tag = loggerName.replace("patentradar.", "").toUpperCase();
    } else {
      tag = loggerName.split(".").pop().toUpperCase();
    }
  } else if (/^ERROR\b/.test(line) || /Traceback/.test(line)) {
    kind = "error";
    tag = "STDERR";
  } else if (/^WARNING\b/.test(line)) {
    tag = "WARN";
  } else if (/^INFO\b/.test(line)) {
    tag = "INFO";
  }

  appendLine(n, kind, tag, msg, p.ts);
}

// ------------------- REST helpers -------------------

async function refreshStatus() {
  if (!state.pub) return;
  try {
    const res = await fetch(`/api/status/${encodeURIComponent(state.pub)}`);
    if (!res.ok) return;
    const data = await res.json();
    for (const m of data.modules || []) {
      state.modules[m.id].summary = m.summary || null;
      setModuleStatus(m.id, m.status || "pending", m.elapsed_s);
      if (state.activeModule === m.id) renderSummary(m.id);
    }
    setPipelineStatus(data.pipeline_state);
  } catch {}
}

async function refreshOutputs() {
  if (!state.pub) return;
  try {
    const res = await fetch(`/api/status/${encodeURIComponent(state.pub)}`);
    if (!res.ok) return;
    const data = await res.json();
    const items = [];
    for (const m of data.modules || []) {
      const files = m.summary?.files;
      if (!Array.isArray(files) || !files.length) continue;
      for (const f of files) {
        // .md 走渲染 endpoint（直接显示成漂亮的 HTML）；其余原样返回
        const href = f.kind === "md"
          ? `/api/render/${encodeURIComponent(state.pub)}/${encodeURIComponent(f.name)}`
          : `/api/output/${encodeURIComponent(state.pub)}/${encodeURIComponent(f.name)}`;
        const icon = f.kind === "md" ? "📄" : f.kind === "pdf" ? "📕" : "📋";
        items.push({
          href,
          label: `${icon} 模块 ${m.id} · ${f.name}`,
        });
      }
    }
    if (items.length) {
      els.outputsList.innerHTML = items.map((it) =>
        `<li><a href="${escape(it.href)}" target="_blank" rel="noopener">${escape(it.label)}</a></li>`
      ).join("");
      els.outputsSection.hidden = false;
    } else {
      els.outputsSection.hidden = true;
    }
  } catch {}
}

// 历史 run 下拉已删除，按用户要求只能回看刚跑完的本次专利。

// ------------------- events -------------------

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pub = els.input.value.trim().toUpperCase();
  if (!pub) return;
  // Tear down any prior replay
  if (state.replayer) { state.replayer.pause(); state.replayer = null; }
  els.replayBar.hidden = true;
  els.replayBtn.hidden = true;   // 新跑开始时藏起"回看本次"按钮
  state.mode = "live";
  state.pub = pub;
  state.followCurrent = true;
  clearAllBuffers();
  showActiveModule(1);
  setPipelineStatus("running");
  els.btn.disabled = true;
  // 写 URL hash 以便刷新后能恢复
  window.location.hash = pub;
  try {
    const res = await fetch(`/api/run/${encodeURIComponent(pub)}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.text();
      alert(`启动失败: ${err}`);
      els.btn.disabled = false;
      return;
    }
    connectStream(pub);
    if (state.mode === "live") refreshStatus();
  } catch (err) {
    alert(`网络错误: ${err}`);
    els.btn.disabled = false;
  }
});

els.replayBtn.addEventListener("click", async () => {
  if (!state.pub) return;
  state.followCurrent = true;
  clearAllBuffers();
  state.activeModule = null;
  clearStage();
  // 关掉实时 SSE 进入回放模式
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  state.mode = "replay";
  els.replayBtn.hidden = true;  // 进回放后藏起触发按钮，由回放控件接管
  await startReplay(state.pub);
});

els.moduleItems.forEach((item) => {
  item.addEventListener("click", () => {
    const n = Number(item.dataset.module);
    state.followCurrent = false;  // 手动切了就关掉自动跟随
    showActiveModule(n);
  });
});

els.followBtn.addEventListener("click", () => {
  state.autoScroll = !state.autoScroll;
  els.followBtn.classList.toggle("active", state.autoScroll);
  if (state.autoScroll) {
    els.stageLog.scrollTop = els.stageLog.scrollHeight;
  }
});

// 用户手动向上滚 → 关闭自动滚；滚到底 → 重新打开
els.stageLog.addEventListener("scroll", () => {
  const el = els.stageLog;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (!atBottom && state.autoScroll) {
    state.autoScroll = false;
    els.followBtn.classList.remove("active");
  } else if (atBottom && !state.autoScroll) {
    state.autoScroll = true;
    els.followBtn.classList.add("active");
  }
});

// 历史 run 自动列表已删除：用户只能回看本次刚跑完的专利。

// 如果 URL 里带了 hash（例如 #CN114512759B），刷新页面后自动恢复
// 实时模式：重新连接 SSE → SSE 会从文件 offset=0 把所有历史事件再推一遍 →
// 前端 replay 一次重建状态。如果该 run 已结束（pipeline_end 事件会到），
// connectStream 仍保留为 idle 长连接，无害。
(async function restoreFromHash() {
  const initialPub = (window.location.hash || "").replace(/^#/, "").trim().toUpperCase();
  if (!initialPub) return;
  state.pub = initialPub;
  state.mode = "live";
  state.followCurrent = true;
  els.input.value = initialPub;
  els.btn.disabled = true;  // 跑过程中也不允许重复点
  setPipelineStatus("running");
  connectStream(initialPub);
  // refreshStatus 拉一次 server 端 summary（数据已写完的模块能立即看到）
  try { await refreshStatus(); } catch {}
  // 如果 server 已经判定 pipeline 结束（ok/failed），按钮可以放开 + 露出回看
  try {
    const res = await fetch(`/api/status/${encodeURIComponent(initialPub)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.pipeline_state === "ok" || data.pipeline_state === "failed") {
        els.btn.disabled = false;
        els.replayBtn.hidden = false;
      }
    }
  } catch {}
})();

// ------------------- utils -------------------

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

function mmss(seconds) {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// =================== Replayer ===================

class Replayer {
  constructor(events, duration) {
    this.events = events;
    this.duration = duration;
    this.startEventTs = events[0]?.ts || 0;
    this.idx = 0;
    this.speed = 1;
    this.playing = false;
    this.timer = null;
    this.frameHandle = null;
    this.startWall = null;     // performance.now() of "speed 1x t=0" reference
    this.playedEventMs = 0;    // virtual event-time consumed so far
  }

  _virtualNowMs() {
    if (!this.playing) return this.playedEventMs;
    const wallElapsed = performance.now() - this.startWall;
    return this.playedEventMs + wallElapsed * this.speed;
  }

  start() {
    if (this.playing) return;
    this.playing = true;
    this.startWall = performance.now();
    this._scheduleNext();
    this._updateProgress();
  }

  pause() {
    if (!this.playing) return;
    this.playedEventMs = this._virtualNowMs();
    this.playing = false;
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    if (this.frameHandle) { cancelAnimationFrame(this.frameHandle); this.frameHandle = null; }
  }

  setSpeed(s) {
    const wasPlaying = this.playing;
    if (wasPlaying) this.pause();
    this.speed = s;
    if (wasPlaying) this.start();
  }

  seek(fractionOfDuration) {
    const wasPlaying = this.playing;
    if (wasPlaying) this.pause();
    const targetMs = fractionOfDuration * this.duration * 1000;
    // Reset everything (cheaper than incremental for large jumps)
    this._resetVisuals();
    this.idx = 0;
    this.playedEventMs = 0;
    // Fast-forward dispatch up to target (no UI delay)
    while (this.idx < this.events.length) {
      const ev = this.events[this.idx];
      const elapsedMs = (ev.ts - this.startEventTs) * 1000;
      if (elapsedMs > targetMs) break;
      dispatchReplayEvent(ev);
      this.idx++;
    }
    this.playedEventMs = targetMs;
    this._updateProgressUI();
    if (wasPlaying) this.start();
  }

  _resetVisuals() {
    // Reset all 4 modules to pending state + clear log buffers + stage
    for (const n of [1, 2, 3, 4]) {
      state.modules[n] = { lines: [], status: "pending", elapsed: null, summary: null, startedAt: null, pendingLLM: null };
      state.llmBuffer[n] = "";
      setModuleStatus(n, "pending", null);
    }
    state.activeModule = null;
    clearStage();
  }

  _scheduleNext() {
    if (!this.playing) return;
    if (this.idx >= this.events.length) {
      this._onEnded();
      return;
    }

    // High-speed batch mode: in one animation frame, dispatch everything
    // whose ts ≤ current virtual cursor. Avoids setTimeout storm.
    if (this.speed > 50) {
      const cursorMs = this._virtualNowMs();
      while (this.idx < this.events.length) {
        const ev = this.events[this.idx];
        const elapsedMs = (ev.ts - this.startEventTs) * 1000;
        if (elapsedMs > cursorMs) break;
        dispatchReplayEvent(ev);
        this.idx++;
      }
      this._updateProgressUI();
      if (this.idx >= this.events.length) { this._onEnded(); return; }
      this.frameHandle = requestAnimationFrame(() => this._scheduleNext());
      return;
    }

    // Normal mode: schedule next single event via setTimeout
    const ev = this.events[this.idx];
    const elapsedMs = (ev.ts - this.startEventTs) * 1000;
    const cursorMs = this._virtualNowMs();
    const wallDelay = Math.max(0, (elapsedMs - cursorMs) / this.speed);
    this.timer = setTimeout(() => {
      dispatchReplayEvent(ev);
      this.idx++;
      this._updateProgressUI();
      this._scheduleNext();
    }, wallDelay);
  }

  _updateProgress() {
    // Animation-frame loop to refresh UI even when no events fire (e.g. between
    // sparse stdout lines), so the progress bar feels smooth.
    const loop = () => {
      if (!this.playing) return;
      this._updateProgressUI();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  _updateProgressUI() {
    const cursorMs = this._virtualNowMs();
    const totalMs = this.duration * 1000;
    const frac = totalMs > 0 ? Math.min(1, cursorMs / totalMs) : 0;
    els.progressFill.style.width = `${frac * 100}%`;
    els.progressThumb.style.left = `${frac * 100}%`;
    els.progressTime.textContent = `${mmss(cursorMs / 1000)} / ${mmss(this.duration)}`;
  }

  _onEnded() {
    this.playing = false;
    this.playedEventMs = this.duration * 1000;
    this._updateProgressUI();
    els.replayToggle.textContent = "↺";
    els.replayToggle.title = "重播";
  }
}

function dispatchReplayEvent(ev) {
  // Reuse the same handlers as SSE.
  if (ev.type === "progress") handleProgress(ev);
  else if (ev.type === "token") handleToken(ev);
  else if (ev.type === "stdout") handleStdout(ev);
}

async function startReplay(pub) {
  els.replayBar.hidden = false;
  els.replayToggle.textContent = "⏳";
  try {
    const res = await fetch(`/api/replay/${encodeURIComponent(pub)}`);
    if (!res.ok) {
      alert(`无法加载回放: HTTP ${res.status}`);
      els.replayBar.hidden = true;
      return;
    }
    const data = await res.json();
    if (!data.events?.length) {
      alert("该 run 暂无可回放数据");
      els.replayBar.hidden = true;
      return;
    }
    state.replayer = new Replayer(data.events, data.duration_s);
    els.replayToggle.textContent = "▶";
    // sync UI to selected speed (default 1x)
    els.speedBtns.forEach(b => b.classList.toggle("active", Number(b.dataset.speed) === 1));
    state.replayer.start();
    els.replayToggle.textContent = "⏸";
  } catch (err) {
    alert(`回放出错: ${err}`);
    els.replayBar.hidden = true;
  }
}

// Replay control events
els.replayToggle.addEventListener("click", () => {
  if (!state.replayer) return;
  if (state.replayer.playing) {
    state.replayer.pause();
    els.replayToggle.textContent = "▶";
  } else {
    if (state.replayer.idx >= state.replayer.events.length) {
      // Replay finished → restart from beginning
      state.replayer.seek(0);
    }
    state.replayer.start();
    els.replayToggle.textContent = "⏸";
  }
});

els.speedBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    const s = Number(btn.dataset.speed);
    els.speedBtns.forEach(b => b.classList.toggle("active", b === btn));
    if (state.replayer) state.replayer.setSpeed(s);
  });
});

// Click on progress bar to seek
els.progressBar.addEventListener("click", (e) => {
  if (!state.replayer) return;
  const rect = els.progressBar.getBoundingClientRect();
  const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  state.replayer.seek(frac);
  if (state.replayer.playing) {
    els.replayToggle.textContent = "⏸";
  } else {
    els.replayToggle.textContent = "▶";
  }
});
