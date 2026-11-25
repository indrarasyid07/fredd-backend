"""Speech to text behind `SpeechToText` (roadmap 12.7, D7). `STT_PROVIDER=openai` sends voice
notes to OpenAI's transcription endpoint; `STT_PROVIDER=fake` (the default) reads the "audio"
as the words spoken, so development, the devtools chat and tests run without an API key."""

from dataclasses import dataclass
from typing import Protocol

import openai

from app.core.config import settings
from app.core.errors import AppError
from app.modules.ai import openai_client


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


class OpenAISpeechToText:
    """OpenAI's transcription endpoint. Telegram voice notes (Ogg/Opus) are sent as they are."""

    name = "openai"

    def __init__(self, client: openai.AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def transcribe(self, audio: bytes, content_type: str, language: str = "id") -> Transcript:
        ext = _EXTENSIONS.get(content_type.split(";")[0].strip(), "ogg")
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(f"voice.{ext}", audio, content_type),
            language=language,
            # Field reports: farming words, numbers and units are the likely content.
            prompt=TRANSCRIPTION_HINT,
        )
        return Transcript(result.text.strip(), language, self.name)


TRANSCRIPTION_HINT = (
    "Laporan lapangan penyuluh pertanian: nama petani, luas lahan dalam hektar, "
    "kondisi tanaman, hama dan penyakit, padi, jagung, cabai, angka dan tanggal."
)
_EXTENSIONS = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/wav": "wav"}


# Tests set this, so every caller uses the same fake.
override: SpeechToText | None = None


def get_speech_to_text() -> SpeechToText:
    if override is not None:
        return override
    if settings.stt_provider == "fake":
        return FakeSpeechToText()
    client = openai_client.get_client()
    if settings.stt_provider == "openai" and client is not None:
        return OpenAISpeechToText(client, settings.stt_model)
    raise SpeechUnavailable()


def transcribes_every_voice_note() -> bool:
    """A real provider is set up: voice notes answer any question, not only in Voice Lab. The
    fake provider would turn real audio into noise, so it stays limited to voice-mode topics."""
    return override is not None or (
        settings.stt_provider == "openai" and openai_client.get_client() is not None
    )
