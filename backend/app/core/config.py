from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SN_", env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "Sistem Screening Naskah"
    # Zona waktu tampilan untuk agregat harian (data tetap disimpan dalam UTC).
    display_timezone: str = "Asia/Jakarta"
    environment: str = "development"

    database_url: str = "postgresql+psycopg:///screening_naskah?host=/tmp"

    # Wajib diganti di produksi melalui environment/secret manager.
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 480
    jwt_algorithm: str = "HS256"

    # Login throttling (dihitung dari audit log, bukan memori proses).
    login_max_failures: int = 5
    login_window_minutes: int = 15

    # Penyimpanan berkas privat. Jangan arahkan ke direktori publik.
    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 50
    # Batas pembongkaran ZIP (DOCX) untuk mencegah zip bomb.
    max_docx_uncompressed_mb: int = 300
    max_docx_entries: int = 5000
    max_docx_compression_ratio: int = 100

    # Ambang kualitas ekstraksi (kebijakan internal, dapat dikonfigurasi).
    min_extracted_chars: int = 500
    min_extraction_quality: float = 60.0
    scanned_page_char_threshold: int = 40
    max_scanned_page_ratio: float = 0.2

    # Mode otomatis: keputusan kelayakan ISBN diambil sistem tanpa verifikasi manual; fitur verifikasi
    # editor & keputusan manajer disembunyikan di UI.
    auto_mode: bool = True
    # Ruas "Kategori Terbitan" formulir ISBN: Pemerintah | Perguruan tinggi | Swasta.
    publisher_category: str = "Swasta"

    # Jalankan ekstraksi di background task setelah unggah. Test mematikannya.
    extract_on_upload: bool = True

    cors_origins: list[str] = ["http://localhost:5173"]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
