window.__AI_CHAT_TRIAL_APP_LOADED__ = true;

const API = window.location.protocol === "file:"
  ? "http://127.0.0.1:8000/api"
  : "/api";

const SUPPORTED_PROVIDERS = {
  deepseek: { label: "DeepSeek", defaultBaseUrl: "https://api.deepseek.com/v1", defaultModel: "deepseek-chat" },
  qwen: { label: "Qwen", defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", defaultModel: "qwen-plus" },
  kimi: { label: "Kimi", defaultBaseUrl: "https://api.moonshot.cn/v1", defaultModel: "moonshot-v1-8k" },
  openai: { label: "OpenAI", defaultBaseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini" },
  openai_compatible: { label: "OpenAI Compatible", defaultBaseUrl: "", defaultModel: "" },
};

const TASK_BINDING_FIELDS = [
  ["intent_parse", "bindIntentParse"],
  ["plan_dispatch", "bindPlanDispatch"],
  ["character_card_generate", "bindCharacterCard"],
  ["lorebook_generate", "bindLorebook"],
  ["story_blueprint_generate", "bindStoryBlueprint"],
  ["story_lorebook_generate", "bindStoryLorebook"],
  ["illustration_prompt_generate", "bindIllustration"],
  ["audio_plan_generate", "bindAudio"],
  ["story_continuity_review", "bindStoryContinuity"],
  ["result_review", "bindReview"],
  ["story_continue", "bindStoryContinue"],
];

const state = {
  characters: [],
  stories: [],
  endpoints: [],
  settings: null,
  selectedCharacter: null,
  selectedStory: null,
  sessionId: null,
  storySessionId: null,
  storySession: null,
  storyLorebooks: [],
  storyActions: [],
  storyDraft: null,
  taskEndpointBindings: {},
  draft: null,
  theme: localStorage.getItem("theme") || "light",
  activeMode: "roleplay",
  editingCharacterId: null,
  editingEndpointId: null,
  editingStoryLorebookId: null,
};

const $ = (id) => document.getElementById(id);

const els = {
  characterList: $("characterList"),
  storyList: $("storyList"),
  newCharacterBtn: $("newCharacterBtn"),
  newStoryBtn: $("newStoryBtn"),
  modeRoleplayBtn: $("modeRoleplayBtn"),
  modeStoryBtn: $("modeStoryBtn"),
  workspaceTitle: $("workspaceTitle"),
  workspaceEyeline: $("workspaceEyeline"),
  settingsBtn: $("settingsBtn"),
  closeSettingsBtn: $("closeSettingsBtn"),
  settingsPanel: $("settingsPanel"),
  exportBtn: $("exportBtn"),
  themeBtn: $("themeBtn"),
  createPanel: $("createPanel"),
  storyCreatePanel: $("storyCreatePanel"),
  storyDraftPrompt: $("storyDraftPrompt"),
  storyDraftIncludeIllustration: $("storyDraftIncludeIllustration"),
  storyDraftIncludeAudio: $("storyDraftIncludeAudio"),
  storyGenerateBtn: $("storyGenerateBtn"),
  storyDraftPanel: $("storyDraftPanel"),
  applyStoryNewBtn: $("applyStoryNewBtn"),
  applyStoryCurrentBtn: $("applyStoryCurrentBtn"),
  storyDraftReviewStatus: $("storyDraftReviewStatus"),
  storyDraftTitle: $("storyDraftTitle"),
  storyDraftTone: $("storyDraftTone"),
  storyDraftPremise: $("storyDraftPremise"),
  storyDraftOpeningScene: $("storyDraftOpeningScene"),
  storyDraftSystemPrompt: $("storyDraftSystemPrompt"),
  storyDraftProtagonistProfile: $("storyDraftProtagonistProfile"),
  storyDraftChapterEntries: $("storyDraftChapterEntries"),
  addStoryDraftChapterBtn: $("addStoryDraftChapterBtn"),
  storyDraftLorebookEntries: $("storyDraftLorebookEntries"),
  addStoryDraftLorebookEntryBtn: $("addStoryDraftLorebookEntryBtn"),
  storyDraftIllustrationPrompt: $("storyDraftIllustrationPrompt"),
  storyDraftAudioPlan: $("storyDraftAudioPlan"),
  storyDraftContinuitySummary: $("storyDraftContinuitySummary"),
  storyDraftContinuityMissing: $("storyDraftContinuityMissing"),
  storyDraftContinuityRisks: $("storyDraftContinuityRisks"),
  draftPanel: $("draftPanel"),
  chatPanel: $("chatPanel"),
  storyPanel: $("storyPanel"),
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
  editCharacterBtn: $("editCharacterBtn"),
  deleteCharacterBtn: $("deleteCharacterBtn"),
  backToCreateBtn: $("backToCreateBtn"),
  storyTitle: $("storyTitle"),
  storyPremise: $("storyPremise"),
  storyOpeningScene: $("storyOpeningScene"),
  storySystemPrompt: $("storySystemPrompt"),
  createStoryBtn: $("createStoryBtn"),
  storyLorebookKeyword: $("storyLorebookKeyword"),
  storyLorebookSortOrder: $("storyLorebookSortOrder"),
  storyLorebookInsertText: $("storyLorebookInsertText"),
  saveStoryLorebookBtn: $("saveStoryLorebookBtn"),
  storyLorebookList: $("storyLorebookList"),
  storyProjectName: $("storyProjectName"),
  storySummary: $("storySummary"),
  storyFacts: $("storyFacts"),
  storyCheckpoints: $("storyCheckpoints"),
  storyMessageList: $("storyMessageList"),
  storyActionHistory: $("storyActionHistory"),
  storyInput: $("storyInput"),
  storySendBtn: $("storySendBtn"),
  editStoryBtn: $("editStoryBtn"),
  deleteStoryBtn: $("deleteStoryBtn"),
  backToStoryCreateBtn: $("backToStoryCreateBtn"),
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
  cancelEndpointEditBtn: $("cancelEndpointEditBtn"),
  endpointList: $("endpointList"),
  bindIntentParse: $("bindIntentParse"),
  bindPlanDispatch: $("bindPlanDispatch"),
  bindCharacterCard: $("bindCharacterCard"),
  bindLorebook: $("bindLorebook"),
  bindStoryBlueprint: $("bindStoryBlueprint"),
  bindStoryLorebook: $("bindStoryLorebook"),
  bindIllustration: $("bindIllustration"),
  bindAudio: $("bindAudio"),
  bindStoryContinuity: $("bindStoryContinuity"),
  bindReview: $("bindReview"),
  bindStoryContinue: $("bindStoryContinue"),
  saveBindingsBtn: $("saveBindingsBtn"),
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
      if (payload.detail) detail = formatApiDetail(payload.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function formatApiDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        const path = Array.isArray(item.loc) ? item.loc.join(".") : "";
        return [path, item.msg].filter(Boolean).join(": ");
      })
      .filter(Boolean)
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail ?? "请求失败");
}

