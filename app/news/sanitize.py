"""Input sanitization (PHASE6B_DESIGN section 7.2) — deterministic, no LLM.

Before anything downstream sees source text we: strip HTML/script/style,
normalize Unicode (NFKC), remove zero-width / bidirectional-override / control
characters, collapse whitespace, cap length, and *flag* (never act on)
homoglyph-heavy tokens and prompt-injection markers. Original and sanitized
SHA-256 hashes are kept for audit. Severe flags quarantine the item.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from app.news.items import RawItem

TITLE_MAX_CHARS = 300
EXCERPT_MAX_CHARS = 1000

_ZERO_WIDTH = frozenset("​‌‍⁠﻿᠎­")
_BIDI = frozenset("‪‫‬‭‮⁦⁧⁨⁩‎‏؜")
_KEEP_CONTROL = frozenset("\n\t\r")

_SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]{0,500}>")
_WS_RE = re.compile(r"\s+")

# Markers that mean "this text is trying to talk to the model, not report news".
INJECTION_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\bignore\s+(?:all\s+|the\s+|any\s+|your\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules)", re.I),
    re.compile(r"\bdisregard\s+(?:all\s+|the\s+|your\s+|any\s+)?(?:previous|prior|above|earlier\s+)?\s*(?:instructions?|rules|guidelines)", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:a|an|the|in)\b", re.I),
    re.compile(r"\bact\s+as\s+(?:a|an)?\s*(?:unrestricted|unfiltered|uncensored|dan)\b", re.I),
    re.compile(r"\bdeveloper\s+mode\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\b(?:classifier|assistant|model|ai)\s*[:,]?\s*(?:set|mark|classify|output|return)\b.{0,80}\b(?:BLOCK_NEW_LONGS|REDUCE_SIZE|NO_EFFECT|SINGLE_SOURCE|confidence)\b", re.I | re.S),
    re.compile(r"\b(?:respond|reply|answer|output)\s+(?:only\s+)?with\s+(?:json|the\s+following)\b", re.I),
    re.compile(r"\[\s*(?:inst|/inst|system|sys)\s*\]", re.I),
    re.compile(r"<\|?\s*(?:im_start|im_end|system|endoftext)\s*\|?>", re.I),
)

SEVERE_FLAGS = frozenset({"prompt_injection_suspect", "homoglyph_suspect", "bidi_controls_removed"})

_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "HEBREW", "ARABIC", "DEVANAGARI", "THAI", "HANGUL", "HIRAGANA", "KATAKANA", "CJK")
_CONFUSABLE_SCRIPTS = {"CYRILLIC", "GREEK", "ARMENIAN"}


def _script(ch: str) -> str:
    if not ch.isalpha():
        return ""
    name = unicodedata.name(ch, "")
    for script in _SCRIPTS:
        if name.startswith(script):
            return script
    return "OTHER"


def homoglyph_suspect(text: str) -> bool:
    """True when a single token mixes Latin with a confusable script (e.g. Cyrillic 'а')."""
    for token in text.split():
        scripts = {_script(ch) for ch in token}
        scripts.discard("")
        if "LATIN" in scripts and scripts & _CONFUSABLE_SCRIPTS:
            return True
    return False


def strip_html(text: str) -> Tuple[str, bool]:
    """Remove script/style blocks and tags; unescape entities. Returns (text, changed)."""
    no_blocks = _SCRIPT_STYLE_RE.sub(" ", text)
    no_tags = _TAG_RE.sub(" ", no_blocks)
    unescaped = html.unescape(no_tags)
    return unescaped, unescaped != text


def injection_suspect(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


@dataclass(frozen=True)
class SanitizedText:
    text: str
    original_sha256: str
    sanitized_sha256: str
    flags: Tuple[str, ...]

    @property
    def severe(self) -> bool:
        return bool(SEVERE_FLAGS & set(self.flags))


def sanitize_text(text: str, *, max_chars: int) -> SanitizedText:
    original = text if isinstance(text, str) else ""
    flags: List[str] = []
    out, changed = strip_html(original)
    if changed:
        flags.append("html_stripped")
    normalized = unicodedata.normalize("NFKC", out)
    if normalized != out:
        flags.append("unicode_normalized")
    chars: List[str] = []
    zero_width = bidi = control = False
    for ch in normalized:
        if ch in _ZERO_WIDTH:
            zero_width = True
            continue
        if ch in _BIDI:
            bidi = True
            continue
        category = unicodedata.category(ch)
        if (category == "Cc" and ch not in _KEEP_CONTROL) or category == "Cf":
            control = True
            continue
        chars.append(ch)
    if zero_width:
        flags.append("zero_width_removed")
    if bidi:
        flags.append("bidi_controls_removed")
    if control:
        flags.append("control_chars_removed")
    cleaned = _WS_RE.sub(" ", "".join(chars)).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
        flags.append("truncated")
    if homoglyph_suspect(cleaned):
        flags.append("homoglyph_suspect")
    # Check both the cleaned text and the raw original (hidden text may only be in the raw form).
    if injection_suspect(cleaned) or injection_suspect(original):
        flags.append("prompt_injection_suspect")
    return SanitizedText(
        text=cleaned,
        original_sha256=sha256_hex(original),
        sanitized_sha256=sha256_hex(cleaned),
        flags=tuple(flags),
    )


def sanitize_item(raw: RawItem) -> dict:
    """Sanitize title + excerpt; return the JSON-serializable stored record."""
    title = sanitize_text(raw.title, max_chars=TITLE_MAX_CHARS)
    excerpt = sanitize_text(raw.excerpt, max_chars=EXCERPT_MAX_CHARS)
    flags = tuple(sorted(set(title.flags) | set(excerpt.flags)))
    record = raw.to_dict()
    record.update(
        {
            "title": title.text,
            "excerpt": excerpt.text,
            "title_sha256_original": title.original_sha256,
            "title_sha256_sanitized": title.sanitized_sha256,
            "excerpt_sha256_original": excerpt.original_sha256,
            "excerpt_sha256_sanitized": excerpt.sanitized_sha256,
            "sanitization_flags": list(flags),
            "quarantined": bool(SEVERE_FLAGS & set(flags)),
            "schema_version": 1,
        }
    )
    return record


def flags_are_severe(flags: Iterable[str]) -> bool:
    return bool(SEVERE_FLAGS & set(flags))
