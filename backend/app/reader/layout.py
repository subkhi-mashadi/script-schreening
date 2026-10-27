"""Analisis tata letak fisik naskah (DOCX/PDF) untuk tahap cek layout.

Hasil berupa ringkasan terukur — ukuran halaman, margin, font dan ukuran huruf isi, spasi baris,
perataan paragraf, nomor halaman, resolusi gambar, font tertanam (PDF), halaman kosong — yang
kemudian dinilai oleh aturan LAY-*. Tidak ada heuristik berbasis AI; semua dibaca dari struktur berkas.
"""

import io
import re
import zipfile
from collections import Counter
from typing import Any

import pymupdf
from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
TWIP_CM = 2.54 / 1440
EMU_CM = 1 / 360000
PT_CM = 2.54 / 72

RE_HEADING_STYLE = re.compile(r"^(heading|judul|title|toc)", re.IGNORECASE)
SAMPLE_CHARS = 90


def analyze(source_format: str, data: bytes) -> dict[str, Any]:
    if source_format == "docx":
        return _docx(data)
    if source_format == "pdf":
        return _pdf(data)
    return {"supported": False, "reason": "Berkas teks tidak memiliki informasi tata letak."}


def _share(counter: Counter) -> list[dict[str, Any]]:
    total = sum(counter.values()) or 1
    return [{"value": k, "chars": v, "share": round(v / total, 4)} for k, v in counter.most_common(12)]


def _sample(text: str) -> str:
    t = " ".join(text.split())
    return t[:SAMPLE_CHARS]


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _docx(data: bytes) -> dict[str, Any]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    doc = etree.fromstring(zf.read("word/document.xml"))
    styles = etree.fromstring(zf.read("word/styles.xml")) if "word/styles.xml" in zf.namelist() else None
    rels = _rels(zf, "word/_rels/document.xml.rels")
    theme = _theme_fonts(zf)

    # --- section: ukuran halaman, margin, nomor halaman
    sections = []
    for i, sect in enumerate(doc.iter(f"{W}sectPr")):
        pg, mar = sect.find(f"{W}pgSz"), sect.find(f"{W}pgMar")
        w = int(pg.get(f"{W}w", 0)) * TWIP_CM if pg is not None else None
        h = int(pg.get(f"{W}h", 0)) * TWIP_CM if pg is not None else None
        margins = {k: round(int(mar.get(f"{W}{k}", 0)) * TWIP_CM, 2) for k in ("top", "bottom", "left", "right")} if mar is not None else {}
        page_number = False
        for ref in sect.findall(f"{W}footerReference") + sect.findall(f"{W}headerReference"):
            target = rels.get(ref.get(f"{R}id"))
            if target and f"word/{target}" in zf.namelist() and _has_page_field(zf.read(f"word/{target}")):
                page_number = True
        sections.append({"index": i + 1, "width_cm": round(w, 2) if w else None, "height_cm": round(h, 2) if h else None,
                         "margins_cm": margins, "page_number_field": page_number})

    # --- gaya: font & ukuran default, warisan basedOn
    style_info = _docx_styles(styles, theme)
    default = style_info.get("__default__", {})

    fonts, sizes, spacing, align = Counter(), Counter(), Counter(), Counter()
    samples: dict[str, dict[str, str]] = {"font": {}, "size": {}, "spacing": {}, "align": {}}
    body = doc.find(f"{W}body")
    paragraph_no = 0
    for p in body.iter(f"{W}p"):
        if any(a.tag == f"{W}tbl" for a in p.iterancestors()):
            continue  # tabel punya tata letak sendiri
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        if not text.strip():
            continue
        paragraph_no += 1
        ppr = p.find(f"{W}pPr")
        sid = ppr.find(f"{W}pStyle").get(f"{W}val") if ppr is not None and ppr.find(f"{W}pStyle") is not None else "Normal"
        st = style_info.get(sid, default)
        if RE_HEADING_STYLE.match(st.get("name", "")) or len(text.strip()) < 40:
            continue  # nilai isi diukur dari paragraf isi, bukan judul/baris pendek
        # Spasi baris & perataan (paragraf → gaya → default)
        sp = ppr.find(f"{W}spacing") if ppr is not None else None
        line = (sp.get(f"{W}line"), sp.get(f"{W}lineRule")) if sp is not None and sp.get(f"{W}line") else (st.get("line"), st.get("lineRule"))
        spacing_key = _spacing_label(*line)
        jc = ppr.find(f"{W}jc").get(f"{W}val") if ppr is not None and ppr.find(f"{W}jc") is not None else st.get("jc", "left")
        jc = {"both": "rata kiri-kanan", "distribute": "rata kiri-kanan", "center": "tengah", "right": "rata kanan", "end": "rata kanan"}.get(jc, "rata kiri")
        n = len(text)
        spacing[spacing_key] += n
        align[jc] += n
        samples["spacing"].setdefault(spacing_key, _sample(text))
        samples["align"].setdefault(jc, _sample(text))
        for r in p.iter(f"{W}r"):
            rt = "".join(t.text or "" for t in r.findall(f"{W}t"))
            if not rt.strip():
                continue
            rpr = r.find(f"{W}rPr")
            font = _run_font(rpr, theme) or st.get("font") or default.get("font") or "(tidak diketahui)"
            size = _run_size(rpr) or st.get("size") or default.get("size") or 10.0
            fonts[font] += len(rt)
            sizes[size] += len(rt)
            samples["font"].setdefault(font, _sample(text))
            samples["size"].setdefault(str(size), _sample(text))

    images = _docx_images(zf, doc, rels)
    pages = None
    if "docProps/app.xml" in zf.namelist():
        m = re.search(rb"<Pages>(\d+)</Pages>", zf.read("docProps/app.xml"))
        pages = int(m.group(1)) if m else None

    return {
        "supported": True,
        "format": "docx",
        "pages": pages,
        "page_sizes": _page_size_groups([(s["width_cm"], s["height_cm"], f"section {s['index']}") for s in sections if s["width_cm"]]),
        "sections": sections,
        "margins": [{"where": f"section {s['index']}", **s["margins_cm"]} for s in sections if s["margins_cm"]],
        "page_numbers": {"present": any(s["page_number_field"] for s in sections), "method": "field PAGE di header/footer",
                         "sections_without": [s["index"] for s in sections if not s["page_number_field"]]},
        "body_fonts": _share(fonts),
        "body_sizes": _share(sizes),
        "line_spacing": _share(spacing),
        "alignment": _share(align),
        "samples": samples,
        "images": images,
        "fonts_embedded": None,
        "blank_pages": None,
    }


