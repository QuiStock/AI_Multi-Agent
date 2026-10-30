# Exposição MCP das consultas de Product Workflow

Status: definição inicial na branch `refactor` (2026-10-13). Nenhum servidor MCP está implementado.

## Decisões confirmadas

- Os agentes do Quistock continuam chamando suas tools localmente. O MCP é uma entrada adicional para consumidores autorizados; não substitui o grafo nem a execução nativa.
- A primeira exposição contém somente `get_suggestion_for_product` e `get_suggestion_detail`, ambas somente leitura.
- As regras comerciais e a autorização por usuário, `role_code` e loja continuam pertencendo ao servidor e ao repositório existentes. O consumidor não escolhe esses valores nos argumentos MCP.
- O serviço consumidor executa as chamadas em nome de um usuário autenticado. Cada chamada MCP apresenta um JWT válido desse usuário; a identidade técnica do serviço, sozinha, não concede acesso às sugestões.

## Contrato público proposto

O servidor MCP será montado na FastAPI em `/mcp`, com transporte Streamable HTTP. As funções MCP serão registradas explicitamente e delegarão às duas tools existentes de Product Workflow. `tools/list` anunciará exatamente estas duas funções nesta primeira versão.

| Tool | Argumentos públicos | Regra de entrada | Dados de saída |
|---|---|---|---|
| `get_suggestion_for_product` | `product_query: string` | Texto não vazio, até 200 caracteres depois de remover espaços das pontas | `product_query`, `outcome` (`found`, `ambiguous`, `not_found`) e até 6 `candidates` numerados |
| `get_suggestion_detail` | `selection_ref: string` | Referência decimal positiva retornada na lista | `visibility`, `card` e, para gerente quando existir, `triage` |

Cada candidato usa os campos já definidos em `ProductSuggestionCandidate`: `position`, `selection_ref`, nome, categoria, SKU, loja, tipo e status. O detalhe usa `SuggestionDetailData`. O contrato não aceita SQL, `user_id`, email, `role_code`, `store_ids` ou identificadores de loja como parâmetros públicos.

O `structuredContent` proposto é um objeto JSON com `schema_version`, `status`, `data`, `evidence`, `warnings` e `error`. A projeção deve ser explícita: não publicar `meta`, detalhes internos de erros ou a diretiva `response` que hoje orienta a composição do agente. Evidências mantêm identificadores e conteúdo apenas na visão autorizada para a role. A resposta MCP não deve duplicar todo o estado do agente.

Exemplo abreviado de listagem:

```json
{
  "schema_version": "1.0",
  "status": "success",
  "data": {
    "product_query": "arroz",
    "outcome": "found",
    "candidates": [
      {
        "position": 1,
        "selection_ref": "42",
        "product_name": "Arroz branco",
        "category_name": "Alimentos",
        "sku": "ARZ-001",
        "store_name": "Loja Centro",
        "suggestion_type": "ORDER",
        "suggestion_status": "IN_EMPLOYEE_TRIAGE"
      }
    ]
  },
  "evidence": [
    {
      "evidence_id": "product-search:suggestion:42",
      "source_type": "product_workflow",
      "source_id": "postgresql:suggestion:42",
      "content": "{\"position\":1,\"selection_ref\":\"42\",\"product_name\":\"Arroz branco\",\"category_name\":\"Alimentos\",\"sku\":\"ARZ-001\",\"store_name\":\"Loja Centro\",\"suggestion_type\":\"ORDER\",\"suggestion_status\":\"IN_EMPLOYEE_TRIAGE\"}",
      "metadata": {"entity_type": "suggestion_candidate", "suggestion_id": "42"}
    }
  ],
  "warnings": [],
  "error": null
}
```

O exemplo é ilustrativo; os registros e evidências reais vêm das tools existentes. `selection_ref` é atualmente o ID da sugestão, não uma credencial e não uma prova de que a listagem ocorreu. A chamada de detalhe pode ser feita diretamente, mas sempre repete a autorização no PostgreSQL. O consumidor é responsável por esperar a escolha da pessoa antes de chamar o detalhe em uma jornada conversacional.

## Identidade e erros propostos

