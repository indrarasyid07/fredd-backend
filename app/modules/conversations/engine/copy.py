"""Every message Fluctuz sends to extension workers (chat-ux.md: one question per message,
progress "3/5", recorded values in *bold*, errors say what is wrong plus a correct example)."""

import datetime as dt
from decimal import Decimal

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

JOIN_FIRST = "Halo! Kirim kode dari admin Anda untuk mulai melapor, contoh: K7M2-9QXA."
CHOOSE_TOPIC = "Mau melapor untuk yang mana?"
TOPIC_UNKNOWN = "Pilih salah satu topik di bawah ini."
OPTIONAL_HINT = "(boleh dilewati)"
SKIP = "Lewati"
HELP = "Minta bantuan admin"
YES = "Ya"
CHANGE = "Ubah"
NOT_THIS = "Bukan"
SUBMIT = "Kirim sekarang"
EDIT = "Ubah jawaban"
DONE = "Selesai"
REQUIRED = "Pertanyaan ini wajib dijawab."
EDIT_WHICH = "Jawaban mana yang mau diubah?"
HELP_SENT = "Baik, admin sudah diberi tahu dan akan membalas di sini. Mohon tunggu sebentar."
THREE_FAILS = "Sudah 3 kali jawaban belum sesuai. Mau bagaimana?"
VOICE_LATER = "Pesan suara belum bisa saya baca untuk pertanyaan ini. Mohon ketik jawabannya."
SUBMIT_FIRST = "Laporan siap dikirim. Tekan *Kirim sekarang* atau *Ubah jawaban*."
CONFIRM_FIRST = "Mohon jawab *Ya* atau *Ubah* dulu."
# --- Joining with a code (join-codes.md) ---
CODE_UNKNOWN = "Kode tidak dikenali. Periksa kode dari admin Anda, contoh: K7M2-9QXA."
RATE_LIMITED = (
    "Pesan Anda terlalu banyak dalam satu menit, jadi pesan setelah ini belum saya terima. "
    "Tunggu sebentar, lalu kirim ulang."
)
CODE_CLOSED = "Kode ini sudah tidak menerima anggota baru. Hubungi admin Anda untuk kode terbaru."
KEEP = "Ya, tetap"
NOT_MINE = "Bukan, ganti"
ADD_TOPIC = "Tambah topik"
CANCEL = "Batal"
AFTER_KEEP = (
    "Siap. Saya Fluctuz, asisten yang membantu mencatat laporan lapangan. "
    "Ketik *mulai* untuk melapor."
)
AFTER_CHANGE = (
    "Baik, tidak jadi bergabung. Kirim kode yang benar dari admin Anda, contoh: K7M2-9QXA."
)
CHOICE_EXPIRED = "Pilihan ini sudah kedaluwarsa. Kirim kodenya sekali lagi."
CANCELLED = "Baik, topik Anda tidak berubah."
EDITED = "Pesan yang diubah tidak saya baca. Mohon kirim ulang jawabannya sebagai pesan baru."

# Why an answer was not accepted, with an example (chat-ux.md moment 3).
NOT_A_NUMBER = "Format belum sesuai. Tulis angka, contoh: 1,5"
NOT_A_DATE = "Tanggal belum terbaca. Tulis seperti: kemarin, 12/11, atau 12 Nov 2026."
NOT_A_CHOICE = "Pilihan belum dikenali. Pilih salah satu tombol, atau ketik nomornya."
EMPTY_TEXT = "Jawaban masih kosong. Mohon tulis jawabannya."
NEED_LOCATION = "Mohon bagikan lokasi lewat tombol lampiran (📎) → Lokasi."
NEED_MEDIA = {
    "photo": "Mohon kirim foto.",
    "video": "Mohon kirim video.",
    "voice": "Mohon kirim pesan suara.",
    "document": "Mohon kirim foto dokumen atau berkasnya.",
    "signature": "Mohon kirim foto tanda tangan.",
}
MEDIA_WORD = {
    "photo": "foto",
    "video": "video",
    "voice": "pesan suara",
    "document": "berkas",
    "signature": "foto",
}


