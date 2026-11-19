from app.core.errors import AppError, Conflict, Forbidden, NotFound


class MemberNotFound(NotFound):
    code = "member_not_found"
    message = "Anggota tidak ditemukan."


class LastAdmin(AppError):
    """Every workspace keeps at least one approved admin."""

    status_code = 409
    code = "last_admin"
    message = (
        "Workspace harus punya minimal satu Administrator. Jadikan anggota lain Administrator dulu."
    )


class InviteNotFound(NotFound):
    code = "invite_not_found"
    message = "Undangan tidak ditemukan."


class InviteInvalid(NotFound):
    """Unknown, used, revoked or expired link; one message so a link reveals nothing more."""

    code = "invite_invalid"
    message = (
        "Undangan ini tidak berlaku lagi: sudah dipakai, dibatalkan, atau kedaluwarsa. "
        "Minta Administrator workspace mengirim ulang undangan."
    )


class InviteEmailMismatch(Forbidden):
    code = "invite_email_mismatch"
    message = "Undangan ini untuk email lain. Masuk dengan akun email yang menerima undangan."


class AlreadyMember(Conflict):
    code = "already_member"
    message = "Email ini sudah menjadi anggota workspace."


class PersonalWorkspace(Conflict):
    code = "personal_workspace"
    message = (
        "Workspace perorangan hanya untuk satu orang. Undang anggota dari workspace organisasi."
    )
