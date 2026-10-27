"""Peran dan izin (PRD §5). Least privilege: izin dicek di backend untuk setiap endpoint sensitif."""

from enum import StrEnum


class Role(StrEnum):
    # Satu akun yang mengerjakan seluruh alur (unggah → cek ISBN → cek layout → laporan).
    PUBLISHER_ADMIN = "publisher_admin"
    SYSTEM_ADMIN = "system_admin"
    RULE_ADMIN = "rule_admin"
    EDITOR = "editor"
    MANAGER = "manager"
    INTAKE_OPERATOR = "intake_operator"
    AUDITOR = "auditor"


ROLE_LABELS = {
    Role.PUBLISHER_ADMIN: "Pengelola penerbitan",
    Role.SYSTEM_ADMIN: "Admin sistem",
    Role.RULE_ADMIN: "Admin aturan/editorial",
    Role.EDITOR: "Editor/verifikator",
    Role.MANAGER: "Manajer/editor-in-chief",
    Role.INTAKE_OPERATOR: "Operator penerimaan naskah",
    Role.AUDITOR: "Auditor/pembaca laporan",
}


class Perm(StrEnum):
    USER_MANAGE = "user.manage"
    AUDIT_READ = "audit.read"
    MANUSCRIPT_CREATE = "manuscript.create"
    MANUSCRIPT_UPDATE = "manuscript.update"
    # Membaca seluruh naskah, tanpa batasan penugasan.
    MANUSCRIPT_READ_ALL = "manuscript.read_all"
    # Membaca naskah yang dibuat sendiri atau ditugaskan.
    MANUSCRIPT_READ_SCOPED = "manuscript.read_scoped"
    VERSION_UPLOAD = "version.upload"
    VERSION_DOWNLOAD = "version.download"
    VERSION_REEXTRACT = "version.reextract"
    # Menjalankan/mengulang screening atas naskah yang dapat diakses.
    SCREENING_RUN = "screening.run"
    # Melihat katalog aturan, rule set, dan rubrik.
    RULE_READ = "rule.read"
    # Mengubah aturan, membuat/menguji/menerbitkan rule set dan rubrik.
    RULE_MANAGE = "rule.manage"
    # Memverifikasi temuan & mencatat bukti manual (bukan mengubah skor).
    FINDING_VERIFY = "finding.verify"
    # Menetapkan keputusan akhir.
    DECISION_MAKE = "decision.make"
    REPORT_EXPORT = "report.export"


ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.PUBLISHER_ADMIN: frozenset(Perm),
    Role.SYSTEM_ADMIN: frozenset({Perm.USER_MANAGE, Perm.AUDIT_READ}),
    Role.RULE_ADMIN: frozenset({Perm.RULE_READ, Perm.RULE_MANAGE}),
    Role.EDITOR: frozenset(
        {Perm.MANUSCRIPT_READ_SCOPED, Perm.VERSION_DOWNLOAD, Perm.SCREENING_RUN, Perm.RULE_READ, Perm.FINDING_VERIFY, Perm.REPORT_EXPORT}
    ),
    Role.MANAGER: frozenset(
        {
            Perm.MANUSCRIPT_READ_ALL,
            Perm.MANUSCRIPT_UPDATE,
            Perm.VERSION_DOWNLOAD,
            Perm.AUDIT_READ,
            Perm.SCREENING_RUN,
            Perm.RULE_READ,
            Perm.FINDING_VERIFY,
            Perm.DECISION_MAKE,
            Perm.REPORT_EXPORT,
        }
    ),
    Role.INTAKE_OPERATOR: frozenset(
        {
            Perm.MANUSCRIPT_CREATE,
            Perm.MANUSCRIPT_UPDATE,
            Perm.MANUSCRIPT_READ_SCOPED,
            Perm.VERSION_UPLOAD,
            Perm.VERSION_DOWNLOAD,
            Perm.VERSION_REEXTRACT,
            Perm.SCREENING_RUN,
            Perm.REPORT_EXPORT,
        }
    ),
    Role.AUDITOR: frozenset({Perm.MANUSCRIPT_READ_ALL, Perm.AUDIT_READ, Perm.RULE_READ, Perm.REPORT_EXPORT}),
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def permissions_for(role: str) -> list[str]:
    try:
        return sorted(p.value for p in ROLE_PERMISSIONS[Role(role)])
    except ValueError:
        return []
