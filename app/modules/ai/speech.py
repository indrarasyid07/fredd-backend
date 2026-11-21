"""Speech to text. The cloud provider (D7: a cloud service, not chosen yet) plugs in behind
`SpeechToText` in roadmap 12.7; until then `STT_PROVIDER=fake` reads the "audio" as the words
spoken, so development, the devtools chat and tests run without an API key."""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.core.errors import AppError


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    provider: str
    # The provider's own score when it gives one (0–1); field confidence is decided later.
    confidence: float | None = None


class SpeechToText(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, content_type: str, language: str = "id"
    ) -> Transcript: ...


# Fake voice notes are an Ogg header followed by the spoken words, so they pass the media check
# (a voice note must start with "OggS") and the fake provider can read them back.
FAKE_AUDIO_PREFIX = b"OggS\x00"


def fake_voice_note(said: str) -> bytes:
    """Development and tests: a "recording" of `said` for the fake provider."""
    return FAKE_AUDIO_PREFIX + said.encode()


class FakeSpeechToText:
    """Development and tests only: the audio bytes are the spoken text in UTF-8."""

    name = "fake"

    async def transcribe(self, audio: bytes, content_type: str, language: str = "id") -> Transcript:
        audio = audio.removeprefix(FAKE_AUDIO_PREFIX)
        return Transcript(audio.decode("utf-8", errors="replace").strip(), language, self.name)


class SpeechUnavailable(AppError):
    status_code = 503
    code = "speech_unavailable"
    message = "Pengubah suara ke teks belum tersedia. Hubungi admin Fluctuz."


# Tests set this, so every caller uses the same fake.
override: SpeechToText | None = None


def get_speech_to_text() -> SpeechToText:
    if override is not None:
        return override
    if settings.stt_provider == "fake":
        return FakeSpeechToText()
    # Cloud providers arrive with roadmap 12.7 (decision D7).
    raise SpeechUnavailable()
