const API = "/api";

const state = {
  characters: [],
  selectedCharacter: null,
  sessionId: null,
  draft: null,
  theme: localStorage.getItem("theme") || "light",
};

const $ = (id) => document.getElementById(id);

const els = {
  characterList: $("characterList"),
  newCharacterBtn: $("newCharacterBtn"),
  workspaceTitle: $("workspaceTitle"),
  settingsBtn: $("settingsBtn"),
  closeSettingsBtn: $("closeSettingsBtn"),
  settingsPanel: $("settingsPanel"),
  exportBtn: $("exportBtn"),
  themeBtn: $("themeBtn"),
  createPanel: $("createPanel"),
  draftPanel: $("draftPanel"),
  chatPanel: $("chatPanel"),
  creationPrompt: $("creationPrompt"),
  includeIllustration: $("includeIllustration"),
  generateBtn: $("generateBtn"),
  saveDraftBtn: $("saveDraftBtn"),
  draftName: $("draftName"),
  draftDescription: $("draftDescription"),
  draftSystemPrompt: $("draftSystemPrompt"),
  draftFirstMessage: $("draftFirstMessage"),
  draftLorebook: $("draftLorebook"),
  draftImagePrompt: $("draftImagePrompt"),
  chatCharacterName: $("chatCharacterName"),
  messageList: $("messageList"),
  chatInput: $("chatInput"),
  sendBtn: $("sendBtn"),
  backToCreateBtn: $("backToCreateBtn"),
  byokBaseUrl: $("byokBaseUrl"),
  byokModel: $("byokModel"),
  byokApiKey: $("byokApiKey"),
  saveSettingsBtn: $("saveSettingsBtn"),
  endpointProvider: $("endpointProvider"),
  endpointName: $("endpointName"),
  endpointBaseUrl: $("endpointBaseUrl"),
  endpointModel: $("endpointModel"),
  endpointApiKey: $("endpointApiKey"),
  addEndpointBtn: $("addEndpointBtn"),
  endpointList: $("endpointList"),
  toast: $("toast"),
};

function toast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.style.background = isError ? "#b42318" : "#191813";
  els.toast.classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => els.toast.classList.add("hidden"), 3800);
}

