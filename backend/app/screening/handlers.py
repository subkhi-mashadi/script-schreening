"""Handler aturan deterministik (tanpa AI/ML).

Setiap handler menerima `DocView` dan konfigurasi aturan, lalu mengembalikan `Outcome`:
- `applicable`  : aturan berlaku untuk naskah ini;
- `observed`    : hasil pengamatan untuk aturan kepatuhan (pass | fail | unknown);
- `findings`    : temuan berlokasi untuk peta revisi;
- `evidence`    : bukti ringkas yang disimpan bersama hasil.

Pesan temuan ditulis untuk editor: apa yang ditemukan, di mana, dan apa yang harus dilakukan.
"""

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.screening.docview import Blk, DocView, norm

EXCERPT_RADIUS = 70


@dataclass
class FindingDraft:
    title: str
    description: str
    suggested_action: str
    block: Blk | None = None
    span: tuple[int, int] | None = None  # posisi relatif terhadap teks blok
    severity: str | None = None  # override severity aturan
    requires_human_verification: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def excerpt(self) -> str | None:
        if self.block is None:
            return None
        text = self.block.text
        if self.span is None:
            return text if len(text) <= 2 * EXCERPT_RADIUS else text[: 2 * EXCERPT_RADIUS] + "…"
        s, e = self.span
        a, b = max(0, s - EXCERPT_RADIUS), min(len(text), e + EXCERPT_RADIUS)
        return ("…" if a > 0 else "") + text[a:b] + ("…" if b < len(text) else "")


@dataclass
class Outcome:
    applicable: bool = True
    observed: str | None = None  # pass | fail | unknown — hanya untuk jalur kepatuhan
    findings: list[FindingDraft] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str | None = None


Handler = Callable[[DocView, dict[str, Any]], Outcome]
HANDLERS: dict[str, Handler] = {}


