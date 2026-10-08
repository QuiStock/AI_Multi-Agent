import './style.css';
import './overrides.css';

const API = import.meta.env.VITE_API_BASE_URL || '/api/v1';
const OBS = `${API}/observability`;
const state = {
  view: 'overview',
  metrics: null,
  traces: [],
  traceTotal: 0,
  conversations: [],
  conversationTotal: 0,
  traceOffset: 0,
  conversationOffset: 0,
  selectedTraceId: null,
  selectedTrace: null,
  selectedConversationId: null,
  selectedConversation: null,
  activeTraces: [],
  liveEvents: [],
  liveByTrace: new Map(),
  cursor: 0,
  pollBusy: false,
  fetches: [],
  traceStatus: null,
  filters: { from: null, to: null, consumer: '', conversation: '', environment: '', status: '' },
  labModels: [],
  labModelsLoaded: false,
  labLoadedAgent: null,
};

const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const dateTime = (value) => value ? new Date(value).toLocaleString('pt-BR') : '—';
const shortId = (value, length = 15) => value && value.length > length ? `${value.slice(0, 8)}…${value.slice(-5)}` : (value || '—');
const number = (value, digits = 0) => value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('pt-BR', { maximumFractionDigits: digits });
const duration = (value) => value == null ? '—' : value < 1000 ? `${number(value, 1)} ms` : `${number(value / 1000, 2)} s`;
const statusText = (status) => ({ completed: 'Concluído', error: 'Erro', running: 'Em andamento', interrupted: 'Interrompido' }[status] || status || '—');

function recordFetch(label, startedAt, elapsedMs, ok, statusTextValue = '') {
  state.fetches.unshift({ label, startedAt, elapsedMs, ok, statusText: statusTextValue });
  state.fetches = state.fetches.slice(0, 16);
  renderFetchHistory();
}

async function requestJSON(path, { method = 'GET', body, label = `${method} ${path}` } = {}) {
  const start = performance.now();
  const startedAt = new Date();
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    recordFetch(label, startedAt, performance.now() - start, true, `HTTP ${response.status}`);
    setApiStatus(true);
    return payload;
  } catch (error) {
    recordFetch(label, startedAt, performance.now() - start, false, error.message);
    setApiStatus(false);
    throw error;
  }
}

function setApiStatus(connected) {
  $('api-status').textContent = connected ? 'API conectada' : 'API indisponível';
  $('api-status-dot').classList.toggle('offline', !connected);
}

function queryFromFilters({ conversationId, includePagination = false } = {}) {
  const params = new URLSearchParams();
  if (state.filters.from) params.set('started_from', state.filters.from);
  if (state.filters.to) params.set('started_to', state.filters.to);
  if (state.filters.consumer) params.set('consumer_id', state.filters.consumer);
  if (state.filters.conversation) params.set('conversation_id', state.filters.conversation);
  if (state.filters.environment) params.set('environment', state.filters.environment);
  if (state.filters.status) params.set('status', state.filters.status);
  if (conversationId) params.set('conversation_id', conversationId);
  if (includePagination) {
    params.set('limit', '50');
    params.set('offset', String(state.traceOffset));
  }
  return params.toString();
}

function conversationQuery() {
  const params = new URLSearchParams();
  if (state.filters.from) params.set('updated_from', state.filters.from);
  if (state.filters.to) params.set('updated_to', state.filters.to);
  if (state.filters.consumer) params.set('consumer_id', state.filters.consumer);
  if (state.filters.conversation) params.set('conversation_id', state.filters.conversation);
  params.set('limit', '50');
  params.set('offset', String(state.conversationOffset));
  return params.toString();
}

async function loadData({ quiet = false } = {}) {
  const metricsParams = new URLSearchParams();
  metricsParams.set('started_from', state.filters.from || new Date(Date.now() - 86400000).toISOString());
  metricsParams.set('started_to', state.filters.to || new Date().toISOString());
  if (state.filters.consumer) metricsParams.set('consumer_id', state.filters.consumer);
  if (state.filters.conversation) metricsParams.set('conversation_id', state.filters.conversation);
  if (state.filters.environment) metricsParams.set('environment', state.filters.environment);
  if (state.filters.status) metricsParams.set('status', state.filters.status);

  const traceQuery = queryFromFilters({ includePagination: true });
  const requests = await Promise.allSettled([
    requestJSON(`${OBS}/metrics?${metricsParams}`, { label: 'GET /observability/metrics' }),
    requestJSON(`${OBS}/traces?${traceQuery}`, { label: 'GET /observability/traces' }),
    requestJSON(`${OBS}/conversations?${conversationQuery()}`, { label: 'GET /observability/conversations' }),
  ]);
  if (requests[0].status === 'fulfilled') state.metrics = requests[0].value;
  else if (!quiet) toast(`Métricas: ${requests[0].reason.message}`);
  if (requests[1].status === 'fulfilled') {
    state.traces = requests[1].value.traces || [];
    state.traceTotal = requests[1].value.total || 0;
  } else if (!quiet) toast(`Traces: ${requests[1].reason.message}`);
  if (requests[2].status === 'fulfilled') {
    state.conversations = requests[2].value.conversations || [];
    state.conversationTotal = requests[2].value.total || 0;
  } else if (!quiet) toast(`Conversas: ${requests[2].reason.message}`);
  renderAll();
}

function initDateFilters() {
  const now = new Date();
  const from = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  $('date-from').value = toLocalDate(from);
  $('date-to').value = toLocalDate(now);
  state.filters.from = from.toISOString();
  state.filters.to = now.toISOString();
}

function toLocalDate(date) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function applyDatePreset() {
  const preset = $('period-filter').value;
  if (preset === 'custom') return;
  const days = preset === '7d' ? 7 : preset === '30d' ? 30 : 1;
  const now = new Date();
  const start = new Date(now.getTime() - days * 86400000);
  $('date-from').value = toLocalDate(start);
  $('date-to').value = toLocalDate(now);
}