def _rels(zf: zipfile.ZipFile, path: str) -> dict[str, str]:
    if path not in zf.namelist():
        return {}
    root = etree.fromstring(zf.read(path))
    return {r.get("Id"): r.get("Target") for r in root}


def _has_page_field(xml: bytes) -> bool:
    return bool(re.search(rb'(instr="\s*PAGE\b|<w:instrText[^>]*>\s*PAGE\b)', xml))


def _theme_fonts(zf: zipfile.ZipFile) -> dict[str, str]:
    out = {}
    for name in zf.namelist():
        if name.startswith("word/theme/") and name.endswith(".xml"):
            root = etree.fromstring(zf.read(name))
            for kind in ("major", "minor"):
                el = root.find(f".//{A}{kind}Font/{A}latin")
                if el is not None:
                    out[kind] = el.get("typeface")
            break
    return out


def _run_font(rpr, theme: dict[str, str]) -> str | None:
    if rpr is None:
        return None
    rf = rpr.find(f"{W}rFonts")
    if rf is None:
        return None
    if rf.get(f"{W}ascii"):
        return rf.get(f"{W}ascii")
    t = rf.get(f"{W}asciiTheme") or ""
    if t.startswith("major"):
        return theme.get("major")
    if t.startswith("minor"):
        return theme.get("minor")
    return None


def _run_size(rpr) -> float | None:
    if rpr is None:
        return None
    sz = rpr.find(f"{W}sz")
    return int(sz.get(f"{W}val")) / 2 if sz is not None and sz.get(f"{W}val", "").isdigit() else None


def _spacing_label(line: str | None, rule: str | None) -> str:
    if not line:
        return "1,0 (tunggal)"
    v = int(line)
    if rule in (None, "auto"):
        ratio = round(v / 240, 2)
        return {1.0: "1,0 (tunggal)", 1.15: "1,15", 1.5: "1,5", 2.0: "2,0 (ganda)"}.get(ratio, f"{ratio:g}".replace(".", ","))
    return f"tepat {round(v / 20, 1):g} pt"


