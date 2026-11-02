# FAQ geral do QuiStock

## O que é o QuiStock?

O QuiStock é um aplicativo de apoio à decisão de estoque para lojas Swift no
varejo. Ele apresenta análises de fluxo de vendas, validade de produtos,
sugestões e decisões registradas. A proposta é apoiar decisões humanas sobre
risco de ruptura e perdas por vencimento.

## Como o modelo classifica o fluxo de vendas?

O modelo de Machine Learning publica uma classificação: `ALTO`, `NORMAL` ou
`BAIXO`. Para chegar a essa classificação, compara o produto com outros da
mesma categoria e da mesma loja, considerando uma janela móvel de 30 dias que
termina na data de corte da análise. O QuiStock consulta a classificação
publicada; não a recalcula com regras próprias.

## Como as classificações podem gerar sugestões?

- Fluxo `ALTO` pode gerar uma sugestão de pedido, para apoiar a prevenção de
  ruptura de estoque.
- Fluxo `BAIXO` com validade próxima pode gerar uma sugestão de promoção, para
  apoiar a redução de perdas por vencimento.
- Fluxo `NORMAL` gera um registro de acompanhamento `MONITOR`, sem entrar na
  triagem comercial.

Validade próxima significa vencimento em até 15 dias a partir da data de corte
da análise. Produtos já vencidos não recebem sugestão de promoção.

## Como funciona o fluxo de uma sugestão?

O modelo pode publicar sugestões candidatas. O funcionário faz a triagem e
pode encaminhar uma sugestão ao gerente regional. O gerente decide se aprova
ou recusa uma sugestão encaminhada. Depois da aprovação, o funcionário pode
consultar a sugestão aprovada dentro do escopo autorizado.

## O QuiStock envia pedidos ou ativa promoções?

Não. Pedidos e promoções apresentados pelo QuiStock são sugestões para apoiar
uma decisão humana. O aplicativo não envia pedidos de compra, não processa
compras nem ativa promoções automaticamente. A aprovação registra a decisão e
encerra o fluxo da sugestão dentro do aplicativo.

## Como as alterações e decisões ficam registradas?

O histórico distingue o valor original da sugestão, os ajustes feitos pelo
funcionário e o valor final decidido pelo gerente, quando aplicável. O
encaminhamento registra autor, data e as informações apresentadas naquele
momento. Um descarte é lógico: a sugestão sai da lista ativa, mas o evento
permanece no histórico de auditoria.

## Como o agente de FAQ responde?

O agente usa trechos recuperados da base de conhecimento e informa as fontes
quando elas estão disponíveis. Se a base não trouxer evidência suficiente,
ele informa que não encontrou suporte para a resposta.
