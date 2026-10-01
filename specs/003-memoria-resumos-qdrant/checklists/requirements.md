# Specification Quality Checklist: Persistência de turnos e resumos no Qdrant

**Purpose**: Validar a completude e a qualidade da especificação antes do planejamento técnico
**Created**: 2026-09-30
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] A especificação descreve valor para usuário e serviço sem definir implementação detalhada.
- [x] As histórias podem ser entendidas por pessoas técnicas e não técnicas.
- [x] As seções obrigatórias estão preenchidas.
- [x] O escopo distingue documento de conversa, mensagens/turnos e resumo conversacional.

## Requirement Completeness

- [x] Os requisitos têm identificadores estáveis e comportamento testável.
- [x] Os critérios de sucesso são observáveis e verificáveis.
- [x] As histórias principais incluem cenários de aceite.
- [x] Casos de falha, retry, isolamento e dados legados foram identificados.
- [x] A granularidade está definida como um documento por conversa, com mensagens no array físico `messages` (`mensagens` no exemplo do usuário).
- [x] O comportamento para exclusão explícita de conversa está definido para turnos MongoDB e resumo Qdrant.
- [x] A política de retenção automática foi explicitamente deixada fora do escopo desta feature.

## Feature Readiness

- [x] A decisão confirmada de não persistir resumo no MongoDB está explícita.
- [x] A decisão anterior conflitante foi identificada como substituída para esta feature.
- [x] A atualização do resumo ocorre em segundo plano após o encerramento, sem bloquear o encerramento.
- [x] O comportamento esperado de idempotência, retry, reconciliação e proteção contra exclusão concorrente está definido em alto nível.
- [x] O escopo de migração de resumos legados está definido: validar/reutilizar Qdrant, reconstruir faltantes a partir dos turnos e remover a cópia Mongo após verificação.

## Notes

- Decisões confirmadas: resumo apenas no Qdrant; um documento MongoDB por conversa com mensagens no array físico `messages`; migração dos resumos legados; atualização assíncrona ao encerrar; exclusão conjunta dos dados nos dois armazenamentos; comportamento esperado de idempotência, retry, reconciliação e proteção contra jobs atrasados. A decisão atual substitui a interpretação anterior de um documento MongoDB por turno. Retenção automática fica fora do escopo. Parâmetros técnicos de execução permanecem no plano/implementação; qualquer detalhe que altere comportamento de usuário deve voltar para clarify.
