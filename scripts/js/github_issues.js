/**
 * github_issues.js
 * 使用 Node.js 内置 fetch 拉取 facebook/react 最新 5 条 Issue 标题，
 * 再通过 MyMemory 免费翻译 API 将标题翻译为中文，输出中文列表。
 * 两处网络请求均带 5 秒超时处理。
 */

const API_URL = "https://api.github.com/repos/facebook/react/issues?per_page=5";
const TIMEOUT_MS = 5000;

/**
 * 通用带超时的 fetch 封装
 */
async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 拉取最新 5 条 Issue 标题
 */
async function fetchLatestIssues() {
  const response = await fetchWithTimeout(API_URL, {
    headers: {
      Accept: "application/vnd.github+json",
      // GitHub API 要求带 User-Agent，否则会返回 403
      "User-Agent": "github-issues-script",
    },
  });

  if (!response.ok) {
    throw new Error(`请求失败：HTTP ${response.status} ${response.statusText}`);
  }

  const issues = await response.json();
  if (!Array.isArray(issues) || issues.length === 0) {
    return [];
  }
  return issues.slice(0, 5).map((issue) => issue.title);
}

/**
 * 使用 MyMemory 免费翻译 API 将英文翻译为中文
 * 返回翻译后的文本；失败时抛出异常由调用方降级处理
 */
async function translate(text) {
  const url =
    "https://api.mymemory.translated.net/get?q=" +
    encodeURIComponent(text) +
    "&langpair=en%7Czh-CN";

  const response = await fetchWithTimeout(url, {
    headers: { "User-Agent": "github-issues-script" },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();
  const translated = data && data.responseData && data.responseData.translatedText;
  if (!translated) {
    throw new Error("翻译结果为空");
  }
  return translated;
}

async function main() {
  try {
    const titles = await fetchLatestIssues();

    if (titles.length === 0) {
      console.log("React 暂无最新 Issue。");
      return;
    }

    console.log("React 最新 Issue 标题（中文）：");
    for (let i = 0; i < titles.length; i++) {
      const en = titles[i];
      let zh = null;
      try {
        zh = await translate(en);
      } catch (error) {
        // 单条翻译失败时降级为原文
        zh = null;
      }

      if (zh) {
        console.log(`${i + 1}. ${zh}`);
      } else {
        console.log(`${i + 1}. ${en}（翻译失败，显示原文）`);
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      console.error(`请求超时（超过 ${TIMEOUT_MS / 1000} 秒无响应），请稍后重试。`);
    } else {
      console.error(`发生错误：${error.message}`);
    }
  }
}

main();
