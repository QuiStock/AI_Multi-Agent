<!--
Sync Impact Report
- Version change: template -> 1.0.0
- Modified principles: replaced the uninitialized template with six project
  principles for traceable SDD and grounded multi-agent development.
- Added sections: artifact layout, status classification, quality gates and
  amendment governance.
- Removed sections: unresolved template placeholders.
- Follow-up: existing planning documents and code evidence will be classified
  during the first consolidation audit.
-->

# Quistock AI Service Constitution

## Core Principles

### I. Spec-First and Traceable Delivery

Every material change to scope, behavior, architecture, data, security or
integration MUST be represented in a Spec Kit feature directory under `specs/`
before implementation. The delivery sequence is `spec.md`, clarification,
`plan.md`, `tasks.md`, consistency analysis, implementation, tests and
evidence. Requirements, decisions, tasks and evidence MUST use stable
identifiers or explicit links so that the path from intent to verification is
recoverable.

### II. Explicit Status and No Silent Decisions

Planning items MUST be classified as exactly one of `confirmado`,
`implementado`, `proposto`, `aberto` or `divergente`. The current state, target
state and roadmap MUST remain separate. A contradiction MUST identify its
sources, impact and required decision. An `aberto` item that can materially
change the solution MUST NOT generate an executable implementation task.

### III. Contracts and Bounded Responsibilities

Agents, tools, graph nodes, APIs, databases and external integrations MUST have
explicit contracts and ownership boundaries. Agents MUST operate only within
their declared capability. Domain tools MUST be narrow, typed, authorized and
read-only unless a separately approved specification defines a write operation.
The MVP Product Workflow remains consultive and MUST NOT execute commercial
orders or promotions.

### IV. Evidence-Grounded and Fail-Safe AI

Factual answers MUST be supported by available evidence and citations when the
capability requires them. The FAQ/RAG capability MUST refuse or return a
controlled response when evidence is insufficient. Judges and guardrails MUST
be treated as release gates for their declared risks. Timeouts, invalid model
outputs, unavailable dependencies and authorization failures MUST produce a
safe, observable outcome and MUST NOT be replaced with invented facts.

### V. Identity, Privacy and Tenant Isolation

Identity, role and store scope MUST be established by a trusted server-side
boundary and propagated to every protected read or write. Data from one user,
conversation, region or store MUST NOT be exposed to another scope. Credentials,
private prompts, chain-of-thought, sensitive personal data and unrestricted SQL
MUST NOT be persisted, emitted to users or included in ordinary telemetry.

### VI. Tests, Review and Academic Evidence

Every relevant change MUST include proportionate unit, contract or integration
tests and a reproducible validation path. Changes to agents or the graph MUST
cover routing, authorization, groundedness, fallback, error handling and
traceability when applicable. A feature is not complete until its tests and
academic or operational evidence are linked to the corresponding requirements.
Code review and the repository quality gates MUST be completed before a
feature is considered ready for delivery.

## Artifact Layout and Authority

- `.specify/memory/constitution.md` defines governance principles for the
  service.
- `specs/<feature>/` is the official location for feature specifications,
  plans, tasks, research, models, contracts, checklists and quickstarts created
  by Spec Kit.
- Existing documents outside `specs/` may provide context or historical
  evidence, but a new or revised feature decision MUST be recorded in the
  corresponding Spec Kit artifact.
- Source code and tests describe the implemented state. They MUST NOT be used
  as proof that an unimplemented target decision has been delivered.
- The five status values are case-sensitive and MUST be used consistently in
  planning reviews and traceability records.

## Development Workflow and Quality Gates

1. Inventory relevant context and implementation evidence.
2. Create or update one focused feature specification.
3. Resolve high-impact ambiguities before planning.
4. Generate and review the implementation plan and design artifacts.
5. Generate tasks only for decided, implementable requirements.
6. Run cross-artifact consistency analysis before implementation.
7. Implement in independently testable vertical slices.
8. Run tests, quality checks and evidence capture before completion.

No implementation work may bypass the specification and planning gates unless
the change is a narrowly scoped corrective action whose existing contract and
acceptance criteria are already explicit. Such a correction MUST still update
its tests and evidence.

## Governance

This constitution governs all Spec Kit feature work in the Quistock AI service.
An amendment MUST be proposed in the active conversation, explain its impact on
existing specifications and tasks, update this file, and trigger review of
affected feature artifacts. Versioning follows semantic versioning: MAJOR for
incompatible governance changes, MINOR for new or materially expanded
principles, and PATCH for clarifications that do not change obligations.

Every plan and implementation review MUST check compliance with the principles
above. If a principle conflicts with an existing requirement, the conflict MUST
be recorded as `divergente` and resolved explicitly; it MUST NOT be hidden by
weakening the principle inside a feature plan.

**Version**: 1.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30
