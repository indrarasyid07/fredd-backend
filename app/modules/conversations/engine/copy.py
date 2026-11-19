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