function dateInputBounds() {
  const from = $('date-from').value ? new Date(`${$('date-from').value}T00:00:00`) : null;
  const to = $('date-to').value ? new Date(`${$('date-to').value}T23:59:59.999`) : null;
  return { from: from?.toISOString() || null, to: to?.toISOString() || null };
}

function applyFilters() {
  const preset = $('period-filter').value;
  const now = new Date();
  let dateBounds;
  if (preset === 'custom') {
    dateBounds = dateInputBounds();
  } else {
    const days = preset === '7d' ? 7 : preset === '30d' ? 30 : 1;
    dateBounds = { from: new Date(now.getTime() - days * 86400000).toISOString(), to: now.toISOString() };
  }
  state.filters = {
    ...dateBounds,
    consumer: $('consumer-filter').value.trim(),
    conversation: $('conversation-filter').value.trim(),
    environment: $('environment-filter').value,
    status: $('status-filter').value,
  };
  state.traceOffset = 0;
  state.conversationOffset = 0;
  loadData();
}

function renderAll() {
  renderMetrics();
  renderTraceTables();
  renderConversations();
  renderActiveStatus();
  renderLiveEvents();
  if (state.view === 'traces' && state.selectedTrace) renderTraceDetail();
  if (state.view === 'conversations' && state.selectedConversation) renderConversationDetail();
}

function renderMetrics() {
  const metrics = state.metrics;
  if (!metrics) return;
  renderSLOMetrics(metrics.slos);
  $('metric-runs').textContent = number(metrics.traces?.count);
  $('metric-p95').textContent = duration(metrics.traces?.latency?.p95_ms);
  $('metric-latency-samples').textContent = `${number(metrics.traces?.latency?.sample_count)} amostras de turno`;
  const errorRate = metrics.traces?.error_rate;
  $('metric-errors').textContent = errorRate == null ? '—' : `${number(errorRate * 100, 2)}%`;
  $('metric-error-count').textContent = `${number(metrics.traces?.error_count)} execuções com erro`;
  const traceCount = metrics.traces?.count || 0;
  const completedTraceCount = metrics.traces?.completed_count || 0;
  const completedTraceRate = traceCount ? completedTraceCount / traceCount : null;
  $('metric-success').textContent = completedTraceRate == null ? '—' : `${number(completedTraceRate * 100, 2)}%`;
  $('metric-success-count').textContent = `${number(completedTraceCount)} de ${number(traceCount)} traces concluídos`;
  const modelGroups = Object.values(metrics.models || {});
  const completedModelCalls = modelGroups.reduce((total, model) => total + (model.completed_count || 0), 0);
  const modelErrors = modelGroups.reduce((total, model) => total + (model.error_count || 0), 0);
  const terminalModelCalls = completedModelCalls + modelErrors;
  const modelSuccessRate = terminalModelCalls ? completedModelCalls / terminalModelCalls : null;
  $('metric-model-success').textContent = modelSuccessRate == null ? '—' : `${number(modelSuccessRate * 100, 2)}%`;
  $('metric-model-success-count').textContent = `${number(completedModelCalls)} de ${number(terminalModelCalls)} chamadas terminais concluídas`;
  const tokens = metrics.tokens || {};
  const totalTokens = (tokens.input_tokens || 0) + (tokens.output_tokens || 0);
  $('metric-tokens').textContent = tokens.input_tokens == null && tokens.output_tokens == null ? '—' : number(totalTokens);
  $('metric-token-calls').textContent = `${number(tokens.llm_calls)} chamadas · ${number(tokens.calls_without_usage)} sem uso informado`;
  renderComponentChart(metrics.components || {});
  renderModels(metrics.models || {});
  const cost = metrics.cost || {};
  $('metric-cost-per-turn').textContent = cost.cost_per_completed_trace_usd == null
    ? '—'
    : `US$ ${number(cost.cost_per_completed_trace_usd, 6)}`;
  $('metric-cost-per-turn-note').textContent = cost.completed_trace_count > 0
    ? `${number(cost.completed_trace_count)} turnos · GPT-6 Luna, entrada sem cache`
    : 'Sem turnos concluídos com custo estimável';
  $('cost-note').textContent = cost.estimated_total_usd == null
    ? `Custo do LLM não estimado para o período: ${number(cost.unpriced_calls)} chamadas sem preço/uso completo.`
    : `Custo estimado do LLM: US$ ${number(cost.estimated_total_usd, 6)} · ${number(cost.priced_calls)} chamadas precificadas; entrada sem cache.`;
  renderApplicationCost(metrics.application_cost || {});
}

function renderApplicationCost(applicationCost) {
  const total = applicationCost.estimated_total_usd;
  const coverageComplete = applicationCost.coverage_complete === true;
  const formattedTotal = !coverageComplete
    ? 'Cobertura parcial'
    : total == null ? 'Incompleto' : `US$ ${number(total, 6)}`;
  const tier = applicationCost.embedding_tier === 'paid' ? 'Gemini pago' : 'Gemini gratuito';
  $('metric-app-cost').textContent = coverageComplete && total != null ? formattedTotal : '—';
  $('metric-app-cost-note').textContent = `${tier} · ${number(applicationCost.unpriced_calls)} chamadas sem uso/preço`;
  $('application-cost-total').textContent = formattedTotal;
  const coverageStart = applicationCost.coverage_start_at
    ? `medição completa desde ${dateTime(applicationCost.coverage_start_at)}`
    : 'início da medição indisponível';
  $('application-cost-scope').textContent = `Período selecionado · todos os ambientes · sem filtros de usuário/status · GPT sem cache · ${tier} · ${coverageStart}`;

  const origins = applicationCost.origins || [];
  $('cost-origin-rows').innerHTML = origins.length ? origins.map((origin) => {
    const cost = origin.estimated_cost_usd == null
      ? `Incompleto · ${number(origin.unpriced_calls)} sem uso/preço`
      : `US$ ${number(origin.estimated_cost_usd, 6)}`;
    const inputTokens = origin.input_tokens == null ? '—' : number(origin.input_tokens);
    const outputTokens = origin.output_tokens == null ? '—' : number(origin.output_tokens);
    return `<tr><td>${escapeHTML(origin.label || origin.source)}</td><td title="${escapeHTML(origin.model)}">${escapeHTML(shortId(origin.model, 32))}</td><td>${number(origin.calls)}</td><td>${inputTokens}</td><td>${outputTokens}</td><td>${cost}</td></tr>`;
  }).join('') : '<tr><td colspan="6" class="empty-cell">Sem chamadas registradas no período.</td></tr>';
}

