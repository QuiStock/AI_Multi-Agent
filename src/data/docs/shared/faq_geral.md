# FAQ geral do Quistock

## O que é o Quistock?

O Quistock é um aplicativo de apoio à decisão de estoque para lojas Swift. Ele
consulta análises publicadas por um modelo de Machine Learning e apresenta
informações sobre fluxo de vendas, validade, sugestões e decisões registradas.

## O que significam as classes de fluxo?

O modelo de Machine Learning publica uma classificação de fluxo `ALTO`,
`NORMAL` ou `BAIXO`. A aplicação consulta essa classificação e não recalcula a
classe usando limiares próprios.

Para a classificação, o modelo compara o produto somente com produtos da mesma
categoria e da mesma loja em uma janela móvel de 30 dias encerrada na data de
corte da análise.

## Quando uma sugestão é apresentada?

- Fluxo `ALTO` pode gerar sugestão de pedido.
- Fluxo `BAIXO` com validade próxima pode gerar sugestão de promoção.
- Fluxo `NORMAL` gera um registro de acompanhamento `MONITOR`, sem entrar na
  triagem comercial.

Validade próxima significa vencimento em até 15 dias a partir da data de corte.
Um produto já vencido não recebe sugestão de promoção.

## O Quistock executa pedidos ou promoções?

Não. As sugestões são recomendações para apoiar uma decisão humana. O Quistock
não envia pedidos, não processa compras e não ativa promoções automaticamente.
Uma aprovação encerra o fluxo da sugestão dentro do aplicativo.

## Como as respostas do FAQ são produzidas?

O agente FAQ usa somente trechos recuperados da base de conhecimento e deve
indicar as fontes utilizadas. Quando não há evidência suficiente, ele deve
informar que não encontrou suporte para a resposta.
