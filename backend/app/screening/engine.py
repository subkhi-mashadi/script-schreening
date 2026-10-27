"""Eksekusi rule set terhadap satu dokumen dan keputusan jalur ISBN/administrasi (PRD §8.2)."""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.screening.docview import DocView
from app.screening.handlers import HANDLERS, FindingDraft

log = logging.getLogger(__name__)

ENGINE_VERSION = "screening-engine/1.0"
OFFICIAL = ("official_regulation", "official_procedure")


@dataclass
class RuleResult:
    rule: dict[str, Any]  # snapshot aturan
    applicable: bool = True
    observed: str | None = None
    findings: list[FindingDraft] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str | None = None
    error: str | None = None

    @property
    def code(self) -> str:
        return self.rule["rule_code"]

    @property
    def is_compliance(self) -> bool:
        return self.rule["track"] == "compliance"


def run_rules(doc: DocView, items: list[dict[str, Any]]) -> list[RuleResult]:
    """`items`: snapshot aturan (dengan `enabled` & `override_config_json` opsional), urut eksekusi."""
    results = []
    for snap in sorted(items, key=lambda s: (s.get("execution_order", 100), s["rule_code"])):
        if snap.get("enabled") is False:
            continue
        rr = RuleResult(rule=snap)
        types = snap.get("applies_to_types")
        if types and doc.manuscript.manuscript_type not in types:
            rr.applicable = False
            rr.explanation = "Tidak berlaku untuk jenis naskah ini."
            results.append(rr)
            continue
        fn = HANDLERS.get(snap["engine_key"])
        if fn is None:
            rr.error = f"Handler '{snap['engine_key']}' tidak dikenal."
            results.append(rr)
            continue
        cfg = {**(snap.get("config_json") or {}), **(snap.get("override_config_json") or {})}
        try:
            out = fn(doc, cfg)
        except Exception as exc:  # satu aturan gagal tidak menggagalkan aturan lain
            log.exception("Aturan %s gagal", snap["rule_code"])
            rr.error = f"{exc.__class__.__name__}: {exc}"[:500]
            results.append(rr)
            continue
        rr.applicable, rr.observed, rr.findings = out.applicable, out.observed, out.findings if out.applicable else []
        rr.evidence, rr.explanation = out.evidence, out.explanation
        results.append(rr)
    return results


def compliance_status(rr: RuleResult) -> str:
    """Status per aturan kepatuhan. Aturan resmi yang belum diverifikasi tidak pernah memberi pass/fail resmi."""
    if not rr.applicable:
        return "not_applicable"
    if rr.error:
        return "incomplete"
    if rr.observed == "unknown" or rr.rule.get("requires_human_verification"):
        return "needs_verification"
    if rr.rule.get("verification_status") != "verified":
        return "needs_verification"
    return "pass" if rr.observed == "pass" else "fail"


def compliance_explanation(rr: RuleResult, status: str) -> str:
    base = rr.explanation or ""
    if status == "needs_verification" and rr.rule.get("verification_status") != "verified" and rr.observed in ("pass", "fail"):
        label = "resmi" if rr.rule.get("authority_type") in OFFICIAL else "kebijakan"
        return f"{base} Aturan {label} ini belum diverifikasi pemilik proses, sehingga hasil belum dapat dinyatakan lulus/gagal.".strip()
    return base


def is_attachment(rule: dict[str, Any]) -> bool:
    """Dokumen pengajuan di luar naskah (surat permohonan, pernyataan, izin): daftar persiapan, bukan penentu kelayakan."""
    return rule.get("engine_key") == "human_evidence"


def isbn_overall(results: list[RuleResult], extraction_ok: bool) -> tuple[str, dict[str, int]]:
    """Kelayakan naskah untuk diajukan ISBN.

    FAIL  : ada syarat wajib (blocking) yang tidak terpenuhi;
    INCOMPLETE : pembacaan tidak lengkap atau aturan gagal dijalankan;
    NEEDS_VERIFICATION : ada syarat wajib yang aturannya belum diverifikasi;
    PASS  : semua syarat wajib yang dapat diperiksa dari naskah terpenuhi.
    Peringatan (non-blocking) dan dokumen pengajuan tidak mengubah status.
    """
    if not extraction_ok:
        return "INCOMPLETE", {}
    # Hasil "tidak dapat dipastikan dari berkas" (mis. jumlah halaman draf A4) dicatat, bukan penentu.
    rows = [(r, compliance_status(r)) for r in results if r.is_compliance and not is_attachment(r.rule)
            and (r.observed != "unknown" or r.evidence.get("requires_confirmation"))]
    counts: dict[str, int] = {}
    for _, st in rows:
        counts[st] = counts.get(st, 0) + 1
    if any(st == "fail" and r.rule.get("blocking") for r, st in rows):
        return "FAIL", counts
    if any(st == "incomplete" for _, st in rows):
        return "INCOMPLETE", counts
    if any(st == "needs_verification" and r.rule.get("blocking") for r, st in rows):
        return "NEEDS_VERIFICATION", counts
    if rows and all(st == "not_applicable" for _, st in rows):
        return "NOT_APPLICABLE", counts
    return "PASS", counts