function assertGenerationJobSucceeded(job, label) {
  if (!job || job.status !== "completed") {
    throw new Error(job?.error_message || `${label}未成功完成。`);
  }
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

function switchMode(mode) {
  state.activeMode = mode;
  els.modeRoleplayBtn.className = mode === "roleplay" ? "primary full" : "ghost full";
  els.modeStoryBtn.className = mode === "story" ? "primary full" : "ghost full";
  els.newCharacterBtn.classList.toggle("hidden", mode !== "roleplay");
  els.newStoryBtn.classList.toggle("hidden", mode !== "story");
  if (mode === "roleplay") {
    showCreate();
  } else {
    showStoryCreate();
  }
}

function hideAllPanels() {
  [els.createPanel, els.storyCreatePanel, els.draftPanel, els.chatPanel, els.storyPanel].forEach((el) => el.classList.add("hidden"));
}

function showCreate() {
  hideAllPanels();
  state.selectedCharacter = null;
  state.sessionId = null;
  state.editingCharacterId = null;
  els.workspaceEyeline.textContent = "本地运行 / 手动配置模型";
  els.workspaceTitle.textContent = "角色创作台";
  els.saveDraftBtn.textContent = "保存到角色列表";
  els.createPanel.classList.remove("hidden");
  if (state.draft) els.draftPanel.classList.remove("hidden");
  els.exportBtn.disabled = true;
  renderCharacters();
}

function showStoryCreate({ preserveSelection = false } = {}) {
  hideAllPanels();
  if (!preserveSelection) {
    state.selectedStory = null;
    state.storySessionId = null;
    state.storySession = null;
    state.storyLorebooks = [];
    state.storyActions = [];
    resetStoryLorebookForm();
  }
  els.workspaceEyeline.textContent = "互动小说 / 自由输入续写";
  els.workspaceTitle.textContent = "故事创作台";
  els.storyCreatePanel.classList.remove("hidden");
  els.exportBtn.disabled = true;
  if (state.selectedStory) {
    els.storyTitle.value = state.selectedStory.title || "";
    els.storyPremise.value = state.selectedStory.premise || "";
    els.storyOpeningScene.value = state.selectedStory.opening_scene || "";
    els.storySystemPrompt.value = state.selectedStory.system_prompt || "";
    els.createStoryBtn.textContent = "保存故事修改";
  } else {
    els.storyTitle.value = "";
    els.storyPremise.value = "";
    els.storyOpeningScene.value = "";
    els.storySystemPrompt.value = "";
    els.createStoryBtn.textContent = "创建故事";
  }
  renderStoryLorebooks();
  renderStories();
  fillStoryDraft();
}

function showChat() {
  hideAllPanels();
  els.chatPanel.classList.remove("hidden");
  els.exportBtn.disabled = !state.selectedCharacter;
}

function showStoryPanel() {
  hideAllPanels();
  els.storyPanel.classList.remove("hidden");
  els.exportBtn.disabled = true;
}

function renderCharacters() {
  els.characterList.innerHTML = "";
  if (!state.characters.length) {
    const empty = document.createElement("div");
    empty.className = "character-card";
    empty.innerHTML = "<strong>暂无角色</strong><small>先在角色创作台创建一个角色。</small>";
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

function renderStories() {
  els.storyList.innerHTML = "";
  if (!state.stories.length) {
    const empty = document.createElement("div");
    empty.className = "character-card";
    empty.innerHTML = "<strong>暂无故事</strong><small>先在故事创作台创建一个故事项目。</small>";
    els.storyList.appendChild(empty);
    return;
  }
  state.stories.forEach((story) => {
    const card = document.createElement("button");
    card.className = `character-card ${state.selectedStory?.project_id === story.project_id ? "active" : ""}`;
    card.innerHTML = `<strong>${escapeHtml(story.title)}</strong><small>${escapeHtml(story.premise || "暂无故事前提").slice(0, 120)}</small>`;
    card.addEventListener("click", () => openStoryProject(story.project_id));
    els.storyList.appendChild(card);
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

function readStoryForm() {
  return {
    title: els.storyTitle.value.trim(),
    premise: els.storyPremise.value.trim(),
    opening_scene: els.storyOpeningScene.value.trim(),
    system_prompt: els.storySystemPrompt.value.trim(),
  };
}

function readStoryDraftRequest() {
  return {
    user_input: els.storyDraftPrompt.value.trim(),
    pipeline_type: "story_project",
    include_illustration_prompt: els.storyDraftIncludeIllustration.checked,
    include_audio_plan: els.storyDraftIncludeAudio.checked,
  };
}

function readEditedStoryDraftPayload() {
  const chapters = readStoryDraftChapterEntries();
  const lorebookEntries = readStoryDraftLorebookEntries();
  const audioText = els.storyDraftAudioPlan.value.trim();
  let audioPlan = {};
  if (audioText) {
    try {
      const parsed = JSON.parse(audioText);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) audioPlan = parsed;
    } catch (_) {
      audioPlan = {
    voice_style: "narrative",
    tone: els.storyDraftTone.value.trim() || "已编辑草案",
        sample_line: audioText.slice(0, 500),
      };
    }
  }
  return {
    story_blueprint: {
      title: els.storyDraftTitle.value.trim(),
      premise: els.storyDraftPremise.value.trim(),
      opening_scene: els.storyDraftOpeningScene.value.trim(),
      system_prompt: els.storyDraftSystemPrompt.value.trim(),
      chapters_outline: chapters,
      tone: els.storyDraftTone.value.trim(),
      protagonist_profile: els.storyDraftProtagonistProfile.value.trim(),
    },
    story_lorebook: { entries: lorebookEntries },
    illustration_prompt: els.storyDraftIllustrationPrompt.value.trim()
      ? { prompt: els.storyDraftIllustrationPrompt.value.trim() }
      : {},
    audio_plan: audioPlan,
  };
}

function readStoryDraftChapterEntries() {
  return Array.from(els.storyDraftChapterEntries.querySelectorAll(".story-draft-chapter-entry"))
    .map((row) => row.querySelector(".story-draft-chapter-text")?.value.trim() || "")
    .filter(Boolean);
}

function renderStoryDraftChapterEntries(chapters) {
  els.storyDraftChapterEntries.innerHTML = "";
  const normalized = Array.isArray(chapters) ? chapters.map((item) => String(item).trim()).filter(Boolean) : [];
  if (!normalized.length) {
    addStoryDraftChapterEntry();
    return;
  }
  normalized.forEach((chapter) => addStoryDraftChapterEntry(chapter));
}

function addStoryDraftChapterEntry(chapter = "") {
  const row = document.createElement("div");
  row.className = "story-draft-chapter-entry";
  row.innerHTML = `
    <div class="story-draft-chapter-toolbar">
      <strong class="story-draft-chapter-index"></strong>
      <div class="endpoint-actions">
        <button class="mini" data-action="up" type="button">上移</button>
        <button class="mini" data-action="down" type="button">下移</button>
        <button class="mini danger" data-action="delete" type="button">删除</button>
      </div>
    </div>
    <textarea class="story-draft-chapter-text">${escapeHtml(chapter)}</textarea>
  `;
  row.querySelector("[data-action='up']").addEventListener("click", () => {
    const prev = row.previousElementSibling;
    if (prev) els.storyDraftChapterEntries.insertBefore(row, prev);
    refreshStoryDraftChapterIndexes();
    renderStoryDraftContinuityReview();
  });
  row.querySelector("[data-action='down']").addEventListener("click", () => {
    const next = row.nextElementSibling;
    if (next) els.storyDraftChapterEntries.insertBefore(next, row);
    refreshStoryDraftChapterIndexes();
    renderStoryDraftContinuityReview();
  });
  row.querySelector("[data-action='delete']").addEventListener("click", () => {
    row.remove();
    if (!els.storyDraftChapterEntries.children.length) addStoryDraftChapterEntry();
    refreshStoryDraftChapterIndexes();
    renderStoryDraftContinuityReview();
  });
  row.querySelector(".story-draft-chapter-text").addEventListener("input", () => renderStoryDraftContinuityReview());
  els.storyDraftChapterEntries.appendChild(row);
  refreshStoryDraftChapterIndexes();
  renderStoryDraftContinuityReview();
}

function refreshStoryDraftChapterIndexes() {
  Array.from(els.storyDraftChapterEntries.querySelectorAll(".story-draft-chapter-entry")).forEach((row, index) => {
    const label = row.querySelector(".story-draft-chapter-index");
    if (label) label.textContent = `第 ${index + 1} 章`;
  });
}

function normalizeIssueList(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const normalized = [];
  value.forEach((item) => {
    const text = String(item ?? "").trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    normalized.push(text);
  });
  return normalized;
}

function getStoryDraftContinuityState(storyDraftPayload = null) {
  const draft = state.storyDraft || {};
  const continuity = draft.continuity || {};
  const payload = storyDraftPayload || readEditedStoryDraftPayload();
  const blueprint = payload.story_blueprint || {};
  const lorebook = payload.story_lorebook || {};
  const blockers = normalizeIssueList(continuity.missing);
  const warnings = normalizeIssueList(continuity.risks);

  if (continuity.accepted === false && !blockers.length) {
    blockers.push("连续性检查未通过");
  }
  if (!String(blueprint.title || "").trim()) blockers.push("缺少故事标题");
  if (!String(blueprint.premise || "").trim()) blockers.push("缺少故事前提");
  if (!String(blueprint.opening_scene || "").trim()) blockers.push("缺少开场场景");
  if (!Array.isArray(blueprint.chapters_outline) || blueprint.chapters_outline.length < 3) {
    blockers.push("章节大纲至少需要 3 条");
  }
  if (!Array.isArray(lorebook.entries) || !lorebook.entries.length) {
    blockers.push("至少需要 1 条有效故事世界书条目");
  }

  const uniqueBlockers = normalizeIssueList(blockers);
  return {
    accepted: uniqueBlockers.length === 0,
    blockers: uniqueBlockers,
    warnings,
  };
}

function renderStoryDraftContinuityReview(storyDraftPayload = null) {
  if (!state.storyDraft) {
    els.storyDraftContinuitySummary.innerHTML = "";
    els.storyDraftReviewStatus.value = "";
    els.storyDraftContinuityMissing.value = "";
    els.storyDraftContinuityRisks.value = "";
    return null;
  }
  const review = getStoryDraftContinuityState(storyDraftPayload);
  const status = review.blockers.length
    ? `阻塞（${review.blockers.length} 项）`
    : review.warnings.length
      ? `可应用，有提醒（${review.warnings.length} 项）`
      : "可应用";
  els.storyDraftReviewStatus.value = status;
  els.storyDraftContinuityMissing.value = review.blockers.join("\n");
  els.storyDraftContinuityRisks.value = review.warnings.join("\n");
  els.storyDraftContinuitySummary.className = `wide continuity-card ${
    review.blockers.length ? "blocked" : review.warnings.length ? "warning" : "accepted"
  }`;
  const title = review.blockers.length
    ? "暂不能应用"
    : review.warnings.length
      ? "可应用，但建议先检查"
      : "可以应用";
  const detail = review.blockers.length
    ? "请先修复阻塞问题，再应用这个故事草案。"
    : review.warnings.length
      ? "当前草案可应用，但建议先查看提醒事项。"
      : "当前草案已通过本地应用检查。";
  els.storyDraftContinuitySummary.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <small>${escapeHtml(detail)}</small>
  `;
  return review;
}

function readStoryDraftLorebookEntries({ includeDisabled = false } = {}) {
  return Array.from(els.storyDraftLorebookEntries.querySelectorAll(".story-draft-lorebook-entry"))
    .map((row, index) => {
      const enabled = row.querySelector(".story-draft-lorebook-enabled")?.checked ?? true;
      if (!enabled && !includeDisabled) return null;
      const keyword = row.querySelector(".story-draft-lorebook-keyword")?.value.trim() || "";
      const insertText = row.querySelector(".story-draft-lorebook-insert")?.value.trim() || "";
      const sortRaw = row.querySelector(".story-draft-lorebook-sort")?.value || "";
      const sortOrder = Number.parseInt(sortRaw, 10);
      if (!keyword || !insertText) return null;
      return {
        keyword,
        insert_text: insertText,
        sort_order: Number.isFinite(sortOrder) ? sortOrder : 100 + index * 10,
      };
    })
    .filter(Boolean);
}

function renderStoryDraftLorebookEntries(entries) {
  els.storyDraftLorebookEntries.innerHTML = "";
  if (!entries.length) {
    addStoryDraftLorebookEntry();
    return;
  }
  entries.forEach((entry) => addStoryDraftLorebookEntry(entry));
}

function addStoryDraftLorebookEntry(entry = {}) {
  const row = document.createElement("div");
  row.className = "story-draft-lorebook-entry";
  row.innerHTML = `
    <div class="story-draft-lorebook-toolbar">
      <label class="inline-check">
        <input class="story-draft-lorebook-enabled" type="checkbox" ${entry.enabled === false ? "" : "checked"}>
        应用
      </label>
      <button class="mini danger" type="button">删除</button>
    </div>
    <div class="story-draft-lorebook-grid">
      <label>关键词<input class="story-draft-lorebook-keyword" type="text" value="${escapeHtml(entry.keyword || "")}"></label>
      <label>排序值<input class="story-draft-lorebook-sort" type="number" value="${escapeHtml(entry.sort_order ?? 100)}" min="0" max="10000"></label>
      <label class="wide">插入文本<textarea class="story-draft-lorebook-insert">${escapeHtml(entry.insert_text || "")}</textarea></label>
    </div>
  `;
  row.querySelector(".mini.danger").addEventListener("click", () => {
    row.remove();
    if (!els.storyDraftLorebookEntries.children.length) addStoryDraftLorebookEntry();
    renderStoryDraftContinuityReview();
  });
  row.addEventListener("input", () => renderStoryDraftContinuityReview());
  row.addEventListener("change", () => renderStoryDraftContinuityReview());
  els.storyDraftLorebookEntries.appendChild(row);
  renderStoryDraftContinuityReview();
}

function readStoryLorebookForm() {
  return {
    keyword: els.storyLorebookKeyword.value.trim(),
    sort_order: Number.parseInt(els.storyLorebookSortOrder.value || "100", 10) || 100,
    insert_text: els.storyLorebookInsertText.value.trim(),
    enabled: true,
  };
}

function renderStoryDraftFromGeneration(_job, artifacts) {
  const byType = Object.fromEntries(artifacts.map((item) => [item.artifact_type, item.payload || {}]));
  const blueprint = byType.story_blueprint || {};
  const lorebook = byType.story_lorebook || {};
  const continuity = byType.story_continuity_review || {};
  const illustration = byType.illustration_prompt || {};
  const audio = byType.audio_plan || {};
  const bundle = byType.story_bundle || {};
  state.storyDraft = {
    prompt: els.storyDraftPrompt.value.trim(),
    blueprint,
    lorebook,
    continuity,
    illustration,
    audio,
    bundle,
  };
  fillStoryDraft();
}

function fillStoryDraft() {
  const draft = state.storyDraft;
  if (!draft) {
    els.storyDraftPanel.classList.add("hidden");
    renderStoryDraftContinuityReview();
    return;
  }
  const blueprint = draft.blueprint || {};
  const lorebookEntries = Array.isArray(draft.lorebook?.entries) ? draft.lorebook.entries : [];
  els.storyDraftTitle.value = blueprint.title || "";
  els.storyDraftTone.value = blueprint.tone || "";
  els.storyDraftPremise.value = asText(blueprint.premise);
  els.storyDraftOpeningScene.value = asText(blueprint.opening_scene);
  els.storyDraftSystemPrompt.value = asText(blueprint.system_prompt);
  els.storyDraftProtagonistProfile.value = asText(blueprint.protagonist_profile);
  renderStoryDraftChapterEntries(blueprint.chapters_outline || []);
  renderStoryDraftLorebookEntries(lorebookEntries);
  els.storyDraftIllustrationPrompt.value = asText(draft.illustration?.prompt || "");
  els.storyDraftAudioPlan.value = asText(draft.audio);
  els.applyStoryCurrentBtn.disabled = !state.selectedStory;
  renderStoryDraftContinuityReview();
  els.storyDraftPanel.classList.remove("hidden");
}

async function loadCharacters() {
  state.characters = await api("/characters");
  renderCharacters();
}

async function loadStories() {
  state.stories = await api("/story/projects");
  renderStories();
}

async function loadSettings() {
  const settings = await api("/settings");
  state.settings = settings;
  state.taskEndpointBindings = { ...(settings.task_endpoint_bindings || {}) };
  els.byokBaseUrl.value = settings.byok_base_url || "";
  els.byokModel.value = settings.byok_model || "";
  renderTaskBindingSelects();
}

async function loadEndpoints() {
  state.endpoints = await api("/model-endpoints?include_disabled=true");
  renderEndpoints();
  renderTaskBindingSelects();
}

function renderEndpoints() {
  els.endpointList.innerHTML = "";
  if (!state.endpoints.length) {
    els.endpointList.innerHTML = '<div class="endpoint-item"><small>暂无任务端点，请先新增一个。</small></div>';
    return;
  }
  state.endpoints.forEach((endpoint) => {
    const item = document.createElement("div");
    item.className = "endpoint-item";
    item.innerHTML = `
      <div class="endpoint-row">
        <div>
          <strong>${escapeHtml(endpoint.name)} · ${escapeHtml(endpoint.provider)}</strong>
          <small>${escapeHtml(endpoint.model)}<br>${escapeHtml(endpoint.base_url)}<br>${endpoint.enabled ? "已启用" : "已停用"} · ${endpoint.has_api_key ? "已保存 API Key" : "未保存 API Key"}</small>
        </div>
        <div class="endpoint-actions">
          <button class="mini" data-action="edit" data-id="${endpoint.endpoint_id}">编辑</button>
          <button class="mini danger" data-action="delete" data-id="${endpoint.endpoint_id}">删除</button>
        </div>
      </div>
    `;
    els.endpointList.appendChild(item);
  });
  els.endpointList.querySelectorAll("button[data-action='edit']").forEach((button) => {
    button.addEventListener("click", () => beginEndpointEdit(button.dataset.id));
  });
  els.endpointList.querySelectorAll("button[data-action='delete']").forEach((button) => {
    button.addEventListener("click", () => deleteEndpoint(button.dataset.id));
  });
}

function renderTaskBindingSelects() {
  TASK_BINDING_FIELDS.forEach(([taskType, selectId]) => {
    const select = els[selectId];
    if (!select) return;
    const current = state.taskEndpointBindings?.[taskType] || "";
    select.innerHTML = "";
    select.appendChild(new Option("自动选择", ""));
    state.endpoints.filter((endpoint) => endpoint.enabled).forEach((endpoint) => {
      select.appendChild(new Option(`${endpoint.name} · ${endpoint.provider} · ${endpoint.model}`, endpoint.endpoint_id));
    });
    select.value = current;
  });
}

function applyProviderDefaults({ overwrite = false } = {}) {
  const provider = els.endpointProvider.value;
  const config = SUPPORTED_PROVIDERS[provider];
  if (!config) return;
  if (overwrite || !els.endpointBaseUrl.value.trim()) els.endpointBaseUrl.value = config.defaultBaseUrl;
  if (overwrite || !els.endpointModel.value.trim()) els.endpointModel.value = config.defaultModel;
  if (!els.endpointName.value.trim()) els.endpointName.value = `${provider}-task`;
}

function readEndpointForm() {
  return {
    provider: els.endpointProvider.value.trim(),
    name: els.endpointName.value.trim(),
    base_url: els.endpointBaseUrl.value.trim(),
    model: els.endpointModel.value.trim(),
    api_key: els.endpointApiKey.value.trim() || null,
    enabled: true,
    priority: 100,
    is_fallback: false,
  };
}

function validateEndpointForm(payload) {
  if (!SUPPORTED_PROVIDERS[payload.provider]) return "模型供应商无效。";
  if (!payload.name) return "端点名称不能为空。";
  if (!payload.base_url) return "Base URL 不能为空。";
  if (!payload.model) return "模型名称不能为空。";
  return "";
}

function readTaskBindings() {
  const bindings = {};
  TASK_BINDING_FIELDS.forEach(([taskType, selectId]) => {
    bindings[taskType] = els[selectId]?.value || null;
  });
  return bindings;
}

function resetEndpointForm() {
  state.editingEndpointId = null;
  els.addEndpointBtn.textContent = "新增端点";
  els.cancelEndpointEditBtn.classList.add("hidden");
  els.endpointApiKey.value = "";
  els.endpointProvider.value = "deepseek";
  els.endpointName.value = "";
  els.endpointBaseUrl.value = "";
  els.endpointModel.value = "";
  applyProviderDefaults({ overwrite: true });
}

function beginEndpointEdit(endpointId) {
  const endpoint = state.endpoints.find((item) => item.endpoint_id === endpointId);
  if (!endpoint) return;
  state.editingEndpointId = endpointId;
  els.endpointProvider.value = endpoint.provider;
  els.endpointName.value = endpoint.name;
  els.endpointBaseUrl.value = endpoint.base_url;
  els.endpointModel.value = endpoint.model;
  els.endpointApiKey.value = "";
  els.addEndpointBtn.textContent = "保存端点";
  els.cancelEndpointEditBtn.classList.remove("hidden");
}

async function generateDraft() {
  const prompt = els.creationPrompt.value.trim();
  if (!prompt) {
    toast("请先输入角色创建需求。", true);
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
      assertGenerationJobSucceeded(job, "角色草案生成");
      const artifacts = await api(`/generation/jobs/${job.job_id}/artifacts`);
      renderDraftFromGeneration(job, artifacts);
      toast("已生成结构化角色草案。");
    } catch (err) {
      const result = await api("/wizard/generate-character", {
        method: "POST",
        body: JSON.stringify({ user_input: prompt }),
      });
      state.draft = { ...result.draft, lorebook: "", image_prompt: "" };
      fillDraft();
      toast(`已使用基础向导生成草案：${err.message}`);
    }
  } catch (err) {
    toast(`草案生成失败：${err.message}`, true);
  } finally {
    setBusy(els.generateBtn, false);
  }
}

async function saveDraft() {
  const draft = readDraft();
  const wasEditing = Boolean(state.editingCharacterId);
  setBusy(els.saveDraftBtn, true, "保存中...");
  try {
    const characterPayload = {
      name: draft.name,
      description: draft.description,
      system_prompt: draft.system_prompt,
      first_message: draft.first_message,
      avatar_url: null,
    };
    const character = state.editingCharacterId
      ? await api(`/characters/${state.editingCharacterId}`, {
          method: "PUT",
          body: JSON.stringify(characterPayload),
        })
      : await api("/characters", {
          method: "POST",
          body: JSON.stringify(characterPayload),
        });
    if (!wasEditing && draft.lorebook) {
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
    state.editingCharacterId = null;
    els.saveDraftBtn.textContent = "保存到角色列表";
    await loadCharacters();
    await openCharacter(character.character_id);
    toast(wasEditing ? "角色已更新。" : "角色已保存。");
  } catch (err) {
    toast(`保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveDraftBtn, false);
  }
}

async function generateStoryDraft() {
  const payload = readStoryDraftRequest();
  if (!payload.user_input) {
    toast("请先输入故事创建需求。", true);
    return;
  }
  setBusy(els.storyGenerateBtn, true, "生成中...");
  try {
    const job = await api("/generation/jobs", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        apply_mode: "draft_only",
        run_async: false,
      }),
    });
    assertGenerationJobSucceeded(job, "故事草案生成");
    const artifacts = await api(`/generation/jobs/${job.job_id}/artifacts`);
    renderStoryDraftFromGeneration(job, artifacts);
    toast("已生成故事草案。");
  } catch (err) {
    toast(`故事草案生成失败：${err.message}`, true);
  } finally {
    setBusy(els.storyGenerateBtn, false);
  }
}