def _docx_styles(styles, theme: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if styles is None:
        return out
    d = styles.find(f"{W}docDefaults")
    default: dict[str, Any] = {}
    if d is not None:
        rpr = d.find(f"{W}rPrDefault/{W}rPr")
        default["font"] = _run_font(rpr, theme) or theme.get("minor")
        default["size"] = _run_size(rpr)
        sp = d.find(f"{W}pPrDefault/{W}pPr/{W}spacing")
        if sp is not None and sp.get(f"{W}line"):
            default["line"], default["lineRule"] = sp.get(f"{W}line"), sp.get(f"{W}lineRule")
    raw = {}
    for st in styles.findall(f"{W}style"):
        sid = st.get(f"{W}styleId")
        name = st.find(f"{W}name")
        based = st.find(f"{W}basedOn")
        rpr, ppr = st.find(f"{W}rPr"), st.find(f"{W}pPr")
        sp = ppr.find(f"{W}spacing") if ppr is not None else None
        jc = ppr.find(f"{W}jc") if ppr is not None else None
        raw[sid] = {
            "name": name.get(f"{W}val") if name is not None else sid,
            "based": based.get(f"{W}val") if based is not None else None,
            "font": _run_font(rpr, theme), "size": _run_size(rpr),
            "line": sp.get(f"{W}line") if sp is not None else None, "lineRule": sp.get(f"{W}lineRule") if sp is not None else None,
            "jc": jc.get(f"{W}val") if jc is not None else None,
        }

    def resolve(sid: str, depth: int = 0) -> dict[str, Any]:
        s = dict(raw.get(sid, {}))
        parent = resolve(s["based"], depth + 1) if s.get("based") and depth < 10 else default
        for k in ("font", "size", "line", "lineRule", "jc"):
            if s.get(k) is None:
                s[k] = parent.get(k)
        return s

    out = {sid: resolve(sid) for sid in raw}
    out["__default__"] = default
    return out


def _docx_images(zf: zipfile.ZipFile, doc, rels: dict[str, str]) -> list[dict[str, Any]]:
    images = []
    paragraph_no = 0
    for p in doc.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        if text.strip():
            paragraph_no += 1
        for drawing in p.iter(f"{W}drawing"):
            extent = drawing.find(f".//{WP}extent")
            blip = drawing.find(f".//{A}blip")
            if extent is None or blip is None:
                continue
            target = rels.get(blip.get(f"{R}embed"))
            if not target or f"word/{target}" not in zf.namelist():
                continue
            w_cm = int(extent.get("cx", 0)) * EMU_CM
            try:
                pix = pymupdf.Pixmap(zf.read(f"word/{target}"))
                px_w = pix.width
            except Exception:
                continue
            dpi = round(px_w / (w_cm / 2.54)) if w_cm else None
            images.append({"name": target.split("/")[-1], "width_cm": round(w_cm, 2), "px_width": px_w, "dpi": dpi,
                           "where": f"setelah paragraf ke-{paragraph_no}", "paragraph_no": paragraph_no})
    return images


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pdf(data: bytes) -> dict[str, Any]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    sizes_pages, margins, images, blank, labels = [], [], [], [], 0
    fonts, font_sizes = Counter(), Counter()
    samples: dict[str, dict[str, str]] = {"font": {}, "size": {}}
    font_pages: dict[str, int] = {}
    size_pages: dict[str, int] = {}
    non_embedded: dict[str, list[int]] = {}
    line_ratios: list[float] = []
    for page in doc:
        pno = page.number + 1
        rect = page.rect
        sizes_pages.append((round(rect.width * PT_CM, 2), round(rect.height * PT_CM, 2), f"halaman {pno}"))
        d = page.get_text("dict")
        text_boxes = []
        page_chars = 0
        for blk in d.get("blocks", []):
            if blk.get("type") != 0:
                continue
            lines = blk.get("lines", [])
            for ln in lines:
                txt = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
                if not txt:
                    continue
                page_chars += len(txt)
                # Margin diukur dari area isi: header berjalan & nomor halaman di tepi diabaikan.
                if ln["bbox"][3] > rect.height * 0.08 and ln["bbox"][1] < rect.height * 0.92:
                    text_boxes.append(ln["bbox"])
            # Rasio jarak baris/ukuran huruf dari paragraf isi (≥ 3 baris).
            if len(lines) >= 3:
                ys = [ln["bbox"][3] for ln in lines]
                gaps = [b - a for a, b in zip(ys, ys[1:]) if b > a]
                size = max((s.get("size", 0) for ln in lines for s in ln.get("spans", [])), default=0)
                if gaps and size:
                    line_ratios.append(sorted(gaps)[len(gaps) // 2] / size)
            for ln in lines:
                for s in ln.get("spans", []):
                    t = s.get("text", "").strip()
                    if len(t) < 3:
                        continue
                    font = re.sub(r"^[A-Z]{6}\+", "", s.get("font", "?"))
                    size = round(s.get("size", 0) * 2) / 2
                    fonts[font] += len(t)
                    font_sizes[size] += len(t)
                    font_pages.setdefault(font, pno)
                    size_pages.setdefault(str(size), pno)
                    samples["font"].setdefault(font, _sample(t))
                    samples["size"].setdefault(str(size), _sample(t))
        imgs = page.get_image_info(xrefs=True)
        for im in imgs:
            bw = (im["bbox"][2] - im["bbox"][0]) / 72  # inci
            if bw <= 0.3:
                continue
            images.append({"name": f"gambar xref {im.get('xref')}", "width_cm": round(bw * 2.54, 2), "px_width": im.get("width"),
                           "dpi": round(im.get("width", 0) / bw) if bw else None, "where": f"halaman {pno}", "page": pno})
        if page_chars < 5 and not imgs:
            blank.append(pno)
        if text_boxes:
            x0 = min(b[0] for b in text_boxes)
            y0 = min(b[1] for b in text_boxes)
            x1 = max(b[2] for b in text_boxes)
            y1 = max(b[3] for b in text_boxes)
            margins.append({"where": f"halaman {pno}", "page": pno, "top": round(y0 * PT_CM, 2), "bottom": round((rect.height - y1) * PT_CM, 2),
                            "left": round(x0 * PT_CM, 2), "right": round((rect.width - x1) * PT_CM, 2)})
        if page.get_label():
            labels += 1
        for f in page.get_fonts(full=False):
            ext, ftype, name = f[1], f[2], re.sub(r"^[A-Z]{6}\+", "", f[3])
            if ext == "n/a" and ftype not in ("Type3",):
                non_embedded.setdefault(name, []).append(pno)
    # Nomor halaman tercetak: angka berdiri sendiri di margin atas/bawah.
    numbered = 0
    for page in doc:
        h = page.rect.height
        for b in page.get_text("blocks"):
            t = b[4].strip()
            if re.fullmatch(r"[-–]?\s*(\d{1,4}|[ivxlcdm]{1,6})\s*[-–]?", t, re.IGNORECASE) and (b[3] < h * 0.1 or b[1] > h * 0.9):
                numbered += 1
                break
    n_pages = doc.page_count
    doc.close()
    body_size = font_sizes.most_common(1)[0][0] if font_sizes else None
    return {
        "supported": True,
        "format": "pdf",
        "pages": n_pages,
        "page_sizes": _page_size_groups(sizes_pages),
        "margins": margins,
        "page_numbers": {"present": numbered >= max(1, int(n_pages * 0.5)) or labels >= n_pages * 0.5, "method": "angka di margin atas/bawah",
                         "pages_with_number": numbered, "pages": n_pages},
        "body_fonts": _share(fonts),
        "body_sizes": _share(font_sizes),
        "body_size": body_size,
        "line_spacing": [{"value": f"{round(sorted(line_ratios)[len(line_ratios) // 2], 2):g}".replace(".", ","), "share": 1.0}] if line_ratios else [],
        "line_ratio_median": round(sorted(line_ratios)[len(line_ratios) // 2], 2) if line_ratios else None,
        "alignment": [],
        "samples": samples,
        "first_page": {"font": font_pages, "size": size_pages},
        "images": images,
        "fonts_embedded": {"all": not non_embedded, "not_embedded": {k: v[:10] for k, v in non_embedded.items()}},
        "blank_pages": blank,
    }


def _page_size_groups(items: list[tuple[float | None, float | None, str]]) -> list[dict[str, Any]]:
    """Kelompokkan ukuran halaman (toleransi 2 mm, orientasi diabaikan dalam kunci tetapi dicatat)."""
    groups: dict[tuple[float, float], dict[str, Any]] = {}
    for w, h, where in items:
        if not w or not h:
            continue
        key = (round(min(w, h) * 5) / 5, round(max(w, h) * 5) / 5)
        g = groups.setdefault(key, {"width_cm": round(min(w, h), 1), "height_cm": round(max(w, h), 1), "count": 0, "where": [], "landscape": 0})
        g["count"] += 1
        if len(g["where"]) < 20:
            g["where"].append(where)
        if w > h:
            g["landscape"] += 1
    return sorted(groups.values(), key=lambda g: -g["count"])
