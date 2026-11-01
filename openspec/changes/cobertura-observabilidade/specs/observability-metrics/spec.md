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

### Requirement: Service objectives follow the selected metric filters
The completion and latency objectives, including the overall period SLO banner, SHALL use the selected date window and SHALL follow the selected user, conversation, and environment filters. The status filter MUST NOT restrict the objective sample because doing so would bias completion and error rates. Completion and per-model call success target 95%; latency remains targeted at p95 of 20 seconds with 95% of terminal turns under the limit.

#### Scenario: Objective follows the selected window
- **WHEN** the selected period, user, conversation, or environment changes
- **THEN** the completion and latency objectives use the corresponding filtered traces and display that period

#### Scenario: Status filter does not bias service objectives
- **WHEN** the selected status is only completed or only error
- **THEN** the service objectives still use both terminal statuses from the other selected filters

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
The system SHALL show, in addition to the groups above, a period SLO that is met only when p95 is at most 20 seconds and the error rate is at most 5%. It SHALL also show the number of recorded Qwen fallback calls, the most-used model, mean node latency, resolution count, one cost per resolution card, estimated cost per conversation, and weekly cost for 100 and 1000 users. One user represents five conversations per week. A resolution is a completed trace with no error, including out-of-scope, rejected, and clarification responses. Variable conversation cost SHALL include the judge JEV, summaries/titles, and query embeddings associated with a conversation; laboratory calls and embedding-index work SHALL be shown separately and excluded from projections. Cost per resolution uses the selected date period. Cost per conversation and weekly projections SHALL use a rolling reference window of up to 30 days with available metering coverage and MUST NOT change when dashboard date filters change. If any projected conversation call has no price or required token usage, projected weekly cost and cost per conversation are absent. ROI uses a return entered for the selected period and subtracts total estimated AI cost for that same period.

#### Scenario: Qwen fallback call
- **WHEN** the window contains one or more LLM spans whose model ID contains `qwen`
- **THEN** the fallback count includes each recorded Qwen call and its rate counts traces with at least one Qwen call

#### Scenario: JEV input-token cost
- **WHEN** a successful JEV response reports input-token usage
- **THEN** the call is included in model usage and its cost uses the published input-token rate, with no output-token charge

#### Scenario: Operational calls stay out of user projections
- **WHEN** the window includes laboratory or embedding-index calls
- **THEN** those costs remain visible by origin and do not increase the projected conversation cost

#### Scenario: Projection is independent of dashboard filters
- **WHEN** the selected date period changes
- **THEN** the cost-per-conversation card and the 100/1000-user weekly projections remain based on the same rolling metering window

#### Scenario: Priced window inside both limits
- **WHEN** every model call is priced, p95 is at most 20 seconds, and the error rate is at most 5%
- **THEN** the period SLO is met and the 1000-user weekly cost is ten times the 100-user weekly cost
