"""Extraction preserves raw bytes separately; locators are stable in this representation."""

import io
import json
import re
import zipfile

from docx import Document
from pypdf import PdfReader

FORMATS = {
    "text/plain": {
        "extraction": "UTF-8 text with Unicode character offsets",
        "automatic": "text checks",
        "gaps": "human factual, task and accessibility review",
    },
    "text/markdown": {
        "extraction": "UTF-8 Markdown with offsets",
        "automatic": "text and section checks",
        "gaps": "rendering, links and embedded media require manual review",
    },
    "application/json": {
        "extraction": "JSON scalars with RFC 6901 pointers",
        "automatic": "fields, values, explicit units and text",
        "gaps": "consuming-system and semantic review",
    },
    "application/pdf": {
        "extraction": "readable text with page and page-relative offsets",
        "automatic": "extracted text only",
        "gaps": "layout, figures, tables and accessibility require manual examination; scans need OCR",
    },
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "extraction": "paragraphs and tables with XML paths",
        "automatic": "body text only",
        "gaps": "headers, footnotes, text boxes, visuals and rendering require manual examination",
    },
    "other": {
        "extraction": "registration and original bytes only",
        "automatic": "none",
        "gaps": "unsupported; release blocked",
    },
}
ALIASES = {
    "txt": "text/plain",
    "text": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "json": "application/json",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def normalize_format(fmt):
    return ALIASES.get(fmt.lower(), fmt.lower())


def pointer_get(value, path):
    if path in {"", "/"}:
        return value
    if not path.startswith("/"):
        raise ValueError("Structured paths use RFC 6901 JSON pointers")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def extract(raw, fmt):
    fmt = normalize_format(fmt)
    items, gaps = [], []
    data = None
    errors = []

    def add(text, locator):
        items.append({"id": f"item-{len(items) + 1}", "text": text, "locator": locator, "modality": "text"})

    try:
        if fmt in {"text/plain", "text/markdown"}:
            text = raw.decode("utf-8", errors="strict")
            # Paragraph inventories are independent of model claim extraction.
            for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
                if match.group().strip():
                    add(match.group(), {"kind": "offset", "start": match.start(), "end": match.end()})
            if fmt == "text/markdown":
                gaps.append(
                    {
                        "id": "rendering",
                        "modality": "rendered",
                        "reason": "Rendered Markdown, links and interaction have not been examined.",
                    }
                )
                if re.search(r"!\[|<img|<svg|<video|<audio|<iframe", text, re.I):
                    gaps.append(
                        {
                            "id": "embedded-media",
                            "modality": "visual",
                            "reason": "Embedded material is retained in the original but not extracted.",
                        }
                    )
        elif fmt == "application/json":

            def reject_constant(s):
                raise ValueError("Non-finite JSON value")

            def unique(pairs):
                obj = {}
                for k, v in pairs:
                    if k in obj:
                        raise ValueError("Duplicate JSON key")
                    obj[k] = v
                return obj

            data = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique)
            if not isinstance(data, dict):
                raise ValueError("Product JSON must be an object")

            def visit(v, path=""):
                if isinstance(v, dict):
                    for k, vv in v.items():
                        visit(vv, path + "/" + k.replace("~", "~0").replace("/", "~1"))
                elif isinstance(v, list):
                    for i, vv in enumerate(v):
                        visit(vv, path + "/" + str(i))
                else:
                    add(v if isinstance(v, str) else json.dumps(v), {"kind": "json_pointer", "path": path})

            visit(data)
        elif fmt == "application/pdf":
            pdf = PdfReader(io.BytesIO(raw), strict=True)
            if pdf.is_encrypted:
                raise ValueError("Encrypted PDF is not supported")
            if len(pdf.pages) > 200:
                raise ValueError("PDF page limit exceeded")
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if not text.strip():
                    errors.append(f"PAGE_WITHOUT_TEXT:{i + 1}")
                else:
                    add(text, {"kind": "page", "page": i + 1, "start": 0, "end": len(text)})
            gaps.append(
                {
                    "id": "pdf-visual",
                    "modality": "visual",
                    "reason": "All PDF pages: figures, table relationships, layout, alternatives and interaction need manual review.",
                }
            )
        elif fmt == ALIASES["docx"]:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if sum(i.file_size for i in z.infolist()) > 30_000_000:
                    raise ValueError("DOCX expansion limit exceeded")
            doc = Document(io.BytesIO(raw))
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            for i, child in enumerate(doc.element.body):
                if child.tag == qn("w:p"):
                    add(Paragraph(child, doc).text, {"kind": "xml", "path": f"/document/body/child[{i}]"})
                elif child.tag == qn("w:tbl"):
                    for r, row in enumerate(Table(child, doc).rows):
                        for col, cell in enumerate(row.cells):
                            add(
                                cell.text,
                                {"kind": "xml", "path": f"/document/body/child[{i}]/row[{r}]/cell[{col}]"},
                            )
            gaps.append(
                {
                    "id": "docx-other",
                    "modality": "visual",
                    "reason": "Original DOCX includes unassessed headers, footnotes, embedded objects, layout and non-body content.",
                }
            )
        else:
            errors.append("UNSUPPORTED_FORMAT")
            gaps.append(
                {
                    "id": "unsupported",
                    "modality": fmt,
                    "reason": "No extraction or assessment implementation for this format.",
                }
            )
    except Exception as exc:
        # Avoid exception messages that might disclose uploaded material.
        errors.append("EXTRACTION_FAILED:" + type(exc).__name__)
    if not items or not any(i["text"].strip() for i in items):
        errors.append("NO_READABLE_CONTENT")
    if sum(len(i["text"]) for i in items) > 200_000 or len(items) > 1000:
        errors.append("EXTRACTION_LIMIT_EXCEEDED")
    return {
        "format": fmt,
        "items": items,
        "gaps": gaps,
        "errors": errors,
        "data": data,
        "text": "\n".join(i["text"] for i in items),
        "supported": fmt in FORMATS and not errors,
        "extractor_version": "extract-1",
    }
