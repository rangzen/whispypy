from typing import Any

from .base import TranscriptionEngine
from .parakeet_engine import ParakeetEngine
from .parakeet_onnx_engine import (
    DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL,
    ParakeetOnnxEngine,
)
from .whisper_engine import WhisperEngine


def create_engine(
    engine_type: str,
    model_path: str,
    **engine_kwargs: Any,
) -> TranscriptionEngine:
    """
    Factory function to create appropriate engine instance.

    Args:
        engine_type: Type of engine ("whisper", "parakeet", "parakeet_onnx_int8")
        model_path: Path to the model
        **engine_kwargs: Engine-specific keyword arguments

    Returns:
        TranscriptionEngine instance

    Raises:
        ValueError: If engine_type is not supported
    """
    if engine_type == "whisper":
        return WhisperEngine(model_path)

    elif engine_type == "parakeet":
        return ParakeetEngine(model_path)

    elif engine_type == "parakeet_onnx_int8":
        return ParakeetOnnxEngine(
            model_path=model_path,
            parakeet_onnx_dir=engine_kwargs.get("parakeet_onnx_dir"),
            parakeet_onnx_model_id=engine_kwargs.get(
                "parakeet_onnx_model_id", DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL
            ),
            parakeet_onnx_cache_dir=engine_kwargs.get("parakeet_onnx_cache_dir"),
            onnx_provider=engine_kwargs.get("onnx_provider", "cpu"),
            onnx_threads=engine_kwargs.get("onnx_threads"),
        )

    else:
        raise ValueError(f"Unsupported engine: {engine_type}")
