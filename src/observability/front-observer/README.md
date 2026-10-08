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

O Vite encaminha `/api` para a API. Para apontar a outro host durante o desenvolvimento, configure `OBSERVABILITY_API_URL` antes de iniciar o Vite. Para uma implantação estática em outro domínio, defina `VITE_API_BASE_URL` no build.

## Atualização e trace ao vivo

O frontend consulta `GET /api/v1/observability/traces/live` a cada quatro segundos e envia o cursor `after`, recebendo somente eventos novos. A tela mostra o horário e a duração medidos no browser para cada fetch, além do tempo decorrido desde o início do trace para cada evento. Métricas, lista de traces e conversas são carregadas ao abrir a página, ao aplicar filtros, ao paginar e depois que um trace termina.

O feed ao vivo é um buffer limitado à memória de cada processo FastAPI. A gravação definitiva dos traces e logs correlacionados continua no MongoDB após o turno. Em execução com vários workers, cada processo terá seu próprio feed; Redis pub/sub ou outra camada compartilhada será uma evolução necessária para distribuir eventos entre workers.

O laboratório carrega o prompt cadastrado do agente, mas o endpoint atual executa uma chamada direta ao modelo configurado: não executa o nó do grafo nem suas tools e não salva as alterações no código ou na conversa original.