Fluxo definido: usuário autenticado na Auth → serviço consumidor recebe acesso autorizado ao JWT do usuário → serviço chama `/mcp` com `Authorization: Bearer <JWT>` → API de IA valida o token e consulta a conta → tool executa somente no escopo dessa conta. O agente consumidor decide quando chamar a tool e usa os dados e evidências retornados para compor sua resposta; o MCP não executa o grafo conversacional do Quistock.

- Toda requisição a `/mcp`, inclusive descoberta das tools, requer o JWT do usuário emitido pela Auth para a API de IA. A entrada MCP reutiliza a validação RS256/JWKS, `iss`, `aud = ["quistock-api"]`, `exp` e a resolução da conta/role/lojas no banco. Um header com ID ou email declarado pelo consumidor não autentica a pessoa.
- Token ausente, inválido ou expirado: HTTP 401. Role sem acesso ou sem loja autorizada: HTTP 403. Se a Auth/JWKS ou o PostgreSQL estiver indisponível, usar o tratamento de dependência da API sem converter a falha em 401.
- Entrada inválida, sugestão fora do escopo ou falha da consulta devem produzir erro seguro da tool dentro da resposta MCP, preservando o código funcional existente e sem stack trace, SQL ou dados de outra loja. A semântica exata de `isError` e do envelope será fechada ao escolher o SDK.
- A duração atual do JWT é de cinco minutos. Se ele expirar, a chamada recebe 401 e o consumidor precisa obter outro token válido pelo fluxo da Auth antes de repetir. O serviço não deve persistir nem registrar o token em logs.

## Requisitos e critérios de aceite

- **RF-MCP-PW-001:** anunciar apenas as duas tools aprovadas; os agentes internos continuam usando a execução local.
- **RF-MCP-PW-002:** executar as mesmas consultas e filtros comerciais da implementação nativa, sem duplicar SQL ou lógica de autorização.
- **RF-MCP-PW-003:** exigir o JWT do usuário em cada chamada feita pelo serviço em seu nome e derivar identidade, role e lojas da autenticação validada.
- **RF-MCP-PW-004:** entregar JSON estruturado, versionado e restrito à visão autorizada.
- **RNF-MCP-PW-001:** não publicar credenciais, PII desnecessária, SQL, trace interno ou detalhes de exceções.

- **CA-MCP-PW-001:** `tools/list` autenticado retorna exatamente as duas assinaturas públicas; nenhuma contém campos de identidade ou loja.
- **CA-MCP-PW-002:** uma busca MCP e a tool local, executadas para o mesmo principal e consulta, retornam os mesmos candidatos autorizados.
- **CA-MCP-PW-003:** token inválido/expirado recebe 401; role sem acesso recebe 403; ID de sugestão de outra loja nunca revela o card.
- **CA-MCP-PW-006:** uma chamada do serviço apenas com sua identidade técnica ou com headers declarando outro usuário recebe 401; após receber um novo JWT válido, a chamada usa o escopo do usuário autenticado.
- **CA-MCP-PW-004:** lista vazia retorna `not_found`; várias opções retornam `ambiguous`; o detalhe não amplia o escopo mesmo quando chamado sem listagem anterior.
- **CA-MCP-PW-005:** erros não expõem stack trace, SQL, credenciais ou dados de outra pessoa; o ciclo de vida do servidor MCP inicia e encerra com a FastAPI.

## Questões abertas antes da implementação

1. Qual será o primeiro serviço consumidor? Um serviço conhecido do Quistock ou clientes MCP externos em geral? Clientes genéricos podem exigir descoberta OAuth e um contrato adicional com a Auth.
   Também falta definir como o serviço obterá um JWT atualizado do usuário e, em produção, se haverá autenticação adicional para identificar o próprio serviço chamador.
2. O `structuredContent` deve manter todo o `ToolEvidence.content` autorizado ou apenas IDs e campos resumidos? Isso depende de o consumidor compor explicações a partir da evidência.
3. Qual SDK/versão MCP será fixado e qual será a semântica final de erros de tool e metadados de autorização no transporte escolhido?

## Relação com o código atual

- Implementação local: `src/agents/product_workflow/tools/tools.py`.
- Modelos: `src/agents/product_workflow/models.py` e `src/agents/schemas/tool_result.py`.
- Autorização de entrada: `src/api/dependencies.py` e `src/auth/`.
- Filtro por linha: `src/agents/product_workflow/repository.py`.
- Decisão anterior: `specs/005-product-workflow-read-only/spec.md`.
