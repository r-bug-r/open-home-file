"""Document type classification.

Deterministic keyword scoring runs first and is authoritative when it is
confident. A model may only *add* a suggestion for unclassified documents, and
that suggestion is recorded with its source and confidence so the UI can show
it as a draft.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DocType

_KEYWORDS: dict[DocType, tuple[tuple[str, int], ...]] = {
    DocType.RECEIPT: (
        ("receipt", 4),
        ("sales receipt", 4),
        ("order confirmation", 3),
        ("subtotal", 2),
        ("change due", 2),
        ("thank you for your purchase", 2),
        ("vat", 1),
        ("total", 1),
    ),
    DocType.WARRANTY: (
        ("warranty", 5),
        ("guarantee", 3),
        ("serial number", 3),
        ("serial no", 3),
        ("coverage period", 2),
        ("defect", 2),
        ("proof of purchase", 2),
    ),
    DocType.BILL: (
        ("invoice", 4),
        ("amount due", 4),
        ("payment due", 3),
        ("bill to", 3),
        ("account number", 2),
        ("due date", 2),
        ("balance due", 3),
    ),
    DocType.CONTRACT: (
        ("agreement", 4),
        ("contract", 4),
        ("terms and conditions", 3),
        ("party of the first part", 2),
        ("termination", 3),
        ("governing law", 2),
    ),
    DocType.SUBSCRIPTION: (
        ("subscription", 5),
        ("renews", 3),
        ("renewal", 3),
        ("cancel anytime", 3),
        ("billing period", 2),
        ("monthly plan", 2),
        ("annual plan", 2),
    ),
}


@dataclass(frozen=True, slots=True)
class Classification:
    doc_type: DocType
    confidence: float
    evidence: tuple[str, ...] = ()


def classify_text(text: str) -> Classification:
    lowered = text.lower()
    scores: dict[DocType, int] = {}
    evidence: dict[DocType, list[str]] = {}
    for doc_type, keywords in _KEYWORDS.items():
        score = 0
        hits: list[str] = []
        for keyword, weight in keywords:
            count = lowered.count(keyword)
            if count:
                score += weight * min(count, 3)
                hits.append(keyword)
        if score:
            scores[doc_type] = score
            evidence[doc_type] = hits
    if not scores:
        return Classification(DocType.UNKNOWN, 0.0)
    best_type = max(scores, key=lambda item: scores[item])
    best_score = scores[best_type]
    runner_up = max((value for key, value in scores.items() if key != best_type), default=0)
    total = sum(scores.values())
    share = best_score / total if total else 0.0
    margin = (best_score - runner_up) / best_score if best_score else 0.0
    confidence = round(min(0.98, 0.45 + 0.4 * share + 0.15 * margin), 3)
    if best_score < 4:
        confidence = min(confidence, 0.5)
    return Classification(best_type, confidence, tuple(evidence[best_type]))