function renderSLOMetrics(slos) {
  if (!slos) return;
  const window = slos.window || {};
  const environment = window.environment ? `Ambiente: ${window.environment}` : 'Todos os ambientes';
  $('slo-window-label').textContent = window.started_at && window.ended_at
    ? `${dateTime(window.started_at)} – ${dateTime(window.ended_at)} · ${environment}`
    : 'Últimos 28 dias';

  const completion = slos.turn_completion || {};
  renderSLOStatus('slo-completion-status', completion.status);
  $('slo-completion-value').textContent = formatSLORate(completion.actual_rate);
  $('slo-completion-target').textContent = `Meta ≥ ${number(completion.target_rate * 100, 2)}%`;
  $('slo-completion-budget').textContent = sloBudgetLabel(completion);
  $('slo-completion-samples').textContent = `${number(completion.good_count)} concluídos de ${number(completion.total_count)} turnos terminais`;
  renderSLOProgress('slo-completion-progress', completion);

  const latency = slos.turn_latency || {};
  renderSLOStatus('slo-latency-status', latency.status);
  $('slo-latency-value').textContent = latency.p95_ms == null
    ? (latency.total_count ? 'Sem duração registrada' : 'Sem dados')
    : duration(latency.p95_ms);
  $('slo-latency-target').textContent = `Meta p95 ≤ ${duration(latency.target_p95_ms)}`;
  $('slo-latency-rate').textContent = `${formatSLORate(latency.actual_rate)} dos turnos dentro do limite de ${duration(latency.target_p95_ms)}`;
  $('slo-latency-budget').textContent = sloBudgetLabel(latency);
  $('slo-latency-samples').textContent = `${number(latency.good_count)} dentro do limite de ${number(latency.total_count)} turnos · ${number(latency.duration_sample_count)} durações registradas`;
  renderSLOProgress('slo-latency-progress', latency);

  const models = Object.values(slos.models || {});
  $('slo-model-rows').innerHTML = models.length ? models.map((model) => {
    const status = safeSLOStatus(model.status);
    return `<tr><td title="${escapeHTML(model.model)}">${escapeHTML(shortId(model.model, 28))}</td><td>${formatSLORate(model.actual_rate)}</td><td>${number(model.target_rate * 100, 2)}%</td><td>${escapeHTML(sloBudgetLabel(model))}</td><td>${number(model.total_count)}</td><td><span class="slo-status ${status}">${sloStatusLabel(status)}</span></td></tr>`;
  }).join('') : '<tr><td colspan="6" class="empty-cell">Sem chamadas LLM terminais na janela.</td></tr>';
}

function formatSLORate(rate) {
  return rate == null ? 'Sem dados' : `${number(rate * 100, 2)}%`;
}

function sloBudgetLabel(metric) {
  if (metric.total_count === 0 || metric.error_budget_consumed_pct == null) return 'Sem orçamento calculado';
  const consumed = metric.error_budget_consumed_pct;
  return consumed > 100
    ? `Orçamento excedido em ${number(consumed - 100, 1)}%`
    : `Orçamento usado ${number(consumed, 1)}% · restante ${number(metric.error_budget_remaining_pct, 1)}%`;
}

function safeSLOStatus(status) {
  return ['met', 'breached', 'no_data'].includes(status) ? status : 'no_data';
}

function renderSLOStatus(elementId, status) {
  const safeStatus = safeSLOStatus(status);
  const element = $(elementId);
  element.className = `slo-status ${safeStatus}`;
  element.textContent = sloStatusLabel(safeStatus);
}

function sloStatusLabel(status) {
  return ({ met: 'Dentro da meta', breached: 'Meta violada', no_data: 'Sem dados' })[status] || 'Sem dados';
}

function renderSLOProgress(elementId, metric) {
  const bar = $(elementId);
  const track = bar.parentElement;
  const value = metric.error_budget_consumed_pct;
  const safeStatus = safeSLOStatus(metric.status);
  const width = value == null ? 0 : Math.max(0, Math.min(value, 100));
  track.className = `slo-progress ${safeStatus}`;
  track.setAttribute('aria-valuenow', String(width));
  bar.style.width = `${width}%`;
}

function renderComponentChart(components) {
  const entries = Object.entries(components).map(([name, data]) => ({ name, ...data })).sort((a, b) => (b.latency?.average_ms || 0) - (a.latency?.average_ms || 0));
  if (!entries.length) {
    $('component-chart').innerHTML = '<p class="chart-empty">Sem spans no intervalo selecionado.</p>';
    return;
  }
  const max = Math.max(...entries.map((entry) => entry.latency?.average_ms || 0), 1);
  $('component-chart').innerHTML = entries.slice(0, 9).map((entry) => {
    const value = entry.latency?.average_ms;
    const width = value == null ? 0 : Math.max(3, value / max * 100);
    return `<div class="bar-row"><span title="${escapeHTML(entry.name)}">${escapeHTML(entry.name)}</span><div class="bar-track"><i style="width:${width}%"></i></div><strong>${duration(value)}</strong></div>`;
  }).join('');
}

