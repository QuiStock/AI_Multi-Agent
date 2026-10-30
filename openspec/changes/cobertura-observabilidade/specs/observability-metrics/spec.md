# Spec Delta

## Purpose

Define os números de confiabilidade e de custo que a Visão geral mostra, calculados neste serviço.

## ADDED Requirements

### Requirement: Metrics are calculated in this service
The system SHALL calculate the observability metrics in this service from stored turns and model calls. It MUST NOT call LangSmith to produce them.

#### Scenario: Dashboard load
- **WHEN** an authenticated person opens the Visão geral
- **THEN** the numbers come from this service and no LangSmith request is made

### Requirement: Latency summary uses mean and nearest-rank p95
The system SHALL show mean turn latency and nearest-rank p95. The p95 limit SHALL be 20 seconds. The system MUST NOT replace that limit with the classroom limit of 8 seconds.

#### Scenario: p95 within the limit
- **WHEN** the nearest-rank p95 of the selected window is 20 seconds or less
- **THEN** the latency objective is inside the limit

#### Scenario: p95 over the limit
- **WHEN** the nearest-rank p95 is over 20 seconds
- **THEN** the latency objective is outside the limit

### Requirement: Completion objective stays on the current banner
The system SHALL keep the completion banner at 99.5% over a rolling 28-day window. A separate period banner MAY judge p95 at 20 seconds and error rate at 5%. That period banner MUST NOT replace the 28-day banner.

#### Scenario: Banner window
- **WHEN** the Visão geral loads the service-level banner
- **THEN** completion is judged at 99.5% on the 28-day window and latency at 20 seconds

### Requirement: Blocks are not errors
The system SHALL count an error only when the turn fails by exception. A guardrail block MUST be counted as a block, not as an error.

#### Scenario: Guardrail block
- **WHEN** a turn ends because the guardrail blocked it
- **THEN** the block count increases and the error rate does not

### Requirement: Cost uses the current price table
The system SHALL price GPT-6 Luna at US$ 0.10 per million input tokens and US$ 0.50 per million output tokens, without cache discount. Gemini embeddings SHALL cost US$ 0 on the free tier and US$ 0.20 per million input tokens on the paid tier. Cost SHALL be token count times that price.

#### Scenario: Priced model call
- **WHEN** a completed call records input and output tokens for GPT-6 Luna
- **THEN** its cost uses those two rates and is included in the period total

### Requirement: Overview shows the agreed metric groups
The system SHALL show, in separate blocks, turn count, in-progress count, mean latency, p95, error rate, blocks, input tokens, output tokens, cost, model-call count, per-model usage, per-route usage, tool aggregates, run-type aggregates, a latency series, and a cumulative-cost series.

#### Scenario: Authenticated overview
- **WHEN** an authenticated person opens the Visão geral
- **THEN** each of those groups is visible as its own block

### Requirement: Overview omits private prompt text and later signals
The system SHALL NOT show prompt text, answer text, time to first token, or an answer-quality score on the observability screen.

#### Scenario: Turn row
- **WHEN** a turn is listed on the observability screen
- **THEN** the row shows time, latency, route, status, tokens, cost, and session, and omits prompt text

### Requirement: Period board adds the classroom reliability numbers
The system SHALL show, in addition to the groups above, a period SLO that is met only when p95 is at most 20 seconds and the error rate is at most 5%. It SHALL also show the Groq fallback count, the most-used model, mean node latency, resolution count, cost per resolution, and weekly cost for 100 and 1000 users. One user counts as one conversation. A resolution is a completed turn that is not blocked and whose route is not `clarification_required`. If any model call in the window has no price, weekly cost and cost per resolution are absent. ROI uses a return typed on the page: empty return shows that none was informed.

#### Scenario: Unpriced fallback call
- **WHEN** the window contains a completed call on the configured Groq model and that model has no price
- **THEN** the fallback count includes that call and the weekly cost is absent

#### Scenario: Priced window inside both limits
- **WHEN** every model call is priced, p95 is at most 20 seconds, and the error rate is at most 5%
- **THEN** the period SLO is met and the 1000-user weekly cost is ten times the 100-user weekly cost