def greet(salutation: str, topic: str, first: str) -> str:
    return f"Halo {salutation}! Laporan *{topic}*.\n\n{first}"


def wrong_unit(unit: str) -> str:
    return f"Tulis dalam {unit}, contoh: 1,5 {unit}"


def out_of_range(low: float | None, high: float | None, unit: str | None) -> str:
    suffix = f" {unit}" if unit else ""
    shown = [number(Decimal(str(x))) if x is not None else None for x in (low, high)]
    if shown[0] is not None and shown[1] is not None:
        return f"Angka harus antara {shown[0]} dan {shown[1]}{suffix}."
    if shown[0] is not None:
        return f"Angka minimal {shown[0]}{suffix}."
    return f"Angka maksimal {shown[1]}{suffix}."


def unknown_choices(parts: list[str]) -> str:
    return f"Belum dikenali: {', '.join(parts)}. Pilih dari daftar, pisahkan dengan koma."


def choice_count(low: float | None, high: float | None) -> str:
    if low and high:
        return f"Pilih {int(low)} sampai {int(high)} jawaban."
    return (
        f"Pilih minimal {int(low)} jawaban."
        if low
        else f"Pilih paling banyak {int(high or 0)} jawaban."
    )


def location_inaccurate(limit: int) -> str:
    return f"Lokasi kurang akurat (lebih dari {limit} m). Coba bagikan lagi di tempat terbuka."


def media_received(kind: str, count: int, more_allowed: bool) -> str:
    word = MEDIA_WORD.get(kind, "berkas")
    if more_allowed:
        return f"{word.capitalize()} ke-{count} diterima. Kirim lagi, atau ketik *selesai*."
    return f"{word.capitalize()} ke-{count} diterima."


def media_too_few(kind: str, low: int) -> str:
    return f"Kirim minimal {low} {MEDIA_WORD.get(kind, 'berkas')}."


def confirm_value(display: str) -> str:
    return f"Dicatat *{display}*. Benar?"


def did_you_mean(label: str) -> str:
    return f"Maksud Anda *{label}*?"


def summary(lines: list[tuple[str, str]]) -> str:
    body = "\n".join(f"• {label}: *{value}*" for label, value in lines)
    return f"Ringkasan laporan:\n{body}\n\nKirim sekarang?"


def report_saved(code: str, salutation: str) -> str:
    return f"Laporan *{code}* tersimpan. Terima kasih, {salutation}."


def number(value: Decimal) -> str:
    """1.5 → "1,5"; 1250000 → "1.250.000" (Indonesian notation)."""
    sign = "-" if value < 0 else ""
    whole, _, frac = f"{abs(value).normalize():f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{grouped},{frac}" if frac else f"{sign}{grouped}"