function renderModels(models) {
  const rows = Object.values(models);
  $('model-rows').innerHTML = rows.length ? rows.map((model) => {
    const tokenTotal = model.input_tokens == null && model.output_tokens == null ? null : (model.input_tokens || 0) + (model.output_tokens || 0);
    const terminalCalls = (model.completed_count || 0) + (model.error_count || 0);
    const successRate = terminalCalls ? `${number(model.completed_count / terminalCalls * 100, 2)}%` : '—';
    return `<tr><td title="${escapeHTML(model.model)}">${escapeHTML(shortId(model.model, 24))}</td><td>${number(model.calls)}</td><td>${number(tokenTotal)}</td><td>${duration(model.latency?.p95_ms)}</td><td>${successRate}</td></tr>`;
  }).join('') : '<tr><td colspan="5" class="empty-cell">Sem chamadas de modelo com uso registrado.</td></tr>';
}

function activeTraceAsSummary(active) {
  return { trace_id: active.trace_id, conversation_id: active.conversation_id, environment: active.environment, started_at: active.started_at, status: 'running', duration_ms: null };
}

function filteredActiveTraces() {
  const from = state.filters.from ? new Date(state.filters.from).getTime() : null;
  const to = state.filters.to ? new Date(state.filters.to).getTime() : null;
  return state.activeTraces.filter((trace) => {
    const startedAt = new Date(trace.started_at).getTime();
    if (state.filters.consumer) return false;
    if (state.filters.conversation && trace.conversation_id !== state.filters.conversation) return false;
    if (state.filters.environment && trace.environment !== state.filters.environment) return false;
    if (state.filters.status && state.filters.status !== 'running') return false;
    if (from != null && startedAt < from) return false;
    if (to != null && startedAt > to) return false;
    return true;
  });
}

function mergedTraces() {
  const persistedIds = new Set(state.traces.map((trace) => trace.trace_id));
  const running = filteredActiveTraces().filter((trace) => !persistedIds.has(trace.trace_id)).map(activeTraceAsSummary);
  return [...running, ...state.traces].sort((a, b) => new Date(b.started_at) - new Date(a.started_at));
}

function renderTraceTables() {
  const traces = mergedTraces();
  const rowHtml = traces.map((trace) => {
    const spanCount = state.liveByTrace.get(trace.trace_id)?.filter((event) => event.event_type === 'span').length;
    return `<tr class="clickable-row" data-trace="${escapeHTML(trace.trace_id)}"><td class="trace-id">${escapeHTML(shortId(trace.trace_id))}</td><td class="trace-id">${escapeHTML(shortId(trace.conversation_id))}</td><td>${spanCount ? `${spanCount} eventos de span` : 'Abrir detalhe'}</td><td class="duration">${duration(trace.duration_ms)}</td><td><span class="status-pill ${escapeHTML(trace.status)}">${escapeHTML(statusText(trace.status))}</span></td><td>${dateTime(trace.started_at)}</td></tr>`;
  });
  const empty = '<tr><td colspan="6" class="empty-cell">Nenhum trace encontrado para os filtros atuais.</td></tr>';
  $('recent-traces').innerHTML = rowHtml.length ? rowHtml.slice(0, 8).join('') : empty;
  $('all-traces').innerHTML = rowHtml.join('') || empty;
  $('trace-total').textContent = `${number(state.traceTotal + filteredActiveTraces().length)} traces`;
  $('trace-page-label').textContent = `Página ${Math.floor(state.traceOffset / 50) + 1}`;
  $('trace-prev').disabled = state.traceOffset === 0;
  $('trace-next').disabled = state.traceOffset + state.traces.length >= state.traceTotal;
  $('nav-live-count').textContent = String(state.activeTraces.length);
  document.querySelectorAll('[data-trace]').forEach((row) => row.addEventListener('click', () => openTrace(row.dataset.trace)));
}

function renderConversations() {
  $('conversation-total').textContent = `${number(state.conversationTotal)} conversas`;
  $('conversation-page-label').textContent = `Página ${Math.floor(state.conversationOffset / 50) + 1}`;
  $('conversation-prev').disabled = state.conversationOffset === 0;
  $('conversation-next').disabled = state.conversationOffset + state.conversations.length >= state.conversationTotal;
  $('conversation-items').innerHTML = state.conversations.length ? state.conversations.map((conversation) => {
    const selected = conversation.conversation_id === state.selectedConversationId ? ' selected' : '';
    return `<div class="conversation-item${selected}" data-conversation="${escapeHTML(conversation.conversation_id)}"><strong>${escapeHTML(conversation.title || shortId(conversation.conversation_id, 32))}</strong><small>${escapeHTML(conversation.status)} · atualizado ${dateTime(conversation.updated_at)}</small><div class="conversation-preview">${escapeHTML(conversation.conversation_id)}</div></div>`;
  }).join('') : '<p class="empty-note">Nenhuma conversa encontrada.</p>';
  document.querySelectorAll('[data-conversation]').forEach((item) => item.addEventListener('click', () => openConversation(item.dataset.conversation)));
}

async function openConversation(conversationId, offset = 0, append = false) {
  state.selectedConversationId = conversationId;
  try {
    const detail = await requestJSON(`${OBS}/conversations/${encodeURIComponent(conversationId)}?limit=200&offset=${offset}`, { label: `GET /observability/conversations/{id}` });
    if (append && state.selectedConversation) {
      detail.messages = [...state.selectedConversation.messages, ...detail.messages];
    }
    state.selectedConversation = detail;
    const relatedQuery = new URLSearchParams({ conversation_id: conversationId, limit: '100', offset: '0' });
    const related = await requestJSON(`${OBS}/traces?${relatedQuery}`, { label: 'GET /observability/traces?conversation_id' }).catch(() => ({ traces: [] }));
    state.selectedConversation.traces = related.traces || [];
    renderConversations();
    renderConversationDetail();
  } catch (error) {
    toast(`Não foi possível abrir a conversa: ${error.message}`);
  }
}

