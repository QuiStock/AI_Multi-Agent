# ADR-A2A-001 — Fachada A2A sobre o grafo do Quistock

**Estado:** aceito quanto à fachada e aos dois papéis do Quistock;
detalhes de credencial, peer e roteamento dinâmico permanecem em aberto.

## Contexto

O Quistock já possui cinco agentes locais, guardrails, memória e uma rota HTTP
que usa `ConversationService.converse`. A rubrica pede integração A2A com
outro sistema. O usuário quer que o Quistock receba chamadas A2A e possa
enviar perguntas a um sistema próprio externo quando o router decidir.

## Decisão

1. O Quistock publica **uma fachada A2A** com skills de negócio autorizadas.
   Cada chamada recebida é autenticada, traduzida para o serviço de conversa
   existente e passa pelo grafo completo.
2. O Quistock também atua como cliente A2A. Uma capacidade de integração
   controlada pode ser escolhida pelo router e devolver resultado/evidência
   ao mesmo grafo, antes de compiler, juiz e guardrail de saída.
3. Executores locais, prompts, ferramentas, SQL, memória, juiz, guardrails e
   observabilidade não são servidores A2A individuais nem skills públicas.
4. O peer inicial é cadastrado explicitamente. Seleção entre vários peers é
   proposta posterior, sujeita a registro, validação de card e autorização.

## Alternativas consideradas

- **Um endpoint A2A por agente local:** aumentaria a superfície pública e
  permitiria contornar etapas do grafo. Rejeitada.
- **Um segundo grafo exclusivo para A2A:** duplicaria regras de identidade,
  memória, evidência e segurança. Rejeitada.
- **Uma fachada que usa o serviço de conversa atual:** preserva o fluxo e
  suas políticas. Escolhida.

## Consequências

- O contrato A2A exige adaptadores de entrada/saída e autenticação própria
  para peers, mas não altera as regras comerciais do Quistock.
- O card anuncia apenas capacidades realmente disponíveis e autorizadas.
- Respostas de peers são dados externos: só alimentam a resposta final após
  verificação de fonte, compiler, juiz e guardrail.
- O nó de integração A2A não conta como sexto agente local.
- Contexto de conversa, idempotência, falhas e rastreamento devem ser mapeados
  entre HTTP normal, A2A e `ConversationService`.

## Questões em aberto

O emissor do contexto delegado, o contrato exato de evidência, a identidade
definitiva do serviço de caminhões e o cadastro dinâmico constam em
`spec.md` e `plan.md` e precisam de decisão antes da etapa correspondente.
