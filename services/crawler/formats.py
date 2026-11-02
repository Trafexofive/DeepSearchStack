"""Format-specific extractors. Each takes raw bytes + URL hint, returns a
normalized result dict the crawler can route to the warehouse forwarder.

All return shape:
    {
        "ok":            bool,
        "markdown":      str,          # extracted text (markdown-ish)
        "title":         Optional[str],
        "author":        Optional[str],
        "published":     Optional[str],
        "language":      Optional[str],
        "word_count":    int,
        "extractor":     str,          # "pdf" | "docx" | "epub" | "markdown" | "text" | "rtf"
        "error":         Optional[str],
    }
"""
from __future__ import annotations

import io
import logging
import re
from typing import Optional

log = logging.getLogger("crawler.formats")


def _wc(text: str) -> int:
    return len(text.split()) if text else 0


# ─── PDF ───────────────────────────────────────────────────────────────────

def extract_pdf(data: bytes, url: str = "") -> dict:
    """PyMuPDF — fast, accurate, handles arXiv, government docs, papers, scans."""
    try:
        import fitz  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"PyMuPDF not installed: {e}",
                "markdown": "", "extractor": "pdf"}

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return {"ok": False, "error": f"PDF parse failed: {e}",
                "markdown": "", "extractor": "pdf"}

    try:
        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip() or None
        author = (meta.get("author") or "").strip() or None
        # mod/creation date in PDF metadata format: D:YYYYMMDDHHmmSS
        published = (meta.get("creationDate") or "").strip() or None
        if published and published.startswith("D:") and len(published) >= 10:
            published = f"{published[2:6]}-{published[6:8]}-{published[8:10]}"

        chunks: list[str] = []
        for page in doc:
            try:
                txt = page.get_text("text") or ""
                if txt.strip():
                    chunks.append(txt)
            except Exception:
                continue
        text = "\n\n".join(chunks)
        # Normalize: collapse runs of spaces and >2 blank lines.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return {
            "ok": bool(text),
            "markdown": text,
            "title": title,
            "author": author,
            "published": published,
            "language": None,
            "word_count": _wc(text),
            "extractor": "pdf",
            "error": None if text else "empty_pdf",
        }
    finally:
        doc.close()


def render_pdf_pages_to_pngs(data: bytes, max_pages: int = 25, dpi: int = 150) -> list[bytes]:
    """Render PDF pages to PNG bytes. Used by the OCR fallback path for scanned
    PDFs that PyMuPDF can't extract text from. Caps at max_pages to bound CPU
    and at dpi=150 (good OCR balance — higher = sharper text, slower OCR).
    """
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return []
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        out: list[bytes] = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            try:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                out.append(pix.tobytes("png"))
            except Exception as e:
                log.warning("render_pdf_page_failed i=%d err=%s", i, e)
        return out
    finally:
        doc.close()


# ─── DOCX ──────────────────────────────────────────────────────────────────

def extract_docx(data: bytes, url: str = "") -> dict:
    try:
        import docx  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"python-docx not installed: {e}",
                "markdown": "", "extractor": "docx"}

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:
        return {"ok": False, "error": f"DOCX parse failed: {e}",
                "markdown": "", "extractor": "docx"}

    out: list[str] = []
    for p in d.paragraphs:
        line = p.text.strip()
        if not line:
            continue
        style = (p.style.name or "").lower() if p.style else ""
        if style.startswith("heading 1"):
            out.append(f"# {line}")
        elif style.startswith("heading 2"):
            out.append(f"## {line}")
        elif style.startswith("heading 3"):
            out.append(f"### {line}")
        elif "list" in style or p.text.startswith(("•", "-", "*")):
            out.append(f"- {line.lstrip('•-* ')}")
        else:
            out.append(line)
    # Tables — emit as plain text rows.
    for t in d.tables:
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells]
            out.append(" | ".join(c for c in cells if c))

    text = "\n\n".join(out).strip()
    core = d.core_properties
    return {
        "ok": bool(text),
        "markdown": text,
        "title": (core.title or None),
        "author": (core.author or None),
        "published": (core.created.isoformat() if core.created else None),
        "language": (core.language or None),
        "word_count": _wc(text),
        "extractor": "docx",
        "error": None if text else "empty_docx",
    }


# ─── EPUB ──────────────────────────────────────────────────────────────────

