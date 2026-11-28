from app.core.errors import Conflict, Forbidden, NotFound


class ConversationNotFound(NotFound):
    code = "conversation_not_found"
    message = "Percakapan tidak ditemukan."


class ConversationTakenOver(Conflict):
    code = "conversation_taken_over"
    message = "Percakapan ini sudah ditangani admin lain."


class NotTakenOverByYou(Forbidden):
    code = "not_taken_over_by_you"
    message = "Ambil alih percakapan ini dulu sebelum membalas."


class ConversationNotTakenOver(Conflict):
    code = "conversation_not_taken_over"
    message = "Percakapan ini sedang ditangani Fluctuz."


class WhatsAppWindowClosed(Conflict):
    code = "whatsapp_window_closed"
    message = (
        "Sudah lewat 24 jam sejak pesan terakhir penyuluh. WhatsApp hanya mengizinkan pesan "
        "templat sampai penyuluh membalas."
    )
