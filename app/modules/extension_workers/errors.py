from app.core.errors import Conflict, NotFound


class ExtensionWorkerNotFound(NotFound):
    code = "extension_worker_not_found"
    message = "Penyuluh tidak ditemukan."


class ExtensionWorkerNotPending(Conflict):
    code = "extension_worker_not_pending"
    message = "Penyuluh ini tidak sedang menunggu persetujuan."


class ExtensionWorkerAlreadyBlocked(Conflict):
    code = "extension_worker_already_blocked"
    message = "Penyuluh ini sudah diblokir."


class ExtensionWorkerNotBlocked(Conflict):
    code = "extension_worker_not_blocked"
    message = "Penyuluh ini tidak sedang diblokir."
