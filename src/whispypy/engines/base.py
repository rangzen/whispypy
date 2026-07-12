from abc import ABC, abstractmethod
from pathlib import Path

SAMPLE_RATE = 16000  # Hz - the sample rate all engines expect and all recordings are standardized to


class TranscriptionEngine(ABC):
    """Abstract base class for transcription engines."""

    @abstractmethod
    def load_model(self) -> None:
        """Load the transcription model."""
        pass

    @abstractmethod
    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV audio file and return the text."""
        pass

    @abstractmethod
    def get_pipewire_format(self) -> str:
        """Return the preferred sample format for PipeWire ('f32' or 's16')."""
        pass
