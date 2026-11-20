from app.core.errors import NotFound


class ReportNotFound(NotFound):
    code = "report_not_found"
    message = "Laporan tidak ditemukan."
