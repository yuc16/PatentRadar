const state = {
  token: localStorage.getItem("patentradar_workspace_token") || "",
  mcpUrl: `${window.location.origin}/mcp`,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const toast = (message) => {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 2400);
};

function updateCommands() {
  $("#mcp-url-inline").textContent = state.mcpUrl;
  if (!state.token) return;
  $("#mac-command").textContent = `export PATENTRADAR_MCP_TOKEN='${state.token}'\ncodex mcp add patentradar --url ${state.mcpUrl} --bearer-token-env-var PATENTRADAR_MCP_TOKEN`;
  $("#windows-command").textContent = `[Environment]::SetEnvironmentVariable("PATENTRADAR_MCP_TOKEN", "${state.token}", "User")\n$env:PATENTRADAR_MCP_TOKEN="${state.token}"\ncodex mcp add patentradar --url ${state.mcpUrl} --bearer-token-env-var PATENTRADAR_MCP_TOKEN`;
  $("#workspace-token").value = state.token;
  $("#token-result").hidden = false;
  $("#vault-status").textContent = "工作区已连接";
  $("#create-workspace").textContent = "重新创建工作区";
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || payload.message || `请求失败：${response.status}`);
  return payload;
}

$("#create-workspace").addEventListener("click", async () => {
  const button = $("#create-workspace");
  button.disabled = true;
  button.textContent = "正在创建…";
  try {
    const payload = await api("/api/workspaces", { method: "POST" });
    state.token = payload.token;
    state.mcpUrl = payload.mcp_url;
    localStorage.setItem("patentradar_workspace_token", state.token);
    updateCommands();
    await refreshKeyStatus();
    toast("工作区已创建，请保存令牌");
    button.textContent = "重新创建工作区";
  } catch (error) {
    toast(error.message);
    button.textContent = "创建我的工作区";
  } finally {
    button.disabled = false;
  }
});

$("#toggle-token").addEventListener("click", () => {
  const input = $("#workspace-token");
  input.type = input.type === "password" ? "text" : "password";
  $("#toggle-token").textContent = input.type === "password" ? "显示令牌" : "隐藏令牌";
});

$$('[data-copy-target]').forEach((button) => button.addEventListener("click", async () => {
  const target = document.getElementById(button.dataset.copyTarget);
  const text = "value" in target ? target.value : target.textContent;
  await navigator.clipboard.writeText(text);
  toast("已复制到剪贴板");
}));

$$('[data-copy-text]').forEach((button) => button.addEventListener("click", async () => {
  await navigator.clipboard.writeText(button.dataset.copyText);
  toast("示例指令已复制");
}));

$$('[data-os]').forEach((tab) => tab.addEventListener("click", () => {
  $$('[data-os]').forEach((item) => {
    item.classList.toggle("active", item === tab);
    item.setAttribute("aria-selected", item === tab ? "true" : "false");
  });
  $$('[data-os-panel]').forEach((panel) => {
    const active = panel.dataset.osPanel === tab.dataset.os;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
}));

function paintKeyStatus(configured = {}) {
  $$('[data-key-status]').forEach((element) => {
    const active = Boolean(configured[element.dataset.keyStatus]);
    element.textContent = active ? "已配置 · 点击删除" : "未配置";
    element.classList.toggle("configured", active);
    element.dataset.configured = active ? "true" : "false";
  });
  const count = Object.values(configured).filter(Boolean).length;
  $("#vault-status").textContent = count ? `已连接 ${count} 个搜索平台` : (state.token ? "尚未配置搜索 Key" : "等待工作区令牌");
}

async function refreshKeyStatus() {
  if (!state.token) return paintKeyStatus();
  try {
    const payload = await api("/api/keys");
    paintKeyStatus(payload.configured);
  } catch (error) {
    localStorage.removeItem("patentradar_workspace_token");
    state.token = "";
    paintKeyStatus();
    toast("本机保存的工作区令牌已失效，请重新创建");
  }
}

$("#key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.token) return toast("请先创建工作区");
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const payload = Object.fromEntries([...form.entries()].filter(([, value]) => value.trim()));
  if (!Object.keys(payload).length) return toast("至少填写一个 Key");
  try {
    const result = await api("/api/keys", { method: "PUT", body: JSON.stringify(payload) });
    paintKeyStatus(result.configured);
    formElement.reset();
    $("#key-message").textContent = result.message;
    toast("搜索 Key 已加密保存");
  } catch (error) {
    $("#key-message").textContent = error.message;
  }
});

$$('[data-key-status]').forEach((element) => element.addEventListener("click", async () => {
  if (element.dataset.configured !== "true") return;
  const provider = element.dataset.keyStatus;
  if (!window.confirm(`确定删除 ${provider} Key？`)) return;
  try {
    const result = await api(`/api/keys?provider=${encodeURIComponent(provider)}`, { method: "DELETE" });
    paintKeyStatus(result.configured);
    toast(`${provider} Key 已删除`);
  } catch (error) {
    toast(error.message);
  }
}));

updateCommands();
refreshKeyStatus();
