"use strict";

const $ = (id) => document.getElementById(id);
const state = { mode: "answer", key: "", status: null, busy: false, controller: null, lastResponse: null };
const names = { answer: "Ответ по базе", agent: "Агент", search: "Поиск", classify: "Классификация", chunks: "Чанки" };
const descriptions = {
  answer: ["Ответ по базе знаний", "Готовый ответ с цитатами из найденных статей.", "Получить ответ"],
  agent: ["Агент поддержки", "Агент выберет инструменты, ответит или запросит уточнение.", "Запустить агента"],
  search: ["Поиск по источникам", "Найдите фрагменты статей и посмотрите оценку релевантности.", "Найти источники"],
  classify: ["Категория обращения", "Определите одно из 77 банковских намерений на английском.", "Определить категорию"],
  chunks: ["Разбиение по предложениям", "Посмотрите, как текст делится на фрагменты с перекрытием.", "Разбить на чанки"],
};
const examples = {
  ru: ["Как установить зависимости проекта?", "Как запустить API?", "Как проверить, что сервис работает?"],
  en: ["How do I install the dependencies?", "How do I start the local API?", "How do I run the tests?"],
  classify: ["I lost my card", "My bank transfer is still pending", "How do I change my PIN?"],
  agent: { ru: ["Как установить зависимости проекта?", "Ничего не работает", "Позовите оператора"], en: ["How do I start the local API?", "Nothing works", "Please connect me to a human operator"] },
};
const chunkSample = "Банк принимает обращения через мобильное приложение. Сначала выберите тему и опишите свою ситуацию. Не указывайте пароль или полный номер карты.\n\nОператор проверит обращение и предложит следующий шаг. Если информации недостаточно, он задаст уточняющий вопрос. Ответ сохраняется в истории обращения. Вы можете вернуться к нему в удобное время.";
let savedQuestion = $("query").value;
let savedChunkText = chunkSample;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = String(text);
  return item;
}

function icon(name) {
  const item = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  item.setAttribute("aria-hidden", "true");
  item.append(use);
  return item;
}

function hidden(id, value) { $(id).classList.toggle("hidden", value); }

function plural(number, forms) {
  const tail = number % 100;
  const index = tail >= 11 && tail <= 14 ? 2 : number % 10 === 1 ? 0 : number % 10 >= 2 && number % 10 <= 4 ? 1 : 2;
  return `${number} ${forms[index]}`;
}

function notify(text) {
  $("toast").textContent = text;
  hidden("toast", false);
  window.setTimeout(() => hidden("toast", true), 2600);
}

