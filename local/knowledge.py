"""
Lexical knowledge-base retrieval over ../knowledge-base/*.md.

No external dependencies. Each markdown file is split into sections by '##'
headings and, for the FAQ, by '**...?**' question lines. search(query, k=2)
scores sections by lowercased term-overlap (trivial stopwords dropped) and
returns the top-k sections as a structured list. snippet(query, k=2) returns a
formatted string for the agent.
"""

import re
from pathlib import Path

KB_DIR = Path(__file__).parent.parent / "knowledge-base"
KB_FILES = ["faq.md", "hotel-policies.md", "amenities-and-dining.md"]

_STOPWORDS = {
    "a", "an", "the", "is", "are", "am", "to", "of", "in", "on", "at", "for",
    "and", "or", "do", "does", "did", "i", "you", "we", "my", "your", "it",
    "be", "can", "what", "when", "where", "how", "which", "who", "with", "as",
    "that", "this", "there", "have", "has", "will", "would", "me", "us",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    """Lowercased alphanumeric tokens with trivial stopwords removed."""
    toks = _WORD_RE.findall(text.lower())
    return [t for t in toks if t not in _STOPWORDS]


def _split_sections(filename, text):
    """Split one markdown file into sections, keeping source + heading."""
    sections = []
    heading = None
    buf = []

    def flush():
        if heading is None and not any(line.strip() for line in buf):
            return
        body = "\n".join(buf).strip()
        if heading is None and not body:
            return
        sections.append({
            "source": filename,
            "heading": (heading or "").strip(),
            "text": body,
        })

    for line in text.splitlines():
        stripped = line.strip()
        is_md_heading = stripped.startswith("##")
        is_faq_question = (
            stripped.startswith("**") and stripped.endswith("**")
            and stripped.rstrip("*").endswith("?")
        )
        if is_md_heading or is_faq_question:
            flush()
            heading = stripped.lstrip("#").strip() if is_md_heading else stripped.strip("*").strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return [s for s in sections if s["heading"] or s["text"]]


def _load_sections():
    """Load and section all KB files. Empty list if the folder is missing."""
    if not KB_DIR.is_dir():
        return []
    sections = []
    for name in KB_FILES:
        path = KB_DIR / name
        if not path.is_file():
            continue
        sections.extend(_split_sections(name, path.read_text(encoding="utf-8")))
    return sections


def search(query, k=2):
    """Return the top-k KB sections scored by lowercased term-overlap.

    Each result is a dict: {source, heading, text, score}.
    Returns a graceful single-element message list if the KB folder is missing.
    """
    sections = _load_sections()
    if not sections:
        return [{
            "source": None,
            "heading": None,
            "text": "The knowledge base is not available.",
            "score": 0,
        }]

    query_terms = set(_tokens(query))
    scored = []
    for sec in sections:
        haystack = set(_tokens(f"{sec['heading']} {sec['text']}"))
        score = len(query_terms & haystack)
        scored.append({**sec, "score": score})

    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:k]


def snippet(query, k=2):
    """Return a formatted snippet string of the top-k sections for the agent."""
    results = search(query, k=k)
    parts = []
    for r in results:
        if r.get("source"):
            header = f"[{r['source']}] {r['heading']}".strip()
            parts.append(f"{header}\n{r['text']}".strip())
        else:
            parts.append(r["text"])
    return "\n\n".join(parts)
