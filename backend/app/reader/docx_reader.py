"""Reader DOCX berbasis python-docx + lxml.

Teks dibaca dari XML WordprocessingML secara langsung agar:
- teks sisipan tracked changes (`w:ins`) ikut terbaca dan teks terhapus (`w:del`) dibuang;
- referensi catatan kaki tercatat pada locator paragraf;
- konten text box tidak bercampur ke paragraf induk.

DOCX tidak menyimpan nomor halaman final. Halaman diperkirakan dari tata letak terakhir
Word: bila dokumen memuat `w:lastRenderedPageBreak` (disimpan Word di setiap pergantian
halaman hasil render, termasuk setelah page break manual), hanya penanda itu yang dihitung
agar page break manual tidak terhitung dua kali. Bila tidak ada, dipakai page break manual.
Jumlah halaman diambil dari `docProps/app.xml` (<Pages>) bila tersedia.
"""

import io
import re
import zipfile
from importlib.metadata import version

import docx
from docx.document import Document as DocxDocument
from lxml import etree

from app.reader.model import Block, BlockType, NormalizedDocument, WarningCode
from app.reader.patterns import RE_BAB, classify_heading

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
NSMAP = {"w": W_NS}

ENGINE_VERSION = f"docx-reader/1.0 python-docx/{version('python-docx')} lxml/{version('lxml')}"

