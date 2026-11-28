from app.core.errors import AppError, Conflict, NotFound


class ReportNotFound(NotFound):
    code = "report_not_found"
    message = "Laporan tidak ditemukan."


class ReportAlreadyVerified(Conflict):
    code = "report_already_verified"
    message = "Laporan ini sudah diverifikasi dan tidak bisa diubah lagi."


class FieldNotCorrectable(AppError):
    status_code = 422
    code = "field_not_correctable"
    message = "Isian ini tidak bisa dikoreksi di sini."


class InvalidCorrection(AppError):
    status_code = 422
    code = "invalid_correction"
    message = "Nilai koreksi tidak terbaca."


class ExportTooLarge(AppError):
    status_code = 422
    code = "export_too_large"
    message = "Data terlalu banyak untuk diunduh sekaligus. Persempit rentang tanggal."


class InvalidExport(AppError):
    status_code = 422
    code = "invalid_export"
    message = "Pilihan unduhan tidak valid."


class ExportFormatUnavailable(AppError):
    status_code = 422
    code = "export_format_unavailable"
    message = "Format PDF belum tersedia. Pilih Excel atau CSV."


class TooManyExports(AppError):
    status_code = 429
    code = "too_many_exports"
    message = "Masih ada 3 unduhan yang sedang dibuat. Tunggu salah satunya selesai."


class ExportNotFound(NotFound):
    code = "export_not_found"
    message = "Unduhan tidak ditemukan."


class ExportNotReady(Conflict):
    code = "export_not_ready"
    message = "Berkas belum siap diunduh."


class ExportExpired(AppError):
    status_code = 410
    code = "export_expired"
    message = "Berkas sudah dihapus setelah 7 hari. Buat unduhan baru."
