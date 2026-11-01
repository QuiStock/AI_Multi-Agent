# QuiStock Observe

Frontend independente para explorar métricas, traces, conversas e executar experimentos isolados de prompt.

## Serviços

- API FastAPI: `http://127.0.0.1:8000`
- Frontend Vite: `http://127.0.0.1:5173`

Em terminais separados, na raiz do repositório:

```powershell
uv run uvicorn src.main:app --reload --port 8000
```

```powershell
cd src/observability/front-observer
npm install
npm run dev
```

O Vite encaminha `/api` para a API. Para apontar a outro host durante o desenvolvimento, configure `OBSERVABILITY_API_URL` antes de iniciar o Vite. Para uma implantação estática, `VITE_API_BASE_URL` é incorporada durante o build e aceita tanto a raiz da API quanto a URL completa com `/api/v1`. Exemplo no Render: `https://api-chatbot-gdox.onrender.com`.

## Configuração no Render

- No serviço estático `quistock-ai-observability`, defina `VITE_API_BASE_URL=https://api-chatbot-gdox.onrender.com` nas variáveis de build. O frontend acrescenta `/api/v1` quando a variável contém apenas a raiz.
- No serviço da API, defina `OBSERVABILITY_FRONTEND_ORIGIN=https://quistock-ai-observability.onrender.com` e `OBSERVABILITY_SESSION_SECRET` com um segredo aleatório próprio, de pelo menos 32 caracteres. Não reutilize `JWT_SECRET` das conversas.
- O container escuta `0.0.0.0:$PORT` (padrão local 10000). Em **Settings → Health Check Path** do serviço da API, configure `/health`.
- Após alterar variáveis do frontend, faça um novo build; variáveis `VITE_*` são compiladas no bundle estático.

A sessão da observabilidade usa um cookie `HttpOnly`, separado do JWT do chatbot. Em produção ele é `Secure` e `SameSite=None` para permitir as chamadas autenticadas entre os dois serviços Render.

## Atualização e trace ao vivo

O frontend consulta `GET /api/v1/observability/traces/live` a cada quatro segundos e envia o cursor `after`, recebendo somente eventos novos. A tela mostra o horário e a duração medidos no browser para cada fetch, além do tempo decorrido desde o início do trace para cada evento. Métricas, lista de traces e conversas são carregadas ao abrir a página, ao aplicar filtros, ao paginar e depois que um trace termina.

O feed ao vivo é um buffer limitado à memória de cada processo FastAPI. A gravação definitiva dos traces e logs correlacionados continua no MongoDB após o turno. Em execução com vários workers, cada processo terá seu próprio feed; Redis pub/sub ou outra camada compartilhada será uma evolução necessária para distribuir eventos entre workers.

O laboratório carrega o prompt e as tools do card. A execução chama o modelo com esse prompt e esse schema, para antes de executar a tool e mostra o `name` e os `args` da chamada. Não altera o código nem a conversa original.
