"""A dependency-free RSS 2.0 + Atom 1.0 parser.

Covers the two formats that make up the overwhelming majority of real feeds,
using only the stdlib (``xml.etree`` + ``email.utils`` for RFC-822 dates). It is
deliberately lenient — a missing field yields an empty string, not an error.

The collector calls :func:`parse_feed`; it's a separate seam so a downstream
that needs exotic formats (RSS 1.0/RDF, iTunes/Media RSS specifics) can swap in
``feedparser`` behind the same :class:`ParsedItem` shape.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"


@dataclass
class ParsedItem:
    title: str = ""
    link: str = ""
    guid: str = ""
    summary: str = ""
    author: str = ""
    published: datetime | None = None
    enclosures: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def parse_feed(content: bytes | str) -> list[ParsedItem]:
    """Parse RSS 2.0 or Atom bytes/str into a list of :class:`ParsedItem`."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    root = ET.fromstring(content)
    tag = _localname(root.tag)
    if tag == "feed":  # Atom
        return [_atom_entry(e) for e in root.findall(f"{ATOM}entry")]
    # RSS 2.0: <rss><channel><item>…
    channel = root.find("channel")
    items = (channel.findall("item") if channel is not None else root.findall(".//item"))
    return [_rss_item(it) for it in items]


# --- RSS 2.0 -------------------------------------------------------------


def _rss_item(el: ET.Element) -> ParsedItem:
    title = _text(el, "title")
    link = _text(el, "link")
    guid = _text(el, "guid") or link or title
    enclosures = []
    for enc in el.findall("enclosure"):
        url = enc.get("url", "")
        if url:
            enclosures.append({
                "url": url,
                "length": enc.get("length", ""),
                "type": enc.get("type", ""),
            })
    return ParsedItem(
        title=title,
        link=link,
        guid=guid,
        summary=_text(el, "description"),
        author=_text(el, "author") or _text(el, f"{DC}creator"),
        published=_parse_date(_text(el, "pubDate") or _text(el, f"{DC}date")),
        enclosures=enclosures,
        raw=_raw(el),
    )


# --- Atom 1.0 ------------------------------------------------------------


def _atom_entry(el: ET.Element) -> ParsedItem:
    link = ""
    enclosures = []
    for lnk in el.findall(f"{ATOM}link"):
        rel = lnk.get("rel", "alternate")
        href = lnk.get("href", "")
        if rel == "alternate" and not link:
            link = href
        elif rel == "enclosure" and href:
            enclosures.append({
                "url": href,
                "length": lnk.get("length", ""),
                "type": lnk.get("type", ""),
            })
    author = ""
    author_el = el.find(f"{ATOM}author")
    if author_el is not None:
        name_el = author_el.find(f"{ATOM}name")
        author = name_el.text.strip() if name_el is not None and name_el.text else ""
    published = _text(el, f"{ATOM}published") or _text(el, f"{ATOM}updated")
    return ParsedItem(
        title=_text(el, f"{ATOM}title"),
        link=link,
        guid=_text(el, f"{ATOM}id") or link,
        summary=_text(el, f"{ATOM}summary") or _text(el, f"{ATOM}content"),
        author=author,
        published=_parse_date(published),
        enclosures=enclosures,
        raw=_raw(el),
    )


# --- helpers -------------------------------------------------------------


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(parent: ET.Element, tag: str) -> str:
    child = parent.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _raw(el: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in el:
        if child.text and child.text.strip():
            out[_localname(child.tag)] = child.text.strip()
    return out


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    # RFC 822 (RSS): "Mon, 06 Sep 2021 16:20:00 +0000"
    try:
        dt = parsedate_to_datetime(value)
        if dt is not None:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    # RFC 3339 / ISO 8601 (Atom): "2021-09-06T16:20:00Z"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
