"""Translate a user-typed query into backend-specific syntax.

The user types a Google-ish query:

    acme support               two terms (implicit AND)
    "customer support"         quoted phrase (adjacency)
    refund*                    prefix match
    api -slow                  AND but exclude
    acme OR beta               either term

This module emits the right dialect for each backend. The fallback
backend ignores operators entirely (its query() does an OR of icontains
across the raw text), so this parser exists for SQLite and Postgres.

Kept deliberately small: ~50 LOC, no external parsing library. The
tradeoff is no support for nested groups (acme AND (refund OR beta));
SmallStack documents this in search.md.
"""

from __future__ import annotations

import re

# Words that look like operators (case-insensitive). Anything else is a term.
_OR_RE = re.compile(r"\bOR\b", re.IGNORECASE)
_QUOTED = re.compile(r'"([^"]+)"')
_TOKEN = re.compile(r'"[^"]+"|\S+')


def _tokens(query: str) -> list[str]:
    """Split a query string into tokens, keeping quoted phrases together."""
    return _TOKEN.findall(query.strip())


# ---- SQLite FTS5 dialect -------------------------------------------------


def to_fts5(query: str) -> str:
    """Translate to FTS5 MATCH syntax.

    FTS5 already speaks our user syntax pretty closely — quoted
    phrases, prefix `term*`, explicit OR. The main translation is the
    leading-dash exclusion (`-foo`) which FTS5 expects as `NOT foo`.
    """
    if not query.strip():
        return ""

    parts: list[str] = []
    for tok in _tokens(query):
        if tok.upper() == "OR":
            parts.append("OR")
            continue
        if tok.startswith("-") and len(tok) > 1:
            inner = tok[1:]
            parts.append(f"NOT {_quote_for_fts5(inner)}")
            continue
        parts.append(_quote_for_fts5(tok))

    return " ".join(parts)


def _quote_for_fts5(token: str) -> str:
    """Wrap raw tokens so FTS5 doesn't mistake them for operators.

    - Already-quoted phrases: passed through verbatim.
    - Prefix `foo*`: kept (FTS5 supports prefix matching).
    - Plain alphanumeric: wrap in double quotes (treats as a single
      term even if it contains FTS-reserved characters).
    """
    if token.startswith('"') and token.endswith('"'):
        return token
    if token.endswith("*") and re.match(r"^[\w-]+\*$", token):
        return token
    cleaned = token.replace('"', "")
    return f'"{cleaned}"'


# ---- PostgreSQL FTS dialect ----------------------------------------------


def to_postgres(query: str) -> tuple[str, str]:
    """Translate to a Postgres SearchQuery input.

    Returns (query_string, search_type) where search_type is one of:
      - "raw"      — for queries with operators (AND, OR, NOT, prefix)
      - "phrase"   — for a single quoted phrase
      - "plain"    — for plain space-separated terms (implicit AND)

    Postgres' tsquery syntax uses & (AND), | (OR), ! (NOT), :* (prefix).
    """
    if not query.strip():
        return "", "plain"

    tokens = _tokens(query)

    # If the whole thing is one quoted phrase, use phrase mode.
    if len(tokens) == 1 and tokens[0].startswith('"') and tokens[0].endswith('"'):
        inner = tokens[0][1:-1]
        return inner, "phrase"

    # If there are no operators or prefixes, use plain mode (cleanest).
    has_operators = any(
        tok.upper() == "OR" or tok.startswith("-") or tok.endswith("*")
        for tok in tokens
    )
    if not has_operators and not any('"' in t for t in tokens):
        return query.strip(), "plain"

    # Otherwise build a raw tsquery expression.
    pieces: list[str] = []
    pending_operator: str | None = None
    for tok in tokens:
        if tok.upper() == "OR":
            pending_operator = "|"
            continue

        if tok.startswith('"') and tok.endswith('"'):
            inner = tok[1:-1]
            words = [_clean_pg_term(w) for w in inner.split()]
            words = [w for w in words if w]
            if not words:
                continue
            piece = "(" + " <-> ".join(words) + ")"
        elif tok.startswith("-") and len(tok) > 1:
            cleaned = _clean_pg_term(tok[1:])
            if not cleaned:
                continue
            piece = f"!{cleaned}"
        elif tok.endswith("*"):
            cleaned = _clean_pg_term(tok[:-1])
            if not cleaned:
                continue
            piece = f"{cleaned}:*"
        else:
            piece = _clean_pg_term(tok)
            if not piece:
                # Skip tokens that are entirely operator chars (& | ! etc).
                continue

        if pieces:
            pieces.append(pending_operator or "&")
        pieces.append(piece)
        pending_operator = None

    return " ".join(pieces), "raw"


def _clean_pg_term(token: str) -> str:
    """Strip characters that would unbalance a tsquery expression."""
    return re.sub(r'[&|!():"*]', "", token).strip()
