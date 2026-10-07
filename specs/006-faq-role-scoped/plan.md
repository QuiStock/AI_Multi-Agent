# Plano técnico: FAQ por audiência

1. Resolver a audiência da fonte pelo diretório confiável durante a indexação.
2. Persistir `audience` em cada chunk e criar índice payload no Qdrant.
3. Usar uma collection versionada (`faq_v2`) para evitar pontos legados sem
   audiência.
4. Encaminhar `request` ao `FAQExecutor`.
5. Criar a ferramenta FAQ por requisição com escopo `shared + role`.
6. Manter `role_id` fora dos argumentos controlados pelo modelo.
7. Validar a collection antes do cutover com
   `scripts/validate_faq_index.py`.

O executor não mantém role em estado compartilhado. A autenticação continua
sendo responsável por obter o `role_id`; o FAQ apenas traduz os valores
canônicos 2 e 3 para seu filtro de audiência.
