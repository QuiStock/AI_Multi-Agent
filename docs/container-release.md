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
   para `clusters/us-east1/apps/api-chatbot/deployment.yaml` na PR de Infra.
4. Na primeira publicação, confira que o pacote GHCR está público para permitir
   pull sem credenciais. Se permanecer privado, configure imagePullSecrets no
   Kubernetes antes do bootstrap.
5. A PR automática usa como base a branch indicada em infra_ref. Ela aceita o
   placeholder inicial ou um digest/tag existente e altera somente a imagem
   deste Deployment. Não altera IDs Bitwarden, Secrets ou imagens de outros apps.
6. Integre os digests na PR de Infra, preencha os IDs Bitwarden e mescle o Infra
   em main. Só então execute o provisionamento/bootstrap: Argo acompanha main.

O chatbot mantém API na porta 8000 e requer seus Secrets externos; não se cria
worker ou rota pública neste workflow. O website compila `VITE_API_URL=/api`,
serve React na porta 8080 e aceita a configuração Nginx montada pelo Infra para
rotear /api e /auth. O runtime do website usa usuário sem privilégios; o Infra
configura PID e arquivos temporários em /tmp. Rotas/Auth e integração entre APIs
continuam sujeitas aos contratos das aplicações, independentemente da publicação.

## Diagnosticar readiness

`GET /health` retorna `ok` ou `unavailable` por dependência. Quando um probe
falha ou excede o timeout, a API escreve `health_probe_failed` em stdout do
container, incluindo nome da dependência, tipo da exceção e uma mensagem
sanitizada. Consulte os logs do deployment `api-chatbot` no namespace usado
pelo Infra. A resposta HTTP não inclui mensagens internas nem credenciais.

Para releases seguintes, crie uma release estável depois de revisar o commit.
O workflow abre uma PR para main do Infra quando o token estiver configurado.
Não publique prereleases esperando deploy automático: elas são ignoradas.