def date(value: dt.date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def topic_title(organization: str, topic: str) -> str:
    return f"{organization} · {topic}"


def consent(organization: str, privacy_url: str) -> str:
    """UU PDP No. 27/2022: who controls the data. Draft wording, to be approved (roadmap 3.0)."""
    text = (
        f"Data laporan Anda dikelola oleh {organization} sebagai pengendali data, "
        "dengan Fluctuz sebagai pemroses data."
    )
    return f"{text} Kebijakan privasi: {privacy_url}" if privacy_url else text


def joined(name: str | None, organization: str, topic: str, privacy_url: str) -> str:
    hello = f"Halo {name}!" if name else "Halo!"
    return (
        f"{hello} Anda bergabung di *{topic_title(organization, topic)}*. "
        "Laporan Anda akan masuk ke topik ini seterusnya. Sudah benar?\n\n"
        + consent(organization, privacy_url)
    )


def topic_not_open(topic: str) -> str:
    return f"{topic} belum dibuka. Coba lagi setelah admin mengaktifkannya."


def waiting_approval(organization: str) -> str:
    return (
        f"Permintaan Anda sudah dikirim ke admin {organization}. "
        "Saya kabari di sini setelah disetujui."
    )


def approved(name: str | None, organization: str, topic: str, privacy_url: str) -> str:
    """Sent by the admin's approval (roadmap 4.6), with the usual Ya, tetap / Bukan, ganti."""
    hello = f"Halo {name}!" if name else "Halo!"
    return (
        f"{hello} Permintaan Anda sudah disetujui admin {organization}. "
        f"Anda bergabung di *{topic_title(organization, topic)}*. "
        "Laporan Anda akan masuk ke topik ini seterusnya. Sudah benar?\n\n"
        + consent(organization, privacy_url)
    )


def approved_elsewhere(organization: str, topic: str) -> str:
    """Approved while the chat is busy with another topic: the current one stays."""
    return (
        f"Permintaan Anda untuk *{topic_title(organization, topic)}* sudah disetujui. "
        "Kirim kodenya lagi bila ingin pindah ke topik ini atau menambahkannya."
    )


def already_joined(organization: str, topic: str) -> str:
    title = topic_title(organization, topic)
    return f"Anda sudah tergabung di *{title}*. Ketik *mulai* untuk melapor."


def switch_or_add(organization: str, topic: str) -> str:
    return (
        f"Kode ini untuk *{topic_title(organization, topic)}*. "
        "Pindah ke topik ini, atau tambahkan tanpa melepas yang lama?"
    )


def switch_to(topic: str) -> str:
    return f"Pindah ke {topic}"


def switched(organization: str, topic: str, privacy_url: str) -> str:
    return (
        f"Siap, laporan berikutnya masuk ke *{topic_title(organization, topic)}*. "
        "Ketik *mulai* untuk melapor.\n\n" + consent(organization, privacy_url)
    )


# --- Report flow in the service (roadmap 3.7) ---------------------------------------------------

CONFIRM_TOPIC_FIRST = (
    "Sebelum melapor, mohon pastikan dulu topiknya. Laporan Anda akan masuk ke topik ini "
    "seterusnya. Sudah benar?"
)
UNSUPPORTED = (
    "Jenis pesan ini belum bisa saya baca. Mohon kirim teks, foto, atau lokasi sesuai pertanyaan."
)
RESUME = "Lanjutkan"
RESTART = "Mulai ulang"
DRAFT_EXISTS = "Ada laporan yang belum selesai. Mau dilanjutkan atau mulai ulang dari awal?"
RESTART_CONFIRM = "Mulai ulang dari awal? Jawaban yang sudah diisi akan dihapus."
YES_RESTART = "Ya, mulai ulang"
CANCEL_CONFIRM = "Batalkan laporan yang sedang diisi? Jawaban yang sudah diisi akan dihapus."
YES_CANCEL = "Ya, batalkan"
DRAFT_CANCELLED = "Laporan dibatalkan. Ketik *mulai* bila ingin melapor lagi."
NO_DRAFT = "Tidak ada laporan yang sedang diisi. Ketik *mulai* untuk melapor."
KEEP_GOING = "Baik, kita lanjutkan."
STOP_CONFIRM = (
    "Berhenti menerima pesan dari Fluctuz untuk semua topik di chat ini? "
    "Draf yang belum terkirim akan dibuang."
)
YES_STOP = "Ya, berhenti"
STOPPED = (
    "Anda tidak akan menerima pesan lagi. Untuk bergabung kembali, kirim kode dari admin Anda."
)
STOP_CANCELLED = "Baik, Anda tetap tergabung."
HELP_TEXT = (
    "Perintah yang bisa dipakai:\n"
    "• *mulai*: mulai laporan baru\n"
    "• *lanjut*: ulangi pertanyaan terakhir\n"
    "• *mulai ulang*: isi ulang dari awal\n"
    "• *topik*: pilih topik lain\n"
    "• *batal*: batalkan laporan yang sedang diisi\n"
    "• *berhenti*: berhenti menerima pesan"
)


def only_topic(organization: str, topic: str) -> str:
    return f"Anda hanya tergabung di *{topic_title(organization, topic)}*."


def topic_closed(organization: str, topic: str) -> str:
    return (
        f"*{topic_title(organization, topic)}* sedang tidak menerima laporan. "
        "Hubungi admin Anda bila ini keliru."
    )