async function applyStoryDraft(mode) {
  const payload = readStoryDraftRequest();
  if (!payload.user_input) {
    toast("请先输入故事创建需求。", true);
    return;
  }
  if (!state.storyDraft) {
    toast("请先生成故事草案，再应用。", true);
    return;
  }
  if (mode === "current" && !state.selectedStory) {
    toast("请先选择一个故事项目。", true);
    return;
  }
  const storyDraftPayload = readEditedStoryDraftPayload();
  const review = renderStoryDraftContinuityReview(storyDraftPayload);
  if (review?.blockers.length) {
    toast(`故事草案存在阻塞问题：${review.blockers.slice(0, 3).join("；")}`, true);
    return;
  }
  if (review?.warnings.length) {
    const confirmed = window.confirm(
      `这个故事草案有 ${review.warnings.length} 条提醒：\n\n${review.warnings.slice(0, 5).join("\n")}\n\n仍然应用吗？`
    );
    if (!confirmed) return;
  }
  const button = mode === "current" ? els.applyStoryCurrentBtn : els.applyStoryNewBtn;
  setBusy(button, true, "应用中...");
  try {
    const job = await api("/generation/jobs", {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        apply_mode: "direct_apply",
        story_project_id: mode === "current" ? state.selectedStory?.project_id || null : null,
        story_draft_payload: storyDraftPayload,
        run_async: false,
      }),
    });
    assertGenerationJobSucceeded(job, "故事应用");
    const artifacts = await api(`/generation/jobs/${job.job_id}/artifacts`);
    renderStoryDraftFromGeneration(job, artifacts);
    const bundle = artifacts.find((item) => item.artifact_type === "story_bundle")?.payload || {};
    const projectId = bundle.apply_result?.project_id;
    if (!projectId) {
      throw new Error(job.error_message || "故事应用未返回 project_id。");
    }
    await loadStories();
    await openStoryProject(projectId);
    toast(mode === "current" ? "已覆盖当前故事。" : "已应用为新故事。");
  } catch (err) {
    toast(`故事应用失败：${err.message}`, true);
  } finally {
    setBusy(button, false);
  }
}

