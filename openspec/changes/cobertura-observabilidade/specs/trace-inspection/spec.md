# Spec Delta

## Purpose

Define a leitura de um trace e das suas etapas dentro da plataforma, sem abrir o LangSmith.

## ADDED Requirements

### Requirement: Traces open inside the platform
The system SHALL list traces and open one trace inside the observability page for an authenticated person.

#### Scenario: Select a trace
- **WHEN** an authenticated person selects a trace
- **THEN** the page shows that trace without leaving the platform and without calling LangSmith

### Requirement: Trace detail shows the steps
The system SHALL show each stored step of the selected trace with its name, duration, and status, plus tokens and cost when those values were stored for the step.

#### Scenario: Trace with steps
- **WHEN** the selected trace has stored steps
- **THEN** each step is visible with name, duration, and status

#### Scenario: Step without token counts
- **WHEN** a step has no stored token counts
- **THEN** the step still shows name, duration, and status, and does not invent tokens or cost
