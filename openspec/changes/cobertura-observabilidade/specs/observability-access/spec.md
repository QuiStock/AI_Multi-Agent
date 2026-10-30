# Spec Delta

## Purpose

Define quem entra na página e na API de observabilidade, sem alterar o acesso das conversas.

## ADDED Requirements

### Requirement: Observability session gates the page and its API
The system SHALL require a successful observability login before showing the observability page or returning data from `/api/v1/observability`, including the lab routes on that API.

#### Scenario: Anonymous API call
- **WHEN** a client calls `/api/v1/observability` without an observability session
- **THEN** the system refuses the call and returns no observability data

#### Scenario: Anonymous page
- **WHEN** a person opens the observability page without an observability session
- **THEN** the system shows the login screen and does not show metrics or traces

### Requirement: Conversation API keeps its current login
The system SHALL keep the conversation API on its current bearer-token login. An observability session MUST NOT be required for conversation routes, and a conversation token MUST NOT by itself open observability.

#### Scenario: Conversation call without observability session
- **WHEN** a client calls a conversation route with a valid conversation token and no observability session
- **THEN** the conversation route behaves as it does today

### Requirement: Login matches email and password on super_admin
The system SHALL grant an observability session only when the submitted email and password match one existing row in `super_admin`. The row lives in the same Postgres database as `user_account`. This delivery MUST NOT create, update, or delete `super_admin` rows.

The columns are `email` and `password`. The password column stores a bcrypt hash with prefix `$2a$`, `$2b$`, or `$2y$`.

#### Scenario: Matching row
- **WHEN** the submitted email matches `super_admin.email` and bcrypt accepts the password against `super_admin.password`
- **THEN** the system grants an observability session and the page opens on the metrics view

#### Scenario: Unknown email
- **WHEN** no `super_admin` row has the submitted email
- **THEN** the system responds `usuário não encontrado` and does not grant a session

#### Scenario: Wrong password
- **WHEN** the email exists and bcrypt rejects the password
- **THEN** the system responds `usuário não autenticado` and does not grant a session
