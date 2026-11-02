import './style.css';
import './overrides.css';

const configuredAPI = import.meta.env.VITE_API_BASE_URL?.trim();
const apiBase = configuredAPI || (import.meta.env.PROD
  ? 'https://api-chatbot-gdox.onrender.com/api/v1'
  : '/api/v1');
const API = /\/api\/v1\/?$/i.test(apiBase)
  ? apiBase.replace(/\/+$/, '')
  : `${apiBase.replace(/\/+$/, '')}/api/v1`;
const OBS = `${API}/observability`;
const TAB_KEY = 'observability-tab';
let authState = 'anonymous';
const state = {
  view: 'overview',
  metrics: null,
  metricsLoadError: '',
  traces: [],
  traceTotal: 0,
  traceLoadError: '',
  lastTurn: null,
  lastTurnLoadError: false,
  lastTurnLoading: false,
  lastTurnLoadSeq: 0,
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
  loadSeq: 0,
  traceStatus: null,
  filters: { from: null, to: null, consumer: '', conversation: '', status: '' },
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
const usd = (value) => {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const amount = Number(value);
  const minimumFractionDigits = Math.abs(amount) >= 0.01 || amount === 0 ? 2 : 0;
  const maximumFractionDigits = minimumFractionDigits === 2 ? 2 : 8;
  return `US$ ${amount.toLocaleString('pt-BR', { minimumFractionDigits, maximumFractionDigits })}`;
};
const duration = (value) => value == null ? '—' : value < 1000 ? `${number(value, 1)} ms` : `${number(value / 1000, 2)} s`;
const statusText = (status) => ({ completed: 'Concluído', error: 'Erro', running: 'Em andamento', interrupted: 'Interrompido' }[status] || status || '—');
const attributeLine = (attributes) => {
  if (!attributes || typeof attributes !== 'object') return '';
  const hidden = new Set(['langgraph_node', 'agent_id', 'prompt_version']);
  const parts = Object.entries(attributes)
    .filter(([key, value]) => !hidden.has(key) && value != null && value !== '')
    .map(([key, value]) => `${key}: ${value}`);
  return parts.length ? `<div class="timeline-meta">${escapeHTML(parts.join(' · '))}</div>` : '';
};

async function requestJSON(path, { method = 'GET', body } = {}) {
  const started = authState;
  try {
    const response = await fetch(path, {
      method,
      credentials: 'include',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      const detail = typeof payload.detail === 'string' ? payload.detail : 'Sessão de observabilidade ausente.';
      if (path.endsWith('/login')) showLogin(detail);
      else if (started === 'active' && authState === 'active') {
        authState = 'anonymous';
        sessionStorage.removeItem(TAB_KEY);
        showLogin();
      }
      const error = new Error(detail);
      error.status = 401;
      throw error;
    }
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : `HTTP ${response.status}`;
      throw new Error(detail);
    }
    setApiStatus(true);
    if (started === 'active' && authState === 'active') hideLogin();
    return payload;
  } catch (error) {
    if (error.status !== 401) setApiStatus(false);
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

function advanceOpenWindow() {
  if ($('period-filter').value === 'custom') return;
  const now = new Date();
  state.filters.to = now.toISOString();
  $('date-to').value = toLocalDate(now);
}

async function loadData({ quiet = false } = {}) {
  const seq = ++state.loadSeq;
  const metricsParams = new URLSearchParams();
  metricsParams.set('started_from', state.filters.from || new Date(Date.now() - 86400000).toISOString());
  metricsParams.set('started_to', state.filters.to || new Date().toISOString());
  if (state.filters.consumer) metricsParams.set('consumer_id', state.filters.consumer);
  if (state.filters.conversation) metricsParams.set('conversation_id', state.filters.conversation);
  if (state.filters.status) metricsParams.set('status', state.filters.status);

  const traceQuery = queryFromFilters({ includePagination: true });
  void loadLatestTurn({ quiet });
  const requests = await Promise.allSettled([
    requestJSON(`${OBS}/metrics?${metricsParams}`, { label: 'GET /observability/metrics' }),
    requestJSON(`${OBS}/traces?${traceQuery}`, { label: 'GET /observability/traces' }),
    requestJSON(`${OBS}/conversations?${conversationQuery()}`, { label: 'GET /observability/conversations' }),
  ]);
  if (seq !== state.loadSeq) return false;
  if (requests[0].status === 'fulfilled') {
    state.metrics = requests[0].value;
    state.metricsLoadError = '';
  } else {
    state.metricsLoadError = requests[0].reason.message;
    if (!quiet && requests[0].reason.status !== 401) toast(`Métricas: ${requests[0].reason.message}`);
  }
  if (requests[1].status === 'fulfilled') {
    state.traces = requests[1].value.traces || [];
    state.traceTotal = requests[1].value.total || 0;
    state.traceLoadError = '';
  } else {
    state.traceLoadError = requests[1].reason.message;
    if (!quiet && requests[1].reason.status !== 401) toast(`Traces: ${requests[1].reason.message}`);
  }
  if (requests[2].status === 'fulfilled') {
    state.conversations = requests[2].value.conversations || [];
    state.conversationTotal = requests[2].value.total || 0;
  } else if (!quiet && requests[2].reason.status !== 401) toast(`Conversas: ${requests[2].reason.message}`);
  renderAll();
  return requests[0].status === 'fulfilled';
}

async function loadLatestTurn({ quiet = false } = {}) {
  if (state.lastTurnLoading || authState === 'anonymous') return;
  state.lastTurnLoading = true;
  renderLastTurn();
  const seq = ++state.lastTurnLoadSeq;
  try {
    const latest = await requestJSON(`${OBS}/traces?limit=1&offset=0`, { label: 'GET /observability/traces/latest' });
    if (seq !== state.lastTurnLoadSeq) return;
    const latestTrace = latest.traces?.[0];
    if (!latestTrace) {
      state.lastTurn = null;
      state.lastTurnLoadError = false;
    } else {
      state.lastTurnLoadError = false;
      if (latestTrace.trace_id !== state.lastTurn?.trace_id) {
        state.lastTurn = await requestJSON(`${OBS}/traces/${encodeURIComponent(latestTrace.trace_id)}`, { label: 'GET /observability/traces/latest/{id}' });
        if (seq !== state.lastTurnLoadSeq) return;
      }
    }
  } catch (error) {
    if (seq !== state.lastTurnLoadSeq) return;
    state.lastTurnLoadError = true;
    if (!quiet && error.status !== 401) toast(`Último turno: ${error.message}`);
  } finally {
    if (seq === state.lastTurnLoadSeq) {
      state.lastTurnLoading = false;
      renderLastTurn();
      renderPeriodDataNote();
    }
  }
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
    status: $('status-filter').value,
  };
  state.traceOffset = 0;
  state.conversationOffset = 0;
  loadData();
}

function renderAll() {
  renderLastTurn();
  renderMetrics();
  renderTraceTables();
  renderConversations();
  renderActiveStatus();
  renderLiveEvents();
  renderPeriodDataNote();
  if (state.view === 'traces' && state.selectedTrace) renderTraceDetail();
  if (state.view === 'conversations' && state.selectedConversation) renderConversationDetail();
}

function renderMetrics() {
  const metrics = state.metrics;
  if (!metrics) {
    const reason = state.metricsLoadError
      ? `Não foi possível carregar as métricas: ${state.metricsLoadError}`
      : 'Aguardando dados das métricas.';
    drawSeries($('latency-chart'), [], '#7c3aed', reason);
    drawSeries($('cost-chart'), [], '#0f9f6e', reason);
    $('cost-chart-note').hidden = true;
    $('cost-chart-note').textContent = '';
    renderPeriodDataNote();
    return;
  }
  renderSLOMetrics(metrics.slos);
  $('metric-runs').textContent = number(metrics.traces?.count);
  $('metric-latency-mean').textContent = duration(metrics.traces?.latency?.average_ms);
  $('metric-latency-mean-samples').textContent = `${number(metrics.traces?.latency?.sample_count)} traces com duração registrada`;
  $('metric-p95').textContent = duration(metrics.traces?.latency?.p95_ms);
  $('metric-latency-samples').textContent = `${number(metrics.traces?.latency?.sample_count)} amostras de turno`;
  const errorRate = metrics.traces?.error_rate;
  const traceCount = metrics.traces?.count || 0;
  $('metric-errors').textContent = errorRate == null ? '—' : `${number(errorRate * 100, 2)}%`;
  $('metric-error-count').textContent = `${number(metrics.traces?.error_count)} de ${number(traceCount)} turnos com erro`;
  const completedTraceCount = metrics.traces?.completed_count || 0;
  const completedTraceRate = traceCount ? completedTraceCount / traceCount : null;
  $('metric-success').textContent = completedTraceRate == null ? '—' : `${number(completedTraceRate * 100, 2)}%`;
  $('metric-success-count').textContent = `${number(completedTraceCount)} de ${number(traceCount)} turnos concluídos`;
  const modelGroups = Object.values(metrics.models || {});
  const completedModelCalls = modelGroups.reduce((total, model) => total + (model.completed_count || 0), 0);
  const modelErrors = modelGroups.reduce((total, model) => total + (model.error_count || 0), 0);
  const terminalModelCalls = completedModelCalls + modelErrors;
  const modelSuccessRate = terminalModelCalls ? completedModelCalls / terminalModelCalls : null;
  $('metric-model-success').textContent = modelSuccessRate == null ? '—' : `${number(modelSuccessRate * 100, 2)}%`;
  $('metric-model-success-count').textContent = `${number(completedModelCalls)} de ${number(terminalModelCalls)} chamadas concluídas. Falha de turno não entra aqui.`;
  const tokens = metrics.tokens || {};
  const totalTokens = (tokens.input_tokens || 0) + (tokens.output_tokens || 0);
  const missingUsage = tokens.calls_without_usage || 0;
  const missingUsageNote = missingUsage > 0 ? ` · ${number(missingUsage)} sem uso informado` : '';
  $('metric-tokens').textContent = tokens.input_tokens == null && tokens.output_tokens == null ? '—' : number(totalTokens);
  $('metric-token-calls').textContent = `${number(tokens.input_tokens)} entrada + ${number(tokens.output_tokens)} saída${missingUsageNote}`;
  renderComponentChart(metrics.components || {});
  renderModels(metrics.models || {});
  const cost = metrics.cost || {};
  $('cost-note').textContent = cost.estimated_total_usd == null
    ? `Custo do LLM não estimado para o período: ${number(cost.unpriced_calls)} chamadas sem preço/uso completo.`
    : `Custo estimado do LLM: ${usd(cost.estimated_total_usd)} · ${number(cost.priced_calls)} chamadas precificadas; entrada sem cache.`;
  renderApplicationCost(metrics.application_cost || {});
  renderBoard(metrics.board || {}, metrics);
}

function renderBoard(board, metrics) {
  const banner = $('slo-banner');
  if (board.slo_ok == null) {
    banner.textContent = 'SLO do período: sem turnos suficientes';
    banner.className = 'slo-banner';
  } else if (board.slo_ok) {
    banner.textContent = 'SLO dentro: 95% dos turnos sem erro e p95 até 20 s';
    banner.className = 'slo-banner ok';
  } else {
    banner.textContent = 'SLO estourado: menos de 95% sem erro ou p95 acima de 20 s';
    banner.className = 'slo-banner breached';
  }
  const fallback = metrics.fallback || {};
  const traceCount = metrics.traces?.count || 0;
  if (!traceCount) {
    $('metric-fallbacks').textContent = '—';
    $('metric-fallback-note').textContent = 'Sem traces no período.';
  } else {
    $('metric-fallbacks').textContent = number(fallback.qwen_call_count || 0);
    $('metric-fallback-note').textContent = `${number(fallback.qwen_trace_count || 0)} turnos com Qwen · ${number((fallback.rate || 0) * 100, 2)}% dos traces.`;
  }
  $('metric-model-most-used').textContent = board.most_used_model
    ? `Mais usado: ${board.most_used_model}`
    : 'Mais usado: —';
  const applicationCost = metrics.application_cost || {};
  const resolutionCount = board.resolution_count || 0;
  $('metric-cost-resolution').textContent = usd(board.cost_per_resolution_usd);
  if (applicationCost.conversation_variable_cost_usd == null) {
    $('metric-resolution-note').textContent = 'Custo por turno sem erro indisponível: uso/preço conversacional incompleto ou cobertura parcial.';
  } else if (!resolutionCount) {
    $('metric-resolution-note').textContent = 'Nenhum turno sem erro no período.';
  } else {
    $('metric-resolution-note').textContent = `${number(resolutionCount)} turnos concluídos sem erro no período selecionado · inclui fora de escopo, rejeições e esclarecimentos.`;
  }
  $('metric-cost-conversation').textContent = usd(board.cost_per_conversation_usd);
  $('metric-cost-conversation-note').textContent = board.cost_per_conversation_usd == null
    ? 'Indisponível por cobertura, uso ou preço incompletos.'
    : `Média de ${number(board.conversation_count)} conversas em ${number(board.projection_window_days, 1)} dias de cobertura.`;
  $('metric-weekly-cost-100').textContent = usd(board.weekly_cost_100_users_usd);
  $('metric-weekly-cost-1000').textContent = usd(board.weekly_cost_1000_users_usd);

  const returnRaw = $('roi-return').value;
  const returnValue = Number(returnRaw);
  const totalCost = applicationCost.estimated_total_usd;
  $('metric-net-return').textContent = returnRaw === '' || totalCost == null || !Number.isFinite(returnValue)
    ? '—'
    : usd(returnValue - totalCost);
  if (returnRaw === '' || !Number.isFinite(returnValue)) {
    $('metric-roi').textContent = 'sem retorno informado';
    $('metric-roi-note').textContent = 'Informe o retorno para calcular o ROI estimado.';
  } else if (totalCost == null) {
    $('metric-roi').textContent = 'N/D';
    $('metric-roi-note').textContent = 'Custo de IA indisponível por preço, uso ou cobertura incompletos.';
  } else if (totalCost === 0) {
    $('metric-roi').textContent = 'Indefinido';
    $('metric-roi-note').textContent = 'O custo estimado de IA é zero; não é possível dividir por zero.';
  } else {
    const roi = ((returnValue - totalCost) / totalCost) * 100;
    $('metric-roi').textContent = `${number(roi, 2)}%`;
    $('metric-roi-note').textContent = `(${usd(returnValue)} − ${usd(totalCost)}) / ${usd(totalCost)} × 100.`;
  }

  const projectionNote = $('projection-note');
  if (!board.conversation_count) {
    projectionNote.textContent = 'Projeção indisponível: não há conversas observadas na janela de referência.';
  } else if (board.cost_per_conversation_usd == null) {
    projectionNote.textContent = 'Projeção indisponível: faltam tokens/preços de chamadas ligadas a conversas ou a cobertura de medição é parcial.';
  } else {
    projectionNote.textContent = `Base móvel: ${number(board.conversation_count)} conversas em ${number(board.projection_window_days, 1)} dias de cobertura. Usa ${usd(board.cost_per_conversation_usd)} por conversa e 5 conversas por usuário/semana; independe dos filtros de período. Laboratório e indexação ficam à parte.`;
  }
  const agents = board.agent_latency || [];
  $('agent-latency-rows').innerHTML = agents.length
    ? agents.map((row) => `<tr><td>${escapeHTML(row.name)}</td><td>${duration(row.average_ms)}</td></tr>`).join('')
    : '<tr><td colspan="2" class="empty-cell">Sem nós no período.</td></tr>';
  const latencyPoints = metrics.latency_series || [];
  const latencySamples = metrics.traces?.latency?.sample_count || 0;
  const latencyEmptyReason = state.metricsLoadError
    ? `Não foi possível atualizar as métricas: ${state.metricsLoadError}`
    : traceCount === 0
      ? 'Nenhum trace corresponde aos filtros selecionados neste período.'
      : latencySamples === 0
        ? `${number(traceCount)} trace(s) encontrados, mas nenhum tem duração registrada.`
        : 'A API não retornou pontos diários de latência, apesar de haver amostras.';
  const cost = metrics.cost || {};
  const costEmptyReason = state.metricsLoadError
    ? `Não foi possível atualizar as métricas: ${state.metricsLoadError}`
    : traceCount === 0
      ? 'Nenhum trace corresponde aos filtros selecionados neste período.'
      : (cost.priced_calls || 0) === 0 && (cost.unpriced_calls || 0) > 0
        ? `${number(cost.unpriced_calls)} chamada(s) sem tokens ou preço suficiente para calcular o custo.`
        : (cost.priced_calls || 0) === 0
          ? 'Não houve chamadas de modelo com custo calculável neste período.'
          : 'Há chamadas precificadas, mas a API não retornou a série diária de custo.';
  drawSeries($('latency-chart'), latencyPoints.map((point) => point.duration_ms), '#7c3aed', latencyEmptyReason);
  const costSeries = (cost.priced_calls || 0) > 0
    ? (metrics.cumulative_cost_series || []).map((point) => point.cumulative_cost_usd)
    : [];
  drawSeries($('cost-chart'), costSeries, '#0f9f6e', costEmptyReason);
  const costNote = $('cost-chart-note');
  const partialCost = (cost.priced_calls || 0) > 0 && (cost.unpriced_calls || 0) > 0;
  costNote.hidden = !partialCost;
  costNote.textContent = partialCost
    ? `Série parcial: mostra o subtotal precificado; ${number(cost.unpriced_calls)} chamada(s) não têm preço/uso suficiente para compor o total.`
    : '';
}

function renderLastTurn() {
  if (!$('last-turn-panel')) return;
  const trace = state.lastTurn;
  const statusElement = $('last-turn-status');
  if (!trace) {
    $('last-turn-open-trace').hidden = true;
    statusElement.className = 'last-turn-status no-data';
    statusElement.textContent = state.lastTurnLoadError ? 'Indisponível' : state.lastTurnLoading ? 'Carregando' : 'Sem dados';
    $('last-turn-meta').textContent = state.lastTurnLoadError
      ? 'Não foi possível carregar o trace mais recente.'
      : state.lastTurnLoading
        ? 'Buscando o trace mais recente persistido.'
        : 'Nenhum trace persistido foi encontrado.';
    $('last-turn-duration').textContent = '—';
    $('last-turn-tokens').textContent = '—';
    $('last-turn-tokens-note').textContent = '';
    $('last-turn-cost').textContent = '—';
    $('last-turn-cost-note').textContent = 'Sem chamadas registradas.';
    $('last-turn-route').textContent = '—';
    $('last-turn-outcome').textContent = '—';
    return;
  }

  const spans = Array.isArray(trace.spans) ? trace.spans : [];
  const modelCalls = spans.filter((span) => span.kind === 'llm');
  const usageEvents = Array.isArray(trace.usage_events) ? trace.usage_events : [];
  const calls = [...modelCalls, ...usageEvents];
  const inputTokens = calls.reduce((sum, call) => sum + (Number.isInteger(call.input_tokens) ? call.input_tokens : 0), 0);
  const outputTokens = calls.reduce((sum, call) => sum + (Number.isInteger(call.output_tokens) ? call.output_tokens : 0), 0);
  const callsWithUsage = calls.filter((call) => Number.isInteger(call.input_tokens) || Number.isInteger(call.output_tokens)).length;
  const completeTokens = calls.length > 0 && calls.every((call) => Number.isInteger(call.input_tokens) && Number.isInteger(call.output_tokens));
  $('last-turn-duration').textContent = duration(trace.duration_ms);
  $('last-turn-tokens').textContent = callsWithUsage ? number(inputTokens + outputTokens) : '—';
  $('last-turn-tokens-note').textContent = calls.length
    ? `${number(inputTokens)} entrada · ${number(outputTokens)} saída · ${number(callsWithUsage)} de ${number(calls.length)} chamadas com uso${completeTokens ? '' : ' · parcial'}`
    : 'Nenhuma chamada de modelo registrada.';

  const pricedCalls = calls.filter((call) => call.estimated_cost_usd != null && Number.isFinite(Number(call.estimated_cost_usd)));
  const costComplete = pricedCalls.length === calls.length;
  const totalCost = pricedCalls.reduce((sum, call) => sum + Number(call.estimated_cost_usd), 0);
  $('last-turn-cost').textContent = !calls.length
    ? '—'
    : costComplete
      ? usd(totalCost)
      : pricedCalls.length
        ? `${usd(totalCost)} parcial`
        : 'Incompleto';
  $('last-turn-cost-note').textContent = !calls.length
    ? 'Nenhuma chamada de modelo foi registrada; não há dados para estimar o custo.'
    : costComplete
      ? 'Estimativa calculada a partir das chamadas e preços configurados.'
      : `${number(calls.length - pricedCalls.length)} chamada(s) sem preço/uso completo.`;

  const logs = Array.isArray(trace.logs) ? trace.logs : [];
  const routeLog = logs.find((log) => log.event === 'router_decision_completed');
  const routeValue = routeLog?.attributes?.route;
  const routeLabels = {
    faq: 'FAQ / RAG',
    product_workflow: 'Product Workflow',
    memory_recall: 'Memória',
    clarification_required: 'Esclarecimento',
    out_of_scope: 'Fora de escopo',
  };
  const fallbackRoute = spans.find((span) => ['faq', 'product_workflow'].includes(span.attributes?.langgraph_node))?.attributes?.langgraph_node;
  $('last-turn-route').textContent = routeLabels[routeValue] || routeLabels[fallbackRoute] || 'Não identificada';

  const completionLog = logs.find((log) => log.event === 'conversation_turn_completed');
  const outcome = completionLog?.attributes?.status || (trace.status === 'error' ? 'error' : 'success');
  const outcomeLabels = {
    success: 'Concluído',
    rejected: 'Rejeitado',
    clarification_required: 'Esclarecimento',
    out_of_scope: 'Fora de escopo',
    error: 'Erro técnico',
  };
  $('last-turn-outcome').textContent = outcomeLabels[outcome] || outcome;
  statusElement.className = `last-turn-status ${trace.status === 'error' ? 'error' : 'completed'}`;
  statusElement.textContent = trace.status === 'error' ? 'Falha técnica' : 'Trace concluído';
  $('last-turn-open-trace').hidden = false;
  $('last-turn-meta').textContent = `${dateTime(trace.started_at)} · trace ${shortId(trace.trace_id, 22)} · independente do período${state.lastTurnLoadError ? ' · falha ao atualizar; exibindo último dado carregado' : ''}`;
}

function renderPeriodDataNote() {
  const note = $('period-data-note');
  if (!note) return;
  if (state.metricsLoadError) {
    note.hidden = false;
    note.textContent = `Falha ao atualizar as métricas do período: ${state.metricsLoadError}. Os valores visíveis podem ser da consulta anterior.`;
    return;
  }
  const metrics = state.metrics;
  if (!metrics) {
    note.hidden = true;
    note.textContent = '';
    return;
  }
  if (state.traceLoadError) {
    note.hidden = false;
    note.textContent = `Falha ao carregar a lista de traces: ${state.traceLoadError}. As métricas podem ter sido carregadas, mas a tabela não foi atualizada.`;
    return;
  }
  const latestStartedAt = state.lastTurn ? new Date(state.lastTurn.started_at).getTime() : NaN;
  const from = state.filters.from ? new Date(state.filters.from).getTime() : null;
  const to = state.filters.to ? new Date(state.filters.to).getTime() : null;
  const latestWithinPeriod = Number.isFinite(latestStartedAt)
    && (from == null || latestStartedAt >= from)
    && (to == null || latestStartedAt <= to);
  const latestOutsidePeriod = Number.isFinite(latestStartedAt) && !latestWithinPeriod;
  const hasIdentityOrStatusFilter = Boolean(
    state.filters.consumer || state.filters.conversation || state.filters.status,
  );
  const latestListed = state.traces.some((trace) => trace.trace_id === state.lastTurn?.trace_id);
  if (state.traceOffset === 0 && latestWithinPeriod && !hasIdentityOrStatusFilter && !latestListed) {
    note.hidden = false;
    note.textContent = `A API retornou o trace global mais recente (${dateTime(state.lastTurn.started_at)}), dentro da janela selecionada, mas não o incluiu na lista filtrada. Verifique a consulta/persistência de traces; os gráficos usam os dados agregados retornados pela API.`;
    return;
  }
  if ((metrics.traces?.count || 0) > 0) {
    if (latestOutsidePeriod) {
      note.hidden = false;
      note.textContent = `O último trace global é de ${dateTime(state.lastTurn.started_at)}, fora da janela exata (${from == null ? 'sem início' : dateTime(state.filters.from)} a ${to == null ? 'sem fim' : dateTime(state.filters.to)}). As métricas e os gráficos abaixo mostram os traces que estão dentro do período selecionado.`;
      return;
    }
    note.hidden = true;
    note.textContent = '';
    return;
  }
  note.hidden = false;
  if (!state.lastTurn) {
    if (state.lastTurnLoading) {
      note.hidden = true;
      note.textContent = '';
      return;
    }
    note.textContent = state.lastTurnLoadError
      ? 'As métricas não encontraram traces no período; também não foi possível consultar o trace mais recente. Os gráficos não têm amostras para exibir.'
      : 'Nenhum trace foi encontrado no período e nos filtros selecionados. Os gráficos não têm amostras para exibir.';
    return;
  }
  const outsidePeriod = Number.isFinite(latestStartedAt)
    && ((from != null && latestStartedAt < from) || (to != null && latestStartedAt > to));
  note.textContent = outsidePeriod
    ? `Nenhum trace corresponde aos filtros no período. O trace mais recente é de ${dateTime(state.lastTurn.started_at)} e ficou fora da janela exata (${from == null ? 'sem início' : dateTime(state.filters.from)} a ${to == null ? 'sem fim' : dateTime(state.filters.to)}); os gráficos usam apenas essa janela.`
    : 'Nenhum trace corresponde a todos os filtros selecionados. Confira usuário, conversa e status; os gráficos usam somente os registros que correspondem a esses filtros.';
}

function drawSeries(canvas, values, color, emptyMessage) {
  if (!canvas) return;
  const empty = $(`${canvas.id}-empty`);
  const width = Math.max(280, canvas.parentElement.clientWidth - 32);
  const height = 160;
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  const samples = (Array.isArray(values) ? values : [])
    .filter((value) => value != null && Number.isFinite(Number(value)))
    .map(Number);
  if (!samples.length) {
    canvas.hidden = true;
    if (empty) {
      empty.hidden = false;
      empty.textContent = emptyMessage;
    }
    return;
  }
  canvas.hidden = false;
  if (empty) {
    empty.hidden = true;
    empty.textContent = '';
  }
  const max = Math.max(...samples, 0.000001);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  samples.forEach((value, index) => {
    const x = samples.length === 1 ? width / 2 : (index / (samples.length - 1)) * (width - 16) + 8;
    const y = height - 16 - (value / max) * (height - 32);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  if (samples.length === 1) {
    const y = height - 16 - (samples[0] / max) * (height - 32);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(width / 2, y, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

function showLogin(message) {
  $('login-screen').hidden = false;
  if (message && message !== 'Sessão de observabilidade ausente.') $('login-error').textContent = message;
}

function hideLogin() {
  $('login-screen').hidden = true;
  $('login-error').textContent = '';
}

function startSession() {
  authState = 'active';
  sessionStorage.setItem(TAB_KEY, '1');
  hideLogin();
  if (state.pollStarted) return;
  state.pollStarted = true;
  loadLabModels();
  pollLiveFeed();
  setInterval(refreshScreen, 4000);
}

async function submitLogin(event) {
  event.preventDefault();
  $('login-error').textContent = '';
  authState = 'logging-in';
  try {
    await requestJSON(`${OBS}/login`, {
      method: 'POST',
      body: { email: $('login-email').value.trim(), password: $('login-password').value },
    });
    $('login-password').value = '';
    const loaded = await loadData({ quiet: true });
    if (authState === 'anonymous' || !loaded) {
      authState = 'anonymous';
      showLogin();
      $('login-error').textContent = 'Não foi possível carregar os dados.';
      return;
    }
    startSession();
  } catch (error) {
    authState = 'anonymous';
    if (error.status !== 401) $('login-error').textContent = error.message;
  }
}

async function logout() {
  try {
    if (authState === 'active') await requestJSON(`${OBS}/logout`, { method: 'POST' });
  } catch { /* a tela de login abre mesmo se a API não responder */ }
  authState = 'anonymous';
  sessionStorage.removeItem(TAB_KEY);
  state.loadSeq += 1;
  state.metrics = null;
  state.metricsLoadError = '';
  state.traces = [];
  state.traceTotal = 0;
  state.traceLoadError = '';
  state.lastTurn = null;
  state.lastTurnLoadError = false;
  state.lastTurnLoadSeq += 1;
  state.lastTurnLoading = false;
  state.conversations = [];
  state.conversationTotal = 0;
  state.selectedTraceId = null;
  state.selectedTrace = null;
  state.selectedConversationId = null;
  state.selectedConversation = null;
  state.activeTraces = [];
  state.liveEvents = [];
  state.liveByTrace = new Map();
  renderAll();
  showLogin();
}

function renderApplicationCost(applicationCost) {
  const total = applicationCost.estimated_total_usd;
  const coverageComplete = applicationCost.coverage_complete === true;
  const formattedTotal = !coverageComplete
    ? 'Cobertura parcial'
    : total == null ? 'Incompleto' : usd(total);
  const tier = applicationCost.embedding_tier === 'paid' ? 'Gemini pago' : 'Gemini gratuito';
  $('application-cost-total').textContent = formattedTotal;
  const coverageStart = applicationCost.coverage_start_at
    ? `medição completa desde ${dateTime(applicationCost.coverage_start_at)}`
    : 'início da medição indisponível';
  $('application-cost-scope').textContent = `Período selecionado · sem filtros de usuário/status · GPT sem cache · JEV por tokens de entrada · ${tier} · ${coverageStart}`;
  const formatCost = (value) => value == null ? 'Incompleto' : usd(value);
  $('application-cost-split').textContent = `Conversacional: ${formatCost(applicationCost.conversation_variable_cost_usd)} · Laboratório/indexação/sem conversa associada: ${formatCost(applicationCost.operational_cost_usd)}`;

  const origins = applicationCost.origins || [];
  $('cost-origin-rows').innerHTML = origins.length ? origins.map((origin) => {
    const cost = origin.estimated_cost_usd == null
      ? `Incompleto · ${number(origin.unpriced_calls)} sem cálculo (${number(origin.calls_missing_usage)} sem uso · ${number(origin.calls_missing_price)} sem preço · ${number(origin.calls_missing_both)} ambos)`
      : usd(origin.estimated_cost_usd);
    const inputTokens = origin.input_tokens == null ? '—' : number(origin.input_tokens);
    const outputTokens = origin.output_tokens == null ? '—' : number(origin.output_tokens);
    return `<tr><td>${escapeHTML(origin.label || origin.source)}</td><td title="${escapeHTML(origin.model)}">${escapeHTML(shortId(origin.model, 32))}</td><td>${number(origin.calls)}</td><td>${inputTokens}</td><td>${outputTokens}</td><td>${cost}</td></tr>`;
  }).join('') : '<tr><td colspan="6" class="empty-cell">Sem chamadas registradas no período.</td></tr>';
}

function renderSLOMetrics(slos) {
  if (!slos) return;
  const window = slos.window || {};
  $('slo-window-label').textContent = window.started_at && window.ended_at
    ? `${dateTime(window.started_at)} – ${dateTime(window.ended_at)} · ${number(window.duration_days, 1)} dias`
    : 'Período selecionado';

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
  const measuredEntries = entries.filter((entry) => entry.latency?.average_ms != null && Number.isFinite(Number(entry.latency.average_ms)));
  if (!measuredEntries.length) {
    const reason = !entries.length
      ? 'Sem spans registrados no período e filtros selecionados.'
      : `${number(entries.length)} tipo(s) de componente encontrado(s), mas nenhum span tem duração registrada.`;
    $('component-chart').innerHTML = `<p class="chart-empty">${escapeHTML(reason)}</p>`;
    return;
  }
  const max = Math.max(...measuredEntries.map((entry) => entry.latency.average_ms), 1);
  $('component-chart').innerHTML = measuredEntries.slice(0, 9).map((entry) => {
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
  return { trace_id: active.trace_id, conversation_id: active.conversation_id, started_at: active.started_at, status: 'running', duration_ms: null };
}

function filteredActiveTraces() {
  const from = state.filters.from ? new Date(state.filters.from).getTime() : null;
  const to = state.filters.to ? new Date(state.filters.to).getTime() : null;
  const openEnded = $('period-filter').value !== 'custom';
  return state.activeTraces.filter((trace) => {
    const startedAt = new Date(trace.started_at).getTime();
    if (state.filters.consumer) return false;
    if (state.filters.conversation && trace.conversation_id !== state.filters.conversation) return false;
    if (state.filters.status && state.filters.status !== 'running') return false;
    if (from != null && startedAt < from) return false;
    if (!openEnded && to != null && startedAt > to) return false;
    return true;
  });
}

function runningTracesNotListed() {
  const listed = new Set(state.traces.map((trace) => trace.trace_id));
  return filteredActiveTraces().filter((trace) => !listed.has(trace.trace_id));
}

function traceWindowCount() {
  return state.traceTotal + runningTracesNotListed().length;
}

function mergedTraces() {
  const persistedIds = new Set(state.traces.map((trace) => trace.trace_id));
  const running = filteredActiveTraces().filter((trace) => !persistedIds.has(trace.trace_id)).map(activeTraceAsSummary);
  return [...running, ...state.traces].sort((a, b) => new Date(b.started_at) - new Date(a.started_at));
}

function renderTraceTables() {
  const traces = mergedTraces();
  const rowHtml = traces.map((trace) => {
    return `<tr class="clickable-row" data-trace="${escapeHTML(trace.trace_id)}"><td class="trace-id">${escapeHTML(shortId(trace.trace_id))}</td><td class="trace-id">${escapeHTML(shortId(trace.conversation_id))}</td><td class="duration">${duration(trace.duration_ms)}</td><td><span class="status-pill ${escapeHTML(trace.status)}">${escapeHTML(statusText(trace.status))}</span></td><td>${dateTime(trace.started_at)}</td></tr>`;
  });
  const emptyMessage = state.traceLoadError
    ? `Falha ao carregar traces: ${escapeHTML(state.traceLoadError)}`
    : 'Nenhum trace encontrado para os filtros atuais.';
  const empty = `<tr><td colspan="5" class="empty-cell">${emptyMessage}</td></tr>`;
  $('recent-traces').innerHTML = rowHtml.length ? rowHtml.slice(0, 8).join('') : empty;
  $('all-traces').innerHTML = rowHtml.join('') || empty;
  $('trace-total').textContent = `${number(traceWindowCount())} traces`;
  $('trace-page-label').textContent = `Página ${Math.floor(state.traceOffset / 50) + 1}`;
  $('trace-prev').disabled = state.traceOffset === 0;
  $('trace-next').disabled = state.traceOffset + state.traces.length >= state.traceTotal;
  $('nav-live-count').textContent = String(traceWindowCount());
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
  const spans = traceSpans(trace).sort((left, right) => new Date(left.started_at) - new Date(right.started_at));
  const usageEvents = trace.usage_events || [];
  const startedAt = new Date(trace.started_at).getTime();
  const timeline = events.map((event) => renderTraceEvent(event, startedAt)).join('');
  const labAgentIds = new Set(['faq_rag', 'product_workflow', 'router', 'compiler']);
  const agentSpans = traceSpans(trace).filter((span) => span.kind === 'node' && span.attributes?.agent_id);
  const agentIds = [...new Set(agentSpans.map((span) => span.attributes.agent_id))].filter((agentId) => labAgentIds.has(agentId));
  const labButtons = agentIds.map((agentId) => `<button class="button button-secondary" data-lab-agent="${escapeHTML(agentId)}">Testar ${escapeHTML(agentId)}</button>`).join('');
  const detail = $('trace-detail');
  detail.innerHTML = `<div class="detail-head"><h2>${escapeHTML(trace.trace_id)}</h2><p>Conversa ${escapeHTML(trace.conversation_id)}</p><div class="detail-actions"><span class="status-pill ${escapeHTML(trace.status)}">${escapeHTML(statusText(trace.status))}</span><span class="subtle-label">${duration(trace.duration_ms)} · início ${dateTime(trace.started_at)}</span></div>${labButtons ? `<div class="detail-actions">${labButtons}</div>` : ''}</div><div class="detail-section-title">Spans e chamadas <small>${number(spans.length)} spans · ${number(usageEvents.length)} chamadas de uso fora dos spans</small></div>${renderTraceSpans(spans, usageEvents)}<div class="detail-section-title">Eventos do trace <small>${number(spanEvents.length)} eventos · ${number(logs.length)} logs</small></div><div class="timeline">${timeline || '<p class="empty-note">Aguardando spans e logs.</p>'}</div>`;
  detail.querySelectorAll('[data-lab-agent]').forEach((button) => button.addEventListener('click', () => openLabFromTrace(button.dataset.labAgent)));
}

function renderTraceSpans(spans, usageEvents = []) {
  if (!spans.length && !usageEvents.length) return '<p class="empty-note">Nenhum span ou chamada registrada.</p>';
  const spanRows = spans.map((span) => {
    const hasTokens = span.input_tokens != null || span.output_tokens != null;
    const tokens = hasTokens
      ? `${span.input_tokens == null ? '—' : number(span.input_tokens)} / ${span.output_tokens == null ? '—' : number(span.output_tokens)}`
      : '—';
    const model = span.model ? `<small>${escapeHTML(span.model)}</small>` : '';
    return `<tr><td><strong class="trace-span-name">${escapeHTML(span.name || span.kind || 'span')}</strong><small>${escapeHTML(span.kind || 'componente')}${model ? ` · ${model}` : ''}</small></td><td><span class="status-pill ${escapeHTML(span.status)}">${escapeHTML(statusText(span.status))}</span></td><td class="duration">${duration(span.duration_ms)}</td><td>${tokens}</td><td>${span.estimated_cost_usd == null ? '—' : usd(span.estimated_cost_usd)}</td></tr>`;
  }).join('');
  const usageRows = usageEvents.map((event) => {
    const tokens = event.input_tokens == null && event.output_tokens == null
      ? '—'
      : `${event.input_tokens == null ? '—' : number(event.input_tokens)} / ${event.output_tokens == null ? '—' : number(event.output_tokens)}`;
    const source = event.source === 'judge_jev' ? 'Judge JEV' : event.source;
    return `<tr><td><strong class="trace-span-name">${escapeHTML(source || 'Uso de modelo')}</strong><small>${escapeHTML(event.model || 'modelo desconhecido')} · chamada fora dos spans</small></td><td><span class="status-pill ${escapeHTML(event.status)}">${escapeHTML(statusText(event.status))}</span></td><td class="duration">${duration(event.duration_ms)}</td><td>${tokens}</td><td>${event.estimated_cost_usd == null ? '—' : usd(event.estimated_cost_usd)}</td></tr>`;
  }).join('');
  return `<div class="table-scroll trace-span-table"><table><thead><tr><th>SPAN / CHAMADA</th><th>STATUS</th><th>DURAÇÃO</th><th>TOKENS (ENTRADA / SAÍDA)</th><th>CUSTO ESTIMADO</th></tr></thead><tbody>${spanRows}${usageRows}</tbody></table></div>`;
}

function renderTraceEvent(event, traceStartedAt) {
  const data = event.data || {};
  const elapsed = Math.max(0, new Date(event.timestamp).getTime() - traceStartedAt);
  if (event.event_type === 'log') {
    return `<div class="timeline-item log"><div class="timeline-top"><strong>LOG ${escapeHTML(data.level || 'INFO')} · ${escapeHTML(data.logger || 'src')}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-body">${escapeHTML(data.message || '')}</div><div class="timeline-meta">${escapeHTML(data.agent_id || 'sem agent_id')} · span ${escapeHTML(shortId(data.span_id || '—'))} · ${dateTime(event.timestamp)}</div>${attributeLine(data.attributes)}</div>`;
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
      toolSummary.tool_outcome && `Desfecho: ${toolSummary.tool_outcome}`,
      toolSummary.tool_suggestion_type && `Tipo: ${toolSummary.tool_suggestion_type}`,
      toolSummary.tool_direction && `Direção: ${toolSummary.tool_direction}`,
      toolSummary.tool_has_next_page != null && `Próxima página: ${toolSummary.tool_has_next_page ? 'sim' : 'não'}`,
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
  return `<div class="timeline-item ${failed ? 'error' : ''}"><div class="timeline-top"><strong>${escapeHTML(data.name || data.kind || 'span')} · ${escapeHTML(event.phase)}</strong><small>+${duration(elapsed)}</small></div><div class="timeline-meta">${escapeHTML(identity)} · ${escapeHTML(data.kind || 'span')} · ${duration(data.duration_ms)} · ${dateTime(event.timestamp)}</div>${attributeLine(data.attributes)}${data.error_type ? `<div class="timeline-meta">Erro: ${escapeHTML(data.error_type)}</div>` : ''}${data.input_tokens != null || data.output_tokens != null ? `<div class="timeline-meta">Tokens: ${number(data.input_tokens)} entrada / ${number(data.output_tokens)} saída</div>` : ''}</div>`;
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

function renderActiveStatus() {
  $('nav-live-count').textContent = String(traceWindowCount());
}

async function refreshScreen() {
  if (authState !== 'active' || state.pollBusy) return;
  state.pollBusy = true;
  try {
    advanceOpenWindow();
    await loadData({ quiet: true });
    await pollLiveFeed();
  } finally {
    state.pollBusy = false;
  }
}

async function pollLiveFeed() {
  const startedAt = new Date();
  const started = performance.now();
  try {
    const feed = await requestJSON(`${OBS}/traces/live?after=${state.cursor}&limit=500`);
    $('poll-label').textContent = `Feed 4s · última ${startedAt.toLocaleTimeString('pt-BR')} · ${number(performance.now() - started, 1)} ms`;
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
  } catch (error) {
    $('poll-label').textContent = error.status === 401 ? 'Aguardando login' : 'Feed ao vivo indisponível';
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
    $('lab-tools').textContent = JSON.stringify(config.tools || [], null, 2);
    $('lab-messages').value = formatLabMessages(history);
    updateLabMessageCount();
    $('lab-agent-caption').textContent = `${config.name} · ${config.role} · versão ${config.version}`;
    state.labLoadedAgent = config.agent_id;
    if (notify) toast('Prompt, tools e histórico carregados como rascunho.');
    return true;
  } catch (error) {
    $('lab-agent-caption').textContent = 'O prompt deste agente não pôde ser carregado.';
    $('lab-tools').textContent = 'As tools deste agente não puderam ser carregadas.';
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
  const agentId = $('lab-agent-id').value.trim();
  const modelId = $('lab-model-id').value;
  const prompt = $('lab-prompt').value.trim();
  let messages;
  try {
    messages = parseLabMessages($('lab-messages').value);
  } catch (error) {
    return toast(error.message);
  }
  if (!agentId || !prompt || !modelId || !messages.some((message) => message.role === 'user')) return toast('Preencha o agente, o prompt, o modelo e ao menos uma mensagem de usuário.');
  $('lab-result').textContent = 'Executando modelo…';
  $('lab-run-time').textContent = 'Em execução';
  const started = performance.now();
  try {
    const result = await requestJSON(`${OBS}/lab/run`, { method: 'POST', body: { agent_id: agentId, model_id: modelId, prompt, messages }, label: 'POST /observability/lab/run' });
    const calls = result.tool_calls || [];
    $('lab-result').textContent = calls.length ? JSON.stringify(calls, null, 2) : (result.result || '');
    $('lab-run-time').textContent = `${duration(performance.now() - started)} · decisão do modelo`;
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
$('last-turn-open-trace').addEventListener('click', () => {
  if (state.lastTurn?.trace_id) void openTrace(state.lastTurn.trace_id);
});
$('roi-return').addEventListener('input', () => {
  if (state.metrics) renderBoard(state.metrics.board || {}, state.metrics);
});
$('apply-filters').addEventListener('click', applyFilters);
$('consumer-filter').addEventListener('keydown', (event) => { if (event.key === 'Enter') applyFilters(); });
$('conversation-filter').addEventListener('keydown', (event) => { if (event.key === 'Enter') applyFilters(); });
$('period-filter').addEventListener('change', applyDatePreset);
$('date-from').addEventListener('change', () => { $('period-filter').value = 'custom'; });
$('date-to').addEventListener('change', () => { $('period-filter').value = 'custom'; });
$('trace-prev').addEventListener('click', () => { state.traceOffset = Math.max(0, state.traceOffset - 50); loadData({ quiet: true }); });
$('trace-next').addEventListener('click', () => { state.traceOffset += 50; loadData({ quiet: true }); });
$('conversation-prev').addEventListener('click', () => { state.conversationOffset = Math.max(0, state.conversationOffset - 50); loadData({ quiet: true }); });
$('conversation-next').addEventListener('click', () => { state.conversationOffset += 50; loadData({ quiet: true }); });
$('load-agent-prompt').addEventListener('click', () => loadAgentPrompt());
$('run-lab').addEventListener('click', runLab);
$('lab-messages').addEventListener('input', updateLabMessageCount);
$('login-screen').addEventListener('submit', submitLogin);
$('logout-button').addEventListener('click', logout);

async function boot() {
  initDateFilters();
  const initialView = location.hash.slice(1);
  if (['overview', 'traces', 'conversations', 'lab'].includes(initialView)) activateView(initialView);
  if (!sessionStorage.getItem(TAB_KEY)) {
    showLogin();
    return;
  }
  authState = 'active';
  const loaded = await loadData();
  if (authState !== 'active' || !loaded) return;
  startSession();
}

boot();
