from app.core.errors import NotFound


class ConversationNotFound(NotFound):
    code = "conversation_not_found"
    message = "Percakapan tidak ditemukan."
