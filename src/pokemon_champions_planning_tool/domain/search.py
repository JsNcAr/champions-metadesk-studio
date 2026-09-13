"""Search query parsing for inclusions, exclusions, and structured tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(
    r'(?:^|[\s,]+)([-!])?(?:\"([^\"]*)\"?|\'([^\']*)\'?|([^ \t\r\n,]+))'
)
_PREFIX_NEGATIONS = ("without:", "not:", "no:")


@dataclass(frozen=True)
class QueryToken:
    is_neg: bool
    value: str
    raw_token: str


@dataclass(frozen=True)
class ParsedSearchQuery:
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    tokens: tuple[QueryToken, ...]


def parse_search_query(text: str | None) -> ParsedSearchQuery:
    """Parse a search string into positive (include) and negative (exclude) terms.

    Supports:
    - Negation prefixes: ``-species``, ``!species``, ``without:species``, ``not:species``
    - Quoted multi-word names: ``"iron hands"``, ``-"iron hands"``, ``!"flutter mane"``
    - Hyphenated names: ``ho-oh`` (include), ``-ho-oh`` (exclude), ``-iron-hands`` (exclude)
    - Comma or whitespace delimiters
    - Gracefully handles unclosed quotes or bare symbols
    """
    if not text:
        return ParsedSearchQuery(includes=(), excludes=(), tokens=())

    includes: list[str] = []
    excludes: list[str] = []
    tokens: list[QueryToken] = []

    for match in _TOKEN_PATTERN.finditer(text):
        prefix = match.group(1)
        val = (
            match.group(2)
            if match.group(2) is not None
            else (match.group(3) if match.group(3) is not None else match.group(4))
        )
        if not val:
            continue

        cleaned = val.strip()
        if not cleaned:
            continue

        is_neg = bool(prefix)
        # If token was quoted with negation inside quotes (e.g. "-iron hands") or starts with - / !
        if not is_neg and cleaned.startswith(("-", "!")):
            is_neg = True
            cleaned = cleaned.lstrip("-!").strip()

        if not is_neg:
            cleaned_lower = cleaned.lower()
            for p in _PREFIX_NEGATIONS:
                if cleaned_lower.startswith(p):
                    is_neg = True
                    cleaned = cleaned[len(p) :].strip("\"'").strip()
                    break

        if not cleaned:
            continue

        raw_token = match.group(0).strip(" ,")
        token_obj = QueryToken(is_neg=is_neg, value=cleaned, raw_token=raw_token)
        tokens.append(token_obj)

        if is_neg:
            excludes.append(cleaned)
        else:
            includes.append(cleaned)

    return ParsedSearchQuery(
        includes=tuple(includes),
        excludes=tuple(excludes),
        tokens=tuple(tokens),
    )


def remove_query_token(query: str | None, token_to_remove: str) -> str:
    """Remove a specific token from the search query string and return the updated query."""
    if not query:
        return ""
    parsed = parse_search_query(query)
    target = token_to_remove.strip()
    remaining: list[str] = []
    removed = False

    for t in parsed.tokens:
        if not removed and (t.raw_token == target or t.value == target or f"-{t.value}" == target or f"!{t.value}" == target):
            removed = True
            continue
        remaining.append(t.raw_token)

    return " ".join(remaining)