function renderConversationDetail() {
  const conversation = state.selectedConversation;
  if (!conversation) return;
  const messages = conversation.messages || [];
  const more = conversation.has_more ? `<button class="button button-secondary" id="load-more-messages">Carregar mensagens anteriores</button>` : '';
  $('conversation-detail').innerHTML = `<div class="conversation-head"><div><h2>${escapeHTML(conversation.conversation_id)}</h2><p>${escapeHTML(conversation.status)} · ${number(messages.length)} mensagens exibidas · atualizada ${dateTime(conversation.updated_at)}</p></div><button class="button button-primary" id="lab-conversation">Abrir no laboratório</button></div><div class="message-list">${messages.map((message) => {
    const canOpenLab = message.role === 'assistant' && message.message_id;
    const attributes = canOpenLab
      ? `role="button" tabindex="0" data-lab-message="${escapeHTML(message.message_id)}" aria-label="Abrir esta resposta no Laboratório"`
      : '';
    const agentLabel = message.consulted_agents?.length
      ? ` · agente ${escapeHTML(message.consulted_agents[0])}`
      : '';
    const hint = canOpenLab ? '<span class="message-lab-hint">Clique para testar no Laboratório ↗</span>' : '';
    return `<article class="message ${escapeHTML(message.role)}${canOpenLab ? ' lab-launch' : ''}" ${attributes}><small>${escapeHTML(message.role)} · ${dateTime(message.created_at)}${agentLabel}</small>${escapeHTML(message.content)}${hint}</article>`;
  }).join('')}</div>${more}<div class="related-traces"><div class="detail-section-title">Traces relacionados <small>${number(conversation.traces?.length)} execuções</small></div>${conversation.traces?.length ? conversation.traces.map((trace) => `<div class="related-trace" data-related-trace="${escapeHTML(trace.trace_id)}"><span class="trace-id">${escapeHTML(shortId(trace.trace_id))}</span><span class="status-pill ${escapeHTML(trace.status)}">${escapeHTML(statusText(trace.status))}</span><small>${duration(trace.duration_ms)} · ${dateTime(trace.started_at)}</small></div>`).join('') : '<p class="empty-note">Nenhum trace associado foi encontrado.</p>'}</div>`;
  const detail = $('conversation-detail');
  $('lab-conversation')?.addEventListener('click', () => openLabFromConversation());
  $('load-more-messages')?.addEventListener('click', () => openConversation(conversation.conversation_id, conversation.next_offset, true));
  detail.querySelectorAll('[data-lab-message]').forEach((message) => {
    const open = () => openLabFromMessage(message.dataset.labMessage);
    message.addEventListener('click', open);
    message.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        open();
      }
    });
  });
  detail.querySelectorAll('[data-related-trace]').forEach((row) => row.addEventListener('click', () => openTrace(row.dataset.relatedTrace)));
}

async function openTrace(traceId) {
  state.selectedTraceId = traceId;
  state.view = 'traces';
  activateView('traces');
  try {
    state.selectedTrace = await requestJSON(`${OBS}/traces/${encodeURIComponent(traceId)}`, { label: 'GET /observability/traces/{id}' });
  } catch (error) {
    if (state.activeTraces.some((trace) => trace.trace_id === traceId)) {
      state.selectedTrace = activeTraceAsSummary(state.activeTraces.find((trace) => trace.trace_id === traceId));
    } else {
      toast(`Não foi possível carregar o trace: ${error.message}`);
      return;
    }
  }
  renderTraceDetail();
  renderTraceTables();
}

function normalizedTraceEvents(trace) {
  const live = state.liveByTrace.get(trace.trace_id) || [];
  const persistedSpans = (trace.spans || []).map((span) => ({
    event_type: 'span', phase: span.status, timestamp: span.ended_at || span.started_at,
    data: { ...span, name: span.name, status: span.status, duration_ms: span.duration_ms },
  }));
  const persistedLogs = (trace.logs || []).map((log) => ({ event_type: 'log', phase: 'recorded', timestamp: log.timestamp, data: log }));
  const all = [...persistedSpans, ...persistedLogs, ...live];
  const unique = new Map();
  for (const event of all) {
    const key = event.event_type === 'span'
      ? `${event.event_type}:${event.data.span_id}:${event.phase}`
      : event.event_type === 'log' ? `log:${event.data.log_id || event.data.sequence}` : `trace:${event.phase}:${event.timestamp}`;
    unique.set(key, event);
  }
  return [...unique.values()].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
}

function traceSpans(trace) {
  const byId = new Map((trace.spans || []).map((span) => [span.span_id, span]));
  for (const event of state.liveByTrace.get(trace.trace_id) || []) {
    if (event.event_type !== 'span' || !event.data?.span_id) continue;
    const previous = byId.get(event.data.span_id) || {};
    byId.set(event.data.span_id, {
      ...previous,
      ...event.data,
      attributes: { ...(previous.attributes || {}), ...(event.data.attributes || {}) },
    });
  }
  return [...byId.values()];
}

function renderTraceDetail() {
  const trace = state.selectedTrace;
  if (!trace) return;
  const events = normalizedTraceEvents(trace);
  const spanEvents = events.filter((event) => event.event_type === 'span');
  const logs = events.filter((event) => event.event_type === 'log');
  const startedAt = new Date(trace.started_at).getTime();
  const timeline = events.map((event) => renderTraceEvent(event, startedAt)).join('');
  const agentSpans = traceSpans(trace).filter((span) => span.kind === 'node' && span.attributes?.agent_id);
  const agentIds = [...new Set(agentSpans.map((span) => span.attributes.agent_id))];
  const labButtons = agentIds.map((agentId) => `<button class="button button-secondary" data-lab-agent="${escapeHTML(agentId)}">Testar ${escapeHTML(agentId)}</button>`).join('');
  const detail = $('trace-detail');
  detail.innerHTML = `<div class="detail-head"><h2>${escapeHTML(trace.trace_id)}</h2><p>Conversa ${escapeHTML(trace.conversation_id)} · ${escapeHTML(trace.environment || 'ambiente não informado')}</p><div class="detail-actions"><span class="status-pill ${escapeHTML(trace.status)}">${escapeHTML(statusText(trace.status))}</span><span class="subtle-label">${duration(trace.duration_ms)} · início ${dateTime(trace.started_at)}</span></div>${labButtons ? `<div class="detail-actions">${labButtons}</div>` : ''}</div><div class="detail-section-title">Fluxo do trace <small>${number(spanEvents.length)} eventos de span · ${number(logs.length)} logs</small></div><div class="timeline">${timeline || '<p class="empty-note">Aguardando spans e logs.</p>'}</div>`;
  detail.querySelectorAll('[data-lab-agent]').forEach((button) => button.addEventListener('click', () => openLabFromTrace(button.dataset.labAgent)));
}

