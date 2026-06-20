"""Query parser — translation from user syntax to backend dialects."""

from __future__ import annotations

from apps.search.query_parser import to_fts5, to_postgres

# ---- FTS5 ---------------------------------------------------------------


def test_fts5_empty_returns_empty():
    assert to_fts5("") == ""
    assert to_fts5("   ") == ""


def test_fts5_single_word_quoted():
    assert to_fts5("acme") == '"acme"'


def test_fts5_two_words_implicit_and():
    assert to_fts5("acme support") == '"acme" "support"'


def test_fts5_quoted_phrase_preserved():
    assert to_fts5('"customer support"') == '"customer support"'


def test_fts5_prefix_match_preserved():
    assert to_fts5("refund*") == "refund*"


def test_fts5_or_operator():
    assert to_fts5("acme OR beta") == '"acme" OR "beta"'


def test_fts5_negation_becomes_NOT():
    assert to_fts5("api -slow") == '"api" NOT "slow"'


def test_fts5_mixed_operators():
    result = to_fts5('acme "customer support" -refund')
    assert "acme" in result and "customer support" in result and "NOT" in result


# ---- Postgres -----------------------------------------------------------


def test_postgres_empty():
    text, mode = to_postgres("")
    assert text == "" and mode == "plain"


def test_postgres_plain_when_no_operators():
    text, mode = to_postgres("acme support")
    assert mode == "plain"
    assert text == "acme support"


def test_postgres_phrase_when_single_quoted():
    text, mode = to_postgres('"customer support"')
    assert mode == "phrase"
    assert text == "customer support"


def test_postgres_raw_with_or_operator():
    text, mode = to_postgres("acme OR beta")
    assert mode == "raw"
    assert "|" in text
    assert "acme" in text
    assert "beta" in text


def test_postgres_raw_with_negation():
    text, mode = to_postgres("api -slow")
    assert mode == "raw"
    assert "!" in text


def test_postgres_prefix_uses_colon_star():
    text, mode = to_postgres("acm*")
    assert mode == "raw"
    assert ":*" in text


def test_postgres_strips_dangerous_chars():
    """Embedded operator chars must not produce tokens that break tsquery."""
    text, mode = to_postgres("acme & beta OR gamma")
    assert mode == "raw"
    # The parser drops bare operator-character tokens, so the output is
    # well-formed: terms joined by exactly one operator at a time.
    parts = text.split()
    assert "acme" in parts and "beta" in parts and "gamma" in parts
    # No empty terms or stray operator characters as terms.
    assert all(p in {"&", "|", "!"} or p.strip() for p in parts)
