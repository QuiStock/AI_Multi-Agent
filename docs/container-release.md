# Imagem ARM64 e implantação no Infra

A imagem `ghcr.io/quistock/ai-multi-agent` usa `linux/arm64` e o lockfile do projeto.
O workflow Container image (ARM64) valida o build em PR, sem publicar.
Publish chatbot image publica no GHCR em release estável ou execução manual.
A referência por digest aparece no resumo da execução; tags manuais usam o SHA
do commit e releases usam sua tag. O workflow não faz deploy nem Terraform apply.

## Preparar as imagens junto com a PR de Infra

1. Mescle esta PR de publicação na main do serviço.
2. Em Actions, execute Publish chatbot image na main com
   `infra_ref=codex/simplify-four-apps` enquanto a PR QuiStock-Infra #29 estiver
   aberta. Após sua integração, use o padrão `main`.
3. Para uma PR automática com o digest, configure `INFRA_REPO_TOKEN`: token
   fine-grained limitado a QuiStock-Infra com Contents e Pull requests em escrita.
   Sem esse secret, a imagem ainda é publicada; copie a referência do resumo
   para as imagens dos containers `api-chatbot` e `summary-worker` em
   `clusters/us-east1/apps/api-chatbot/deployment.yaml` na PR de Infra.
4. Na primeira publicação, confira que o pacote GHCR está público para permitir
   pull sem credenciais. Se permanecer privado, configure imagePullSecrets no
   Kubernetes antes do bootstrap.
5. A PR automática usa como base a branch indicada em infra_ref. Ela aceita o
   placeholder inicial ou um digest/tag existente e atualiza as duas imagens
   juntas. Durante a migração aceita também o Deployment anterior, com somente
   a API. Recusa containers inesperados ou imagem inválida antes de escrever.
   Não altera IDs Bitwarden, Secrets ou imagens de outros apps.
6. Integre os digests na PR de Infra, preencha os IDs Bitwarden e mescle o Infra
   em main. Só então execute o provisionamento/bootstrap: Argo acompanha main.

O chatbot mantém API na porta 8000 e requer seus Secrets externos. O Infra
executa o worker em um segundo container no mesmo Deployment, com a mesma
imagem e o mesmo Secret, usando `python -m src.memory.worker.run_summary_worker`.
A API inicia Uvicorn pelo CMD padrão; o worker não expõe porta HTTP. A imagem
ARM64 é validada com imports de ambos os entry points sem acessar provedores.
Não é necessário mudar o Dockerfile nem publicar um pacote separado.

Integre primeiro esta mudança de publicação, depois a PR do Infra que adiciona
o worker. A imagem atualmente publicada já contém o módulo; publicações futuras
mantêm API e worker no mesmo digest. O workflow só altera o manifest existente,
não cria o container worker. Para preparar uma nova imagem antes de integrar o
Infra, use `infra_ref` apontando à branch da PR do worker.

Para acompanhar o processo:

```bash
kubectl logs -n api-chatbot deployment/api-chatbot -c summary-worker --tail=100 -f
```

Readiness da API não comprova conclusão de resumos. Faça um teste de
encerramento de conversa autenticada e confirme conclusão do job e indexação
no Qdrant depois do deploy; MongoDB, Redis, Qdrant e credenciais de IA precisam
estar acessíveis. O worker compartilha escala e rollouts com a API, e leases
coordenam consumidores durante sobreposição de Pods.

O website compila `VITE_API_URL=/api`,
serve React na porta 8080 e aceita a configuração Nginx montada pelo Infra para
rotear /api e /auth. O runtime do website usa usuário sem privilégios; o Infra
configura PID e arquivos temporários em /tmp. Rotas/Auth e integração entre APIs
continuam sujeitas aos contratos das aplicações, independentemente da publicação.

Para releases seguintes, crie uma release estável depois de revisar o commit.
O workflow abre uma PR para main do Infra quando o token estiver configurado.
Não publique prereleases esperando deploy automático: elas são ignoradas.
