# FAQ do funcionário

## O que o funcionário pode consultar?

O funcionário consulta sugestões disponíveis para triagem e informações da
própria loja. O acesso é limitado pelo escopo autorizado da identidade
autenticada.

## O funcionário pode encaminhar uma sugestão?

Sim. O funcionário pode encaminhar ao gerente uma sugestão que considere
pertinente. O sistema registra o autor, a data e o retrato das informações
apresentadas no encaminhamento.

## O funcionário pode alterar uma sugestão do Machine Learning?

Sim. Antes do encaminhamento, o funcionário pode editar a quantidade de lotes
de uma sugestão de pedido ou o percentual de desconto de uma sugestão de
promoção. O valor original calculado pelo modelo permanece registrado.

## O funcionário pode descartar uma sugestão?

Sim. Uma sugestão candidata do Machine Learning que ainda não foi encaminhada
pode ser descartada da triagem. O descarte é lógico: a sugestão deixa de
aparecer na lista ativa, mas o evento permanece no log de auditoria.

## O funcionário pode criar uma sugestão manual?

Sim. O funcionário pode criar uma sugestão manual de pedido ou promoção para um
produto da própria loja e encaminhá-la ao gerente. Ela deve ser identificada
como origem humana, não como resultado do Machine Learning.

## O que acontece depois da aprovação?

O funcionário pode consultar sugestões aprovadas da própria loja. A aprovação
não significa que um pedido foi enviado ou que uma promoção foi ativada fora
do aplicativo.
