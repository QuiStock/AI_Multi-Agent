from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.graphs.state import Evidence, ResponseDraft

JevVerdict = Literal["approved", "rejected"]
JevReasonCode = Literal[
    "none",
    "missing_evidence",
    "unsupported_claim",
    "contradiction",
    "invalid_citation",
    "ambiguous_evidence",
    "low_confidence",
    "does_not_answer_question",
]

_REASON_CODES = {
    "none",
    "missing_evidence",
    "unsupported_claim",
    "contradiction",
    "invalid_citation",
    "ambiguous_evidence",
    "low_confidence",
    "does_not_answer_question",
}
_NOUL_APPROVAL_THRESHOLD = 0.70
_JUDGE_RULES = (
    "Se o state incluir prior_assistant_message, esse texto é apenas contexto "
    "para entender o que o usuário pediu. Julgue se o pedido faz sentido "
    "diante dele e se a resposta candidata corresponde às evidências deste "
    "turno. A mensagem anterior não sustenta fato, número, nome ou preço. "
    "Sem esse campo, julgue apenas a mensagem do usuário.\n"
    "<sobre memória>\n"
    'Perguntas como "o que falamos tal dia", "sobre o que falamos mais cedo", '
    '"o que foi falado" e "sobre o que conversamos", e qualquer menção a '
    "outro dia, são memory recall. "
    '"Mais cedo" é conversa anterior recuperada, não a mensagem imediatamente '
    "anterior. A evidência tem source_type conversation_summary. Não chame "
    "tool: confira as evidências já presentes. Uma lista com até três "
    "resumos atende, inclusive quando a pergunta é singular. Se o status "
    "for semantic ou "
    "temporal, repetir o resumo atende, inclusive nome, preço e regra que "
    "já estejam nesse resumo. Se o status for recent_fallback, apresentar "
    "as conversas como recentes, sem tratá-las como correspondência do "
    "assunto, atende. Se o status for not_found, declarar que a referência "
    "não foi encontrada atende. Não aprove um texto de memória que troque "
    "esses status. Aprove o texto que segue o status com reason_code none. "
    "Combinada com evidência de produto ou de política, a parte sobre a "
    "conversa anterior segue esta seção e o restante segue a seção "
    "correspondente. Não acrescente fato comercial que o resumo não contém.\n"
    "</sobre memória>\n"
    "<sobre produtos ou sugestão>\n"
    "Ignore esta seção quando todas as evidências citadas forem "
    "conversation_summary. "
    "As tools comerciais podem devolver uma listagem, e essa listagem pode "
    "ter mais de uma página. Perguntas como quais promoções, quais pedidos, "
    "quais sugestões e quais as sugestões de promoções vigentes são pergunta "
    "de listagem. A lista fiel da evidência ambiguous deste turno atende, "
    "mesmo que a pergunta diga sugestões e o título diga promoções, ou o "
    "contrário. Aprove com reason_code none. Um pedido página_n, como "
    "página 2, pagina 2 ou próxima página, não é o item de mesmo número. "
    "A evidência esperada é outra lista com status ambiguous e candidates, "
    "com position e nome. "
    "A lista que reproduz a posição e o nome de cada candidate, sem preço "
    "e sem campo ausente da evidência, atende a esse pedido. A página 2 "
    "pode começar na posição 7, porque a numeração continua entre páginas. "
    "O título da lista e a frase final, para pedir a próxima página ou para "
    "escolher um número, fazem parte dessa resposta e não são alegação sem "
    "suporte. Essa lista não contradiz a mensagem anterior. O pedido "
    '"próxima página" é o mesmo caso de página_n. Quando o candidate '
    "tem suggestion_type, o sufixo (pedido) ou (promoção) faz parte da "
    "lista fiel. Aprove essa lista com reason_code none. Se a evidência "
    "for um único card unique de promotion-expiration, explicar esse "
    "card atende à pergunta sobre qual promoção vence mais cedo ou dura "
    "mais, inclusive o preço promocional e as datas que estão no card, "
    "e a direction nearest ou longest sustenta essa comparação. Aprove "
    "com reason_code none. Um número que está "
    "na listagem já mostrada, como 2, opção 7 ou quero a 12, espera o "
    "detalhe do produto: um único card unique, em geral suggestion-detail. "
    "Explicar esse card atende à pergunta. Não repita o selection_id. Se "
    "houver uma única evidência com status unique e um card, em "
    "product-search, suggestion-list, promotion-expiration ou "
    "suggestion-detail, explicar esse card atende à pergunta sobre o "
    "produto. Loja, triagem, origem, status interno e preço de referência "
    "continuam alegação sem suporte, porque não estão no card. Se a "
    "evidência tiver status not_found, a frase que só declara a ausência "
    "atende à pergunta. Não use ambiguous_evidence quando a resposta for "
    "essa lista fiel. Use ambiguous_evidence quando a resposta escolher um "
    "produto sem um card unique.\n"
    "</sobre produtos ou sugestão>\n"
    "<sobre políticas>\n"
    "Se a evidência do FAQ tiver outcome not_found e result_count 0, "
    "a frase que declara a ausência documental atende à pergunta.\n"
    "</sobre políticas>"
)


