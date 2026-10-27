"""Klasifikasi jenis terbitan secara deterministik untuk tahap 1 (kelayakan ISBN).

Mengikuti ruas formulir pengajuan ISBN dalam Petunjuk Teknis Layanan ISBN Perpusnas (27-01-2023), bagian 5
(Kelompok Pembaca, Jenis Pustaka, Kategori Terbitan, Penelitian/Non penelitian, Media, kategori Lepas/Berjilid)
dan jenis terbitan bagian 4.3/4.5. Setiap hasil disertai alasan (sinyal terukur) dan tingkat keyakinan.
"""

import re
from typing import Any

from app.screening.docview import DocView, norm
from app.screening.handlers import _citations, _references

SOURCE = "Petunjuk Teknis (Juknis) Layanan ISBN Perpusnas (27-01-2023), bagian 4.3, 4.5, dan 5 (ruas formulir)"

TYPE_LABELS = {
    "buku_anak": "Buku anak",
    "fiksi": "Karya sastra (fiksi)",
    "buku_ajar": "Buku ajar",
    "buku_ilmiah": "Buku ilmiah / monograf",
    "referensi": "Buku referensi",
    "kompilasi": "Bunga rampai / antologi",
    "prosiding": "Prosiding",
    "nonfiksi_umum": "Buku umum / populer (nonfiksi)",
    "biografi": "Buku biografi / memoar",
}

LEARNING = ["tujuan pembelajaran", "capaian pembelajaran", "kompetensi dasar", "indikator pembelajaran", "rangkuman",
            "latihan soal", "soal latihan", "uji kompetensi", "evaluasi", "tugas mandiri", "refleksi", "glosarium"]
RESEARCH = ["metode penelitian", "metodologi penelitian", "hasil penelitian", "responden", "hipotesis", "tinjauan pustaka",
            "kajian pustaka", "kerangka teori", "teknik analisis data", "populasi dan sampel", "abstrak", "abstract"]
PROCEEDINGS = ["prosiding", "seminar nasional", "seminar internasional", "konferensi nasional", "pemakalah"]
ANTHOLOGY = ["bunga rampai", "antologi", "kumpulan cerpen", "kumpulan puisi", "kumpulan tulisan", "kumpulan esai"]
REFERENCE = ["kamus", "ensiklopedia", "ensiklopedi", "atlas", "direktori"]
CHILD = ["buku anak", "cerita anak", "bacaan anak", "dongeng", "fabel", "buku cerita bergambar", "untuk anak", "adik-adik"]
BIOGRAPHY = ["autobiografi", "biografi", "memoar", "memoir", "perjalanan hidup", "kisah hidup", "riwayat hidup", "kisah nyata perjalanan"]
TRANSLATION = ["diterjemahkan dari", "judul asli", "alih bahasa", "penerjemah", "translated by", "original title", "terjemahan dari"]
RE_VOLUME = re.compile(r"\b(jilid|volume|vol\.)\s+([ivxlcdm]+|\d+)\b", re.IGNORECASE)
RE_QUOTE_START = re.compile(r'^\s*[“"‘\'«]')
RE_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+")


def _hits(text: str, phrases: list[str]) -> list[str]:
    return [p for p in phrases if re.search(rf"\b{re.escape(p)}\b", text)]