def extract_epub(data: bytes, url: str = "") -> dict:
    try:
        from ebooklib import epub  # type: ignore
        from bs4 import BeautifulSoup
    except Exception as e:
        return {"ok": False, "error": f"ebooklib not installed: {e}",
                "markdown": "", "extractor": "epub"}

    try:
        book = epub.read_epub(io.BytesIO(data))
    except Exception as e:
        return {"ok": False, "error": f"EPUB parse failed: {e}",
                "markdown": "", "extractor": "epub"}

    parts: list[str] = []
    for item in book.get_items():
        if item.get_type() != 9:  # ITEM_DOCUMENT == 9
            continue
        try:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            parts.append(soup.get_text("\n", strip=True))
        except Exception:
            continue

    text = "\n\n".join(p for p in parts if p).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)

    title = None
    author = None
    language = None
    try:
        title = (book.get_metadata("DC", "title") or [(None,)])[0][0]
    except Exception:
        pass
    try:
        author = (book.get_metadata("DC", "creator") or [(None,)])[0][0]
    except Exception:
        pass
    try:
        language = (book.get_metadata("DC", "language") or [(None,)])[0][0]
    except Exception:
        pass

    return {
        "ok": bool(text),
        "markdown": text,
        "title": title,
        "author": author,
        "published": None,
        "language": language,
        "word_count": _wc(text),
        "extractor": "epub",
        "error": None if text else "empty_epub",
    }


# ─── Markdown / plain text / RTF ──────────────────────────────────────────

def extract_markdown(data: bytes, url: str = "") -> dict:
    text = data.decode("utf-8", errors="replace").strip()
    return {
        "ok": bool(text), "markdown": text, "title": None, "author": None,
        "published": None, "language": None, "word_count": _wc(text),
        "extractor": "markdown", "error": None if text else "empty_md",
    }


def extract_text(data: bytes, url: str = "") -> dict:
    text = data.decode("utf-8", errors="replace").strip()
    return {
        "ok": bool(text), "markdown": text, "title": None, "author": None,
        "published": None, "language": None, "word_count": _wc(text),
        "extractor": "text", "error": None if text else "empty_text",
    }


def extract_rtf(data: bytes, url: str = "") -> dict:
    # Minimal RTF stripper — good enough for most plain RTF (no fonts/colors).
    raw = data.decode("latin-1", errors="replace")
    text = re.sub(r"\\par[d]?", "\n", raw)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {
        "ok": bool(text), "markdown": text, "title": None, "author": None,
        "published": None, "language": None, "word_count": _wc(text),
        "extractor": "rtf", "error": None if text else "empty_rtf",
    }


# ─── Dispatcher ────────────────────────────────────────────────────────────

_TYPE_MAP = {
    "application/pdf":                                                                 extract_pdf,
    "application/x-pdf":                                                                extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":         extract_docx,
    "application/msword":                                                              extract_docx,  # legacy .doc — partial
    "application/epub+zip":                                                            extract_epub,
    "text/markdown":                                                                   extract_markdown,
    "text/x-markdown":                                                                 extract_markdown,
    "text/plain":                                                                      extract_text,
    "application/rtf":                                                                 extract_rtf,
    "text/rtf":                                                                        extract_rtf,
}

# Extension fallback when the server sends a generic Content-Type.
_EXT_MAP = {
    ".pdf":  extract_pdf,
    ".docx": extract_docx,
    ".doc":  extract_docx,
    ".epub": extract_epub,
    ".md":   extract_markdown,
    ".markdown": extract_markdown,
    ".txt":  extract_text,
    ".rtf":  extract_rtf,
}


def classify(content_type: Optional[str], url: str = "") -> Optional[str]:
    """Return the extractor name for a given Content-Type / URL extension.
    Returns None when HTML/unknown — caller falls through to the crawl4ai
    + browser-renderer escalation ladder.
    """
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _TYPE_MAP:
            return _TYPE_MAP[ct].__name__.replace("extract_", "")
    if url:
        low = url.lower().split("?")[0]
        for ext, fn in _EXT_MAP.items():
            if low.endswith(ext):
                return fn.__name__.replace("extract_", "")
    return None


def extract(data: bytes, content_type: Optional[str], url: str = "") -> Optional[dict]:
    """Pick the right extractor. Returns None if no doc-format match (HTML)."""
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _TYPE_MAP:
            return _TYPE_MAP[ct](data, url)
    if url:
        low = url.lower().split("?")[0]
        for ext, fn in _EXT_MAP.items():
            if low.endswith(ext):
                return fn(data, url)
    return None
