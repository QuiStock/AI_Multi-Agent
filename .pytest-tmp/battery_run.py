"""One-shot live battery. Not part of the application."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BLOCKED = "Não encontrei informação documentada suficiente"
OUT = Path(".pytest-tmp/battery.jsonl")

TURNS = [
    ("bat-orders", "Quais são os pedidos vigentes?"),
    ("bat-orders", "1"),
    ("bat-both", "Quais são as sugestões vigentes?"),
    ("bat-both", "próxima página"),
    ("bat-name", "Tem sugestão de Agua de Coco?"),
    ("bat-near", "Qual promoção vence mais cedo?"),
    ("bat-until", "Quais promoções vencem até 15/11/2026?"),
    ("bat-miss", "Tem sugestão do produto InexistenteXYZ?"),
    ("bat-bad", "Quais são as promoções vigentes?"),
    ("bat-bad", "99"),
]


def post(conv: str, message: str) -> dict[str, str]:
    body = json.dumps(
        {
            "message": message,
            "sent_at": "2026-10-23T15:00:00Z",
            "is_resuming_conversation": False,
        },
        ensure_ascii=False,
    ).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/conversations/{conv}/messages",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read().decode())
    text = data.get("response") or ""
    row = {
        "conv": conv,
        "message": message,
        "status": data.get("status", ""),
        "request_id": data.get("request_id", ""),
        "blocked": str(text.startswith(BLOCKED)),
        "response": text,
    }
    with OUT.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(conv, "|", message, "|", row["status"], "|", row["blocked"], "|", row["request_id"])
    return row


def main() -> None:
    OUT.write_text("", encoding="utf-8")
    for conv, message in TURNS:
        post(conv, message)


if __name__ == "__main__":
    main()