async function createStoryProject() {
  const payload = readStoryForm();
  if (!payload.title || !payload.premise) {
    toast("故事标题和故事前提不能为空。", true);
    return;
  }
  const isUpdating = Boolean(state.selectedStory?.project_id);
  setBusy(els.createStoryBtn, true, isUpdating ? "保存中..." : "创建中...");
  try {
    const project = isUpdating
      ? await api(`/story/projects/${state.selectedStory.project_id}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        })
      : await api("/story/projects", {
          method: "POST",
          body: JSON.stringify(payload),
        });
    if (!isUpdating) {
      els.storyTitle.value = "";
      els.storyPremise.value = "";
      els.storyOpeningScene.value = "";
      els.storySystemPrompt.value = "";
    }
    await loadStories();
    await openStoryProject(project.project_id);
    toast(isUpdating ? "故事项目已更新。" : "故事项目已创建。");
  } catch (err) {
    toast(`${isUpdating ? "更新" : "创建"}故事失败：${err.message}`, true);
  } finally {
    setBusy(els.createStoryBtn, false);
  }
}

async function openCharacter(characterId) {
  const character = await api(`/characters/${characterId}`);
  state.selectedCharacter = character;
  state.editingCharacterId = null;
  state.selectedStory = null;
  renderCharacters();
  renderStories();
  els.workspaceEyeline.textContent = "角色扮演 / 持久会话";
  els.workspaceTitle.textContent = character.name;
  els.chatCharacterName.textContent = character.name;
  els.messageList.innerHTML = "";
  showChat();
  const started = await api(`/chat/start?character_id=${encodeURIComponent(characterId)}`, { method: "POST" });
  state.sessionId = started.session_id;
  addRoleplayMessage("assistant", started.welcome_message);
}

function beginCharacterEdit() {
  if (!state.selectedCharacter) {
    toast("请先选择一个角色。", true);
    return;
  }
  const character = state.selectedCharacter;
  state.editingCharacterId = character.character_id;
  state.draft = {
    name: character.name,
    description: character.description,
    system_prompt: character.system_prompt,
    first_message: character.first_message,
    lorebook: "",
    image_prompt: "",
  };
  hideAllPanels();
  els.workspaceEyeline.textContent = "角色编辑 / 已保存角色";
  els.workspaceTitle.textContent = `编辑：${character.name}`;
  els.createPanel.classList.remove("hidden");
  fillDraft();
  els.saveDraftBtn.textContent = "保存角色修改";
  els.exportBtn.disabled = true;
}

async function deleteCharacter() {
  if (!state.selectedCharacter) {
    toast("请先选择一个角色。", true);
    return;
  }
  const character = state.selectedCharacter;
  const confirmed = window.confirm(`确认删除角色“${character.name}”？此操作不会自动恢复。`);
  if (!confirmed) return;
  try {
    await api(`/characters/${character.character_id}`, { method: "DELETE" });
    state.selectedCharacter = null;
    state.sessionId = null;
    state.draft = null;
    state.editingCharacterId = null;
    await loadCharacters();
    showCreate();
    toast("角色已删除。");
  } catch (err) {
    toast(`删除角色失败：${err.message}`, true);
  }
}

async function openStoryProject(projectId) {
  const project = await api(`/story/projects/${projectId}`);
  state.selectedStory = project;
  state.selectedCharacter = null;
  state.editingCharacterId = null;
  renderStories();
  renderCharacters();
  let sessions = await api(`/story/sessions?project_id=${encodeURIComponent(projectId)}`);
  let session = sessions[0] || null;
  if (!session) {
    session = await api(`/story/projects/${projectId}/sessions`, { method: "POST" });
  }
  state.storySessionId = session.session_id;
  state.storySession = session;
  els.workspaceEyeline.textContent = "互动小说 / 自由输入续写";
  els.workspaceTitle.textContent = project.title;
  els.storyProjectName.textContent = project.title;
  await loadStoryLorebooks(projectId);
  showStoryPanel();
  await refreshStoryWorkspace();
  fillStoryDraft();
}

function beginStoryEdit() {
  if (!state.selectedStory) {
    toast("请先选择一个故事。", true);
    return;
  }
  showStoryCreate({ preserveSelection: true });
}

async function deleteStoryProject() {
  if (!state.selectedStory) {
    toast("请先选择一个故事。", true);
    return;
  }
  const story = state.selectedStory;
  const confirmed = window.confirm(`确认删除故事“${story.title}”？相关会话、事实、检查点、世界书和动作记录都会一并删除。`);
  if (!confirmed) return;
  try {
    await api(`/story/projects/${story.project_id}`, { method: "DELETE" });
    state.selectedStory = null;
    state.storySessionId = null;
    state.storySession = null;
    state.storyLorebooks = [];
    state.storyActions = [];
    await loadStories();
    showStoryCreate();
    toast("故事项目已删除。");
  } catch (err) {
    toast(`删除故事失败：${err.message}`, true);
  }
}

function addRoleplayMessage(role, content) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.innerHTML = `<div>${escapeHtml(content)}</div>`;
  if (role === "assistant" && state.sessionId) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const imageBtn = document.createElement("button");
    imageBtn.className = "mini";
    imageBtn.textContent = "生成图片提示词";
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

function addStoryMessage(role, content, entryType = "narrative") {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.innerHTML = `<div>${escapeHtml(content)}</div>`;
  if (role === "assistant" && entryType === "narrative" && state.storySessionId) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    [
      ["生成图片提示词", "image_prompt"],
      ["直接生图", "image_generate"],
      ["生成音频方案", "audio_plan"],
    ].forEach(([label, actionType]) => {
      const button = document.createElement("button");
      button.className = "mini";
      button.textContent = label;
      button.addEventListener("click", () => runStoryAigcAction(content, actionType));
      actions.appendChild(button);
    });
    node.appendChild(actions);
  }
  els.storyMessageList.appendChild(node);
  els.storyMessageList.scrollTop = els.storyMessageList.scrollHeight;
}

async function sendMessage() {
  const message = els.chatInput.value.trim();
  if (!message || !state.sessionId) return;
  els.chatInput.value = "";
  addRoleplayMessage("user", message);
  setBusy(els.sendBtn, true, "等待回复...");
  try {
    const reply = await api("/chat/message", {
      method: "POST",
      body: JSON.stringify({ session_id: state.sessionId, message }),
    });
    addRoleplayMessage("assistant", reply.reply);
  } catch (err) {
    addRoleplayMessage("assistant", `请求失败：${err.message}`);
  } finally {
    setBusy(els.sendBtn, false);
  }
}

async function sendStoryMessage() {
  const message = els.storyInput.value.trim();
  if (!message || !state.storySessionId) return;
  els.storyInput.value = "";
  addStoryMessage("user", message);
  setBusy(els.storySendBtn, true, "续写中...");
  try {
    const reply = await api("/story/message", {
      method: "POST",
      body: JSON.stringify({ session_id: state.storySessionId, message }),
    });
    addStoryMessage("assistant", reply.reply);
    await refreshStoryWorkspace();
  } catch (err) {
    addStoryMessage("assistant", `故事请求失败：${err.message}`);
  } finally {
    setBusy(els.storySendBtn, false);
  }
}

async function refreshStoryWorkspace() {
  if (!state.storySessionId) return;
  const [session, history, stats, facts, checkpoints, actions] = await Promise.all([
    api(`/story/sessions/${state.storySessionId}`),
    api(`/story/history/${state.storySessionId}`),
    api(`/story/context/${state.storySessionId}/stats`),
    api(`/story/facts/${state.storySessionId}`),
    api(`/story/sessions/${state.storySessionId}/checkpoints`),
    api(`/story/actions/${state.storySessionId}`),
  ]);
  state.storySession = session;
  state.storyActions = actions || [];
  els.storySummary.textContent = session.current_summary || "暂无摘要。";
  renderStoryFacts(facts);
  renderStoryCheckpoints(checkpoints, session.active_checkpoint_id);
  renderStoryHistory(history.history || []);
  renderStoryActionHistory(actions || []);
  els.storyProjectName.textContent =
    `${state.selectedStory?.title || "故事"} · ` +
    `最近 ${stats.recent_entry_count} 条 · 事实 ${stats.fact_count} 条 · ` +
    `世界书命中 ${stats.lorebook_hit_count} 次 · 检查点 ${stats.checkpoint_count} 个`;
}

function renderStoryHistory(history) {
  els.storyMessageList.innerHTML = "";
  history.forEach((item) => addStoryMessage(item.role, item.content, item.entry_type));
}

function renderStoryFacts(facts) {
  els.storyFacts.innerHTML = "";
  if (!facts.length) {
    els.storyFacts.innerHTML = '<small>暂无提取出的事实记忆。</small>';
    return;
  }
  facts.forEach((fact) => {
    const node = document.createElement("div");
    node.className = "story-fact-item";
    node.textContent = fact.fact_text;
    els.storyFacts.appendChild(node);
  });
}

function renderStoryCheckpoints(checkpoints, activeCheckpointId) {
  els.storyCheckpoints.innerHTML = "";
  if (!checkpoints.length) {
    els.storyCheckpoints.innerHTML = '<small>暂无检查点。</small>';
    return;
  }
  checkpoints.forEach((checkpoint) => {
    const wrap = document.createElement("div");
    wrap.className = `checkpoint-item ${checkpoint.checkpoint_id === activeCheckpointId ? "active" : ""}`;
    wrap.innerHTML = `
      <div>
        <strong>${escapeHtml(checkpoint.title)}</strong>
        <small>${escapeHtml((checkpoint.summary_text || "暂无摘要").slice(0, 160))}</small>
      </div>
      <button class="mini" data-checkpoint-id="${checkpoint.checkpoint_id}">回滚</button>
    `;
    wrap.querySelector("button").addEventListener("click", async () => {
      try {
        await api(`/story/sessions/${state.storySessionId}/rollback/${checkpoint.checkpoint_id}`, { method: "POST" });
        await refreshStoryWorkspace();
        toast("已回滚到检查点。");
      } catch (err) {
        toast(`回滚失败：${err.message}`, true);
      }
    });
    els.storyCheckpoints.appendChild(wrap);
  });
}

function renderStoryActionHistory(actions) {
  els.storyActionHistory.innerHTML = "";
  if (!actions.length) {
    els.storyActionHistory.innerHTML = '<small>暂无故事动作记录。</small>';
    return;
  }
  actions.forEach((action) => {
    const item = document.createElement("div");
    item.className = "story-action-item";
    item.innerHTML = `
      <strong>${escapeHtml(action.action_type)}</strong>
      <small>${escapeHtml(action.selected_text.slice(0, 180))}</small>
      <pre>${escapeHtml(JSON.stringify(action.result, null, 2))}</pre>
    `;
    els.storyActionHistory.appendChild(item);
  });
}

async function loadStoryLorebooks(projectId) {
  if (!projectId) {
    state.storyLorebooks = [];
    renderStoryLorebooks();
    return;
  }
  state.storyLorebooks = await api(`/story/projects/${projectId}/lorebooks`);
  renderStoryLorebooks();
}

function resetStoryLorebookForm() {
  state.editingStoryLorebookId = null;
  els.storyLorebookKeyword.value = "";
  els.storyLorebookSortOrder.value = "100";
  els.storyLorebookInsertText.value = "";
  els.saveStoryLorebookBtn.textContent = "新增世界书条目";
}

function renderStoryLorebooks() {
  els.storyLorebookList.innerHTML = "";
  if (!state.selectedStory) {
    els.storyLorebookList.innerHTML = '<div class="story-lorebook-item"><small>请选择或创建故事项目后，再管理项目世界书。</small></div>';
    return;
  }
  if (!state.storyLorebooks.length) {
    els.storyLorebookList.innerHTML = '<div class="story-lorebook-item"><small>暂无项目世界书条目。</small></div>';
    return;
  }
  state.storyLorebooks.forEach((item) => {
    const row = document.createElement("div");
    row.className = "story-lorebook-item";
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(item.keyword)}</strong>
        <small>#${item.sort_order} · ${item.enabled ? "已启用" : "已停用"}</small>
        <p>${escapeHtml(item.insert_text.slice(0, 240))}</p>
      </div>
      <div class="endpoint-actions">
        <button class="mini" data-action="edit-story-lorebook" data-id="${item.lorebook_id}">编辑</button>
        <button class="mini danger" data-action="delete-story-lorebook" data-id="${item.lorebook_id}">删除</button>
      </div>
    `;
    els.storyLorebookList.appendChild(row);
  });
  els.storyLorebookList.querySelectorAll("button[data-action='edit-story-lorebook']").forEach((button) => {
    button.addEventListener("click", () => beginStoryLorebookEdit(button.dataset.id));
  });
  els.storyLorebookList.querySelectorAll("button[data-action='delete-story-lorebook']").forEach((button) => {
    button.addEventListener("click", () => deleteStoryLorebook(button.dataset.id));
  });
}

