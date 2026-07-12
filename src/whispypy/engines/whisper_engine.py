import logging
from pathlib import Path
import time
from typing import Any

import soundfile as sf
import whisper

from .base import TranscriptionEngine


class WhisperEngine(TranscriptionEngine):
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model: Any = None

    def load_model(self) -> None:
        """Load Whisper model."""
        logging.info(f"Loading Whisper model from {self.model_path}...")
        model_load_start = time.time()
        self.model = whisper.load_model(self.model_path)
        model_load_time = time.time() - model_load_start
        logging.info(f"Whisper model loaded in {model_load_time:.2f} seconds")

    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Whisper."""
        samples, _ = sf.read(str(audio_file), dtype="float32")
        result = self.model.transcribe(
            samples, fp16=False, language=None, task="transcribe"
        )
        return str(result["text"]).strip()

    def get_pipewire_format(self) -> str:
        """Whisper works well with f32 samples."""
        return "f32"
