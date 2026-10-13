# Plano

1. Ler o documento MongoDB por `conversation_id` e email autenticado, aceitando somente `active` e `ended`, sem mutações e preservando a ordem do array.
2. Expor o histórico por schema, service, controller e rota GET protegida pela autenticação existente.
3. Mapear ausência/escopo para 404 e falha do MongoDB para 503.
4. Verificar o contrato HTTP, isolamento por usuário, ordem e persistência após append.
5. No cliente, após o POST de mensagem bem-sucedido, chamar o GET e usar a lista retornada como estado completo do chat; manter a lista atual caso o GET falhe.