function beginStoryLorebookEdit(lorebookId) {
  const item = state.storyLorebooks.find((entry) => entry.lorebook_id === lorebookId);
  if (!item) return;
  state.editingStoryLorebookId = lorebookId;
  els.storyLorebookKeyword.value = item.keyword;
  els.storyLorebookSortOrder.value = String(item.sort_order);
  els.storyLorebookInsertText.value = item.insert_text;
  els.saveStoryLorebookBtn.textContent = "保存世界书条目";
}

async function saveStoryLorebook() {
  if (!state.selectedStory) {
    toast("请先选择或创建一个故事项目。", true);
    return;
  }
  const payload = readStoryLorebookForm();
  if (!payload.keyword || !payload.insert_text) {
    toast("故事世界书的关键词和插入文本不能为空。", true);
    return;
  }
  setBusy(els.saveStoryLorebookBtn, true, state.editingStoryLorebookId ? "保存中..." : "新增中...");
  try {
    if (state.editingStoryLorebookId) {
      await api(`/story/lorebooks/${state.editingStoryLorebookId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      toast("故事世界书条目已更新。");
    } else {
      await api(`/story/projects/${state.selectedStory.project_id}/lorebooks`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      toast("故事世界书条目已新增。");
    }
    await loadStoryLorebooks(state.selectedStory.project_id);
    resetStoryLorebookForm();
  } catch (err) {
    toast(`故事世界书保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveStoryLorebookBtn, false);
  }
}

async function deleteStoryLorebook(lorebookId) {
  const item = state.storyLorebooks.find((entry) => entry.lorebook_id === lorebookId);
  if (!item) return;
  const confirmed = window.confirm(`确认删除故事世界书条目“${item.keyword}”？`);
  if (!confirmed) return;
  try {
    await api(`/story/lorebooks/${lorebookId}`, { method: "DELETE" });
    if (state.editingStoryLorebookId === lorebookId) resetStoryLorebookForm();
    await loadStoryLorebooks(state.selectedStory?.project_id);
    toast("故事世界书条目已删除。");
  } catch (err) {
    toast(`删除故事世界书失败：${err.message}`, true);
  }
}

async function runStoryAigcAction(text, actionType) {
  if (!state.storySessionId) return;
  try {
    await api("/story/actions", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.storySessionId,
        action_type: actionType,
        selected_text: text.slice(0, 4000),
      }),
    });
    await refreshStoryWorkspace();
    toast("故事动作已完成。");
  } catch (err) {
    toast(`故事 AIGC 失败：${err.message}`, true);
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
    addRoleplayMessage("assistant", `AIGC 结果：\n${JSON.stringify(result.result, null, 2)}`);
  } catch (err) {
    toast(`AIGC 失败：${err.message}`, true);
  }
}