def classify(doc: DocView, layout: dict[str, Any] | None, source_format: str, publisher_category: str = "Swasta") -> dict[str, Any]:
    blocks = [b for b in doc.blocks if not b.is_toc]
    front = norm(" ".join(b.text for b in doc.front_matter[:60] if len(b.text) <= 160))
    heads = norm(" | ".join(b.text for b in doc.headings))
    body_paras = [b for b in blocks if b.type == "paragraph" and len(b.text) >= 2]
    words = sum(len(b.text.split()) for b in blocks)

    # --- sinyal terukur
    dialog = sum(1 for b in body_paras if RE_QUOTE_START.match(b.text) or b.text.count("“") >= 1)
    dialog_ratio = round(dialog / len(body_paras), 3) if body_paras else 0.0
    sentences = [s for b in body_paras for s in RE_SENTENCE.findall(b.text)]
    avg_sentence = round(sum(len(s.split()) for s in sentences) / len(sentences), 1) if sentences else 0.0
    _, refs = _references(doc)
    cites = len(_citations(doc))
    learning = _hits(heads, LEARNING)
    research = _hits(heads + " " + front, RESEARCH)
    proceedings = _hits(front + " " + heads[:2000], PROCEEDINGS)
    anthology = _hits(front, ANTHOLOGY)
    reference = _hits(front[:600], REFERENCE)
    child_words = _hits(front + " " + heads, CHILD)
    translation = _hits(front, TRANSLATION)
    pre = doc.find_section(["kata pengantar", "prakata", "pengantar", "sekapur sirih"], allow_paragraph=False)
    preface = norm(" ".join(b.text for b in doc.section_of(pre))) if pre else ""
    biography = _hits(front + " " + preface + " " + heads, BIOGRAPHY)
    all_words = norm(" ".join(b.text for b in blocks)).split()
    first_person = round((all_words.count("aku") + all_words.count("saya")) / max(1, len(all_words)) * 1000, 1)
    volume = RE_VOLUME.search(" ".join(b.text for b in doc.front_matter[:30] if len(b.text) <= 120))
    body_pt = None
    images = 0
    if layout and layout.get("supported"):
        sizes = layout.get("body_sizes") or []
        body_pt = float(sizes[0]["value"]) if sizes else None
        images = len(layout.get("images") or [])
    images_per_kw = round(images / max(1, words / 1000), 2)

    signals = {
        "kata": words, "porsi_dialog": dialog_ratio, "rata_kata_per_kalimat": avg_sentence, "sitasi": cites,
        "entri_daftar_pustaka": len(refs), "penanda_buku_ajar": learning, "penanda_penelitian": research,
        "penanda_prosiding": proceedings, "penanda_antologi": anthology, "penanda_referensi": reference,
        "penanda_anak": child_words, "penanda_terjemahan": translation, "ukuran_huruf_isi_pt": body_pt,
        "penanda_biografi": biography, "orang_pertama_per_1000_kata": first_person,
        "gambar_per_1000_kata": images_per_kw,
    }

    # --- jenis pustaka
    fiction = dialog_ratio >= 0.12 and cites < 3 and len(learning) < 2 and len(research) < 2
    pustaka = {
        "value": "Fiksi" if fiction else "Non fiksi",
        "confidence": "tinggi" if (fiction and dialog_ratio >= 0.25) or (not fiction and (cites >= 5 or refs)) else "sedang",
        "reasons": [f"{round(dialog_ratio * 100)}% paragraf berupa dialog", f"{cites} sitasi, {len(refs)} entri daftar pustaka"],
    }

    # --- kelompok pembaca
    child_points = []
    if child_words:
        child_points.append(f"penanda: {', '.join(child_words[:3])}")
    if avg_sentence and avg_sentence <= 10:
        child_points.append(f"kalimat pendek (rata-rata {str(avg_sentence).replace('.', ',')} kata)")
    if words and words <= 15000:
        child_points.append(f"naskah pendek ({words:,} kata)".replace(",", "."))
    if body_pt and body_pt >= 13.5:
        child_points.append(f"huruf isi besar ({body_pt:g} pt)")
    if images_per_kw >= 0.3:
        child_points.append(f"bergambar ({images} gambar)")
    is_child = bool(child_words) or len(child_points) >= 3
    adult_points = []
    if research or cites >= 5:
        adult_points.append("bersifat ilmiah/penelitian")
    if biography and not fiction:
        adult_points.append("biografi/memoar")
    if avg_sentence >= 16:
        adult_points.append(f"kalimat panjang (rata-rata {str(avg_sentence).replace('.', ',')} kata)")
    if is_child:
        pembaca = {"value": "Anak", "confidence": "tinggi" if len(child_points) >= 4 or child_words else "sedang", "reasons": child_points}
    elif adult_points:
        pembaca = {"value": "Dewasa", "confidence": "sedang", "reasons": adult_points}
    else:
        pembaca = {"value": "Semua umur", "confidence": "rendah", "reasons": ["tidak ada penanda khusus anak maupun dewasa"]}

    # --- jenis terbitan (urutan aturan = prioritas)
    def pick(t: str, conf: str, why: list[str]) -> dict[str, Any]:
        return {"value": t, "label": TYPE_LABELS[t], "confidence": conf, "reasons": why}

    if proceedings:
        jenis = pick("prosiding", "tinggi", [f"penanda: {', '.join(proceedings)}"])
    elif reference:
        jenis = pick("referensi", "sedang", [f"penanda: {', '.join(reference)}"])
    elif len(learning) >= 2:
        jenis = pick("buku_ajar", "tinggi" if len(learning) >= 3 else "sedang", [f"subbab pembelajaran: {', '.join(learning[:4])}"])
    elif len(research) >= 2 or (cites >= 10 and refs):
        jenis = pick("buku_ilmiah", "tinggi" if len(research) >= 2 and refs else "sedang",
                     [f"penanda penelitian: {', '.join(research[:4]) or '-'}", f"{cites} sitasi, {len(refs)} entri pustaka"])
    elif biography and not fiction:
        jenis = pick("biografi", "tinggi" if len(biography) >= 2 or first_person >= 20 else "sedang",
                     [f"penanda: {', '.join(biography[:3])}", f"kata ganti orang pertama {str(first_person).replace('.', ',')} per 1.000 kata"])
    elif anthology:
        jenis = pick("kompilasi", "sedang", [f"penanda: {', '.join(anthology)}"])
    elif is_child:
        jenis = pick("buku_anak", pembaca["confidence"], [*child_points, f"jenis pustaka: {pustaka['value'].lower()}"])
    elif fiction:
        jenis = pick("fiksi", pustaka["confidence"], pustaka["reasons"])
    else:
        jenis = pick("nonfiksi_umum", "rendah", ["tidak ada penanda jenis khusus; nonfiksi umum/populer"])

    research_kind = {
        "value": "Penelitian" if len(research) >= 2 else "Non penelitian",
        "confidence": "sedang" if research else "tinggi",
        "reasons": [f"penanda: {', '.join(research[:4])}"] if research else ["tidak ada penanda hasil penelitian"],
    }
    return {
        "source": SOURCE,
        "jenis_terbitan": jenis,
        "jenis_pustaka": pustaka,
        "kelompok_pembaca": pembaca,
        "kategori_buku": {"value": f"Berjilid ({volume.group(0)})" if volume else "Lepas", "confidence": "sedang" if volume else "tinggi",
                          "reasons": [f"penanda '{volume.group(0)}' di halaman awal"] if volume else ["tidak ada nomor jilid di halaman awal"]},
        "terjemahan": {"value": "Ya" if translation else "Tidak", "confidence": "tinggi" if translation else "sedang",
                       "reasons": [f"penanda: {', '.join(translation)}"] if translation else ["tidak ada keterangan judul asli/penerjemah"]},
        "penelitian": research_kind,
        "kategori_penerbit": {"value": publisher_category, "confidence": "tinggi", "reasons": ["pengaturan penerbit"]},
        "peredaran": _distribution(doc),
        "media": {"value": "Buku (cetak)" if source_format == "docx" else "Buku (cetak) / PDF", "confidence": "rendah",
                  "reasons": ["ditentukan dari format berkas; pilih PDF/EPUB bila terbit elektronik"]},
        "signals": signals,
    }


def _distribution(doc: DocView) -> dict[str, Any]:
    from app.core.constants import DISTRIBUTION_OPTIONS

    declared = (doc.manuscript.metadata or {}).get("distribution")
    if declared in DISTRIBUTION_OPTIONS:
        return {"value": DISTRIBUTION_OPTIONS[declared], "confidence": "tinggi", "reasons": ["dinyatakan pengguna"]}
    return {"value": "Belum dikonfirmasi", "confidence": "rendah", "reasons": ["rencana peredaran tidak tercantum di naskah"]}
