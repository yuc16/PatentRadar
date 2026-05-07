// PatentRadar 仪表盘 —— 动态版本：所有数据来自后端 API
// 旧的写死 EVENTS 数组已删除，改为从 /api/patents/<pub>/events 拉取

window.AGENTS = [
  { key: "controller", name: "GPT-5.5 控制器", role: "解析 · 规划 · 复核",  model: "gpt-5.5",         color: "ctrl" },
  { key: "deepseek",   name: "DeepSeek Agent", role: "中文公开资料视角",     model: "deepseek-v4-pro", color: "ds" },
  { key: "kimi",       name: "Kimi Agent",     role: "官方 / 长文资料视角",  model: "kimi-k2.6",       color: "km" },
  { key: "glm",        name: "GLM Agent",      role: "语义扩展视角",         model: "glm-5.1",         color: "gl" },
];

// 后端动态填充
window.EVENTS = [];
window.ARTIFACTS = [];

// 后端 API 封装（供 index.html 调用）
window.PatentRadarAPI = {
  async getCurrentRun() {
    const r = await fetch("/api/current-run");
    if (!r.ok) throw new Error(`current-run → HTTP ${r.status}`);
    return await r.json();  // { has_run, pub_no?, log_path?, started_at?, last_mtime?, is_active? }
  },
  async loadEvents(pubNo) {
    const r = await fetch(`/api/patents/${encodeURIComponent(pubNo)}/events`);
    if (!r.ok) throw new Error(`events → HTTP ${r.status}`);
    return await r.json();
  },
  async listArtifacts(pubNo, since) {
    const url = since
      ? `/api/patents/${encodeURIComponent(pubNo)}/artifacts?since=${encodeURIComponent(since)}`
      : `/api/patents/${encodeURIComponent(pubNo)}/artifacts`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`artifacts → HTTP ${r.status}`);
    return await r.json();
  },
  artifactUrl(pubNo, artId) {
    return `/api/patents/${encodeURIComponent(pubNo)}/artifacts/${encodeURIComponent(artId)}`;
  },
  openStream(pubNo, offset, onLog, onEnd) {
    const url = `/api/patents/${encodeURIComponent(pubNo)}/stream?offset=${offset}`;
    const es = new EventSource(url);
    es.addEventListener("log", (e) => {
      try { onLog(JSON.parse(e.data)); } catch (err) { console.warn("bad log event", err); }
    });
    es.addEventListener("end", () => { onEnd && onEnd(); es.close(); });
    es.onerror = () => { /* 浏览器自动重试 */ };
    return es;
  },
};