async function saveSettings() {
  setBusy(els.saveSettingsBtn, true, "保存中...");
  try {
    const settings = await api("/settings", {
      method: "PUT",
      body: JSON.stringify({
        mode: "byok",
        byok_base_url: els.byokBaseUrl.value.trim(),
        byok_model: els.byokModel.value.trim(),
        byok_api_key: els.byokApiKey.value.trim() || null,
      }),
    });
    state.settings = settings;
    state.taskEndpointBindings = { ...(settings.task_endpoint_bindings || {}) };
    renderTaskBindingSelects();
    els.byokApiKey.value = "";
    toast("BYOK 配置已保存。");
  } catch (err) {
    toast(`保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveSettingsBtn, false);
  }
}

async function addOrUpdateEndpoint() {
  applyProviderDefaults();
  const payload = readEndpointForm();
  const validationError = validateEndpointForm(payload);
  if (validationError) {
    toast(validationError, true);
    return;
  }
  setBusy(els.addEndpointBtn, true, state.editingEndpointId ? "保存中..." : "新增中...");
  try {
    const body = { ...payload };
    if (state.editingEndpointId && !els.endpointApiKey.value.trim()) {
      delete body.api_key;
    }
    if (state.editingEndpointId) {
      await api(`/model-endpoints/${state.editingEndpointId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      toast("端点已更新。");
    } else {
      await api("/model-endpoints", {
        method: "POST",
        body: JSON.stringify(body),
      });
      toast("端点已新增。");
    }
    await loadEndpoints();
    resetEndpointForm();
  } catch (err) {
    toast(`端点保存失败：${err.message}`, true);
  } finally {
    setBusy(els.addEndpointBtn, false);
  }
}

async function deleteEndpoint(endpointId) {
  const endpoint = state.endpoints.find((item) => item.endpoint_id === endpointId);
  if (!endpoint) return;
  const confirmed = window.confirm(`确认删除端点“${endpoint.name}”？`);
  if (!confirmed) return;
  try {
    await api(`/model-endpoints/${endpointId}`, { method: "DELETE" });
    if (state.editingEndpointId === endpointId) resetEndpointForm();
    await loadEndpoints();
    toast("端点已删除。");
  } catch (err) {
    toast(`删除失败：${err.message}`, true);
  }
}

async function saveTaskBindings() {
  setBusy(els.saveBindingsBtn, true, "保存中...");
  try {
    const settings = await api("/settings", {
      method: "PUT",
      body: JSON.stringify({ task_endpoint_bindings: readTaskBindings() }),
    });
    state.settings = settings;
    state.taskEndpointBindings = { ...(settings.task_endpoint_bindings || {}) };
    renderTaskBindingSelects();
    toast("任务绑定已保存。");
  } catch (err) {
    toast(`任务绑定保存失败：${err.message}`, true);
  } finally {
    setBusy(els.saveBindingsBtn, false);
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
  els.newCharacterBtn.addEventListener("click", () => switchMode("roleplay"));
  els.newStoryBtn.addEventListener("click", () => switchMode("story"));
  els.modeRoleplayBtn.addEventListener("click", () => switchMode("roleplay"));
  els.modeStoryBtn.addEventListener("click", () => switchMode("story"));
  els.generateBtn.addEventListener("click", generateDraft);
  els.saveDraftBtn.addEventListener("click", saveDraft);
  els.storyGenerateBtn.addEventListener("click", generateStoryDraft);
  els.applyStoryNewBtn.addEventListener("click", () => applyStoryDraft("new"));
  els.applyStoryCurrentBtn.addEventListener("click", () => applyStoryDraft("current"));
  els.addStoryDraftChapterBtn.addEventListener("click", () => addStoryDraftChapterEntry(""));
  els.addStoryDraftLorebookEntryBtn.addEventListener("click", () => addStoryDraftLorebookEntry({
    keyword: "",
    insert_text: "",
    sort_order: 100 + els.storyDraftLorebookEntries.children.length * 10,
  }));
  [
    els.storyDraftTitle,
    els.storyDraftTone,
    els.storyDraftPremise,
    els.storyDraftOpeningScene,
    els.storyDraftSystemPrompt,
    els.storyDraftProtagonistProfile,
  ].forEach((el) => el.addEventListener("input", () => renderStoryDraftContinuityReview()));
  els.createStoryBtn.addEventListener("click", createStoryProject);
  els.saveStoryLorebookBtn.addEventListener("click", saveStoryLorebook);
  els.sendBtn.addEventListener("click", sendMessage);
  els.storySendBtn.addEventListener("click", sendStoryMessage);
  els.editCharacterBtn.addEventListener("click", beginCharacterEdit);
  els.deleteCharacterBtn.addEventListener("click", deleteCharacter);
  els.editStoryBtn.addEventListener("click", beginStoryEdit);
  els.deleteStoryBtn.addEventListener("click", deleteStoryProject);
  els.exportBtn.addEventListener("click", exportCharacter);
  els.backToCreateBtn.addEventListener("click", () => switchMode("roleplay"));
  els.backToStoryCreateBtn.addEventListener("click", () => showStoryCreate({ preserveSelection: true }));
  els.settingsBtn.addEventListener("click", () => els.settingsPanel.classList.add("open"));
  els.closeSettingsBtn.addEventListener("click", () => els.settingsPanel.classList.remove("open"));
  els.saveSettingsBtn.addEventListener("click", saveSettings);
  els.endpointProvider.addEventListener("change", () => applyProviderDefaults({ overwrite: true }));
  els.addEndpointBtn.addEventListener("click", addOrUpdateEndpoint);
  els.cancelEndpointEditBtn.addEventListener("click", resetEndpointForm);
  els.saveBindingsBtn.addEventListener("click", saveTaskBindings);
  els.themeBtn.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    applyTheme();
  });
  els.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) sendMessage();
  });
  els.storyInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.ctrlKey) sendStoryMessage();
  });
}

async function boot() {
  applyTheme();
  bindEvents();
  resetEndpointForm();
  try {
    await Promise.all([loadCharacters(), loadStories(), loadSettings(), loadEndpoints()]);
    switchMode("roleplay");
  } catch (err) {
    toast(`初始化失败：${err.message}`, true);
  }
}

boot();