RE_HEADING_STYLE = re.compile(r"^(heading|judul)\s*(\d)$", re.IGNORECASE)
RE_TOC_STYLE = re.compile(r"^(toc|daftar isi)\s*(\d)$", re.IGNORECASE)
RE_TOC_PAGE = re.compile(r"^(.*?)[\s.…·_-]*\t\s*([0-9]{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
RE_APP_PAGES = re.compile(rb"<Pages>(\d+)</Pages>")


class DocxReadError(Exception):
    pass


def read_docx(data: bytes) -> NormalizedDocument:
    try:
        document: DocxDocument = docx.Document(io.BytesIO(data))
    except Exception as exc:  # berkas rusak / bukan DOCX valid
        raise DocxReadError(f"DOCX tidak dapat dibuka: {exc.__class__.__name__}") from exc

    out = NormalizedDocument(source_format="docx", engine_version=ENGINE_VERSION)
    out.metadata = _core_metadata(document)
    styles = _style_index(document)
    footnotes = _footnotes(document)

    body = document.element.body
    state = _WalkState(rendered_breaks=body.find(f".//{W}lastRenderedPageBreak") is not None)
    for el in _body_elements(body):
        if el.tag == f"{W}p":
            _handle_paragraph(el, styles, footnotes, state, out)
        elif el.tag == f"{W}tbl":
            _handle_table(el, state, out)

    if state.tracked_changes:
        out.warn(
            WarningCode.TRACKED_CHANGES,
            "Dokumen memiliki tracked changes. Teks sisipan dibaca, teks terhapus diabaikan. "
            "Sebaiknya terima/tolak semua perubahan sebelum diunggah.",
            insertions=state.tracked_changes,
        )
    if state.text_boxes:
        out.warn(
            WarningCode.UNSUPPORTED_ELEMENTS,
            "Text box tidak diekstrak dan tidak ikut diperiksa.",
            text_boxes=state.text_boxes,
        )
    if state.pattern_headings:
        out.warn(
            WarningCode.HEADINGS_FROM_PATTERN,
            "Sebagian heading dikenali dari pola teks karena tidak memakai style Heading.",
            severity="info",
            count=state.pattern_headings,
        )
    out.warn(
        WarningCode.PAGE_NUMBERS_ESTIMATED,
        "DOCX tidak menyimpan nomor halaman final. Lokasi utama memakai bab/paragraf; "
        "perkiraan halaman (page_estimate) berasal dari tata letak terakhir Word dan dapat berbeda.",
        severity="info",
    )
    out.page_numbers_reliable = False
    word_pages = _app_pages(data)
    if word_pages:
        out.page_count, out.page_count_source = word_pages, "word_app_properties"
    else:
        out.page_count, out.page_count_source = state.page_estimate, "page_breaks"
    return out


def _app_pages(data: bytes) -> int | None:
    """Jumlah halaman menurut Word saat terakhir disimpan (docProps/app.xml)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            m = RE_APP_PAGES.search(zf.read("docProps/app.xml"))
    except (KeyError, zipfile.BadZipFile):
        return None
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


class _WalkState:
    def __init__(self, rendered_breaks: bool) -> None:
        self.rendered_breaks = rendered_breaks
        self.page_estimate = 1
        self.paragraph_no = 0
        self.table_no = 0
        self.tracked_changes = 0
        self.text_boxes = 0
        self.pattern_headings = 0


def _body_elements(body: etree._Element):
    """Paragraf dan tabel level body, termasuk yang berada di dalam content control (w:sdt)."""
    for child in body.iterchildren():
        if child.tag in (f"{W}p", f"{W}tbl"):
            yield child
        elif child.tag == f"{W}sdt":
            content = child.find(f"{W}sdtContent")
            if content is not None:
                yield from _body_elements(content)


def _style_index(document: DocxDocument) -> dict[str, dict]:
    """styleId -> {name, outline_level, is_list}. Mewarisi outline level dari style induk."""
    raw: dict[str, dict] = {}
    for st in document.styles.element.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        name_el = st.find(f"{W}name")
        based = st.find(f"{W}basedOn")
        outline = st.find(f"{W}pPr/{W}outlineLvl")
        num = st.find(f"{W}pPr/{W}numPr")
        raw[sid] = {
            "name": name_el.get(f"{W}val") if name_el is not None else sid,
            "based_on": based.get(f"{W}val") if based is not None else None,
            "outline": int(outline.get(f"{W}val")) if outline is not None else None,
            "is_list": num is not None,
        }

    def resolve(sid: str, depth: int = 0) -> dict:
        s = raw.get(sid, {"name": sid, "based_on": None, "outline": None, "is_list": False})
        if s["outline"] is None and s["based_on"] and depth < 10:
            parent = resolve(s["based_on"], depth + 1)
            return {**s, "outline": parent["outline"]}
        return s

    return {sid: resolve(sid) for sid in raw}


def _core_metadata(document: DocxDocument) -> dict:
    cp = document.core_properties
    meta = {
        "title": cp.title or None,
        "author": cp.author or None,
        "subject": cp.subject or None,
        "keywords": cp.keywords or None,
        "last_modified_by": cp.last_modified_by or None,
        "created": cp.created.isoformat() if cp.created else None,
        "modified": cp.modified.isoformat() if cp.modified else None,
        "revision": cp.revision,
    }
    return {k: v for k, v in meta.items() if v is not None}


def _footnotes(document: DocxDocument) -> dict[str, str]:
    for rel in document.part.rels.values():
        if rel.reltype.endswith("/footnotes") and not rel.is_external:
            root = etree.fromstring(rel.target_part.blob)
            notes: dict[str, str] = {}
            for fn in root.findall(f"{W}footnote"):
                if fn.get(f"{W}type") in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                text = " ".join(t for p in fn.findall(f".//{W}p") if (t := _paragraph_text(p)[0].strip()))
                notes[fn.get(f"{W}id")] = text
            return notes
    return {}


def _paragraph_text(p: etree._Element) -> tuple[str, dict]:
    """Teks paragraf + info tambahan (page break, footnote refs, tracked changes, text box)."""
    parts: list[str] = []
    # *_lead: penanda yang muncul sebelum teks pertama paragraf (paragraf dimulai di halaman baru).
    info = {"rendered": 0, "rendered_lead": 0, "explicit": 0, "explicit_lead": 0, "footnote_refs": [], "insertions": 0, "text_boxes": 0, "bold_chars": 0, "chars": 0}
    skip_depth_tags = {f"{W}del", f"{W}txbxContent", f"{W}delText"}

    def walk(el: etree._Element, bold: bool) -> None:
        tag = el.tag
        if tag in skip_depth_tags:
            if tag == f"{W}txbxContent":
                info["text_boxes"] += 1
            return
        if tag == f"{W}ins":
            info["insertions"] += 1
        if tag == f"{W}r":
            b = el.find(f"{W}rPr/{W}b")
            bold = b is not None and b.get(f"{W}val") not in ("0", "false")
        if tag == f"{W}t" and el.text:
            parts.append(el.text)
            info["chars"] += len(el.text)
            if bold:
                info["bold_chars"] += len(el.text)
        elif tag == f"{W}tab":
            parts.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            if el.get(f"{W}type") == "page":
                info["explicit"] += 1
                if not info["chars"]:
                    info["explicit_lead"] += 1
            else:
                parts.append("\n")
        elif tag == f"{W}lastRenderedPageBreak":
            info["rendered"] += 1
            if not info["chars"]:
                info["rendered_lead"] += 1
        elif tag == f"{W}footnoteReference":
            info["footnote_refs"].append(el.get(f"{W}id"))
        for child in el.iterchildren():
            walk(child, bold)

    for child in p.iterchildren():
        if child.tag == f"{W}pPr":
            continue
        walk(child, False)
    return "".join(parts), info


def _handle_paragraph(p, styles, footnotes, state: _WalkState, out: NormalizedDocument) -> None:
    ppr = p.find(f"{W}pPr")
    style_id = None
    outline = None
    has_num = False
    page_break_before = False
    if ppr is not None:
        ps = ppr.find(f"{W}pStyle")
        style_id = ps.get(f"{W}val") if ps is not None else None
        ol = ppr.find(f"{W}outlineLvl")
        outline = int(ol.get(f"{W}val")) if ol is not None else None
        has_num = ppr.find(f"{W}numPr") is not None
        pbb = ppr.find(f"{W}pageBreakBefore")
        page_break_before = pbb is not None and pbb.get(f"{W}val") not in ("0", "false")

    style = styles.get(style_id or "", {}) if style_id else styles.get("Normal", {})
    style_name = style.get("name") or style_id or "Normal"
    if outline is None:
        outline = style.get("outline")
    has_num = has_num or style.get("is_list", False)

    text, info = _paragraph_text(p)
    if state.rendered_breaks:
        lead, total = info["rendered_lead"], info["rendered"]
    else:
        lead, total = info["explicit_lead"] + int(page_break_before), info["explicit"] + int(page_break_before)
    page_here = state.page_estimate + lead
    state.page_estimate += total
    state.tracked_changes += info["insertions"]
    state.text_boxes += info["text_boxes"]

    if not text.strip():
        return
    state.paragraph_no += 1

    btype = BlockType.PARAGRAPH
    level: int | None = None
    detection: str | None = None
    role: str | None = None
    lname = style_name.lower()

    if m := RE_HEADING_STYLE.match(style_name):
        btype, level, detection = BlockType.HEADING, int(m.group(2)), "style"
    elif lname == "title":
        btype, level, detection, role = BlockType.HEADING, 1, "style", "title"
    elif outline is not None and outline < 9:
        btype, level, detection = BlockType.HEADING, outline + 1, "outline"
    elif RE_TOC_STYLE.match(style_name):
        role = "toc_entry"
    elif "quote" in lname or "kutipan" in lname:
        btype = BlockType.QUOTE
    elif "caption" in lname or "keterangan" in lname:
        btype = BlockType.CAPTION
    elif has_num or lname.startswith("list"):
        btype = BlockType.LIST_ITEM
    else:
        pattern_level = classify_heading(text)
        all_bold = info["chars"] > 0 and info["bold_chars"] / info["chars"] >= 0.9
        if pattern_level is not None and (all_bold or RE_BAB.match(text.strip())):
            btype, level, detection = BlockType.HEADING, pattern_level, "pattern"
            state.pattern_headings += 1

    locator = {"paragraph_no": state.paragraph_no, "page_estimate": page_here, "style": style_name}
    if role:
        locator["role"] = role
    if role == "toc_entry" and (m := RE_TOC_PAGE.match(text.strip())):
        locator["toc_title"] = " ".join(m.group(1).split())
        locator["toc_page"] = m.group(2)
    if info["footnote_refs"]:
        locator["footnote_refs"] = info["footnote_refs"]
    out.blocks.append(
        Block(type=btype, text=text, level=level, style=style_name, detection=detection, locator=locator)
    )
    for ref in info["footnote_refs"]:
        if note := footnotes.get(ref):
            out.blocks.append(
                Block(
                    type=BlockType.FOOTNOTE,
                    text=note,
                    locator={"footnote_id": ref, "page_estimate": page_here, "referenced_from_paragraph": state.paragraph_no},
                )
            )


def _handle_table(tbl, state: _WalkState, out: NormalizedDocument) -> None:
    state.table_no += 1
    rows: list[str] = []
    max_cols = 0
    for tr in tbl.findall(f"{W}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{W}tc"):
            # Sel hasil vertical merge lanjutan tidak membawa isi baru.
            vmerge = tc.find(f"{W}tcPr/{W}vMerge")
            if vmerge is not None and vmerge.get(f"{W}val") in (None, "continue"):
                cells.append("")
                continue
            cell_text = " ".join(t for p in tc.findall(f"{W}p") if (t := _paragraph_text(p)[0].strip()))
            cells.append(cell_text)
        max_cols = max(max_cols, len(cells))
        if any(cells):
            rows.append(" | ".join(cells))
    if rows:
        out.blocks.append(
            Block(
                type=BlockType.TABLE,
                text="\n".join(rows),
                locator={"table_no": state.table_no, "rows": len(rows), "cols": max_cols, "page_estimate": state.page_estimate},
            )
        )
