import logging
from pathlib import Path
import time
from typing import Any

from .base import TranscriptionEngine


class ParakeetEngine(TranscriptionEngine):
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model: Any = None

    def load_model(self) -> None:
        """Load Parakeet model."""
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError:
            raise ImportError(
                "Parakeet (NeMo) is not available. Please see README for installation instructions."
            )

        logging.info(f"Loading Parakeet model from {self.model_path}...")
        model_load_start = time.time()
        self.model = nemo_asr.models.ASRModel.from_pretrained(
            model_name=self.model_path
        )
        model_load_time = time.time() - model_load_start
        logging.info(f"Parakeet model loaded in {model_load_time:.2f} seconds")

    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Parakeet."""
        result = self.model.transcribe([str(audio_file)])
        return str(result[0].text).strip()

    def get_pipewire_format(self) -> str:
        """Parakeet can use f32 samples."""
        return "f32"