def handler(key: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[key] = fn
        return fn

    return deco


def not_applicable(reason: str) -> Outcome:
    return Outcome(applicable=False, explanation=reason)


def _cap(findings: list[FindingDraft], cfg: dict, evidence: dict) -> list[FindingDraft]:
    limit = int(cfg.get("max_findings", 200))
    if len(findings) > limit:
        evidence["total_occurrences"] = len(findings)
        evidence["listed"] = limit
    return findings[:limit]


def _loc(b: Blk) -> str:
    where = f"blok {b.block_id}"
    if b.page_number:
        where = f"halaman {b.page_number}, {where}"
    elif b.page_estimate:
        where = f"± halaman {b.page_estimate}, {where}"
    return where


# ---------------------------------------------------------------------------
# Teknis
# ---------------------------------------------------------------------------

DEFAULT_PLACEHOLDERS = [
    r"\[[^\]\n]{0,40}\b(?:di sini|DI SINI|JUDUL|NAMA|TULIS|ISI|ISIKAN)\b[^\]\n]{0,40}\]",
    r"\bTODO\b",
    r"\bTBD\b",
    r"(?i)lorem ipsum",
    r"\bX{3,}\b",
    r"\?{3,}",
]


@handler("placeholder_text")
def placeholder_text(doc: DocView, cfg: dict) -> Outcome:
    patterns = [re.compile(p) for p in cfg.get("patterns", DEFAULT_PLACEHOLDERS)]
    findings = []
    for b in doc.body_blocks():
        for p in patterns:
            for m in p.finditer(b.text):
                findings.append(
                    FindingDraft(
                        title="Teks placeholder tertinggal",
                        description=f"Ditemukan teks sementara “{m.group(0)}” di {_loc(b)}. Teks seperti ini tidak boleh terbit.",
                        suggested_action="Ganti placeholder dengan isi final atau hapus.",
                        block=b,
                        span=m.span(),
                        details={"match": m.group(0)},
                    )
                )
    ev = {"patterns": len(patterns)}
    return Outcome(findings=_cap(findings, cfg, ev), evidence=ev)


# ---------------------------------------------------------------------------
# Struktur
# ---------------------------------------------------------------------------


@handler("required_sections")
def required_sections(doc: DocView, cfg: dict) -> Outcome:
    by_type = cfg.get("by_type", {})
    reqs = by_type.get(doc.manuscript.manuscript_type, cfg.get("default", []))
    findings, found = [], {}
    if not doc.headings:
        findings.append(
            FindingDraft(
                title="Struktur bab tidak terbaca",
                description="Tidak ada judul bab/subbab yang dikenali di seluruh naskah, sehingga kelengkapan bagian tidak dapat diperiksa.",
                suggested_action="Gunakan style Heading 1/2 untuk judul bab dan subbab (DOCX), atau bookmark (PDF), lalu unggah ulang.",
                severity="critical",
            )
        )
    for r in reqs:
        meta_key = r.get("satisfied_by_metadata")
        if meta_key and str(doc.manuscript.metadata.get(meta_key) or "").strip():
            found[r["label"]] = "metadata"
            continue
        b = doc.find_section(r["aliases"])
        found[r["label"]] = b.block_id if b else None
        if not b:
            findings.append(
                FindingDraft(
                    title=f"Bagian “{r['label']}” tidak ditemukan",
                    description=r.get("why", f"Naskah jenis ini lazimnya memuat bagian {r['label']}. Dicari judul: {', '.join(r['aliases'])}."),
                    suggested_action=r.get("action", f"Tambahkan bagian {r['label']} dengan judul yang jelas."),
                    severity=r.get("severity"),
                )
            )
    return Outcome(findings=findings, evidence={"checked": found, "manuscript_type": doc.manuscript.manuscript_type})


@handler("chapter_sequence")
def chapter_sequence(doc: DocView, cfg: dict) -> Outcome:
    chs = doc.chapters
    if not chs:
        return not_applicable("Tidak ada judul berpola “BAB n”.")
    findings = []
    numbers = [c.number for c in chs]
    styles = {"roman" if not c.label.isdigit() else "arabic" for c in chs}
    if len(styles) > 1:
        odd = next(c for c in chs if ("roman" if not c.label.isdigit() else "arabic") != ("roman" if not chs[0].label.isdigit() else "arabic"))
        findings.append(
            FindingDraft(
                title="Gaya penomoran bab tidak seragam",
                description=f"Penomoran bab mencampur angka Romawi dan Arab (mis. BAB {chs[0].label} dan BAB {odd.label}).",
                suggested_action="Gunakan satu gaya penomoran bab di seluruh naskah.",
                block=odd.heading,
            )
        )
    expected = 1
    seen: set[int] = set()
    for c in chs:
        if c.number is None:
            continue
        if c.number in seen:
            findings.append(
                FindingDraft(
                    title=f"Nomor bab {c.label} terulang",
                    description=f"BAB {c.label} muncul lebih dari sekali ({_loc(c.heading)}).",
                    suggested_action="Perbaiki nomor bab agar unik dan berurutan.",
                    block=c.heading,
                    severity="major",
                )
            )
        elif c.number != expected:
            findings.append(
                FindingDraft(
                    title=f"Urutan bab melompat ke BAB {c.label}",
                    description=f"Setelah BAB {expected - 1 if expected > 1 else '—'} diharapkan BAB {expected}, tetapi ditemukan BAB {c.label} ({_loc(c.heading)}).",
                    suggested_action="Periksa apakah ada bab yang hilang atau salah nomor.",
                    block=c.heading,
                )
            )
        seen.add(c.number)
        expected = c.number + 1
    return Outcome(findings=findings, evidence={"chapters": numbers, "styles": sorted(styles)})


@handler("heading_level_jump")
def heading_level_jump(doc: DocView, cfg: dict) -> Outcome:
    if not doc.headings:
        return not_applicable("Tidak ada heading.")
    findings, prev = [], 1
    for h in doc.headings:
        lvl = h.level or 1
        if lvl > prev + 1:
            findings.append(
                FindingDraft(
                    title=f"Tingkat judul melompat (H{prev} → H{lvl})",
                    description=f"Judul “{h.text[:80]}” berada di tingkat {lvl} langsung setelah tingkat {prev} ({_loc(h)}).",
                    suggested_action=f"Ubah menjadi Heading {prev + 1} atau tambahkan judul tingkat perantara.",
                    block=h,
                )
            )
        prev = lvl
    return Outcome(findings=_cap(findings, cfg, {}), evidence={"headings": len(doc.headings)})


RE_TOC_CHAPTER = re.compile(r"^(?:BAB|Bab)\s+([IVXLCDM]+|\d+)\b[\s.:\-–—]*(.*)$")


@handler("toc_consistency")
def toc_consistency(doc: DocView, cfg: dict) -> Outcome:
    entries = doc.toc_entries
    if not entries:
        return not_applicable("Daftar isi tidak ditemukan; keberadaannya diperiksa di jalur ISBN/administrasi.")
    findings = []
    parsed = []
    for e in entries:
        title = e.locator.get("toc_title") or re.sub(r"[\s.…·_-]*\t?\s*\d+\s*$", "", e.text).strip()
        parsed.append((e, title, e.locator.get("toc_page")))
    # Entri "BAB n" tanpa judul yang judulnya ada di baris berikutnya.
    for i, (e, title, _page) in enumerate(parsed):
        m = RE_TOC_CHAPTER.match(title)
        if m and not m.group(2).strip() and i + 1 < len(parsed) and not RE_TOC_CHAPTER.match(parsed[i + 1][1]):
            findings.append(
                FindingDraft(
                    title=f"Entri daftar isi BAB {m.group(1)} terpecah dua baris",
                    description=f"Di daftar isi, “BAB {m.group(1)}” dan judulnya “{parsed[i + 1][1][:80]}” menjadi dua entri terpisah.",
                    suggested_action="Satukan nomor dan judul bab dalam satu baris heading, lalu perbarui daftar isi (Update Table).",
                    block=e,
                )
            )
    toc_by_chapter: dict[str, tuple[Blk, str, str | None]] = {}
    for e, title, page in parsed:
        if m := RE_TOC_CHAPTER.match(title):
            toc_by_chapter.setdefault(m.group(1).upper(), (e, m.group(2).strip(), page))
    reliable = doc.pages_reliable
    for c in doc.chapters:
        hit = toc_by_chapter.get(c.label.upper())
        if not hit:
            findings.append(
                FindingDraft(
                    title=f"BAB {c.label} tidak tercantum di daftar isi",
                    description=f"Bab “{c.heading.text[:90]}” ada di naskah ({_loc(c.heading)}) tetapi tidak ada di daftar isi.",
                    suggested_action="Perbarui daftar isi agar memuat semua bab.",
                    block=c.heading,
                )
            )
            continue
        e, toc_title, toc_page = hit
        if toc_title and c.title and norm(toc_title) not in norm(c.title) and norm(c.title) not in norm(toc_title):
            findings.append(
                FindingDraft(
                    title=f"Judul BAB {c.label} di daftar isi berbeda",
                    description=f"Daftar isi: “{toc_title[:90]}”. Naskah: “{c.title[:90]}”.",
                    suggested_action="Samakan judul bab di daftar isi dengan judul di naskah.",
                    block=e,
                )
            )
        page = c.heading.page
        if toc_page and toc_page.isdigit() and page and abs(int(toc_page) - page) > int(cfg.get("page_tolerance", 0)):
            findings.append(
                FindingDraft(
                    title=f"Halaman BAB {c.label} di daftar isi tidak cocok",
                    description=f"Daftar isi menyebut halaman {toc_page}, sedangkan bab dimulai di {'halaman' if reliable else 'perkiraan halaman'} {page}.",
                    suggested_action="Perbarui nomor halaman daftar isi setelah tata letak final.",
                    block=e,
                    requires_human_verification=not reliable,
                )
            )
    return Outcome(findings=findings, evidence={"toc_entries": len(entries), "chapters": len(doc.chapters)})


@handler("short_chapter")
def short_chapter(doc: DocView, cfg: dict) -> Outcome:
    if not doc.chapters:
        return not_applicable("Tidak ada bab berpola “BAB n”.")
    min_words = int(cfg.get("min_words", 300))
    findings = [
        FindingDraft(
            title=f"BAB {c.label} sangat pendek ({c.words} kata)",
            description=f"Bab ini hanya berisi {c.words} kata (ambang indikator {min_words} kata). Ini indikator, bukan kesalahan otomatis.",
            suggested_action="Periksa apakah isi bab lengkap atau sebaiknya digabung dengan bab lain.",
            block=c.heading,
        )
        for c in doc.chapters
        if c.words < min_words
    ]
    return Outcome(findings=findings, evidence={"words_per_chapter": {c.label: c.words for c in doc.chapters}, "min_words": min_words})


@handler("chapter_title_style")
def chapter_title_style(doc: DocView, cfg: dict) -> Outcome:
    if not doc.chapters:
        return not_applicable("Tidak ada bab berpola “BAB n”.")
    findings = []
    for c in doc.chapters:
        if not c.title:
            findings.append(
                FindingDraft(
                    title=f"BAB {c.label} tanpa judul",
                    description=f"Heading bab hanya berisi “BAB {c.label}” tanpa judul bab ({_loc(c.heading)}).",
                    suggested_action="Tambahkan judul bab pada heading yang sama.",
                    block=c.heading,
                )
            )
    styles = Counter("upper" if c.title.isupper() else "mixed" for c in doc.chapters if c.title)
    if len(styles) > 1:
        minority = min(styles, key=styles.get)
        odd = next(c for c in doc.chapters if c.title and ("upper" if c.title.isupper() else "mixed") == minority)
        findings.append(
            FindingDraft(
                title="Gaya huruf judul bab tidak seragam",
                description=f"{styles['upper']} judul bab memakai huruf kapital semua dan {styles['mixed']} tidak (mis. BAB {odd.label}).",
                suggested_action="Seragamkan gaya penulisan judul bab.",
                block=odd.heading,
                severity="minor",
            )
        )
    return Outcome(findings=findings, evidence={"styles": dict(styles)})


# ---------------------------------------------------------------------------
# Pengulangan internal
# ---------------------------------------------------------------------------


def _key(text: str) -> str:
    return hashlib.sha1(norm(text).encode()).hexdigest()


def _shingles(text: str, k: int = 3) -> set[str]:
    w = norm(text).split()
    return {" ".join(w[i : i + k]) for i in range(max(0, len(w) - k + 1))}


@handler("duplicate_content")
def duplicate_content(doc: DocView, cfg: dict) -> Outcome:
    min_chars = int(cfg.get("min_chars", 120))
    min_run = int(cfg.get("min_run_blocks", 3))
    min_run_chars = int(cfg.get("min_run_chars", 60))
    near_threshold = float(cfg.get("near_threshold", 0.9))
    near_min_chars = int(cfg.get("near_min_chars", 250))
    blocks = [b for b in doc.blocks if not b.is_toc and not b.is_heading and b.text.strip()]
    keys = [_key(b.text) for b in blocks]
    findings: list[FindingDraft] = []
    covered: set[int] = set()

    # 1) Rangkaian blok berulang (mis. halaman judul tercetak dua kali).
    positions: dict[str, list[int]] = defaultdict(list)
    i = 0
    while i < len(blocks):
        best = (0, -1)
        for j in positions.get(keys[i], []):
            k = 0
            while i + k < len(blocks) and j + k < i and keys[i + k] == keys[j + k]:
                k += 1
            if k > best[0]:
                best = (k, j)
        k, j = best
        if k >= min_run and sum(len(b.text) for b in blocks[i : i + k]) >= min_run_chars:
            first, dup = blocks[j], blocks[i]
            findings.append(
                FindingDraft(
                    title=f"{k} paragraf berurutan terulang",
                    description=f"Rangkaian {k} paragraf mulai {_loc(dup)} identik dengan rangkaian mulai {_loc(first)}.",
                    suggested_action="Hapus salah satu salinan.",
                    block=dup,
                    details={"first_block": first.block_id, "length": k},
                )
            )
            for x in range(k):
                positions[keys[i + x]].append(i + x)
                covered.add(i + x)
            i += k
            continue
        positions[keys[i]].append(i)
        i += 1

    # 2) Paragraf panjang identik.
    first_seen: dict[str, int] = {}
    for idx, (b, k) in enumerate(zip(blocks, keys, strict=True)):
        if len(b.text) < min_chars:
            continue
        if k in first_seen and idx not in covered:
            f = blocks[first_seen[k]]
            findings.append(
                FindingDraft(
                    title="Paragraf identik terulang",
                    description=f"Paragraf di {_loc(b)} sama persis dengan paragraf di {_loc(f)}.",
                    suggested_action="Hapus pengulangan atau parafrasekan bila memang perlu disebut ulang.",
                    block=b,
                    details={"first_block": f.block_id},
                )
            )
            covered.add(idx)
        first_seen.setdefault(k, idx)

    # 3) Paragraf sangat mirip (Jaccard 3-gram kata).
    long = [(idx, _shingles(b.text)) for idx, b in enumerate(blocks) if len(b.text) >= near_min_chars and idx not in covered]
    for a in range(len(long)):
        ia, sa = long[a]
        for b_ in range(a):
            ib, sb = long[b_]
            if not sa or not sb or keys[ia] == keys[ib]:
                continue
            small, big = sorted((len(sa), len(sb)))
            if small / big < near_threshold:
                continue
            jac = len(sa & sb) / len(sa | sb)
            if jac >= near_threshold:
                findings.append(
                    FindingDraft(
                        title="Paragraf sangat mirip",
                        description=f"Paragraf di {_loc(blocks[ia])} {round(jac * 100)}% mirip dengan paragraf di {_loc(blocks[ib])}.",
                        suggested_action="Periksa apakah pengulangan disengaja; bila tidak, gabungkan atau hapus.",
                        block=blocks[ia],
                        severity="minor",
                        requires_human_verification=True,
                        details={"similar_to": blocks[ib].block_id, "jaccard": round(jac, 3)},
                    )
                )
                break
    ev = {"blocks_compared": len(blocks), "method": "sha1 normalized + run detection + jaccard 3-gram"}
    return Outcome(findings=_cap(findings, cfg, ev), evidence=ev)


# ---------------------------------------------------------------------------
# Bahasa & tipografi
# ---------------------------------------------------------------------------

TYPO_RULES = [
    ("double_space", re.compile(r"(?<=\S) {2,}(?=\S)"), "Spasi ganda", "Ganti dengan satu spasi."),
    ("space_before_punct", re.compile(r"(?<=\w) +(?=[,;:!?](?!\S*\d)|\.(?!\.|\d))"), "Spasi sebelum tanda baca", "Hapus spasi sebelum tanda baca."),
    ("no_space_after_punct", re.compile(r"(?<=[a-z])[,;](?=[A-Za-z])"), "Tidak ada spasi setelah tanda baca", "Tambahkan spasi setelah koma/titik koma."),
    ("repeated_punct", re.compile(r"([!?,;:])\1+|\.{4,}"), "Tanda baca berulang", "Gunakan satu tanda baca (atau elipsis “…” tiga titik)."),
]


@handler("typography")
def typography(doc: DocView, cfg: dict) -> Outcome:
    enabled = set(cfg.get("checks", [r[0] for r in TYPO_RULES] + ["unbalanced_parentheses"]))
    findings, counts = [], Counter()
    for b in doc.body_blocks():
        if b.type == "table":
            continue
        hits = []
        for key, rx, label, action in TYPO_RULES:
            if key not in enabled:
                continue
            for m in rx.finditer(b.text):
                hits.append((m.start(), m.end(), key, label, action))
        if "unbalanced_parentheses" in enabled and b.text.count("(") != b.text.count(")"):
            pos = b.text.find("(") if b.text.count("(") > b.text.count(")") else b.text.find(")")
            hits.append((max(0, pos), max(0, pos) + 1, "unbalanced_parentheses", "Tanda kurung tidak berpasangan", "Lengkapi pasangan tanda kurung."))
        if not hits:
            continue
        hits.sort()
        for h in hits:
            counts[h[2]] += 1
        s, e, key, label, action = hits[0]
        labels = sorted({h[3] for h in hits})
        findings.append(
            FindingDraft(
                title=label if len(labels) == 1 else f"{len(hits)} masalah tipografi dalam satu paragraf",
                description=f"{', '.join(labels)} di {_loc(b)} ({len(hits)} kemunculan).",
                suggested_action=action if len(labels) == 1 else "Rapikan spasi dan tanda baca pada paragraf ini.",
                block=b,
                span=(s, e),
                details={"occurrences": [{"type": h[2], "start": h[0], "end": h[1]} for h in hits[:20]]},
            )
        )
    ev = {"by_type": dict(counts)}
    return Outcome(findings=_cap(findings, cfg, ev), evidence=ev)


RE_WORD = re.compile(r"[A-Za-zÀ-ÿ’']+")


@handler("word_list")
def word_list(doc: DocView, cfg: dict) -> Outcome:
    """Daftar kata tidak baku → baku yang dikelola (mengacu KBBI). Kecocokan per kata utuh."""
    mapping = {k.lower(): v for k, v in cfg.get("dictionary", {}).items()}
    findings, counts = [], Counter()
    for b in doc.body_blocks():
        for m in RE_WORD.finditer(b.text):
            w = m.group(0)
            right = mapping.get(w.lower().replace("’", "'"))
            if right is None:
                continue
            fix = right.capitalize() if w[0].isupper() else right
            counts[w.lower()] += 1
            findings.append(
                FindingDraft(
                    title=f"“{w}” → “{fix}”",
                    description=f"Bentuk “{w}” tidak baku; bentuk baku: “{fix}” ({_loc(b)}).",
                    suggested_action=f"Ganti “{w}” dengan “{fix}”.",
                    block=b,
                    span=m.span(),
                    details={"word": w, "suggestion": fix},
                )
            )
    ev = {"dictionary_size": len(mapping), "by_word": dict(counts.most_common(50)), "source": cfg.get("source")}
    return Outcome(findings=_cap(findings, cfg, ev), evidence=ev)


@handler("term_consistency")
def term_consistency(doc: DocView, cfg: dict) -> Outcome:
    findings, report = [], []
    text_blocks = doc.body_blocks()
    for group in cfg.get("groups", []):
        hits: dict[str, list[tuple[Blk, re.Match]]] = {}
        for v in group:
            rx = re.compile(rf"(?<![\w-]){re.escape(v)}(?![\w-])", re.IGNORECASE)
            for b in text_blocks:
                for m in rx.finditer(b.text):
                    hits.setdefault(v, []).append((b, m))
        used = {v: len(h) for v, h in hits.items()}
        report.append({"group": group, "used": used})
        if len(used) > 1:
            main = max(used, key=used.get)
            for v, h in hits.items():
                if v == main:
                    continue
                b, m = h[0]
                findings.append(
                    FindingDraft(
                        title=f"Istilah tidak konsisten: “{v}” dan “{main}”",
                        description=f"“{main}” dipakai {used[main]}×, “{v}” dipakai {used[v]}× (pertama di {_loc(b)}).",
                        suggested_action=f"Pilih satu istilah (mis. “{main}”) dan gunakan secara konsisten.",
                        block=b,
                        span=m.span(),
                        details={"variants": used},
                    )
                )
    return Outcome(findings=findings, evidence={"groups": report})


# ---------------------------------------------------------------------------
# Sitasi & referensi
# ---------------------------------------------------------------------------

REF_ALIASES = ["daftar pustaka", "referensi", "bibliografi", "daftar rujukan", "pustaka acuan", "daftar referensi"]
NAME = r"[A-Z][A-Za-zÀ-ÿ'’\-]+"
RE_PAREN = re.compile(r"\(([^()]{3,300})\)")
RE_CIT_PART = re.compile(rf"^\s*(?:lihat\s+|cf\.\s+)?({NAME})(?:\s(?:dkk\.?|et al\.?|(?:&|dan)\s{NAME}))?,?\s((?:19|20)\d{{2}}[a-z]?)\b")
RE_CIT_NARR = re.compile(rf"\b({NAME})(?:\s(?:dkk\.?|et al\.?|(?:&|dan)\s{NAME}))?\s\(((?:19|20)\d{{2}}[a-z]?)(?:[:,][^)]*)?\)")
RE_CIT_NUM = re.compile(r"\[(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]")
RE_YEAR = re.compile(r"\b((?:19|20)\d{2}[a-z]?)\b")
RE_REF_NUM = re.compile(r"^\s*\[?(\d{1,3})[\].)]\s")
RE_APA = re.compile(rf"^{NAME},\s(?:[A-Z]\.\s?-?)+.*\(((?:19|20)\d{{2}}[a-z]?|n\.d\.)\)\.\s.+")


def _references(doc: DocView) -> tuple[Blk | None, list[Blk]]:
    if "refs" not in doc.cache:
        head = doc.find_section(REF_ALIASES, allow_paragraph=False) or doc.find_section(REF_ALIASES)
        entries = [b for b in doc.section_of(head) if not b.is_heading and len(b.text) > 15] if head else []
        doc.cache["refs"] = (head, entries)
    return doc.cache["refs"]


def _citations(doc: DocView) -> list[tuple[Blk, tuple[int, int], str, str | None, str]]:
    """(blok, span, nama/nomor, tahun, gaya) dari isi naskah di luar daftar pustaka dan daftar isi."""
    if "cites" in doc.cache:
        return doc.cache["cites"]
    head, entries = _references(doc)
    skip = {b.index for b in entries} | ({head.index} if head else set())
    out = []
    for b in doc.body_blocks():
        if b.index in skip or b.is_heading:
            continue
        for pm in RE_PAREN.finditer(b.text):
            for part in pm.group(1).split(";"):
                if m := RE_CIT_PART.match(part):
                    out.append((b, pm.span(), m.group(1), m.group(2), "author_year"))
        for m in RE_CIT_NARR.finditer(b.text):
            out.append((b, m.span(), m.group(1), m.group(2), "author_year"))
        for m in RE_CIT_NUM.finditer(b.text):
            for n in re.split(r"\s*,\s*", m.group(1)):
                if "-" in n or "–" in n:
                    a, z = re.split(r"\s*[-–]\s*", n)
                    for k in range(int(a), int(z) + 1):
                        out.append((b, m.span(), str(k), None, "numeric"))
                else:
                    out.append((b, m.span(), n.strip(), None, "numeric"))
    doc.cache["cites"] = out
    return out


def _ref_keys(entries: list[Blk]) -> dict[tuple[str, str | None], Blk]:
    keys: dict[tuple[str, str | None], Blk] = {}
    for e in entries:
        if m := RE_REF_NUM.match(e.text):
            keys.setdefault((m.group(1), None), e)
            continue
        # "Sutrisno, A. (2020)…" → kunci (sutrisno, 2020)
        first = re.split(r"[,.(]", e.text.strip(), maxsplit=1)[0].strip().split()
        surname = first[0] if first else ""
        y = RE_YEAR.search(e.text)
        keys.setdefault((norm(surname), y.group(1) if y else None), e)
    return keys


@handler("references_present")
def references_present(doc: DocView, cfg: dict) -> Outcome:
    head, entries = _references(doc)
    if head and entries:
        return Outcome(evidence={"heading": head.block_id, "entries": len(entries)})
    return Outcome(
        findings=[
            FindingDraft(
                title="Daftar pustaka tidak ditemukan" if not head else "Daftar pustaka kosong",
                description="Naskah jenis ini wajib memuat daftar pustaka/referensi. Dicari judul: " + ", ".join(REF_ALIASES) + ".",
                suggested_action="Tambahkan bagian Daftar Pustaka di akhir naskah dengan semua sumber yang disitir.",
                block=head,
            )
        ],
        evidence={"heading": head.block_id if head else None, "entries": len(entries)},
    )


@handler("citation_without_reference")
def citation_without_reference(doc: DocView, cfg: dict) -> Outcome:
    head, entries = _references(doc)
    cites = _citations(doc)
    if not entries:
        return not_applicable("Daftar pustaka tidak ditemukan; diperiksa oleh aturan keberadaan daftar pustaka.")
    keys = _ref_keys(entries)
    surnames = {k[0] for k in keys}
    findings, seen = [], set()
    for b, span, name, year, style in cites:
        key = (name, None) if style == "numeric" else (norm(name), year)
        ok = key in keys or (style == "author_year" and (norm(name), None) in keys)
        if ok or key in seen:
            continue
        seen.add(key)
        near = style == "author_year" and norm(name) in surnames
        findings.append(
            FindingDraft(
                title=f"Sitasi “{name}{', ' + year if year else ''}” tidak ada di daftar pustaka",
                description=(
                    f"Sitasi di {_loc(b)} tidak memiliki pasangan di daftar pustaka"
                    + (" (nama penulis ada, tetapi tahunnya berbeda)." if near else ".")
                ),
                suggested_action="Tambahkan entri sumber ini ke daftar pustaka, atau perbaiki nama/tahun sitasi.",
                block=b,
                span=span,
                details={"name": name, "year": year, "style": style, "surname_found_other_year": near},
            )
        )
    ev = {"citations_found": len(cites), "reference_entries": len(entries)}
    if not cites:
        findings.append(
            FindingDraft(
                title="Tidak ada sitasi yang dikenali",
                description="Naskah memiliki daftar pustaka, tetapi tidak ditemukan sitasi berformat (Nama, Tahun), Nama (Tahun), atau [n].",
                suggested_action="Pastikan setiap rujukan disitir di dalam teks dengan gaya yang konsisten.",
                block=head,
                severity="minor",
            )
        )
    return Outcome(findings=_cap(findings, cfg, ev), evidence=ev)


@handler("reference_not_cited")
def reference_not_cited(doc: DocView, cfg: dict) -> Outcome:
    head, entries = _references(doc)
    cites = _citations(doc)
    if not entries or not cites:
        return not_applicable("Butuh daftar pustaka dan sitasi yang dikenali.")
    cited = {(n, None) if s == "numeric" else (norm(n), y) for _, _, n, y, s in cites}
    cited_names = {norm(n) for _, _, n, _, s in cites if s == "author_year"}
    findings = []
    for key, e in _ref_keys(entries).items():
        if key in cited or (key[1] is None and key[0] in cited_names):
            continue
        findings.append(
            FindingDraft(
                title="Entri daftar pustaka tidak pernah disitir",
                description=f"Entri di {_loc(e)} tidak ditemukan sitasinya di dalam teks.",
                suggested_action="Sitir sumber ini di teks atau hapus dari daftar pustaka.",
                block=e,
                details={"key": list(key)},
            )
        )
    return Outcome(findings=_cap(findings, cfg, {}), evidence={"reference_entries": len(entries)})


@handler("reference_format")
def reference_format(doc: DocView, cfg: dict) -> Outcome:
    _, entries = _references(doc)
    if not entries:
        return not_applicable("Daftar pustaka tidak ditemukan.")
    if all(RE_REF_NUM.match(e.text) for e in entries):
        return Outcome(evidence={"style": "numeric", "entries": len(entries)}, explanation="Gaya bernomor; format rinci tidak diperiksa.")
    findings = []
    bad = [e for e in entries if not RE_APA.match(e.text.strip())]
    for e in bad:
        findings.append(
            FindingDraft(
                title="Format entri pustaka tidak sesuai gaya yang didukung",
                description=f"Entri di {_loc(e)} tidak mengikuti pola “Nama, I. (Tahun). Judul.” (gaya APA). Sistem tidak menilai kebenaran sumbernya.",
                suggested_action="Seragamkan format entri sesuai gaya selingkung penerbit.",
                block=e,
            )
        )
    names = [norm(e.text)[:30] for e in entries]
    if names != sorted(names):
        findings.append(
            FindingDraft(
                title="Daftar pustaka tidak urut abjad",
                description="Entri daftar pustaka tidak tersusun alfabetis berdasarkan nama penulis.",
                suggested_action="Urutkan entri berdasarkan nama belakang penulis.",
                block=entries[0],
            )
        )
    return Outcome(findings=_cap(findings, cfg, {}), evidence={"entries": len(entries), "non_conforming": len(bad)})


# ---------------------------------------------------------------------------
# Elemen pembahasan
# ---------------------------------------------------------------------------


@handler("book_elements")
def book_elements(doc: DocView, cfg: dict) -> Outcome:
    spec = cfg.get("by_type", {}).get(doc.manuscript.manuscript_type)
    if not spec:
        return not_applicable("Tidak ada elemen pembahasan yang didefinisikan untuk jenis naskah ini.")
    findings, report = [], {"book": {}, "chapters": {}}
    for el in spec.get("book", []):
        b = doc.find_section(el["aliases"])
        report["book"][el["label"]] = b.block_id if b else None
        if not b:
            findings.append(
                FindingDraft(
                    title=f"Elemen “{el['label']}” tidak ditemukan",
                    description=f"Naskah jenis ini lazimnya memuat {el['label']}. Dicari: {', '.join(el['aliases'])}.",
                    suggested_action=el.get("action", f"Tambahkan {el['label']}."),
                    severity=el.get("severity"),
                )
            )
    for c in doc.chapters:
        missing = []
        for el in spec.get("per_chapter", []):
            found = doc.find_section(el["aliases"], scope=c.blocks)
            if not found:
                missing.append(el["label"])
        report["chapters"][c.label] = missing
        if missing:
            findings.append(
                FindingDraft(
                    title=f"BAB {c.label} belum memuat: {', '.join(missing)}",
                    description=f"Untuk jenis naskah ini setiap bab diharapkan memuat {', '.join(e['label'] for e in spec['per_chapter'])}.",
                    suggested_action=f"Tambahkan subbagian {', '.join(missing)} pada BAB {c.label}.",
                    block=c.heading,
                )
            )
    return Outcome(findings=findings, evidence=report)


# ---------------------------------------------------------------------------
# Metadata & elemen penerbitan (editorial)
# ---------------------------------------------------------------------------


def _title_match(doc: DocView) -> Blk | None:
    want = norm(doc.manuscript.title)
    for b in doc.front_matter[:60]:
        n = norm(b.text)
        if len(n) >= 6 and (n in want or want in n):
            return b
    return None


@handler("title_page_title")
def title_page_title(doc: DocView, cfg: dict) -> Outcome:
    b = _title_match(doc)
    if b:
        return Outcome(evidence={"block": b.block_id})
    first = next((x for x in doc.front_matter if x.text.strip()), None)
    return Outcome(
        findings=[
            FindingDraft(
                title="Judul di halaman awal berbeda dengan judul di sistem",
                description=f"Judul kerja “{doc.manuscript.title[:90]}” tidak ditemukan di halaman awal naskah"
                + (f"; baris pertama naskah: “{first.text[:90]}”." if first else "."),
                suggested_action="Samakan judul kerja di sistem dengan judul pada halaman judul naskah.",
                block=first,
                requires_human_verification=True,
            )
        ]
    )


@handler("authors_on_title_page")
def authors_on_title_page(doc: DocView, cfg: dict) -> Outcome:
    if not doc.manuscript.authors:
        return not_applicable("Penulis belum diisi di metadata naskah; lengkapi metadata agar dapat diperiksa.")
    front = norm(" ".join(b.text for b in doc.front_matter[:80]))
    missing = [a for a in doc.manuscript.authors if norm(a) not in front]
    findings = [
        FindingDraft(
            title=f"Nama penulis “{a}” tidak ada di halaman awal",
            description="Nama penulis di metadata tidak ditemukan pada halaman judul/halaman awal naskah.",
            suggested_action="Cantumkan nama penulis pada halaman judul sesuai metadata, atau perbaiki metadata.",
            requires_human_verification=True,
        )
        for a in missing
    ]
    return Outcome(findings=findings, evidence={"authors": doc.manuscript.authors, "missing": missing})


# ---------------------------------------------------------------------------
# Jalur ISBN / administrasi (kepatuhan)
# ---------------------------------------------------------------------------

RE_PUBLISHER = re.compile(r"(?i)\b(penerbit|diterbitkan oleh|publisher)\b")
RE_COPYRIGHT = re.compile(r"(?i)(hak cipta|copyright|©|\(c\)\s*\d{4})")
RE_AUTHOR_LABEL = re.compile(r"(?i)\b(penulis|pengarang|oleh|karya|editor|penyunting)\b")


def _first_match(blocks: list[Blk], rx: re.Pattern) -> Blk | None:
    return next((b for b in blocks if rx.search(b.text)), None)


def _title_candidate(front: list[Blk]) -> Blk | None:
    """Baris pendek pertama yang bukan label penulis/penerbit/hak cipta: kandidat judul buku.
    Kesesuaiannya dengan judul kerja di sistem diperiksa terpisah oleh MET-001."""
    for b in front:
        t = b.text.strip()
        if not t or len(t) > 150 or b.is_heading and norm(t) in ("kata pengantar", "daftar isi", "prakata"):
            continue
        if RE_AUTHOR_LABEL.search(t) or RE_PUBLISHER.search(t) or RE_COPYRIGHT.search(t):
            continue
        return b
    return None


@handler("isbn_title_page")
def isbn_title_page(doc: DocView, cfg: dict) -> Outcome:
    front = doc.front_matter[:60]
    title = _title_match(doc) or _title_candidate(front[:10])
    author = None
    for a in doc.manuscript.authors:
        author = author or next((b for b in front if norm(a) in norm(b.text)), None)
    author = author or _first_match(front, RE_AUTHOR_LABEL)
    publisher = _first_match(front, RE_PUBLISHER)
    elements = {"judul": title, "nama penulis": author, "nama penerbit": publisher}
    missing = [k for k, v in elements.items() if v is None]
    ev = {k: (v.block_id if v else None) for k, v in elements.items()}
    if not missing:
        return Outcome(observed="pass", evidence=ev, explanation="Halaman judul memuat judul, nama penulis, dan nama penerbit.")
    return Outcome(
        observed="fail",
        evidence=ev,
        explanation=f"Halaman judul belum memuat: {', '.join(missing)}.",
        findings=[
            FindingDraft(
                title=f"Halaman judul belum memuat {', '.join(missing)}",
                description="Halaman judul diharapkan memuat judul buku, nama penulis, dan nama penerbit. "
                f"Yang tidak ditemukan di bagian awal naskah: {', '.join(missing)}.",
                suggested_action="Lengkapi halaman judul dengan judul, nama penulis, dan nama penerbit.",
                block=front[0] if front else None,
            )
        ],
    )


@handler("isbn_copyright_page")
def isbn_copyright_page(doc: DocView, cfg: dict) -> Outcome:
    front = doc.front_matter[:120]
    copyright_b = _first_match(front, RE_COPYRIGHT)
    publisher_b = _first_match(front, RE_PUBLISHER)
    ev = {"pernyataan hak cipta": copyright_b.block_id if copyright_b else None, "identitas penerbit": publisher_b.block_id if publisher_b else None}
    missing = [k for k, v in ev.items() if v is None]
    if not missing:
        return Outcome(observed="pass", evidence=ev, explanation="Ditemukan pernyataan hak cipta dan identitas penerbit di bagian awal naskah.")
    return Outcome(
        observed="fail",
        evidence=ev,
        explanation=f"Halaman balik judul belum memuat: {', '.join(missing)}.",
        findings=[
            FindingDraft(
                title="Halaman balik judul (hak cipta) belum lengkap",
                description=f"Tidak ditemukan {', '.join(missing)} di bagian awal naskah.",
                suggested_action="Tambahkan halaman balik judul berisi pernyataan hak cipta, identitas penerbit, dan data terbitan.",
            )
        ],
    )


def is_fiction(doc: DocView) -> bool:
    if doc.manuscript.manuscript_type == "fiksi":
        return True
    cls = (doc.manuscript.metadata or {}).get("classification") or {}
    return (cls.get("jenis_pustaka") or {}).get("value") == "Fiksi"


def classification_flag(doc: DocView, key: str) -> str | None:
    cls = (doc.manuscript.metadata or {}).get("classification") or {}
    return (cls.get(key) or {}).get("value")


@handler("isbn_section_present")
def isbn_section_present(doc: DocView, cfg: dict) -> Outcome:
    label = cfg.get("label", "bagian")
    b = doc.find_section(cfg.get("aliases", [label]))
    if b:
        return Outcome(observed="pass", evidence={"block": b.block_id}, explanation=f"{label} ditemukan ({_loc(b)}).")
    if cfg.get("optional_for_fiction") and is_fiction(doc):
        return not_applicable(f"{label} tidak ditemukan, tetapi tidak wajib untuk karya sastra/fiksi (Juknis Layanan ISBN 4.3.3).")
    return Outcome(
        observed="fail",
        evidence={"block": None, "aliases": cfg.get("aliases")},
        explanation=f"{label} tidak ditemukan.",
        findings=[
            FindingDraft(
                title=f"{label} tidak ditemukan",
                description=f"Dicari judul: {', '.join(cfg.get('aliases', [label]))}.",
                suggested_action=cfg.get("action", f"Tambahkan {label}."),
            )
        ],
    )


@handler("isbn_application_metadata")
def isbn_application_metadata(doc: DocView, cfg: dict) -> Outcome:
    m = doc.manuscript
    checks = {
        "judul": bool(m.title.strip()),
        "penulis": bool(m.authors),
        "jenis naskah": m.manuscript_type not in ("", "lainnya"),
        "bahasa": bool(m.language_code),
    }
    missing = [k for k, ok in checks.items() if not ok]
    if not missing:
        return Outcome(observed="pass", evidence=checks, explanation="Data permohonan dasar lengkap.")
    return Outcome(
        observed="fail",
        evidence=checks,
        explanation=f"Data permohonan belum lengkap: {', '.join(missing)}.",
        findings=[
            FindingDraft(
                title=f"Metadata permohonan belum lengkap: {', '.join(missing)}",
                description="Data ini diperlukan untuk pengajuan ISBN dan tidak diisi otomatis oleh sistem.",
                suggested_action="Lengkapi metadata naskah di tab Metadata & penulis.",
            )
        ],
    )


@handler("human_evidence")
def human_evidence(doc: DocView, cfg: dict) -> Outcome:
    types = cfg.get("only_for_types")
    flag = cfg.get("only_if_translation")
    if flag and not (doc.manuscript.manuscript_type == "terjemahan" or classification_flag(doc, "terjemahan") == "Ya"):
        return not_applicable("Naskah tidak terdeteksi sebagai terjemahan.")
    if types and not flag and doc.manuscript.manuscript_type not in types:
        return not_applicable("Tidak berlaku untuk jenis naskah ini.")
    return Outcome(
        observed="unknown",
        evidence={"required_evidence": cfg.get("evidence")},
        explanation=cfg.get("explanation", "Memerlukan bukti di luar naskah yang harus diperiksa manusia."),
    )


@handler("min_pages")
def min_pages(doc: DocView, cfg: dict) -> Outcome:
    minimum = int(cfg.get("by_type", {}).get(doc.manuscript.manuscript_type, cfg.get("min_pages", 49)))
    pages = doc.page_count
    if pages is None:
        return Outcome(observed="unknown", evidence={"min_pages": minimum}, explanation="Jumlah halaman tidak tersedia dari berkas.")
    lay = getattr(doc, "layout", None) or {}
    size = (lay.get("page_sizes") or [{}])[0]
    if doc.summary.get("source_format") == "docx" and size.get("height_cm", 0) >= cfg.get("draft_page_height_cm", 27) and pages < minimum:
        # Naskah A4/Letter: jumlah halaman akan berubah setelah ditata ke ukuran buku.
        return Outcome(observed="unknown", evidence={"pages": pages, "min_pages": minimum, "page_height_cm": size.get("height_cm")},
                       explanation=f"{pages} halaman dalam ukuran {size.get('width_cm')} × {size.get('height_cm')} cm (draf A4/Letter); "
                       f"minimum {minimum} halaman dinilai ulang setelah naskah ditata ke ukuran buku.")
    ev = {"pages": pages, "min_pages": minimum, "source": doc.summary.get("page_count_source")}
    if pages >= minimum:
        return Outcome(observed="pass", evidence=ev, explanation=f"{pages} halaman (minimum {minimum}).")
    return Outcome(
        observed="fail",
        evidence=ev,
        explanation=f"{pages} halaman, di bawah minimum {minimum}.",
        findings=[
            FindingDraft(
                title=f"Jumlah halaman di bawah minimum ({pages} < {minimum})",
                description=f"Naskah berjumlah {pages} halaman; kebijakan menetapkan minimum {minimum} halaman.",
                suggested_action="Periksa kelengkapan isi atau tata letak naskah.",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Tata letak fisik (tahap cek layout). Membaca DocView.layout dari app.reader.layout.
# ---------------------------------------------------------------------------


def _layout(doc: DocView) -> dict | None:
    lay = getattr(doc, "layout", None)
    return lay if lay and lay.get("supported") else None


def _block_for_sample(doc: DocView, sample: str | None) -> Blk | None:
    if not sample:
        return None
    key = norm(sample)[:60]
    return next((b for b in doc.blocks if key and norm(b.text).startswith(key)), None)


def _block_for_page(doc: DocView, page: int | None) -> Blk | None:
    if not page:
        return None
    return next((b for b in doc.blocks if b.page == page), None)


def _fmt_cm(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + " cm"


@handler("layout_page_size")
def layout_page_size(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay:
        return not_applicable("Informasi tata letak tidak tersedia untuk format ini.")
    groups = lay.get("page_sizes", [])
    ev = {"page_sizes": groups}
    findings = []
    if len(groups) > 1:
        main = groups[0]
        for g in groups[1:]:
            where = ", ".join(g["where"][:8]) + ("…" if g["count"] > 8 else "")
            findings.append(
                FindingDraft(
                    title=f"Ukuran halaman tidak seragam ({_fmt_cm(g['width_cm'])} × {_fmt_cm(g['height_cm'])})",
                    description=f"Sebagian besar halaman berukuran {_fmt_cm(main['width_cm'])} × {_fmt_cm(main['height_cm'])}, "
                    f"tetapi {g['count']} halaman/section berukuran berbeda: {where}.",
                    suggested_action="Samakan ukuran kertas seluruh naskah sesuai ukuran buku yang akan dicetak.",
                    block=_block_for_page(doc, int(g["where"][0].split()[-1])) if g["where"][0].startswith("halaman") else None,
                    severity="major",
                    details={"group": g},
                )
            )
    landscape = sum(g["landscape"] for g in groups)
    if landscape:
        findings.append(
            FindingDraft(
                title=f"{landscape} halaman/section berorientasi lanskap",
                description="Halaman lanskap di dalam buku potret perlu disengaja (mis. tabel lebar) dan diputar saat tata letak.",
                suggested_action="Pastikan halaman lanskap memang disengaja; bila tidak, ubah ke potret.",
                severity="info",
            )
        )
    return Outcome(findings=findings, evidence=ev)


@handler("layout_margins")
def layout_margins(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or not lay.get("margins"):
        return not_applicable("Margin tidak dapat diukur.")
    min_cm = float(cfg.get("min_margin_cm", 1.5))
    spread_cm = float(cfg.get("max_spread_cm", 0.6))
    rows = lay["margins"]
    findings = []
    tight = [m for m in rows if min(m["top"], m["bottom"], m["left"], m["right"]) < min_cm]
    if tight:
        worst = min(tight, key=lambda m: min(m["top"], m["bottom"], m["left"], m["right"]))
        side = min(("atas", worst["top"]), ("bawah", worst["bottom"]), ("kiri", worst["left"]), ("kanan", worst["right"]), key=lambda x: x[1])
        where = ", ".join(m["where"] for m in tight[:8]) + ("…" if len(tight) > 8 else "")
        findings.append(
            FindingDraft(
                title=f"Margin terlalu sempit ({side[0]} {_fmt_cm(side[1])})",
                description=f"Margin minimum yang disarankan {_fmt_cm(min_cm)}. Margin sempit berisiko terpotong saat cetak/jilid. Terjadi pada: {where}.",
                suggested_action=f"Perbesar margin menjadi minimal {_fmt_cm(min_cm)} (tambahkan ruang jilid di sisi dalam).",
                block=_block_for_page(doc, worst.get("page")),
                severity="major",
                details={"min_margin_cm": min_cm, "pages": len(tight)},
            )
        )
    if len(rows) > 1:
        for side in ("top", "bottom"):
            vals = sorted(m[side] for m in rows)
            core = vals[len(vals) // 10 : len(vals) - len(vals) // 10 or None]  # abaikan 10% ekstrem (halaman bab, gambar)
            if core and core[-1] - core[0] > spread_cm:
                findings.append(
                    FindingDraft(
                        title=f"Margin {'atas' if side == 'top' else 'bawah'} tidak konsisten",
                        description=f"Margin {'atas' if side == 'top' else 'bawah'} bervariasi {_fmt_cm(core[0])}–{_fmt_cm(core[-1])} antar halaman/section.",
                        suggested_action="Gunakan pengaturan margin yang sama untuk seluruh isi buku.",
                        severity="minor",
                    )
                )
    med = {k: sorted(m[k] for m in rows)[len(rows) // 2] for k in ("top", "bottom", "left", "right")}
    return Outcome(findings=findings, evidence={"median_cm": med, "min_margin_cm": min_cm, "measured": len(rows)})


@handler("layout_body_font")
def layout_body_font(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or not lay.get("body_fonts"):
        return not_applicable("Font isi tidak dapat diukur.")
    fonts = lay["body_fonts"]
    max_families = int(cfg.get("max_families", 2))
    min_share = float(cfg.get("min_share", 0.02))
    # Varian tebal/miring satu keluarga dihitung sama ("Helvetica-Bold" → "Helvetica").
    fam = Counter()
    for f in fonts:
        fam[re.split(r"[-,]", str(f["value"]))[0].strip()] += f["share"]
    used = [(k, v) for k, v in fam.most_common() if v >= min_share]
    findings = []
    if len(used) > max_families:
        main = used[0][0]
        for name, share in used[max_families:]:
            sample = next((lay["samples"]["font"].get(f["value"]) for f in fonts if str(f["value"]).startswith(name)), None)
            findings.append(
                FindingDraft(
                    title=f"Jenis huruf tambahan di isi: {name} ({round(share * 100)}%)",
                    description=f"Isi naskah didominasi {main}, tetapi {name} dipakai pada {round(share * 100)}% teks isi. "
                    f"Pemakaian lebih dari {max_families} keluarga huruf di isi membuat tampilan tidak seragam.",
                    suggested_action=f"Seragamkan teks isi ke {main} (pakai style paragraf, bukan format manual).",
                    block=_block_for_sample(doc, sample),
                    details={"font": name, "share": share},
                )
            )
    return Outcome(findings=findings, evidence={"families": dict(fam.most_common(8))})


@handler("layout_body_size")
def layout_body_size(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or not lay.get("body_sizes"):
        return not_applicable("Ukuran huruf tidak dapat diukur.")
    lo, hi = cfg.get("by_type", {}).get(doc.manuscript.manuscript_type, cfg.get("range_pt", [10, 14]))
    sizes = lay["body_sizes"]
    main = sizes[0]
    findings = []
    if not (lo <= float(main["value"]) <= hi):
        findings.append(
            FindingDraft(
                title=f"Ukuran huruf isi {main['value']:g} pt di luar rentang {lo:g}–{hi:g} pt",
                description=f"Ukuran huruf isi yang dominan ({round(main['share'] * 100)}% teks) adalah {main['value']:g} pt.",
                suggested_action=f"Gunakan ukuran huruf isi {lo:g}–{hi:g} pt agar nyaman dibaca setelah dicetak.",
                block=_block_for_sample(doc, lay["samples"]["size"].get(str(main["value"]))),
                severity="major",
            )
        )
    stray = [s for s in sizes[1:] if s["share"] >= float(cfg.get("min_share", 0.05)) and abs(float(s["value"]) - float(main["value"])) >= 1]
    for s in stray:
        findings.append(
            FindingDraft(
                title=f"Ukuran huruf isi tidak seragam ({s['value']:g} pt pada {round(s['share'] * 100)}% teks)",
                description=f"Ukuran isi utama {main['value']:g} pt, tetapi sebagian teks isi memakai {s['value']:g} pt.",
                suggested_action=f"Seragamkan ukuran huruf isi menjadi {main['value']:g} pt.",
                block=_block_for_sample(doc, lay["samples"]["size"].get(str(s["value"]))),
            )
        )
    return Outcome(findings=findings, evidence={"main_pt": main["value"], "range_pt": [lo, hi], "sizes": sizes[:6]})


@handler("layout_line_spacing")
def layout_line_spacing(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay:
        return not_applicable("Spasi baris tidak dapat diukur.")
    findings = []
    if lay.get("format") == "pdf":
        ratio = lay.get("line_ratio_median")
        if ratio is None:
            return not_applicable("Spasi baris tidak dapat diukur dari PDF ini.")
        lo, hi = cfg.get("pdf_ratio_range", [1.05, 2.3])
        if not (lo <= ratio <= hi):
            findings.append(
                FindingDraft(
                    title=f"Jarak baris tidak lazim (≈ {ratio:g}× ukuran huruf)",
                    description=f"Jarak antarbaris isi sekitar {ratio:g}× ukuran huruf; rentang lazim {lo:g}–{hi:g}×.",
                    suggested_action="Atur spasi baris isi sekitar 1,0–1,5.",
                )
            )
        return Outcome(findings=findings, evidence={"ratio_median": ratio})
    spacing = lay.get("line_spacing", [])
    variants = [s for s in spacing if s["share"] >= float(cfg.get("min_share", 0.1))]
    if len(variants) > 1:
        findings.append(
            FindingDraft(
                title="Spasi baris isi tidak seragam",
                description="Teks isi memakai beberapa spasi baris: " + ", ".join(f"{v['value']} ({round(v['share'] * 100)}%)" for v in variants) + ".",
                suggested_action=f"Seragamkan spasi baris isi (mis. {variants[0]['value']}).",
                block=_block_for_sample(doc, lay["samples"]["spacing"].get(variants[1]["value"])),
            )
        )
    return Outcome(findings=findings, evidence={"spacing": spacing[:5]})


@handler("layout_alignment")
def layout_alignment(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or not lay.get("alignment"):
        return not_applicable("Perataan paragraf hanya terbaca dari DOCX.")
    al = lay["alignment"]
    body = [a for a in al if a["value"] in ("rata kiri", "rata kiri-kanan") and a["share"] >= float(cfg.get("min_share", 0.15))]
    findings = []
    if len(body) > 1:
        minority = min(body, key=lambda a: a["share"])
        findings.append(
            FindingDraft(
                title="Perataan paragraf isi tidak seragam",
                description="Paragraf isi mencampur " + " dan ".join(f"{a['value']} ({round(a['share'] * 100)}%)" for a in body) + ".",
                suggested_action="Gunakan satu perataan untuk paragraf isi (umumnya rata kiri-kanan untuk buku).",
                block=_block_for_sample(doc, lay["samples"]["align"].get(minority["value"])),
            )
        )
    return Outcome(findings=findings, evidence={"alignment": al[:4]})


@handler("layout_page_numbers")
def layout_page_numbers(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay:
        return not_applicable("Nomor halaman tidak dapat diperiksa untuk format ini.")
    pn = lay.get("page_numbers", {})
    if pn.get("present"):
        return Outcome(evidence=pn)
    return Outcome(
        findings=[
            FindingDraft(
                title="Nomor halaman tidak ditemukan",
                description="Tidak ada nomor halaman di header/footer" + (" (field PAGE)" if lay.get("format") == "docx" else " pada sebagian besar halaman") + ".",
                suggested_action="Tambahkan nomor halaman di header atau footer (Insert → Page Number).",
                severity="major",
            )
        ],
        evidence=pn,
    )


@handler("layout_image_resolution")
def layout_image_resolution(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay:
        return not_applicable("Gambar tidak dapat diperiksa untuk format ini.")
    images = lay.get("images", [])
    if not images:
        return not_applicable("Naskah tidak memuat gambar.")
    min_dpi, warn_dpi = int(cfg.get("min_dpi", 150)), int(cfg.get("recommended_dpi", 300))
    findings = []
    for im in images:
        dpi = im.get("dpi")
        if dpi is None or dpi >= warn_dpi:
            continue
        block = _block_for_page(doc, im.get("page"))
        if block is None and im.get("paragraph_no"):
            block = next((b for b in doc.blocks if b.locator.get("paragraph_no") == im["paragraph_no"]), None)
        findings.append(
            FindingDraft(
                title=f"Resolusi gambar rendah ({dpi} dpi)" if dpi < min_dpi else f"Resolusi gambar di bawah anjuran cetak ({dpi} dpi)",
                description=f"{im['name']} ({im['where']}) dicetak selebar {_fmt_cm(im['width_cm'])} dari {im['px_width']} piksel ≈ {dpi} dpi. "
                f"Anjuran cetak {warn_dpi} dpi; di bawah {min_dpi} dpi hasil cetak tampak pecah.",
                suggested_action="Ganti dengan gambar beresolusi lebih tinggi atau perkecil ukuran tampilnya.",
                block=block,
                severity="major" if dpi < min_dpi else "info",
                details=im,
            )
        )
    return Outcome(findings=_cap(findings, cfg, {}), evidence={"images": len(images), "min_dpi": min_dpi})


@handler("layout_fonts_embedded")
def layout_fonts_embedded(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or lay.get("fonts_embedded") is None:
        return not_applicable("Hanya berlaku untuk PDF.")
    fe = lay["fonts_embedded"]
    findings = [
        FindingDraft(
            title=f"Font tidak tertanam: {name}",
            description=f"Font {name} tidak disertakan dalam PDF (halaman {', '.join(map(str, pages[:6]))}). Percetakan bisa mengganti font ini.",
            suggested_action="Ekspor ulang PDF dengan opsi 'embed all fonts' / PDF/X.",
            block=_block_for_page(doc, pages[0]),
            severity="major",
        )
        for name, pages in fe.get("not_embedded", {}).items()
    ]
    return Outcome(findings=findings, evidence=fe)


@handler("layout_blank_pages")
def layout_blank_pages(doc: DocView, cfg: dict) -> Outcome:
    lay = _layout(doc)
    if not lay or lay.get("blank_pages") is None:
        return not_applicable("Hanya berlaku untuk PDF.")
    blank = lay["blank_pages"]
    pages = lay.get("pages") or 0
    # Halaman kosong tunggal sebelum bab (halaman genap) lazim; yang beruntun atau banyak ditandai.
    runs, cur = [], []
    for p in blank:
        if cur and p == cur[-1] + 1:
            cur.append(p)
        else:
            if cur:
                runs.append(cur)
            cur = [p]
    if cur:
        runs.append(cur)
    findings = [
        FindingDraft(
            title=f"{len(r)} halaman kosong beruntun (hal. {r[0]}–{r[-1]})",
            description="Ada beberapa halaman kosong berturut-turut di tengah naskah.",
            suggested_action="Hapus halaman kosong yang tidak disengaja.",
            details={"pages": r},
        )
        for r in runs
        if len(r) >= int(cfg.get("max_consecutive", 2))
    ]
    if pages and len(blank) / pages > float(cfg.get("max_ratio", 0.1)):
        findings.append(
            FindingDraft(
                title=f"Banyak halaman kosong ({len(blank)} dari {pages})",
                description="Proporsi halaman kosong tinggi untuk sebuah naskah buku.",
                suggested_action="Periksa pemisah halaman/section yang berlebihan.",
            )
        )
    return Outcome(findings=findings, evidence={"blank_pages": blank[:50]})


@handler("layout_heading_style")
def layout_heading_style(doc: DocView, cfg: dict) -> Outcome:
    chs = doc.chapters
    if len(chs) < 2:
        return not_applicable("Butuh minimal dua bab.")
    key = "font_size" if doc.summary.get("source_format") == "pdf" or chs[0].heading.locator.get("font_size") else "style"
    vals = Counter(str(c.heading.locator.get(key)) for c in chs)
    if len(vals) <= 1:
        return Outcome(evidence={key: dict(vals)})
    main = vals.most_common(1)[0][0]
    odd = [c for c in chs if str(c.heading.locator.get(key)) != main]
    return Outcome(
        findings=[
            FindingDraft(
                title=f"Format judul BAB {c.label} berbeda dari bab lain",
                description=f"Judul bab umumnya memakai {'ukuran' if key == 'font_size' else 'style'} “{main}”, "
                f"tetapi BAB {c.label} memakai “{c.heading.locator.get(key)}”.",
                suggested_action="Gunakan style judul bab yang sama (mis. Heading 1) untuk semua bab.",
                block=c.heading,
            )
            for c in odd
        ],
        evidence={key: dict(vals)},
    )


@handler("isbn_final_manuscript")
def isbn_final_manuscript(doc: DocView, cfg: dict) -> Outcome:
    """Pasal 10 ayat (3) huruf c: yang diajukan adalah naskah akhir — tidak boleh ada teks sementara."""
    out = placeholder_text(doc, cfg)
    if out.findings:
        return Outcome(observed="fail", findings=out.findings, evidence={"placeholders": len(out.findings)},
                       explanation=f"Ditemukan {len(out.findings)} teks sementara/placeholder; naskah belum final.")
    return Outcome(observed="pass", evidence={"placeholders": 0}, explanation="Tidak ditemukan teks sementara; naskah tampak final.")


NOT_ELIGIBLE = [
    ("skripsi", "Skripsi"), ("tesis", "Tesis"), ("disertasi", "Disertasi"), ("tugas akhir", "Tugas akhir"),
    ("laporan kkn", "Laporan KKN"), ("laporan kuliah kerja nyata", "Laporan KKN"), ("diktat", "Diktat"),
    ("modul praktikum", "Modul praktikum"), ("panduan praktikum", "Panduan praktikum"), ("petunjuk praktikum", "Petunjuk praktikum"),
    ("laporan penelitian", "Laporan penelitian (format asli)"), ("laporan tahunan", "Laporan internal"), ("policy brief", "Policy brief"),
    ("executive summary", "Executive summary"), ("buku harian", "Buku harian"), ("catatan harian", "Catatan harian"),
    ("diari", "Buku diari"), ("book chapter", "Book chapter"), ("policy paper", "Policy paper"), ("laporan internal", "Laporan internal"),
    ("tugas kuliah", "Tugas kuliah"), ("tugas sekolah", "Tugas sekolah"), ("modul ajar internal", "Modul internal"),
]


@handler("isbn_publication_type")
def isbn_publication_type(doc: DocView, cfg: dict) -> Outcome:
    """Indikasi jenis terbitan yang lazimnya tidak diberi ISBN (Pasal 2: harus untuk umum; Juknis layanan ISBN)."""
    # Hanya baris pendek (judul/keterangan) di halaman awal; kalimat panjang di kata pengantar diabaikan.
    front = norm(" ".join(b.text for b in doc.front_matter[:40] if len(b.text) <= 120))
    hits = [(k, label) for k, label in cfg.get("indicators", NOT_ELIGIBLE) if re.search(rf"\b{re.escape(k)}\b", front)]
    if not hits:
        return Outcome(observed="pass", explanation="Tidak ada indikasi jenis terbitan yang lazimnya tidak diberi ISBN di halaman awal.")
    labels = sorted({label for _, label in hits})
    return Outcome(
        observed="fail",
        evidence={"indicators": labels},
        explanation=f"Halaman awal menyebut: {', '.join(labels)}.",
        findings=[
            FindingDraft(
                title=f"Kemungkinan jenis terbitan tidak diberi ISBN: {', '.join(labels)}",
                description="ISBN diberikan untuk terbitan yang disebarluaskan dan dapat diakses umum (Perpusnas 11/2025 Pasal 2). "
                "Jenis karya ini dalam format aslinya tidak diberikan ISBN (Juknis Layanan ISBN 4.5.2).",
                suggested_action="Pastikan naskah sudah diolah menjadi buku untuk umum (bukan format laporan/tugas akademik asli).",
            )
        ],
    )


LIMITED_PHRASES = [
    "dicetak terbatas", "cetakan terbatas", "edisi terbatas", "jumlah terbatas", "kalangan terbatas", "kalangan sendiri",
    "kalangan internal", "untuk kalangan", "tidak diperjualbelikan", "tidak untuk diperjualbelikan", "tidak untuk dijual",
    "tidak dijual", "tidak dikomersilkan", "tidak dikomersialkan", "hanya untuk keluarga", "untuk keluarga besar",
    "untuk lingkungan sendiri", "khusus anggota", "untuk anggota", "kenang-kenangan", "kenang kenangan", "cenderamata",
    "cinderamata", "souvenir", "suvenir", "dibagikan secara gratis", "dibagikan kepada", "untuk dibagikan", "hadiah pernikahan",
    "buku tahunan", "yearbook", "purnabakti", "purna bakti",
]
COMMERCIAL_TYPES = ["fiksi", "biografi", "buku_anak", "kompilasi"]
MEMOIR_MARKERS = ["autobiografi", "memoar", "memoir", "perjalanan hidup", "kisah hidup", "riwayat hidup", "catatan harian", "buku harian"]
FAMILY_PHRASES = ["anak cucu", "anak dan cucu", "cucu cucuku", "keturunanku", "generasi penerus keluarga", "keluarga besar",
                  "warisan untuk keluarga", "kenangan keluarga", "untuk keluarga"]
RE_PRICE = re.compile(r"\b(?:harga\s*:?\s*)?rp\.?\s?\d{2,3}(?:[.,]\d{3})+", re.IGNORECASE)
COMMERCIAL_EVIDENCE = ["harga jual", "harga eceran", "tersedia di toko", "dapat dibeli", "toko buku", "marketplace", "shopee", "tokopedia",
                       "endorsement", "apa kata mereka", "testimoni", "kata mereka tentang buku ini"]
CONTRIBUTOR_LABELS = ["editor", "penyunting", "tata letak", "layout", "desain sampul", "perancang sampul", "proofreader",
                      "korektor", "penyelaras", "ilustrator", "penata letak"]
RE_DEGREE = re.compile(r"^(?:[a-z]{1,4}\.)+[a-z]{0,4}\.?$|^(?:dr|ir|drs|dra|h|hj|prof)\.?$", re.IGNORECASE)


def _person_tokens(name: str) -> list[str]:
    """Nama tanpa gelar: 'Yanto Nius Gulo S.Ak., M.M.' -> ['yanto', 'nius', 'gulo']."""
    name = name.split(",")[0]
    return [norm(t) for t in name.split() if not RE_DEGREE.match(t.strip()) and len(norm(t)) >= 2]


def _labelled_names(doc: DocView, labels: list[str], max_lines: int = 5) -> list[tuple[Blk, str]]:
    """Nama di bawah/di samping label halaman balik judul, mis. 'Editor :' diikuti baris nama."""
    out: list[tuple[Blk, str]] = []
    front = doc.front_matter[:120]
    for i, b in enumerate(front):
        n = norm(b.text)
        label = next((lb for lb in labels if n == lb or n.startswith(lb + " ")), None)
        if not label or ":" not in b.text:  # label halaman balik judul, bukan tanda tangan "Penulis,"
            continue
        rest = b.text.split(":", 1)[1].strip() if ":" in b.text else ""
        if rest:
            out.append((b, rest))
            continue
        for nb in front[i + 1 : i + 1 + max_lines]:
            t = nb.text.strip().lstrip("\u2060")
            nn = norm(t)
            if not nn or ":" in t or any(nn.startswith(x) for x in ("penerbit", "pt ", "jl ", "hak cipta", "copyright", "isbn", *labels)):
                break
            out.append((nb, t))
    return out


def _private_memoir(doc: DocView) -> dict[str, Any] | None:
    """Pola yang dinilai verifikator Perpusnas sebagai terbitan kalangan sendiri: autobiografi/memoar orang pribadi yang
    disusun lingkup keluarga (penyunting/tim bermarga sama dengan penulis, dipersembahkan untuk keluarga)."""
    front_blocks = [b for b in doc.front_matter[:80] if len(b.text) <= 200]
    front = norm(" ".join(b.text for b in front_blocks))
    pre = doc.find_section(["kata pengantar", "prakata", "pengantar", "sekapur sirih", "persembahan"], allow_paragraph=False)
    preface = norm(" ".join(b.text for b in doc.section_of(pre))) if pre else ""
    markers = [m for m in MEMOIR_MARKERS if re.search(rf"\b{m}\b", front + " " + preface)]
    if not markers:
        return None
    authors = list(doc.manuscript.authors) or [n for _, n in _labelled_names(doc, ["penulis", "oleh", "karya"], max_lines=1)]
    author_tokens = [_person_tokens(a) for a in authors]
    author_tokens = [t for t in author_tokens if t]
    # Penulis = tokoh yang dikisahkan: autobiografi, atau nama penulis tercantum di judul/subjudul.
    self_story = "autobiografi" in markers or "perjalanan hidup penulis" in preface or any(
        len(t) >= 2 and " ".join(t) in front for t in author_tokens)
    if not self_story:
        return None
    family_names = []
    surnames = {t[-1] for t in author_tokens if len(t) >= 2 and len(t[-1]) >= 3}
    for b, name in _labelled_names(doc, CONTRIBUTOR_LABELS):
        tokens = _person_tokens(name)
        if tokens and surnames & set(tokens) and (b, name) not in family_names:
            family_names.append((b, name))
    family_words = [p for p in FAMILY_PHRASES if re.search(rf"\b{p}\b", front + " " + preface)]
    # Bukti komersial dicari di halaman awal, judul bagian, dan bagian setelah bab terakhir (sampul belakang), bukan narasi.
    outer = list(doc.front_matter) + list(doc.headings)
    if doc.chapters:
        last = doc.chapters[-1]
        outer += [b for b in doc.blocks[last.heading.index + 1 :] if b not in last.blocks]
    outer_text = " ".join(b.text for b in outer if len(b.text) <= 400)
    commercial = [p for p in COMMERCIAL_EVIDENCE if re.search(rf"\b{p}\b", norm(outer_text))]
    if RE_PRICE.search(outer_text):
        commercial.append("harga (Rp)")
    return {"markers": markers, "family_contributors": family_names, "family_phrases": family_words, "commercial_evidence": commercial,
            "surnames": sorted(surnames)}


@handler("isbn_public_distribution")
def isbn_public_distribution(doc: DocView, cfg: dict) -> Outcome:
    """Pasal 2 ayat (2): terbitan disebarluaskan & dapat diakses umum. Juknis 4.5.1.3 butir 6–9: novel/antologi,
    biografi, pengembangan diri, buku anak harus dikomersilkan/ditujukan untuk dijual ke masyarakat umum; 4.5.2.3:
    karya yang dicetak terbatas untuk komunitas tertentu tidak diberi ISBN."""
    phrases = cfg.get("limited_phrases", LIMITED_PHRASES)
    # Hanya halaman awal (termasuk kata pengantar) dan bagian setelah bab terakhir: hindari kata "terbatas" di dalam cerita.
    scope = list(doc.front_matter)
    pre = doc.find_section(["kata pengantar", "prakata", "pengantar", "sekapur sirih"], allow_paragraph=False)
    if pre:
        scope += doc.section_of(pre)
    if doc.chapters:
        last = doc.chapters[-1]
        scope += [b for b in doc.blocks[last.heading.index + 1 :] if b not in last.blocks]
    hits = []
    for b in scope:
        n = norm(b.text)
        for p in phrases:
            if re.search(rf"\b{re.escape(norm(p))}\b", n):
                hits.append((b, p))
                break
    declared = (doc.manuscript.metadata or {}).get("distribution")
    mtype = doc.manuscript.manuscript_type
    commercial = mtype in cfg.get("commercial_types", COMMERCIAL_TYPES)
    ev = {"declared": declared, "manuscript_type": mtype, "commercial_required": commercial, "requires_confirmation": True,
          "phrases": [p for _, p in hits][:10]}
    if hits:
        b, p = hits[0]
        return Outcome(
            observed="fail", evidence=ev,
            explanation=f"Naskah menyatakan peredaran terbatas (“{p}”). ISBN hanya untuk terbitan yang tersedia bagi masyarakat umum.",
            findings=[FindingDraft(
                title=f"Naskah menyatakan peredaran terbatas: “{p}”",
                description="Terbitan yang dicetak terbatas/hanya untuk kalangan tertentu tidak diberikan ISBN "
                "(Perpusnas 11/2025 Pasal 2 ayat (2); Juknis Layanan ISBN 4.5 dan 4.5.2.3).",
                suggested_action="Hapus pernyataan tersebut bila buku akan dijual/diedarkan untuk umum; bila memang terbatas, ISBN tidak dapat diajukan.",
                block=b, span=None, details={"phrase": p},
            )],
        )
    memoir = _private_memoir(doc)
    if memoir:
        ev["private_memoir"] = {k: v for k, v in memoir.items() if k != "family_contributors"} | {
            "family_contributors": [n for _, n in memoir["family_contributors"]]}
    if memoir and (memoir["family_contributors"] or memoir["family_phrases"]) and not memoir["commercial_evidence"]:
        why = []
        if memoir["family_contributors"]:
            why.append("tim penyusun bermarga sama dengan penulis (" + ", ".join(n for _, n in memoir["family_contributors"][:3]) + ")")
        if memoir["family_phrases"]:
            why.append("ditujukan untuk keluarga (" + ", ".join(memoir["family_phrases"][:3]) + ")")
        anchor = memoir["family_contributors"][0][0] if memoir["family_contributors"] else None
        return Outcome(
            observed="fail", evidence=ev,
            explanation="Autobiografi/memoar pribadi yang disusun di lingkup keluarga: " + "; ".join(why) + ". Perpusnas menilai terbitan "
            "seperti ini sebagai terbitan kalangan sendiri yang tidak perlu ISBN, walaupun dinyatakan akan dijual. Biografi hanya diberi ISBN "
            "bila dikomersilkan untuk masyarakat umum (Juknis 4.5.1.3 butir 7).",
            findings=[FindingDraft(
                title="Memoar pribadi berisiko ditolak sebagai terbitan kalangan sendiri",
                description="Penanda: " + ", ".join(memoir["markers"][:3]) + "; " + "; ".join(why) + ". Tidak ada bukti komersial di naskah "
                "(harga, endorsement/testimoni pihak luar, keterangan toko/marketplace). Penolakan Perpusnas untuk kasus ini: \u201cBuku yang "
                "diterbitkan terbatas/untuk kalangan sendiri ... tidak perlu memintakan ISBN.\u201d",
                suggested_action="Bila buku memang untuk keluarga/kenangan, terbitkan tanpa ISBN. Bila akan dijual umum: libatkan penyunting "
                "penerbit di luar keluarga, cantumkan harga dan blurb/endorsement pihak luar di sampul belakang, dan siapkan link penjualan "
                "publik sebelum mengajukan ulang.",
                block=anchor, span=None, details={"markers": memoir["markers"], "surnames": memoir["surnames"]},
            )],
        )
    if declared == "terbatas":
        return Outcome(observed="fail", evidence=ev,
                       explanation="Peredaran dinyatakan cetak terbatas/kalangan tertentu; terbitan ini tidak diberikan ISBN.",
                       findings=[FindingDraft(title="Peredaran buku terbatas",
                                              description="ISBN hanya untuk terbitan yang disebarluaskan dan dapat diakses masyarakat umum.",
                                              suggested_action="Ajukan ISBN hanya bila buku akan dijual/diedarkan untuk umum.")])
    if declared == "gratis_umum" and commercial:
        return Outcome(observed="fail", evidence=ev,
                       explanation="Untuk jenis ini Juknis mensyaratkan buku dikomersilkan/ditujukan untuk dijual kepada masyarakat umum (4.5.1.3).",
                       findings=[FindingDraft(title="Jenis terbitan ini harus dijual untuk umum",
                                              description="Novel/antologi, biografi, pengembangan diri, dan buku anak diberi ISBN bila "
                                              "dikomersilkan/ditujukan untuk dijual kepada masyarakat umum (Juknis 4.5.1.3 butir 6–9).",
                                              suggested_action="Rencanakan penjualan umum (website penerbit, toko, marketplace).")])
    if declared in ("dijual_umum", "gratis_umum"):
        label = "dijual untuk masyarakat umum" if declared == "dijual_umum" else "dapat diakses umum secara gratis"
        return Outcome(observed="pass", evidence=ev, explanation=f"Peredaran dinyatakan {label}; tidak ada pernyataan peredaran terbatas di naskah.")
    return Outcome(observed="unknown", evidence=ev,
                   explanation="Naskah tidak menyatakan peredaran terbatas, tetapi rencana peredaran belum dikonfirmasi. "
                   + ("Jenis ini harus dijual untuk umum." if commercial else "Pilih rencana peredaran buku."))
