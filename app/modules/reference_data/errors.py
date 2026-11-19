from app.core.errors import AppError, NotFound


class ReferenceItemNotFound(NotFound):
    """Unknown id, or a row of another workspace (404, never 403)."""

    code = "reference_item_not_found"
    message = "Data rujukan tidak ditemukan."


class GeometryLimitTooHigh(AppError):
    status_code = 422
    code = "geometry_limit_too_high"
    message = "Batas wilayah hanya bisa dimuat paling banyak 50 baris per halaman."

    def __init__(self) -> None:
        super().__init__(field="limit")


class GeometryOnlyForRegions(AppError):
    status_code = 422
    code = "geometry_only_for_regions"
    message = "Batas wilayah hanya tersedia untuk data rujukan wilayah."

    def __init__(self) -> None:
        super().__init__(field="geometry")


class UnknownRegion(AppError):
    """A region id that is not a platform province / a regency of the chosen province."""

    status_code = 422
    code = "unknown_region"
    message = "Wilayah tidak dikenal atau tidak berada di provinsi yang dipilih."