async function api(path, options = {}) {
  const resp = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const payload = await resp.json();
      if (payload.detail) detail = payload.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label || "处理中...";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function applyTheme() {
  document.body.classList.toggle("dark", state.theme === "dark");
  els.themeBtn.textContent = state.theme === "dark" ? "浅色" : "深色";
  localStorage.setItem("theme", state.theme);
}

function showCreate() {
  state.selectedCharacter = null;
  state.sessionId = null;
  els.workspaceTitle.textContent = "角色创作台";
  els.exportBtn.disabled = true;
  els.createPanel.classList.remove("hidden");
  els.draftPanel.classList.toggle("hidden", !state.draft);
  els.chatPanel.classList.add("hidden");
  renderCharacters();
}

function showChat() {
  els.createPanel.classList.add("hidden");
  els.draftPanel.classList.add("hidden");
  els.chatPanel.classList.remove("hidden");
  els.exportBtn.disabled = !state.selectedCharacter;
}

function renderCharacters() {
  els.characterList.innerHTML = "";
  if (!state.characters.length) {
    const empty = document.createElement("div");
    empty.className = "character-card";
    empty.innerHTML = "<strong>暂无角色</strong><small>先用一句话创建一个角色。</small>";
    els.characterList.appendChild(empty);
    return;
  }

  state.characters.forEach((character) => {
    const card = document.createElement("button");
    card.className = `character-card ${state.selectedCharacter?.character_id === character.character_id ? "active" : ""}`;
    card.innerHTML = `<strong>${escapeHtml(character.name)}</strong><small>${escapeHtml(character.description || "暂无简介").slice(0, 92)}</small>`;
    card.addEventListener("click", () => openCharacter(character.character_id));
    els.characterList.appendChild(card);
  });
}

function renderDraftFromGeneration(job, artifacts) {
  const artifactPayloads = artifacts.map((item) => item.payload || {});
  const characterPayload = artifactPayloads.find((item) => item.name || item.character_card || item.draft) || {};
  const lorePayload = artifactPayloads.find((item) => item.lorebook || item.entries || item.keyword) || {};
  const imagePayload = artifactPayloads.find((item) => item.prompt || item.illustration_prompt || item.image_prompt) || {};

  const draft = characterPayload.draft || characterPayload.character_card || characterPayload;
  state.draft = {
    name: draft.name || "未命名角色",
    description: draft.description || draft.profile || draft.personality || "",
    system_prompt: draft.system_prompt || draft.systemPrompt || draft.prompt || "",
    first_message: draft.first_message || draft.firstMessage || draft.opening || "",
    lorebook: lorePayload.lorebook || lorePayload.entries || lorePayload.insert_text || "",
    image_prompt: imagePayload.prompt || imagePayload.illustration_prompt || imagePayload.image_prompt || "",
  };
  fillDraft();
}

function fillDraft() {
  const draft = state.draft || {};
  els.draftName.value = draft.name || "";
  els.draftDescription.value = asText(draft.description);
  els.draftSystemPrompt.value = asText(draft.system_prompt);
  els.draftFirstMessage.value = asText(draft.first_message);
  els.draftLorebook.value = asText(draft.lorebook);
  els.draftImagePrompt.value = asText(draft.image_prompt);
  els.draftPanel.classList.remove("hidden");
}

function readDraft() {
  return {
    name: els.draftName.value.trim() || "未命名角色",
    description: els.draftDescription.value.trim(),
    system_prompt: els.draftSystemPrompt.value.trim(),
    first_message: els.draftFirstMessage.value.trim(),
    lorebook: els.draftLorebook.value.trim(),
    image_prompt: els.draftImagePrompt.value.trim(),
  };
}

async function loadCharacters() {
  state.characters = await api("/characters");
  renderCharacters();
}

async function loadSettings() {
  const settings = await api("/settings");
  els.byokBaseUrl.value = settings.byok_base_url || "";
  els.byokModel.value = settings.byok_model || "";
}

async function loadEndpoints() {
  const endpoints = await api("/model-endpoints?include_disabled=true");
  els.endpointList.innerHTML = "";
  if (!endpoints.length) {
    els.endpointList.innerHTML = '<div class="endpoint-item"><small>暂无任务模型端点。</small></div>';
    return;
  }
  endpoints.forEach((endpoint) => {
    const item = document.createElement("div");
    item.className = "endpoint-item";
    item.innerHTML = `<strong>${escapeHtml(endpoint.name)} · ${escapeHtml(endpoint.provider)}</strong><small>${escapeHtml(endpoint.model)}<br>${escapeHtml(endpoint.base_url)}</small>`;
    els.endpointList.appendChild(item);
  });
}

async function generateDraft() {
  const prompt = els.creationPrompt.value.trim();
  if (!prompt) {
    toast("请先输入角色需求。", true);
    return;
  }

  setBusy(els.generateBtn, true, "生成中...");
  try {
    try {
      const job = await api("/generation/jobs", {
        method: "POST",
        body: JSON.stringify({
          user_input: prompt,
          include_illustration_prompt: els.includeIllustration.checked,
          include_audio_plan: false,
          run_async: false,
        }),
      });
      const artifacts = await api(`/generation/jobs/${job.job_id}/artifacts`);
      renderDraftFromGeneration(job, artifacts);
      toast("已生成结构化草案。");
    } catch (err) {
      const result = await api("/wizard/generate-character", {
        method: "POST",
        body: JSON.stringify({ user_input: prompt }),
      });
      state.draft = {
        ...result.draft,
        lorebook: "",
        image_prompt: "",
      };
      fillDraft();
      toast(`已使用基础向导生成草案：${err.message}`);
    }
  } catch (err) {
    toast(`生成失败：${err.message}`, true);
  } finally {
    setBusy(els.generateBtn, false);
  }
}

async function saveDraft() {
  const draft = readDraft();
  setBusy(els.saveDraftBtn, true, "保存中...");
  try {
    const character = await api("/characters", {
      method: "POST",
      body: JSON.stringify({
        name: draft.name,
        description: draft.description,
        system_prompt: draft.system_prompt,
        first_message: draft.first_message,
        avatar_url: null,
      }),
    });

    if (draft.lorebook) {
      await api("/lorebooks", {
        method: "POST",
        body: JSON.stringify({
          character_id: character.character_id,
          keyword: draft.name,
          insert_text: draft.lorebook,
          sort_order: 100,
          enabled: true,
        }),
      });
    }

    state.draft = null;
    await loadCharacters();
    await openCharacter(character.character_id);
    toast("角色已保存。");
  } catch (err) {
    toast(`保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveDraftBtn, false);
  }
}

async function openCharacter(characterId) {
  const character = await api(`/characters/${characterId}`);
  state.selectedCharacter = character;
  renderCharacters();
  els.workspaceTitle.textContent = character.name;
  els.chatCharacterName.textContent = character.name;
  els.messageList.innerHTML = "";
  showChat();

  const started = await api(`/chat/start?character_id=${encodeURIComponent(characterId)}`, {
    method: "POST",
  });
  state.sessionId = started.session_id;
  addMessage("assistant", started.welcome_message);
}

function addMessage(role, content) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.innerHTML = `<div>${escapeHtml(content)}</div>`;
  if (role === "assistant" && state.sessionId) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const imageBtn = document.createElement("button");
    imageBtn.className = "mini";
    imageBtn.textContent = "生成图片提示";
    imageBtn.addEventListener("click", () => runAigcAction(content, "image_prompt"));
    const audioBtn = document.createElement("button");
    audioBtn.className = "mini";
    audioBtn.textContent = "生成音频方案";
    audioBtn.addEventListener("click", () => runAigcAction(content, "audio_plan"));
    actions.append(imageBtn, audioBtn);
    node.appendChild(actions);
  }
  els.messageList.appendChild(node);
  els.messageList.scrollTop = els.messageList.scrollHeight;
}

async function sendMessage() {
  const message = els.chatInput.value.trim();
  if (!message || !state.sessionId) return;
  els.chatInput.value = "";
  addMessage("user", message);
  setBusy(els.sendBtn, true, "等待...");
  try {
    const reply = await api("/chat/message", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId, message }),
    });
    addMessage("assistant", reply.reply);
  } catch (err) {
    addMessage("assistant", `请求失败：${err.message}`);
  } finally {
    setBusy(els.sendBtn, false);
  }
}

async function runAigcAction(text, actionType) {
  if (!state.sessionId) return;
  try {
    const result = await api("/chat/actions", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        action_type: actionType,
        selected_text: text.slice(0, 4000),
      }),
    });
    const payload = JSON.stringify(result.result, null, 2);
    addMessage("assistant", `段落级 AIGC 结果：\n${payload}`);
  } catch (err) {
    toast(`段落级 AIGC 失败：${err.message}`, true);
  }
}

async function saveSettings() {
  setBusy(els.saveSettingsBtn, true, "保存中...");
  try {
    await api("/settings", {
      method: "PUT",
      body: JSON.stringify({
        mode: "byok",
        byok_base_url: els.byokBaseUrl.value.trim(),
        byok_model: els.byokModel.value.trim(),
        byok_api_key: els.byokApiKey.value.trim() || null,
      }),
    });
    els.byokApiKey.value = "";
    toast("BYOK 设置已保存。");
  } catch (err) {
    toast(`保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveSettingsBtn, false);
  }
}

async function addEndpoint() {
  setBusy(els.addEndpointBtn, true, "新增中...");
  try {
    await api("/model-endpoints", {
      method: "POST",
      body: JSON.stringify({
        provider: els.endpointProvider.value.trim(),
        name: els.endpointName.value.trim(),
        base_url: els.endpointBaseUrl.value.trim(),
        model: els.endpointModel.value.trim(),
        api_key: els.endpointApiKey.value.trim() || null,
        enabled: true,
        priority: 100,
        is_fallback: false,
      }),
    });
    els.endpointApiKey.value = "";
    await loadEndpoints();
    toast("任务模型端点已新增。");
  } catch (err) {
    toast(`新增失败：${err.message}`, true);
  } finally {
    setBusy(els.addEndpointBtn, false);
  }
}

function exportCharacter() {
  if (!state.selectedCharacter) return;
  window.open(`/api/characters/${state.selectedCharacter.character_id}/export`, "_blank");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function asText(value) {
  if (Array.isArray(value)) return value.map(asText).join("\n\n");
  if (value && typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value ?? "");
}

function bindEvents() {
  els.newCharacterBtn.addEventListener("click", showCreate);
  els.generateBtn.addEventListener("click", generateDraft);
  els.saveDraftBtn.addEventListener("click", saveDraft);
  els.sendBtn.addEventListener("click", sendMessage);
  els.exportBtn.addEventListener("click", exportCharacter);
  els.backToCreateBtn.addEventListener("click", showCreate);
  els.settingsBtn.addEventListener("click", () => els.settingsPanel.classList.add("open"));
  els.closeSettingsBtn.addEventListener("click", () => els.settingsPanel.classList.remove("open"));
  els.saveSettingsBtn.addEventListener("click", saveSettings);
  els.addEndpointBtn.addEventListener("click", addEndpoint);
  els.themeBtn.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
  });
  els.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) sendMessage();
  });
}

async function boot() {
  applyTheme();
  bindEvents();
  try {
    await Promise.all([loadCharacters(), loadSettings(), loadEndpoints()]);
  } catch (err) {
    toast(`初始化失败：${err.message}`, true);
  }
}

boot();