function renderTraceEvent(event, traceStartedAt) {
  const data = event.data || {};
  const elapsed = Math.max(0, new Date(event.timestamp).getTime() - traceStartedAt);
  if (event.event_type === 'log') {
    return `<div class="timeline-item log"><div class="timeline-top"><strong>LOG ${escapeHTML(data.level || 'INFO')} · ${escapeHTML(data.logger || 'src')}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-body">${escapeHTML(data.message || '')}</div><div class="timeline-meta">${escapeHTML(data.agent_id || 'sem agent_id')} · span ${escapeHTML(shortId(data.span_id || '—'))} · ${dateTime(event.timestamp)}</div></div>`;
  }
  if (event.event_type === 'trace') {
    return `<div class="timeline-item"><div class="timeline-top"><strong>TRACE ${escapeHTML(statusText(event.phase))}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-meta">${dateTime(event.timestamp)}${data.duration_ms != null ? ` · duração ${duration(data.duration_ms)}` : ''}</div></div>`;
  }
  const failed = event.phase === 'error' || data.status === 'error';
  const identity = data.attributes?.agent_id || data.model || data.kind || 'componente';
  if (data.kind === 'tool') {
    const toolSummary = data.attributes || {};
    const toolStatusLabels = { success: 'sucesso', partial: 'parcial', error: 'erro' };
    const summaryFields = [
      toolSummary.tool_status && `Status: ${toolStatusLabels[toolSummary.tool_status] || toolSummary.tool_status}`,
      toolSummary.tool_results_count != null && `Resultados: ${number(toolSummary.tool_results_count)}`,
      toolSummary.tool_evidence_count != null && `Evidências: ${number(toolSummary.tool_evidence_count)}`,
      toolSummary.tool_error_code && `Código de erro: ${toolSummary.tool_error_code}`,
      data.error_type && `Tipo de erro: ${data.error_type}`,
    ].filter(Boolean);
    const summaryDetails = summaryFields.length
      ? `<div class="tool-summary-details">${summaryFields.map((field) => `<div class="timeline-meta">${escapeHTML(field)}</div>`).join('')}</div>`
      : '<div class="tool-summary-details"><div class="timeline-meta">Resumo não disponível para este span.</div></div>';
    return `<details class="timeline-item tool-span ${failed ? 'error' : ''}"><summary><div class="timeline-top"><strong>${escapeHTML(data.name || 'tool')} · ${escapeHTML(event.phase)}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-meta">${escapeHTML(identity)} · tool · ${duration(data.duration_ms)} · ${dateTime(event.timestamp)} <span class="tool-disclosure">ver resumo</span></div></summary>${summaryDetails}</details>`;
  }
  return `<div class="timeline-item ${failed ? 'error' : ''}"><div class="timeline-top"><strong>${escapeHTML(data.name || data.kind || 'span')} · ${escapeHTML(event.phase)}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-meta">${escapeHTML(identity)} · ${escapeHTML(data.kind || 'span')} · ${duration(data.duration_ms)} · ${dateTime(event.timestamp)}</div>${data.error_type ? `<div class="timeline-meta">Erro: ${escapeHTML(data.error_type)}</div>` : ''}${data.input_tokens != null || data.output_tokens != null ? `<div class="timeline-meta">Tokens: ${number(data.input_tokens)} entrada / ${number(data.output_tokens)} saída</div>` : ''}</div>`;
}

function renderLiveEvents() {
  $('live-event-count').textContent = String(state.liveEvents.length);
  const events = state.liveEvents.slice(0, 40);
  $('live-events').innerHTML = events.length ? events.map((event) => {
    const label = event.event_type === 'log' ? `${event.data.level || 'INFO'} ${event.data.logger || 'log'}` : event.event_type === 'span' ? `${event.data.name || event.data.kind} · ${event.phase}` : `Trace · ${event.phase}`;
    const detail = event.event_type === 'log' ? event.data.message : event.data.agent_id || event.data.attributes?.agent_id || event.data.model || event.data.duration_ms != null && duration(event.data.duration_ms) || event.conversation_id;
    return `<div class="event-row"><time>${new Date(event.timestamp).toLocaleTimeString('pt-BR')}</time><div><strong>${escapeHTML(label)}</strong>${escapeHTML(shortId(event.trace_id))}<small>${escapeHTML(String(detail || ''))}</small></div></div>`;
  }).join('') : '<p class="empty-note">Aguardando eventos da API.</p>';
}

function renderFetchHistory() {
  $('fetch-history').innerHTML = state.fetches.length ? state.fetches.map((fetch) => `<div class="fetch-row"><strong>${escapeHTML(fetch.label)}</strong><span class="${fetch.ok ? 'fetch-ok' : 'fetch-error'}">${number(fetch.elapsedMs, 1)} ms · ${escapeHTML(fetch.statusText)}</span><small>${fetch.startedAt.toLocaleString('pt-BR')}</small></div>`).join('') : '<p class="empty-note">Nenhuma consulta realizada.</p>';
  const latest = state.fetches[0];
  if (latest?.label === 'GET /observability/traces/live') {
    $('poll-label').textContent = `Feed 4s · última ${latest.startedAt.toLocaleTimeString('pt-BR')} · ${number(latest.elapsedMs, 1)} ms`;
  }
}

function renderActiveStatus() {
  $('nav-live-count').textContent = String(state.activeTraces.length);
  $('environment-label').textContent = state.filters.environment || 'Todos os ambientes';
}