async function api(path, payload, signal) {
  const headers = {};
  if (state.key) headers["x-api-key"] = state.key;
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers, body: payload === undefined ? undefined : JSON.stringify(payload), signal, credentials: "omit",
  });
  const body = await response.json().catch(() => ({ detail: "Сервер вернул ответ в неизвестном формате." }));
  if (!response.ok) {
    const error = new Error(typeof body.detail === "string" ? body.detail : "Проверьте поля запроса.");
    error.code = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function updateCount() {
  const limit = state.mode === "chunks" ? 20000 : 2000;
  $("query").maxLength = limit;
  $("char-count").textContent = `${$("query").value.length} / ${limit}`;
}

function updateExamples() {
  const target = $("examples-list");
  target.replaceChildren();
  const language = $("language").value;
  const values = state.mode === "classify" ? examples.classify : state.mode === "chunks" ? ["Пример текста с предложениями"] : state.mode === "agent" ? examples.agent[language] : examples[language];
  for (const value of values) {
    const button = node("button", "example-button", value);
    button.type = "button";
    button.addEventListener("click", () => {
      if (state.busy) return;
      $("query").value = state.mode === "chunks" ? chunkSample : value;
      if (state.mode === "chunks") $("language").value = "ru";
      updateCount();
      $("query").focus();
    });
    target.append(button);
  }
}

function modeNotice() {
  let text = "";
  if (state.mode === "classify") text = "Классификатор обучен на английских обращениях BANKING77. Русский текст для этого режима не поддерживается.";
  if (state.mode === "agent" && state.status && !state.status.planner_configured) text = "Планировщик агента не настроен. Для конкретного вопроса будет создан черновик передачи оператору. Поиск и ответ из источников доступны без LLM.";
  if (state.mode === "answer" && $("answer-mode").value === "ollama" && state.status && !state.status.answer_model_configured) text = "Модель Ollama не настроена. Выберите точные выдержки или задайте OLLAMA_MODEL при запуске сервера.";
  if (state.mode === "chunks") text = "Перекрытие сохраняет целые предложения, пока они помещаются в лимит. Длинное предложение разбивается по словам; слишком длинное слово — по символам.";
  $("mode-notice").textContent = text;
  hidden("mode-notice", !text);
}

function emptyResult() {
  const box = node("div", "empty-state");
  const image = node("span", "empty-icon");
  image.append(icon(state.mode === "answer" ? "chat" : state.mode));
  box.append(image, node("h3", "", "Готовы к проверке"), node("p", "", "Отправьте запрос, чтобы увидеть результат."));
  $("result").replaceChildren(box);
  hidden("raw-details", true);
  hidden("copy-button", true);
  $("elapsed").textContent = "";
  state.lastResponse = null;
}

function setMode(mode) {
  if (state.busy) return;
  if (state.mode !== "chunks" && mode === "chunks") {
    savedQuestion = $("query").value;
    $("query").value = savedChunkText;
  } else if (state.mode === "chunks" && mode !== "chunks") {
    savedChunkText = $("query").value;
    $("query").value = savedQuestion;
  }
  state.mode = mode;
  const [title, description, submit] = descriptions[mode];
  $("mode-title").textContent = title;
  $("mode-description").textContent = description;
  $("submit-label").textContent = submit;
  $("breadcrumb-mode").textContent = names[mode];
  $("query-label").textContent = mode === "chunks" ? "Текст для разбиения" : mode === "classify" ? "Обращение на английском" : "Ваш вопрос";
  $("query").placeholder = mode === "classify" ? "I lost my card" : mode === "chunks" ? "Вставьте несколько предложений…" : "Например, как установить зависимости проекта?";
  $("query-hint").textContent = mode === "chunks" ? "Предпросмотр не меняет текущий индекс." : "Не указывайте пароли и полные реквизиты.";
  $("language").disabled = mode === "classify";
  if (mode === "classify") {
    $("language").value = "en";
    if (/[А-Яа-яЁё]/.test($("query").value)) $("query").value = examples.classify[0];
  }
  hidden("top-k-field", !["answer", "search"].includes(mode));
  hidden("steps-field", mode !== "agent");
  hidden("answer-options", mode !== "answer");
  hidden("chunk-options", mode !== "chunks");
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.classList.toggle("active", button.dataset.mode === mode);
    if (button.dataset.mode === mode) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  updateCount(); updateExamples(); modeNotice(); emptyResult();
}

async function refreshStatus() {
  try {
    const status = await api("/v1/system/status");
    state.status = status;
    $("connection-dot").className = "status-dot online";
    $("connection-label").textContent = "API подключён";
    $("article-count").textContent = status.article_count;
    $("chunk-count").textContent = status.chunk_count;
    $("retriever-label").textContent = status.retriever.startsWith("bm25") ? "BM25" : status.retriever.startsWith("tfidf") ? "TF-IDF" : "Недоступен";
    $("planner-label").textContent = status.planner_configured ? status.planner_model : "Не настроен";
    $("planner-label").title = status.planner_configured ? "Модель указана в настройках. Доступность проверяется при запросе." : "Нужна переменная AGENT_MODEL и работающий Ollama.";
    $("corpus-scope").textContent = status.corpus_role === "demonstration" ? "База: инструкции по проекту · RU / EN" : `Языки базы: ${status.languages.join(" / ").toUpperCase() || "—"}`;
    let notice = "";
    if (!status.knowledge_ready) notice = "База знаний не загружена. Для готового локального контура запустите python scripts/start_demo.py.";
    else if (status.threshold_status !== "calibrated") notice = "Поиск доступен, но пороги ответа не настроены или не соответствуют индексу. Запустите подготовленный локальный контур либо выполните калибровку.";
    $("system-notice").textContent = notice;
    hidden("system-notice", !notice);
    modeNotice();
  } catch (error) {
    $("connection-dot").className = "status-dot offline";
    $("connection-label").textContent = error.code === 401 ? "Нужен ключ API" : "Нет подключения";
    $("system-notice").textContent = error.code === 401 ? "Для доступа введите ключ API через кнопку «Доступ». Ключ не сохраняется в браузере." : "Не удалось подключиться к API. Проверьте, что сервер запущен, и обновите состояние.";
    hidden("system-notice", false);
  }
}

function badge(text, warn = false) { return node("span", `result-badge${warn ? " warn" : ""}`, text); }
function section(text) { return node("div", "section-label", text); }

function reasonText(reason) {
  const values = {
    threshold_not_configured: "Порог ответа не настроен. Запустите python scripts/start_demo.py для подготовленной базы.",
    calibration_mismatch: "Настройки индекса изменились. Для формирования ответа нужна повторная калибровка.",
    threshold_not_met: "Найденные материалы не прошли настроенный порог релевантности.",
    no_candidates: "В текущей базе нет подходящих фрагментов для этого языка и вопроса.",
    planner_unavailable_or_invalid: "Планировщик недоступен или не настроен. Проверьте AGENT_MODEL и Ollama. Можно использовать режим «Ответ по базе» без LLM.",
    agent_requested_handoff: "Подготовлен черновик обращения для оператора. Он не отправлен во внешнюю систему.",
    time_budget_exceeded: "Исчерпано время обработки. Подготовлен черновик передачи оператору.",
    step_budget_exceeded: "Исчерпан лимит шагов. Подготовлен черновик передачи оператору.",
  };
  return values[reason] || "Система не смогла подготовить подтверждённый ответ. Подробности доступны в техническом ответе.";
}

function sourceCard(hit, number) {
  const card = node("article", "source-card");
  const top = node("div", "source-top");
  top.append(node("div", "source-title", `${number}. ${hit.title || hit.document_id}`));
  if (typeof hit.score === "number") top.append(node("span", "source-score", `score ${hit.score.toFixed(3)}`));
  card.append(top, node("p", "source-quote", hit.quote || hit.text || ""));
  const meta = node("div", "source-meta");
  if (hit.language) meta.append(node("span", "", hit.language.toUpperCase()));
  if (hit.updated_at) meta.append(node("span", "", hit.updated_at));
  const address = String(hit.source || "");
  if (/^https?:\/\//i.test(address)) {
    const link = node("a", "source-address", "Открыть источник ↗");
    link.href = address; link.target = "_blank"; link.rel = "noopener noreferrer"; meta.append(link);
  } else meta.append(node("span", "source-address", address));
  card.append(meta);
  return card;
}

function renderChunks(data, target) {
  target.append(badge(data.title ? "Чанки текущего индекса" : "Предпросмотр по предложениям"));
  if (data.title) target.append(node("h3", "", data.title));
  const config = data.chunking || data;
  target.append(node("p", "chunk-summary", `${plural(data.chunks.length, ["чанк", "чанка", "чанков"])}${data.sentence_count !== undefined ? ` · ${plural(data.sentence_count, ["предложение", "предложения", "предложений"])}` : ""} · лимит ${config.max_chars || "—"} символов`));
  if (data.oversized_sentence_count) target.append(node("p", "inline-note", `${data.oversized_sentence_count} предложений длиннее лимита разбиты на части. Их фрагменты не используются как перекрытие.`));
  data.chunks.forEach((chunk, index) => {
    const card = node("article", "chunk-card");
    const top = node("div", "source-top");
    top.append(node("div", "source-title", `Чанк ${index + 1}`), node("span", "source-score", `${chunk.chars} символов`));
    card.append(top, node("p", "source-quote", chunk.text));
    target.append(card);
  });
}

function render(data, mode = state.mode) {
  const target = $("result"); target.replaceChildren();
  state.lastResponse = data;
  $("raw-json").textContent = JSON.stringify(data, null, 2);
  hidden("raw-details", false); hidden("copy-button", false);
  if (mode === "chunks") return renderChunks(data, target);
  if (mode === "classify") {
    target.append(badge("Категория определена"), section("Намерение обращения"), node("p", "answer-text", data.intent.replaceAll("_", " ")),
      node("p", "chunk-summary", "Класс выбран моделью BANKING77. Это определение темы, а не ответ на обращение."));
    return;
  }
  if (mode === "search") {
    const passed = data.retrieval_status === "threshold_passed";
    target.append(badge(data.hits.length ? `Найдено фрагментов: ${data.hits.length}` : "Подходящих фрагментов нет", !passed));
    if (!passed) target.append(node("p", "chunk-summary", reasonText(data.retrieval_status)));
    if (data.threshold !== null) target.append(node("p", "chunk-summary", `Порог: ${data.threshold}. Score — оценка ранжирования, не вероятность правильного ответа.`));
    data.hits.forEach((hit, index) => target.append(sourceCard(hit, index + 1)));
    return;
  }
  const answered = data.status === "supported_excerpt" || data.status === "answered";
  target.append(badge(answered ? "Ответ из источников" : data.status === "clarification_required" ? "Нужно уточнение" : data.status === "handoff" ? "Черновик передачи оператору" : "Недостаточно оснований для ответа", !answered));
  if (data.answer) target.append(node("p", "answer-text", data.answer));
  else if (data.clarification) target.append(node("p", "answer-text", data.clarification));
  else target.append(node("p", "answer-text", reasonText(data.reason)));
  if (data.ticket_draft) target.append(node("p", "chunk-summary", "Черновик создан. Обращение не отправлено; требуется проверка оператором."));
  if (data.citations && data.citations.length) {
    target.append(section("Источники ответа"));
    data.citations.forEach((citation, index) => target.append(sourceCard(citation, index + 1)));
  }
  if (data.trace && data.trace.length) {
    target.append(section("Шаги агента"));
    const trace = node("ol", "trace");
    const tools = { search_knowledge: "Поиск по базе знаний", prepare_answer: "Подготовка ответа", classify_inquiry: "Классификация обращения", ask_clarification: "Уточнение вопроса", draft_ticket: "Черновик передачи" };
    for (const step of data.trace) {
      const row = node("li", "");
      row.append(node("span", "", tools[step.tool] || step.tool), node("span", "", `${Math.round(step.duration_ms)} мс`));
      trace.append(row);
    }
    target.append(trace);
  }
}

function showError(error) {
  const target = $("result"); target.replaceChildren();
  const title = error.code === 401 ? "Нужен ключ API" : error.code === 429 ? "Достигнут лимит запросов" : error.code === 503 ? "Компонент пока недоступен" : "Не удалось выполнить запрос";
  target.append(node("span", "result-badge error", error.code ? `HTTP ${error.code}` : "Ошибка подключения"), node("h3", "error-title", title));
  let message = error.message;
  if (error.code === 401) message = "Введите ключ API через кнопку «Доступ» и повторите запрос.";
  if (error.code === 429) message = "Подождите минуту и повторите запрос. Также проверьте, не занят ли агент другим обращением.";
  if (error.code === 503 && state.mode === "answer" && $("answer-mode").value === "ollama") message = "Ollama недоступен, модель не настроена или проверка цитат не пройдена. Выберите точные выдержки для ответа без LLM.";
  target.append(node("p", "answer-text", message));
  if (error.body) {
    state.lastResponse = error.body;
    $("raw-json").textContent = JSON.stringify(error.body, null, 2);
    hidden("raw-details", false); hidden("copy-button", false);
  }
}

function setBusy(busy) {
  state.busy = busy;
  $("submit-button").disabled = busy;
  $("query").readOnly = busy;
  $("corpus-button").disabled = busy;
  for (const button of document.querySelectorAll("[data-mode], .example-button")) button.disabled = busy;
  document.querySelector(".result-card").setAttribute("aria-busy", String(busy));
  hidden("cancel-button", !busy);
  $("submit-label").textContent = busy ? "Обрабатываем…" : descriptions[state.mode][2];
}

$("request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const text = $("query").value.trim();
  if (!text || text.length > (state.mode === "chunks" ? 20000 : 2000)) return showError(new Error("Проверьте длину текста и заполните вопрос."));
  const language = $("language").value;
  let path, payload;
  if (state.mode === "chunks") { path = "/v1/chunks/preview"; payload = { text, language, max_chars: Number($("max-chars").value), overlap_sentences: Number($("overlap-sentences").value) }; }
  else if (state.mode === "agent") { path = "/v1/agent/run"; payload = { text, language, max_steps: Number($("max-steps").value) }; }
  else if (state.mode === "classify") { path = "/v1/classify"; payload = { text }; }
  else { path = `/v1/knowledge/${state.mode}`; payload = { text, language, top_k: Number($("top-k").value) }; if (state.mode === "answer") payload.mode = $("answer-mode").value; }
  setBusy(true);
  const loading = node("div", "empty-state");
  loading.append(node("span", "loading-dot"), node("h3", "", state.mode === "agent" ? "Агент выбирает следующий шаг" : "Обрабатываем запрос"), node("p", "", "Результат появится здесь после завершения."));
  $("result").replaceChildren(loading); hidden("raw-details", true); hidden("copy-button", true);
  const started = performance.now();
  state.controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; state.controller.abort(); }, 75000);
  try { render(await api(path, payload, state.controller.signal)); }
  catch (error) {
    if (error.name === "AbortError") showError(new Error(timedOut ? "Истекло время ожидания. Сервер может ещё завершать обработку." : "Ожидание отменено. Сервер может ещё завершать обработку."));
    else showError(error);
  } finally {
    window.clearTimeout(timer); state.controller = null; setBusy(false);
    $("elapsed").textContent = `${((performance.now() - started) / 1000).toFixed(2)} с`;
  }
});

