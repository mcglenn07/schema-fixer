"""Header-only similarity shared by inspection and the baseline proposer."""

import re

from rapidfuzz.fuzz import WRatio


def normalize_header(name: str) -> str:
    return re.sub(r"[\W_]", "", name.casefold())


def rename_hints(
    sources: list[str], targets: list[str]
) -> dict[str, tuple[str, float]]:
    scores = {
        (source, target): WRatio(normalize_header(source), normalize_header(target))
        for source in sources
        for target in targets
    }
    hints = {}
    for target in targets:
        ranked = sorted(((scores[s, target], s) for s in sources), reverse=True)
        if not ranked:
            continue
        score, source = ranked[0]
        if score < 85 or (len(ranked) > 1 and score - ranked[1][0] < 10):
            continue
        competitors = [scores[source, t] for t in targets if t != target]
        if competitors and score - max(competitors) < 10:
            continue
        hints[target] = (source, round(score / 100, 3))
    return hints