async function pollLiveFeed() {
  if (state.pollBusy) return;
  state.pollBusy = true;
  try {
    const feed = await requestJSON(`${OBS}/traces/live?after=${state.cursor}&limit=500`, { label: 'GET /observability/traces/live' });
    if (feed.reset_required) {
      state.liveEvents = [];
      state.liveByTrace.clear();
    }
    for (const event of feed.events || []) {
      state.liveEvents.unshift(event);
      const existing = state.liveByTrace.get(event.trace_id) || [];
      existing.push(event);
      state.liveByTrace.set(event.trace_id, existing.slice(-500));
      if (event.event_type === 'trace' && ['completed', 'error'].includes(event.phase)) {
        setTimeout(() => loadData({ quiet: true }), 100);
        if (state.selectedTraceId === event.trace_id) {
          setTimeout(() => openTrace(event.trace_id), 150);
        }
      }
    }
    state.liveEvents = state.liveEvents.slice(0, 150);
    state.activeTraces = feed.active_traces || [];
    state.cursor = feed.next_cursor;
    renderTraceTables();
    renderActiveStatus();
    renderLiveEvents();
    if (state.selectedTraceId && state.view === 'traces') renderTraceDetail();
  } catch {
    $('poll-label').textContent = 'Feed ao vivo indisponível';
  } finally {
    state.pollBusy = false;
  }
}

function activateView(view) {
  state.view = view;
  document.querySelectorAll('.page-view').forEach((section) => section.classList.toggle('active', section.id === `view-${view}`));
  document.querySelectorAll('.nav-item[data-view]').forEach((button) => button.classList.toggle('active', button.dataset.view === view));
  $('breadcrumb').textContent = ({ overview: 'Visão geral', traces: 'Trace Explorer', conversations: 'Conversas', lab: 'Laboratório' })[view];
  history.replaceState(null, '', `#${view}`);
}

function formatLabMessages(messages) {
  return messages.map(({ role, content }) => `${role === 'user' ? 'Usuário' : 'Assistente'}: ${content}`).join('\n');
}

function parseLabMessages(value) {
  const transcript = value.replace(/\r\n/g, '\n');
  const markers = [...transcript.matchAll(/^(Usuário|Assistente):[ \t]*/gm)];
  const messages = markers.map((marker, index) => ({
    role: marker[1] === 'Usuário' ? 'user' : 'assistant',
    content: transcript.slice(marker.index + marker[0].length, markers[index + 1]?.index ?? transcript.length).trim(),
  })).filter((message) => message.content);
  if (!markers.length && transcript.trim()) {
    throw new Error('Use “Usuário:” ou “Assistente:” no início de cada mensagem.');
  }
  return messages;
}

async function loadLabModels(preferredModelId = null, { notifyError = false } = {}) {
  const select = $('lab-model-id');
  if (state.labModelsLoaded) {
    if (preferredModelId && state.labModels.some((model) => model.model_id === preferredModelId)) {
      select.value = preferredModelId;
    }
    return state.labModels.length > 0;
  }
  try {
    const catalog = await requestJSON(`${OBS}/lab/models`, { label: 'GET /observability/lab/models' });
    state.labModels = catalog.models || [];
    state.labModelsLoaded = true;
    select.replaceChildren(...state.labModels.map((model) => new Option(`${model.label} (${model.model_id})`, model.model_id)));
    select.value = state.labModels.some((model) => model.model_id === preferredModelId)
      ? preferredModelId
      : catalog.default_model_id;
    return state.labModels.length > 0;
  } catch (error) {
    select.replaceChildren(new Option('Modelos indisponíveis', ''));
    if (notifyError) toast(`Não foi possível carregar os modelos: ${error.message}`);
    return false;
  }
}

async function loadAgentPrompt(agentId = $('lab-agent-id').value.trim(), { messages, notify = true } = {}) {
  if (!agentId) {
    if (notify) toast('Selecione uma resposta de agente ou informe um agent_id.');
    return false;
  }
  $('lab-agent-id').value = agentId;
  $('lab-agent-caption').textContent = 'Carregando prompt do agente…';
  state.labLoadedAgent = null;
  let history = messages;
  if (!history) {
    try {
      history = parseLabMessages($('lab-messages').value);
    } catch {
      history = [];
    }
  }
  try {
    const config = await requestJSON(`${OBS}/agents/${encodeURIComponent(agentId)}`, { label: 'GET /observability/agents/{id}' });
    $('lab-agent-id').value = config.agent_id;
    $('lab-prompt').value = config.system_prompt;
    $('lab-messages').value = formatLabMessages(history);
    updateLabMessageCount();
    $('lab-agent-caption').textContent = `${config.name} · ${config.role} · versão ${config.version}`;
    state.labLoadedAgent = config.agent_id;
    if (notify) toast('Prompt e histórico carregados como rascunho.');
    return true;
  } catch (error) {
    $('lab-agent-caption').textContent = 'O prompt deste agente não pôde ser carregado.';
    if (notify) toast(`Não foi possível carregar o prompt: ${error.message}`);
    return false;
  }
}

async function openConversationForLab(conversationId) {
  try {
    const conversation = await requestJSON(`${OBS}/conversations/${encodeURIComponent(conversationId)}?limit=200&offset=0`, { label: 'GET /observability/conversations/{id}' });
    state.selectedConversationId = conversationId;
    state.selectedConversation = conversation;
    return conversation;
  } catch (error) {
    toast(`Histórico da conversa indisponível: ${error.message}`);
    return null;
  }
}

