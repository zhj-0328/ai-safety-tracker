const state = {
  sources: [],
  activeSourceId: null,
  query: "",
  newOnly: false,
};

const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : "";

const elements = {
  sourceNav: document.querySelector("#sourceNav"),
  cards: document.querySelector("#cards"),
  heroTitle: document.querySelector("#heroTitle"),
  heroDescription: document.querySelector("#heroDescription"),
  sourceCount: document.querySelector("#sourceCount"),
  itemCount: document.querySelector("#itemCount"),
  lastUpdated: document.querySelector("#lastUpdated"),
  activeSourceMeta: document.querySelector("#activeSourceMeta"),
  sourceLink: document.querySelector("#sourceLink"),
  searchInput: document.querySelector("#searchInput"),
  newOnlyToggle: document.querySelector("#newOnlyToggle"),
  refreshButton: document.querySelector("#refreshButton"),
  cardTemplate: document.querySelector("#cardTemplate"),
};

async function fetchData(force = false) {
  const response = await fetch(`${API_BASE}/api/data${force ? "?refresh=1" : ""}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`请求失败：${response.status}`);
  }
  const payload = await response.json();
  state.sources = payload.sources || [];
  state.sourceCount = state.sources.length;
  syncActiveSource();
  render();
}

function syncActiveSource() {
  const hashSource = window.location.hash.replace("#", "");
  const fallback = state.sources[0]?.id ?? null;
  const candidate = hashSource || state.activeSourceId || fallback;
  state.activeSourceId = state.sources.some((source) => source.id === candidate) ? candidate : fallback;
}

function groupSources() {
  const groups = new Map();
  for (const source of state.sources) {
    if (!groups.has(source.category)) {
      groups.set(source.category, []);
    }
    groups.get(source.category).push(source);
  }
  return groups;
}

function formatDate(value) {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function getActiveSource() {
  return state.sources.find((source) => source.id === state.activeSourceId) ?? null;
}

function filterItems(items) {
  const query = state.query.trim().toLowerCase();
  return items.filter((item) => {
    if (state.newOnly && !item.is_new) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [item.title, item.authors, item.summary, item.topic, item.subcategory]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query);
  });
}

function renderNav() {
  elements.sourceNav.innerHTML = "";
  for (const [category, sources] of groupSources()) {
    const group = document.createElement("section");
    group.className = "nav-group";

    const label = document.createElement("div");
    label.className = "nav-group-label";
    label.textContent = category;
    group.append(label);

    for (const source of sources) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `nav-link${source.id === state.activeSourceId ? " is-active" : ""}`;
      button.innerHTML = `
        <span>
          <span class="nav-link-name">${source.name}</span>
          <span class="nav-link-meta">${source.count || 0} 条</span>
        </span>
        <span class="nav-link-count">${source.count || 0}</span>
      `;
      button.addEventListener("click", () => {
        state.activeSourceId = source.id;
        window.location.hash = source.id;
        render();
      });
      group.append(button);
    }
    elements.sourceNav.append(group);
  }
}

function renderSourceMeta(source, visibleItems) {
  const chips = [];
  chips.push(`<span class="meta-badge">${source.category}</span>`);
  if (source.error) {
    chips.push(`<span class="meta-badge">抓取异常</span>`);
  }

  elements.activeSourceMeta.innerHTML = `
    <div class="meta-headline">
      <span class="meta-title">${source.name}</span>
      ${chips.join("")}
    </div>
    <div class="meta-copy">${source.description}</div>
    <div class="meta-copy">展示 ${visibleItems.length} / ${source.items.length} 条，最近抓取：${formatDate(source.fetched_at)}</div>
    ${source.error ? `<div class="error-banner">${source.error}</div>` : ""}
  `;
}

function createCard(item) {
  const fragment = elements.cardTemplate.content.cloneNode(true);
  fragment.querySelector(".card-type").textContent = item.content_type === "report" ? "报告" : "论文";

  const topic = fragment.querySelector(".card-topic");
  if (item.topic) {
    topic.textContent = item.topic;
  } else {
    topic.remove();
  }

  const newChip = fragment.querySelector(".card-new");
  if (item.is_new) {
    newChip.classList.add("is-visible");
  }

  fragment.querySelector(".card-title").textContent = item.title;
  fragment.querySelector(".card-authors").textContent = item.authors || "作者信息未提供";
  fragment.querySelector(".card-summary").textContent = item.summary || "暂无摘要。";

  const meta = [];
  if (item.published) meta.push(`时间：${item.published}`);
  if (item.subcategory) meta.push(`分组：${item.subcategory}`);
  if (item.match_score) meta.push(`相关度：${item.match_score}`);
  fragment.querySelector(".card-meta").textContent = meta.join(" · ");

  const link = fragment.querySelector(".primary-link");
  link.href = item.link;
  link.textContent = item.content_type === "report" ? "打开报告" : "打开论文";
  return fragment;
}

function renderCards(source) {
  const visibleItems = filterItems(source.items || []);
  elements.cards.innerHTML = "";
  renderSourceMeta(source, visibleItems);

  if (!visibleItems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前来源没有匹配条目。你可以切换来源，或者缩小关键词过滤范围。";
    elements.cards.append(empty);
    return visibleItems;
  }

  for (const item of visibleItems) {
    elements.cards.append(createCard(item));
  }
  return visibleItems;
}

function renderHero(source, visibleItems) {
  elements.heroTitle.textContent = source ? source.name : "暂无来源";
  elements.heroDescription.textContent = source
    ? `${source.description} 现在每个来源都是一个独立页面入口，点击左侧即可跳转查看对应内容。`
    : "暂无内容。";
  elements.sourceCount.textContent = String(state.sourceCount ?? 0);
  elements.itemCount.textContent = String(visibleItems.length);
  elements.lastUpdated.textContent = source?.fetched_at ? formatDate(source.fetched_at) : "--";
  elements.sourceLink.href = source?.url || "#";
}

function render() {
  renderNav();
  const activeSource = getActiveSource();
  if (!activeSource) {
    elements.heroTitle.textContent = "没有可用来源";
    elements.cards.innerHTML = `<div class="empty-state">还没有抓到任何数据。</div>`;
    return;
  }
  const visibleItems = renderCards(activeSource);
  renderHero(activeSource, visibleItems);
}

function scheduleAutoRefresh() {
  window.setInterval(() => {
    fetchData(true).catch((error) => {
      console.error(error);
    });
  }, 10 * 60 * 1000);
}

function bindEvents() {
  elements.searchInput.addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });

  elements.newOnlyToggle.addEventListener("change", (event) => {
    state.newOnly = event.target.checked;
    render();
  });

  elements.refreshButton.addEventListener("click", async () => {
    elements.refreshButton.disabled = true;
    elements.refreshButton.textContent = "刷新中...";
    try {
      await fetchData(true);
    } finally {
      elements.refreshButton.disabled = false;
      elements.refreshButton.textContent = "立即刷新";
    }
  });

  window.addEventListener("hashchange", () => {
    syncActiveSource();
    render();
  });
}

async function boot() {
  bindEvents();
  try {
    await fetchData(false);
    scheduleAutoRefresh();
  } catch (error) {
    console.error(error);
    elements.heroTitle.textContent = "加载失败";
    if (window.location.protocol === "file:") {
      elements.heroDescription.textContent = "你现在是直接打开本地 HTML 文件。请先启动本地服务，或直接访问 http://127.0.0.1:8765 。";
    } else {
      elements.heroDescription.textContent = error instanceof Error ? error.message : "未知错误";
    }
    elements.cards.innerHTML = `<div class="error-banner">页面初始化失败。请确认本地服务已运行：<code>python3 /Users/hjzhou/codex/ai_safety_tracker/server.py</code>，然后访问 <a href="http://127.0.0.1:8765" target="_blank" rel="noreferrer">http://127.0.0.1:8765</a>。</div>`;
  }
}

boot();
