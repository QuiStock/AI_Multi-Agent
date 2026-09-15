## Description

Briefly explain the problem solved or the new feature implemented. Include the
expected agent behavior and any relevant changes to prompts, tools, models, or
the knowledge base.


## Related Jira card

- [QUIS-XXX](https://quistock.atlassian.net/browse/QUIS-XXX)


## Change category

- [ ] Agent behavior or prompt
- [ ] Tool or integration
- [ ] RAG, embeddings, or knowledge base
- [ ] Model or provider
- [ ] Repository configuration or CI
- [ ] Documentation


## Change type

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Not applicable


## Quality

- [ ] Behavioral tests were added or updated.
- [ ] Tests were developed following Red–Green–Refactor.
- [ ] Tests verify observable outcomes rather than implementation details.
- [ ] Both success, fallback, and error paths were considered.
- [ ] No coverage exclusions were added without justification.
- [ ] Agent instructions, tool descriptions, and documentation were updated,
      where applicable.
- [ ] RAG answers remain grounded in the knowledge base and cite their sources,
      where applicable.
- [ ] Model, environment, cost, latency, and integration impacts were considered,
      where applicable.
- [ ] Not applicable


## How to test

Provide the commands and steps a reviewer can use to validate this change.
Include representative prompts, expected agent behavior, and relevant failure
scenarios.

1.


## AI, knowledge base, and configuration changes

- [ ] No model, prompt, tool contract, knowledge base, or configuration changes.
- [ ] Model, prompt, or tool contract changes and their expected behavior are
      described above.
- [ ] Knowledge-base changes were validated and the expected sources are cited.
- [ ] New or changed environment variables are documented in `.env.example`.


## Impact and rollback plan

Describe relevant risks, affected agents or integrations, expected cost or
latency changes, and how to roll back this change if needed.