async function openLabFromMessage(messageId) {
  const conversation = state.selectedConversation;
  const messageIndex = (conversation?.messages || []).findIndex((message) => message.message_id === messageId);
  if (!conversation || messageIndex < 0) return toast('Não foi possível localizar essa resposta na conversa.');
  const message = conversation.messages[messageIndex];
  const traceId = messageId.endsWith(':assistant') ? messageId.slice(0, -':assistant'.length) : null;
  if (!traceId) return toast('Essa resposta não possui correlação com um trace.');

  let trace;
  try {
    trace = await requestJSON(`${OBS}/traces/${encodeURIComponent(traceId)}`, { label: 'GET /observability/traces/{id}' });
  } catch (error) {
    return toast(`Trace da resposta indisponível: ${error.message}`);
  }
  const tracedAgentIds = new Set(traceSpans(trace)
    .filter((span) => span.kind === 'node' && span.attributes?.agent_id)
    .map((span) => span.attributes.agent_id));
  const agentId = (message.consulted_agents || []).find((id) => tracedAgentIds.has(id))
    || ['faq_rag', 'product_workflow'].find((id) => tracedAgentIds.has(id));
  if (!agentId) return toast('O trace desse turno não identificou um agente especialista.');

  const llmSpan = traceSpans(trace).find((span) => span.kind === 'llm' && span.attributes?.agent_id === agentId && span.model);
  await loadLabModels(llmSpan?.model);
  const history = conversation.messages.slice(0, messageIndex + 1).map(({ role, content }) => ({ role, content }));
  $('lab-agent-id').value = agentId;
  $('lab-prompt').value = '';
  $('lab-messages').value = formatLabMessages(history);
  updateLabMessageCount();
  await loadAgentPrompt(agentId, { messages: history, notify: false });
  state.selectedTrace = trace;
  state.selectedTraceId = trace.trace_id;
  activateView('lab');
  toast(`Turno carregado com o agente ${agentId}. Edite o contexto e execute.`);
}

async function openLabFromTrace(agentId) {
  const trace = state.selectedTrace || {};
  const llmSpan = traceSpans(trace).find((span) => span.kind === 'llm' && span.attributes?.agent_id === agentId && span.model);
  await loadLabModels(llmSpan?.model);
  const conversation = trace.conversation_id ? await openConversationForLab(trace.conversation_id) : null;
  const targetMessageId = `${trace.trace_id}:assistant`;
  const targetIndex = (conversation?.messages || []).findIndex((message) => message.message_id === targetMessageId);
  const sourceMessages = conversation?.messages || [];
  const history = targetIndex >= 0 ? sourceMessages.slice(0, targetIndex + 1) : sourceMessages;
  $('lab-agent-id').value = agentId;
  $('lab-prompt').value = '';
  $('lab-messages').value = formatLabMessages(history);
  updateLabMessageCount();
  await loadAgentPrompt(agentId, { messages: history, notify: false });
  activateView('lab');
}

async function openLabFromConversation() {
  const latestAssistant = [...(state.selectedConversation?.messages || [])].reverse()
    .find((message) => message.role === 'assistant' && message.message_id);
  if (!latestAssistant) return toast('A conversa ainda não tem uma resposta de agente para testar.');
  await openLabFromMessage(latestAssistant.message_id);
}

async function runLab() {
  const modelId = $('lab-model-id').value;
  const prompt = $('lab-prompt').value.trim();
  let messages;
  try {
    messages = parseLabMessages($('lab-messages').value);
  } catch (error) {
    return toast(error.message);
  }
  if (!prompt || !modelId || !messages.some((message) => message.role === 'user')) return toast('Preencha o prompt, modelo e ao menos uma mensagem de usuário.');
  $('lab-result').textContent = 'Executando modelo…';
  $('lab-run-time').textContent = 'Em execução';
  const started = performance.now();
  try {
    const result = await requestJSON(`${OBS}/lab/run`, { method: 'POST', body: { model_id: modelId, prompt, messages }, label: 'POST /observability/lab/run' });
    $('lab-result').textContent = result.result;
    $('lab-run-time').textContent = `${duration(performance.now() - started)} · chamada direta ao modelo`;
  } catch (error) {
    $('lab-result').textContent = error.message;
    $('lab-run-time').textContent = 'Falha na execução';
  }
}

function updateLabMessageCount() {
  let count = 0;
  try { count = parseLabMessages($('lab-messages').value).length; } catch { /* keep the count at zero while the draft is incomplete */ }
  $('lab-message-count').textContent = `${count} ${count === 1 ? 'mensagem' : 'mensagens'}`;
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').classList.add('show');
  setTimeout(() => $('toast').classList.remove('show'), 3200);
}

document.querySelectorAll('[data-view]').forEach((button) => button.addEventListener('click', (event) => {
  const view = event.currentTarget.dataset.view;
  if (view) activateView(view);
}));
$('refresh-button').addEventListener('click', () => loadData());
$('apply-filters').addEventListener('click', applyFilters);
$('consumer-filter').addEventListener('keydown', (event) => { if (event.key === 'Enter') applyFilters(); });
$('conversation-filter').addEventListener('keydown', (event) => { if (event.key === 'Enter') applyFilters(); });
$('period-filter').addEventListener('change', applyDatePreset);
$('date-from').addEventListener('change', () => { $('period-filter').value = 'custom'; });
$('date-to').addEventListener('change', () => { $('period-filter').value = 'custom'; });
$('environment-filter').addEventListener('change', () => $('environment-label').textContent = $('environment-filter').value || 'Todos os ambientes');
$('trace-prev').addEventListener('click', () => { state.traceOffset = Math.max(0, state.traceOffset - 50); loadData({ quiet: true }); });
$('trace-next').addEventListener('click', () => { state.traceOffset += 50; loadData({ quiet: true }); });
$('conversation-prev').addEventListener('click', () => { state.conversationOffset = Math.max(0, state.conversationOffset - 50); loadData({ quiet: true }); });
$('conversation-next').addEventListener('click', () => { state.conversationOffset += 50; loadData({ quiet: true }); });
$('load-agent-prompt').addEventListener('click', () => loadAgentPrompt());
$('run-lab').addEventListener('click', runLab);
$('lab-messages').addEventListener('input', updateLabMessageCount);

initDateFilters();
const initialView = location.hash.slice(1);
if (['overview', 'traces', 'conversations', 'lab'].includes(initialView)) activateView(initialView);
loadData();
loadLabModels();
pollLiveFeed();
setInterval(pollLiveFeed, 4000);
