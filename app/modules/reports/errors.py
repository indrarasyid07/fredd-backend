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
