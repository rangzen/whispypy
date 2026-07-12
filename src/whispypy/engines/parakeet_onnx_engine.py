import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Optional, Union
import wave

import numpy as np

from .base import SAMPLE_RATE, TranscriptionEngine

DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"


def _auto_onnx_threads() -> int:
    cpu_count = os.cpu_count() or 1
    return max(1, min(4, cpu_count // 2))


def _whispypy_cache_dir() -> Path:
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache_home) if xdg_cache_home else (Path.home() / ".cache")
    return base / "whispypy"


def _is_valid_parakeet_onnx_dir(model_dir: Path) -> bool:
    return all(
        (model_dir / name).is_file()
        for name in (
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        )
    )


def ensure_sherpa_onnx_parakeet_model_dir(
    model_id: str,
    cache_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """Ensure the sherpa-onnx model bundle exists locally; download if missing."""
    models_root = (
        Path(cache_dir) if cache_dir is not None else _whispypy_cache_dir()
    ) / "models"
    models_root.mkdir(parents=True, exist_ok=True)

    expected_dir = models_root / model_id
    if _is_valid_parakeet_onnx_dir(expected_dir):
        return expected_dir

    url = (
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        f"{model_id}.tar.bz2"
    )
    logging.info("Downloading sherpa-onnx model bundle from %s", url)

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
            tmp_path = tmp.name

        if shutil.which("curl"):
            download_cmd = [
                "curl",
                "-L",
                "-f",
                "-o",
                tmp_path,
                url,
            ]
        elif shutil.which("wget"):
            download_cmd = [
                "wget",
                "-O",
                tmp_path,
                url,
            ]
        else:
            raise RuntimeError(
                "Auto-download requires either 'curl' or 'wget' to be installed. "
                "Install one of them, or pass --parakeet-onnx-dir to point to a pre-downloaded bundle."
            )

        subprocess.run(
            download_cmd,
            check=True,
        )

        subprocess.run(
            [
                "tar",
                "-xjf",
                tmp_path,
                "-C",
                str(models_root),
            ],
            check=True,
        )
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    if _is_valid_parakeet_onnx_dir(expected_dir):
        return expected_dir

    # Some archives may not extract to the expected directory name.
    candidates = [
        p
        for p in models_root.iterdir()
        if p.is_dir() and _is_valid_parakeet_onnx_dir(p)
    ]
    if len(candidates) == 1:
        return candidates[0]

    raise FileNotFoundError(
        f"Downloaded model bundle but could not find required files under {models_root}. "
        f"Expected {expected_dir} with encoder/decoder/joiner/tokens."
    )


class SherpaOnnxParakeetInt8Transcriber:
    def __init__(
        self,
        model_dir: Union[str, Path],
        provider: str = "cpu",
        num_threads: Optional[int] = None,
    ):
        try:
            import sherpa_onnx
        except ImportError as e:
            raise ImportError(
                "sherpa-onnx is required for engine 'parakeet_onnx_int8'. "
                "Install with the optional extra (to be added): whispypy[parakeet-onnx]"
            ) from e

        self._sherpa_onnx = sherpa_onnx
        self.model_dir = Path(model_dir)

        encoder = self.model_dir / "encoder.int8.onnx"
        decoder = self.model_dir / "decoder.int8.onnx"
        joiner = self.model_dir / "joiner.int8.onnx"
        tokens = self.model_dir / "tokens.txt"

        missing = [
            str(p) for p in (encoder, decoder, joiner, tokens) if not p.is_file()
        ]
        if missing:
            raise FileNotFoundError(
                "Missing required Parakeet INT8 files in model dir. Missing: "
                + ", ".join(missing)
            )

        self.num_threads = (
            num_threads if num_threads is not None else _auto_onnx_threads()
        )
        self.provider = provider

        model_load_start = time.time()

        kwargs: dict[str, Any] = dict(
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            tokens=str(tokens),
            num_threads=self.num_threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type="nemo_transducer",
            debug=False,
        )

        # Provider support varies by sherpa-onnx version; try best-effort.
        if self.provider in {"cpu", "cuda"}:
            kwargs["provider"] = self.provider

        try:
            try:
                self.recognizer = self._sherpa_onnx.OfflineRecognizer.from_transducer(
                    **kwargs
                )
            except TypeError:
                # Older sherpa-onnx may not accept provider/model_type kwargs.
                kwargs.pop("provider", None)
                kwargs.pop("model_type", None)
                self.recognizer = self._sherpa_onnx.OfflineRecognizer.from_transducer(
                    **kwargs
                )
        except Exception as e:
            if self.provider == "cuda":
                logging.warning(
                    "Failed to initialize sherpa-onnx with provider=cuda (%s); falling back to cpu",
                    e,
                )
                self.provider = "cpu"
                kwargs["provider"] = "cpu"
                try:
                    self.recognizer = (
                        self._sherpa_onnx.OfflineRecognizer.from_transducer(**kwargs)
                    )
                except TypeError:
                    kwargs.pop("provider", None)
                    kwargs.pop("model_type", None)
                    self.recognizer = (
                        self._sherpa_onnx.OfflineRecognizer.from_transducer(**kwargs)
                    )
            else:
                raise

        model_load_time = time.time() - model_load_start
        logging.info(
            "Sherpa-ONNX Parakeet INT8 model loaded in %.2f seconds (provider=%s, threads=%s)",
            model_load_time,
            self.provider,
            self.num_threads,
        )

    def transcribe_wav(self, wav_path: Union[str, Path]) -> str:
        stream = self.recognizer.create_stream()

        with wave.open(str(wav_path)) as wf:
            if wf.getnchannels() != 1:
                raise ValueError(f"Expected mono wav, got channels={wf.getnchannels()}")
            if wf.getsampwidth() != 2:
                raise ValueError(
                    f"Expected 16-bit PCM wav, got sampwidth={wf.getsampwidth()} bytes"
                )
            num_frames = wf.getnframes()
            pcm = wf.readframes(num_frames)
            samples_i16 = np.frombuffer(pcm, dtype=np.int16)
            samples_f32 = samples_i16.astype(np.float32) / 32768.0
            sample_rate = wf.getframerate()

        stream.accept_waveform(sample_rate, samples_f32)
        self.recognizer.decode_streams([stream])
        return str(stream.result.text).strip()


class ParakeetOnnxEngine(TranscriptionEngine):
    def __init__(
        self,
        model_path: str,
        parakeet_onnx_dir: Optional[str] = None,
        parakeet_onnx_model_id: str = DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL,
        parakeet_onnx_cache_dir: Optional[str] = None,
        onnx_provider: str = "cpu",
        onnx_threads: Optional[int] = None,
    ):
        self.model_path = model_path
        self.parakeet_onnx_dir = parakeet_onnx_dir
        self.parakeet_onnx_model_id = parakeet_onnx_model_id
        self.parakeet_onnx_cache_dir = parakeet_onnx_cache_dir
        self.onnx_provider = onnx_provider
        self.onnx_threads = onnx_threads
        self.model: Optional[SherpaOnnxParakeetInt8Transcriber] = None

    def load_model(self) -> None:
        """Load Parakeet INT8 model via sherpa-onnx."""
        if not self.parakeet_onnx_dir:
            self.parakeet_onnx_dir = str(
                ensure_sherpa_onnx_parakeet_model_dir(
                    model_id=self.parakeet_onnx_model_id,
                    cache_dir=self.parakeet_onnx_cache_dir,
                )
            )

        self.model = SherpaOnnxParakeetInt8Transcriber(
            model_dir=self.parakeet_onnx_dir,
            provider=self.onnx_provider,
            num_threads=self.onnx_threads,
        )

    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Sherpa-ONNX."""
        assert self.model is not None, "load_model() must be called before transcribe()"
        return self.model.transcribe_wav(audio_file)

    def get_pipewire_format(self) -> str:
        """This ONNX model requires s16 samples."""
        return "s16"