$("corpus-button").addEventListener("click", async () => {
  $("corpus-dialog").showModal();
  $("corpus-list").replaceChildren(node("p", "muted", "Загружаем статьи…"));
  try {
    const data = await api("/v1/knowledge/documents");
    $("corpus-list").replaceChildren();
    for (const article of data.documents) {
      const button = node("button", "corpus-row");
      button.append(node("span", "", article.title), node("span", "", `${article.language.toUpperCase()} · ${article.chunk_count} ч.`));
      button.addEventListener("click", async () => {
        $("corpus-dialog").close(); setMode("chunks");
        try { render(await api(`/v1/knowledge/chunks?document_id=${encodeURIComponent(article.document_id)}`), "chunks"); }
        catch (error) { showError(error); }
      });
      $("corpus-list").append(button);
    }
  } catch (error) { $("corpus-list").replaceChildren(node("p", "muted", error.code === 401 ? "Введите ключ API через кнопку «Доступ»." : error.message)); }
});

for (const button of document.querySelectorAll("[data-mode]")) button.addEventListener("click", () => setMode(button.dataset.mode));
for (const button of document.querySelectorAll("[data-close]")) button.addEventListener("click", () => $(button.dataset.close).close());
$("access-button").addEventListener("click", () => { $("access-dialog").showModal(); $("api-key").focus(); });
$("access-form").addEventListener("submit", (event) => { event.preventDefault(); state.key = $("api-key").value.trim(); $("access-dialog").close(); refreshStatus(); });
$("clear-key").addEventListener("click", () => { state.key = ""; $("api-key").value = ""; $("access-dialog").close(); refreshStatus(); });
$("refresh-status").addEventListener("click", refreshStatus);
$("language").addEventListener("change", updateExamples);
$("answer-mode").addEventListener("change", modeNotice);
$("query").addEventListener("input", updateCount);
$("query").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); $("request-form").requestSubmit(); } });
$("max-chars").addEventListener("input", () => { $("max-chars-value").value = $("max-chars").value; });
$("cancel-button").addEventListener("click", () => state.controller?.abort());
$("copy-button").addEventListener("click", async () => {
  if (!state.lastResponse) return;
  try { await navigator.clipboard.writeText(state.lastResponse.answer || state.lastResponse.clarification || JSON.stringify(state.lastResponse, null, 2)); notify("Результат скопирован"); }
  catch { notify("Не удалось скопировать. Откройте технический ответ и выделите текст."); }
});
setMode("answer");
refreshStatus();
