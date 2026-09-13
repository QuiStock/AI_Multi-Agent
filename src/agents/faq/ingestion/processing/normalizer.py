import re
from dataclasses import replace

from src.agents.faq.models import DocumentLoaded


class DocumentNormalizer:
    def normalize(self, document: DocumentLoaded) -> DocumentLoaded:
        normalized_parts = tuple(
            replace(
                part,
                text=self.normalize_text(part.text),
            )
            for part in document.parts
        )

        return replace(
            document,
            parts=normalized_parts,
        )


    @staticmethod
    def normalize_text(text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        text = text.replace("\ufeff", "")
        text = text.replace("\u00a0", " ")

        lines = [
            line.rstrip()
            for line in text.split("\n")
        ]

        text = "\n".join(lines)

        # Mantém no máximo duas quebras de linha consecutivas.
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