@dataclass(frozen=True)
class JevEvaluation:
    verdict: JevVerdict
    reason_code: JevReasonCode
    model: str
    noul_probability: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class JevJudgeClientPort(Protocol):
    def evaluate(
        self,
        *,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> JevEvaluation: ...


class JevClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TypeSafeJevClient:
    """Small synchronous adapter for TypeSafe's System One API."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "jev-1.13.0",
        base_url: str = "https://api.typesafe.ai",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

        if not self.model:
            raise ValueError("O modelo JEV é obrigatório")
        if not self.base_url:
            raise ValueError("A URL da API TypeSafe é obrigatória")
        if timeout_seconds <= 0:
            raise ValueError("O timeout do JEV deve ser maior que zero")

    @staticmethod
    def _questions() -> dict[str, dict[str, Any]]:
        return {
            "verdict": {
                "type": "noul",
                "instructions": (
                    "Aplique o campo regras do state. "
                    "Se uma seção disser que o texto atende, o veredito é "
                    "verdadeiro e a confiança deve ficar alta. "
                    "Não baixe a confiança só porque um resumo de memória "
                    "repete nome ou preço que já está na evidência. "
                    "Um pedido página_n, como página 2 ou próxima página, "
                    "respondido pela lista fiel da evidência deste turno "
                    "atende à pergunta. "
                    "Um número da listagem respondido pelo único card unique "
                    "atende à pergunta. "
                    "Uma pergunta de listagem respondida pela lista fiel atende. "
                    "Sobre o que falamos mais cedo, o que foi falado ou uma "
                    "menção a outro dia, respondidos pelo status da evidência "
                    "de memória, atendem à pergunta. "
                    "A resposta segue a regra da seção correspondente?"
                ),
                "criteria": {
                    "true": (
                        "Uma regra do campo regras diz que este texto atende, "
                        "como lista fiel, card unique, ausência ou resumo de "
                        "memória no status certo. Isso basta, mesmo com nome "
                        "ou preço copiados do resumo. Se a resposta gerada "
                        "estiver sustentada pelas evidências, atende à pergunta."
                    ),
                    "false": (
                        "Nenhuma regra do campo regras diz que o texto atende, "
                        "e a resposta não corresponde à pergunta ou traz fato "
                        "que nenhuma evidência autoriza."
                    ),
                },
            },
            "reason_code": {
                "type": "choice",
                "instructions": (
                    "Qual é o principal motivo para o veredito? Use none "
                    "quando a resposta estiver aprovada."
                ),
                "criteria": {
                    "none": "A resposta está integralmente sustentada.",
                    "missing_evidence": (
                        "A evidência necessária não foi fornecida ou não existe "
                        "entre as evidências disponíveis."
                    ),
                    "unsupported_claim": (
                        "Uma ou mais alegações não são sustentadas pelas "
                        "evidências. O título da listagem e a frase final "
                        "sobre a próxima página ou sobre escolher um número "
                        "não são alegação sem suporte quando a lista reproduz "
                        "os candidates. Não use quando o texto apenas repete um "
                        "resumo de conversation_summary."
                    ),
                    "contradiction": (
                        "A resposta contradiz uma evidência disponível. "
                        "Uma lista de outra página, com positions diferentes "
                        "da mensagem anterior, não é contradição."
                    ),
                    "invalid_citation": (
                        "A resposta usa uma citação que não sustenta o conteúdo."
                    ),
                    "ambiguous_evidence": (
                        "A resposta escolhe um produto sem um card unique. "
                        "Não use este motivo quando a resposta reproduz a "
                        "lista de candidates com posição e nome, inclusive "
                        "quando o pedido for página_n, nem quando "
                        "o texto de memória segue o status da evidência."
                    ),
                    "low_confidence": (
                        "O julgamento não tem confiança suficiente para "
                        "liberar a resposta."
                    ),
                    "does_not_answer_question": (
                        "A resposta não atende à pergunta atual, mesmo que "
                        "suas afirmações estejam sustentadas. Não use este "
                        "motivo quando uma pergunta de listagem, página_n ou a "
                        "expressão próxima página for respondida pela lista "
                        "fiel da evidência deste turno, quando um único card "
                        "promotion-expiration responder qual promoção vence "
                        "mais cedo ou dura mais, quando um número da listagem "
                        "for respondido pelo único card unique, quando a "
                        "resposta só declarar a ausência sustentada por status "
                        "not_found ou por outcome not_found do FAQ, ou quando "
                        "sobre o que falamos mais cedo, o que foi falado ou "
                        "uma menção a outro dia for respondida pelo status da "
                        "evidência de memória: semantic, temporal, "
                        "recent_fallback ou not_found."
                    ),
                },
            },
        }

    @staticmethod
    def _choice(
        answers: Mapping[str, Any],
        question_id: str,
    ) -> tuple[str, Mapping[str, Any]]:
        answer = answers.get(question_id)
        if not isinstance(answer, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                f"A resposta {question_id} do JEV é inválida.",
            )

        choice = answer.get("choice")
        if not isinstance(choice, str) or not choice:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                f"A escolha {question_id} do JEV é inválida.",
            )
        return choice, answer

    @staticmethod
    @staticmethod
    def _noul_probability(answer: Mapping[str, Any]) -> float:
        probability = answer.get("noul")
        if not isinstance(probability, (int, float)):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV não retornou uma probabilidade noul válida.",
            )
        normalized = float(probability)
        if not 0 <= normalized <= 1:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A probabilidade noul retornada pelo JEV está fora do intervalo.",
            )
        return normalized

    def _payload(
        self,
        *,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "user_question": user_question,
            "response_draft": response_draft,
            "evidences": list(evidences),
            "regras": _JUDGE_RULES,
        }
        if prior_assistant_message:
            state["prior_assistant_message"] = prior_assistant_message
        return {
            "model": self.model,
            "state": state,
            "questions": self._questions(),
        }

    def _request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.api_key:
            raise JevClientError(
                "JEV_API_KEY_MISSING",
                "A chave da API TypeSafe não está configurada.",
            )

        request = Request(
            f"{self.base_url}/v1/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read()
        except HTTPError as exc:
            if exc.code == 401:  # noqa: PLR2004
                code = "JEV_AUTHENTICATION_FAILED"
            elif exc.code == 429:  # noqa: PLR2004
                code = "JEV_RATE_LIMITED"
            elif exc.code == 529:  # noqa: PLR2004
                code = "JEV_OVERLOADED"
            else:
                code = "JEV_HTTP_ERROR"
            raise JevClientError(
                code, "A API TypeSafe não respondeu com sucesso."
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise JevClientError(
                "JEV_UNAVAILABLE",
                "A API TypeSafe está indisponível.",
            ) from exc

        try:
            decoded = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe retornou JSON inválido.",
            ) from exc

        if not isinstance(decoded, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe retornou uma estrutura inválida.",
            )
        return decoded

    def evaluate(
        self,
        *,
        user_question: str,
        response_draft: ResponseDraft,
        evidences: Sequence[Evidence],
        prior_assistant_message: str | None = None,
    ) -> JevEvaluation:
        payload = self._payload(
            user_question=user_question,
            prior_assistant_message=prior_assistant_message,
            response_draft=response_draft,
            evidences=evidences,
        )
        response = self._request(payload)
        answers = response.get("answers")
        if not isinstance(answers, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A API TypeSafe não retornou answers.",
            )

        verdict_answer = answers.get("verdict")
        if not isinstance(verdict_answer, Mapping):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A resposta verdict do JEV é inválida.",
            )
        reason_code, _ = self._choice(answers, "reason_code")
        if reason_code not in _REASON_CODES:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O JEV retornou uma opção fora do contrato.",
            )
        noul_probability = self._noul_probability(verdict_answer)
        verdict: JevVerdict = (
            "approved"
            if reason_code == "none" and noul_probability >= _NOUL_APPROVAL_THRESHOLD
            else "rejected"
        )
        if reason_code == "none" and verdict == "rejected":
            reason_code = "low_confidence"

        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            usage = {}

        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if input_tokens is not None and not isinstance(input_tokens, int):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O uso de tokens de entrada do JEV é inválido.",
            )
        if output_tokens is not None and not isinstance(output_tokens, int):
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "O uso de tokens de saída do JEV é inválido.",
            )

        model = response.get("model", self.model)
        if not isinstance(model, str) or not model:
            raise JevClientError(
                "JEV_INVALID_OUTPUT",
                "A versão do modelo JEV é inválida.",
            )

        return JevEvaluation(
            verdict=verdict,
            reason_code=cast(JevReasonCode, reason_code),
            model=model,
            noul_probability=noul_probability,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
