"""Skor editorial otomatis (PRD §11). Fungsi murni: input sama → hasil sama.

Per kriteria i (metode `deduction`):
    s_i = max(0, 100 − Σ_r min(n_r × potongan_r, batas_r))
dengan n_r = jumlah temuan aturan r yang dipetakan ke kriteria i, tidak termasuk temuan yang
ditandai FALSE_POSITIVE oleh editor dan temuan bertingkat INFO.

Total:  S = Σ w_i s_i / Σ w_i  atas kriteria yang dapat dinilai.
Kriteria yang semua aturannya tidak berlaku dikeluarkan dari penyebut (normalisasi eksplisit
lewat `exclude_not_applicable`), bukan diberi nilai penuh. Bila cakupan bobot < ambang, skor
total tidak diterbitkan.
"""

from dataclasses import dataclass, field
from typing import Any

EXCLUDED_VERIFICATION = {"FALSE_POSITIVE"}


@dataclass
class RuleInput:
    rule_code: str
    title: str
    criterion_code: str | None
    deduction_per_finding: float
    max_deduction: float
    applicable: bool
    error: bool
    findings: list[dict[str, Any]]  # {severity, verification_status, track}


@dataclass
class CriterionResult:
    code: str
    name: str
    weight: float
    status: str  # scored | not_applicable | unscorable
    score: float | None = None
    contribution: float | None = None
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    criterion_id: Any = None


@dataclass
class ScoreOutcome:
    criteria: list[CriterionResult]
    total: float | None
    coverage: float
    scored_count: int
    applicable_count: int
    editorial_status: str
    reasons: list[str]


def _counted(f: dict[str, Any]) -> bool:
    return f.get("verification_status") not in EXCLUDED_VERIFICATION and f.get("severity") != "info"


def score(
    criteria: list[dict[str, Any]],
    rules: list[RuleInput],
    thresholds: dict[str, Any],
    min_coverage: float,
    extraction_ok: bool,
    open_findings: list[dict[str, Any]],
) -> ScoreOutcome:
    if not extraction_ok:
        return ScoreOutcome(
            criteria=[CriterionResult(c["code"], c["name"], c["weight"], "unscorable", explanation="Pembacaan berkas tidak lengkap.",
                                      criterion_id=c.get("id")) for c in criteria],
            total=None, coverage=0.0, scored_count=0, applicable_count=len(criteria),
            editorial_status="NOT_SCORABLE", reasons=["EXTRACTION_INCOMPLETE"],
        )

    results: list[CriterionResult] = []
    for c in criteria:
        mapped = [r for r in rules if r.criterion_code == c["code"]]
        cr = CriterionResult(c["code"], c["name"], float(c["weight"]), "scored", criterion_id=c.get("id"))
        if not mapped:
            cr.status, cr.explanation = "unscorable", "Tidak ada aturan pada rule set yang mengukur kriteria ini."
        elif any(r.error for r in mapped if r.applicable):
            failed = [r.rule_code for r in mapped if r.error]
            cr.status, cr.explanation = "unscorable", f"Aturan {', '.join(failed)} gagal dijalankan; kriteria tidak dinilai."
        elif not any(r.applicable for r in mapped):
            cr.status, cr.explanation = "not_applicable", "Semua aturan kriteria ini tidak berlaku untuk jenis naskah; dikeluarkan dari perhitungan."
        else:
            breakdown, total_ded = [], 0.0
            for r in mapped:
                if not r.applicable:
                    breakdown.append({"rule_code": r.rule_code, "title": r.title, "applicable": False})
                    continue
                n = sum(1 for f in r.findings if _counted(f))
                ded = min(n * r.deduction_per_finding, r.max_deduction)
                total_ded += ded
                breakdown.append({
                    "rule_code": r.rule_code, "title": r.title, "applicable": True, "findings_counted": n,
                    "deduction_per_finding": r.deduction_per_finding, "max_deduction": r.max_deduction, "deduction": round(ded, 2),
                })
            cr.score = round(max(0.0, 100.0 - total_ded), 2)
            cr.details = {"rules": breakdown, "total_deduction": round(total_ded, 2)}
            cr.explanation = f"100 − {round(total_ded, 2)} poin potongan dari {sum(b.get('findings_counted', 0) for b in breakdown)} temuan."
        results.append(cr)

    exclude_na = thresholds.get("exclude_not_applicable", True)
    considered = [r for r in results if not (exclude_na and r.status == "not_applicable")]
    scored = [r for r in considered if r.status == "scored"]
    w_considered = sum(r.weight for r in considered)
    w_scored = sum(r.weight for r in scored)
    coverage = round(100.0 * w_scored / w_considered, 2) if w_considered else 0.0
    for r in scored:
        r.contribution = round(r.weight * r.score / w_scored, 4) if w_scored else None

    reasons: list[str] = []
    if not scored or coverage < float(min_coverage):
        reasons.append("LOW_COVERAGE")
        return ScoreOutcome(results, None, coverage, len(scored), len(considered), "NEEDS_VERIFICATION", reasons)

    total = round(sum(r.weight * r.score for r in scored) / w_scored, 2)
    if total >= thresholds.get("pass", 85):
        status = "PASS_RECOMMENDED"
    elif total >= thresholds.get("minor_revision", 70):
        status = "MINOR_REVISION"
    elif total >= thresholds.get("major_revision", 55):
        status = "MAJOR_REVISION"
    else:
        status = "SUBSTANTIAL_REWORK"

    open_ed = [f for f in open_findings if f.get("track") == "editorial" and f.get("verification_status") not in EXCLUDED_VERIFICATION]
    # Temuan kritis terbuka membatasi rekomendasi terlepas dari angka (PRD §8.2).
    if any(f["severity"] == "critical" for f in open_ed) and status in ("PASS_RECOMMENDED", "MINOR_REVISION"):
        status = "MAJOR_REVISION"
        reasons.append("OPEN_CRITICAL_FINDING")
    elif any(f["severity"] == "major" for f in open_ed) and status == "PASS_RECOMMENDED":
        status = "MINOR_REVISION"
        reasons.append("OPEN_MAJOR_FINDING")
    return ScoreOutcome(results, total, coverage, len(scored), len(considered), status, reasons)
