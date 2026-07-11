# Refactoring Plan: Independent Engine Implementations

## Overview

This document outlines a comprehensive refactoring plan to separate the three transcription engines (Whisper, Parakeet, and Parakeet INT8) into independent implementations with a clean interface-based architecture.

## Current Architecture Issues

The `WhispypyDaemon` class currently has several architectural problems:

1. **Engine-specific logic scattered throughout the codebase**:
   - Line 871: Audio extension selection based on engine
   - Lines 885-892: Engine selection in `__init__`
   - Line 954: Audio extension in `validate_device()`
   - Line 978: PipeWire format selection for parakeet_onnx_int8
   - Line 1052: ALSA container format selection
   - Line 1066: PipeWire format override for parakeet_onnx_int8
   - Lines 1123-1143: Transcription logic with engine conditionals

2. **Mixed responsibilities**: The daemon class handles audio recording, device management, AND transcription logic

3. **Conditional branches**: Multiple `if self.engine == "..."` checks throughout the code

4. **Parameter pollution**: Engine-specific parameters in the main class constructor (parakeet_onnx_dir, onnx_provider, onnx_threads, etc.)

5. **Difficult to extend**: Adding a new engine requires modifying multiple methods across the codebase

## Proposed Architecture: A Unified WAV-Based Approach

The new architecture standardizes on the WAV audio format for all recordings, which dramatically simplifies the engine interface. The `WhispypyDaemon` will be responsible for producing a WAV file, abstracting the recording specifics (ALSA vs. PipeWire) away from the transcription engines.

### 1. Abstract Base Engine Interface

**File**: `src/whispypy/engines/base.py`

The base class is simplified to a core contract: loading a model and transcribing a WAV file.

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

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
```

**Key Design Decisions**:
- **WAV-first**: All engines receive a path to a WAV file, eliminating format-specific logic within the engines.
- **Daemon handles conversion**: The daemon is responsible for recording and, if necessary, converting audio to the WAV format.
- **Simplified Interface**: Engines only need to declare their preferred PipeWire sample format, not container formats or file extensions.

### 2. Whisper Engine Implementation

**File**: `src/whispypy/engines/whisper_engine.py`

**Responsibilities**:
- Load the Whisper model.
- Transcribe a given WAV file.
- Specify `f32` as the preferred PipeWire sample format.

**Implementation Details**:
The implementation is much cleaner, as it no longer deals with raw audio formats or ALSA specifics.

```python
import whisper
import logging
import time
from pathlib import Path
from .base import TranscriptionEngine

class WhisperEngine(TranscriptionEngine):
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None

    def load_model(self) -> None:
        """Load Whisper model."""
        logging.info(f"Loading Whisper model from {self.model_path}...")
        model_load_start = time.time()
        self.model = whisper.load_model(self.model_path)
        model_load_time = time.time() - model_load_start
        logging.info(f"Whisper model loaded in {model_load_time:.2f} seconds")

    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Whisper."""
        # whisper.load_audio can handle WAV files directly.
        samples = whisper.load_audio(str(audio_file))
        result = self.model.transcribe(
            samples, fp16=False, language=None, task="transcribe"
        )
        return result["text"].strip()

    def get_pipewire_format(self) -> str:
        """Whisper works well with f32 samples."""
        return "f32"
```

### 3. Parakeet (NeMo) Engine Implementation

**File**: `src/whispypy/engines/parakeet_engine.py`

The implementation is simplified by removing now-unnecessary methods.

```python
# ... (imports)
class ParakeetEngine(TranscriptionEngine):
    # ... (__init__ and load_model remain the same)
    
    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Parakeet."""
        result = self.model.transcribe([str(audio_file)])
        return result[0].text.strip()

    def get_pipewire_format(self) -> str:
        """Parakeet can use f32 samples."""
        return "f32"
```

### 4. Parakeet INT8 (Sherpa-ONNX) Engine Implementation

**File**: `src/whispypy/engines/parakeet_onnx_engine.py`

This engine prefers `s16` samples, which the daemon will now provide in the final WAV file.

```python
# ... (imports)
class ParakeetOnnxEngine(TranscriptionEngine):
    # ... (__init__ and load_model remain the same)

    def transcribe(self, audio_file: Path) -> str:
        """Transcribe a WAV file using Sherpa-ONNX."""
        return self.model.transcribe_wav(audio_file)

    def get_pipewire_format(self) -> str:
        """This ONNX model requires s16 samples."""
        return "s16"
```

**Note**: The `SherpaOnnxParakeetInt8Transcriber` class (currently at lines 164-279) should be moved into this module, along with its supporting helpers: `_auto_onnx_threads`, `_whispypy_cache_dir`, `_is_valid_parakeet_onnx_dir`, and `ensure_sherpa_onnx_parakeet_model_dir` (currently at lines 64-161).
These helpers are only ever called from ONNX engine code, so they belong in the same module.

### 5. Engine Factory

**File**: `src/whispypy/engines/factory.py`

Create a factory function to instantiate the appropriate engine:

```python
from typing import Any
from .base import TranscriptionEngine
from .whisper_engine import WhisperEngine
from .parakeet_engine import ParakeetEngine
from .parakeet_onnx_engine import ParakeetOnnxEngine

def create_engine(
    engine_type: str,
    model_path: str,
    **engine_kwargs: Any
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
            parakeet_onnx_dir=engine_kwargs.get('parakeet_onnx_dir'),
            parakeet_onnx_model_id=engine_kwargs.get('parakeet_onnx_model_id', DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL),
            parakeet_onnx_cache_dir=engine_kwargs.get('parakeet_onnx_cache_dir'),
            onnx_provider=engine_kwargs.get('onnx_provider', 'cpu'),
            onnx_threads=engine_kwargs.get('onnx_threads')
        )
    
    else:
        raise ValueError(f"Unsupported engine: {engine_type}")
```

**Key Features**:
- Single point of engine creation
- Type-safe interface
- Easy to extend with new engines

### 6. Refactor WhispypyDaemon Class

**File**: `whispypy-daemon.py` (modified)

The daemon class becomes a pure orchestrator, handling audio device management and delegating transcription to the engine.

**Major Changes**:

1.  **Constructor Simplification**:
    The constructor no longer needs to query the engine for audio formats. It now defaults to using the `.wav` extension.

    ```python
    def __init__(
        self,
        engine: TranscriptionEngine,
        device_name: str,
        keep_audio: bool = False,
        autopaste: bool = False,
    ):
        self.engine = engine
        self.device_name = device_name
        self.keep_audio = keep_audio
        self.autopaste = autopaste
        
        # All recordings will be standardized to WAV format.
        self.temp_audio_file = Path(tempfile.gettempdir()) / (
            TEMP_AUDIO_FILENAME + ".wav"
        )
        self.temp_raw_file: Optional[Path] = None
        
        # State, signal handlers, etc. remain the same
        self.recording = False
        self.running = True
        self.pw_record_proc: Optional[subprocess.Popen[bytes]] = None
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)
    ```

2.  **Remove Engine-Specific Load Methods**:
    - Delete `_load_whisper_model()`, `_load_parakeet_model()`, and `_load_parakeet_onnx_int8_model()`. This logic is now encapsulated in the engine classes and called from the main entry point.
    - Delete the module-level helpers `load_audio_f32` and `load_audio_s16_as_f32` (lines 475-497). These exist solely to handle Whisper's raw-sample-loading path, which is replaced by `whisper.load_audio()` on the standardized WAV file. They become unreachable dead code after the refactor.

3.  **Simplify `_start_recording()`**:
    This method now handles two cases: direct WAV recording with ALSA, or raw sample recording with PipeWire, which will be converted later.

    ```python
    def _start_recording(self) -> None:
        """Start audio recording."""
        logging.info("Starting recording...")
        play_start_beep()
        
        if self._is_alsa_device():
            # ALSA can record directly to a WAV file.
            self.temp_raw_file = None
            cmd = [
                "arecord",
                "-D", self._get_alsa_device(),
                "-f", "S16_LE",      # Standard format
                "-r", str(SAMPLE_RATE),
                "-c", str(CHANNELS),
                "-t", "wav",         # Record to WAV container
                str(self.temp_audio_file),
            ]
        else:
            # PipeWire records raw samples, which we'll convert.
            self.temp_raw_file = self.temp_audio_file.with_suffix(".raw")
            pw_format = self.engine.get_pipewire_format()
            cmd = [
                "pw-record",
                f"--target={self.device_name}",
                f"--format={pw_format}",
                f"--rate={SAMPLE_RATE}",
                f"--channels={CHANNELS}",
                str(self.temp_raw_file),
            ]
        
        self.pw_record_proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        self.recording = True
        # ... rest of method
    ```

4.  **Add `_convert_raw_to_wav()` Helper**:
    A new private method is added to handle the conversion from raw PipeWire-recorded samples to a standard WAV file. This requires a new dependency, `soundfile`.

    ```python
    def _convert_raw_to_wav(self, raw_path: Path, wav_path: Path, sample_format: str):
        """Converts a raw audio file to WAV format."""
        try:
            import soundfile as sf
            import numpy as np
        except ImportError:
            logging.error("The 'soundfile' and 'numpy' libraries are required for PipeWire recordings.")
            logging.error("Please install them with: pip install soundfile numpy")
            return

        dtype = np.float32 if sample_format == 'f32' else np.int16
        try:
            data = np.fromfile(raw_path, dtype=dtype)
            # Use FLOAT subtype for f32 sources to avoid a lossy f32->PCM_16->f32 roundtrip.
            # PCM_16 is required for s16 sources because SherpaOnnxParakeetInt8Transcriber
            # validates sampwidth == 2 and raises ValueError otherwise.
            subtype = 'FLOAT' if sample_format == 'f32' else 'PCM_16'
            sf.write(wav_path, data, SAMPLE_RATE, subtype=subtype)
            logging.info(f"Successfully converted {raw_path} to {wav_path}")
        except Exception as e:
            logging.error(f"Failed to convert raw audio to WAV: {e}")

    ```

5.  **Update `_stop_recording_and_transcribe()`**:
    This method now orchestrates the WAV conversion step before calling the engine.

    ```python
    def _stop_recording_and_transcribe(self) -> None:
        """Stop recording, convert if necessary, and transcribe."""
        logging.info("Stopping recording...")
        # ... (logic to stop recording process) ...

        # If we recorded from PipeWire, convert the raw file to WAV.
        if self.temp_raw_file and self.temp_raw_file.exists():
            pw_format = self.engine.get_pipewire_format()
            self._convert_raw_to_wav(self.temp_raw_file, self.temp_audio_file, pw_format)
            if not self.keep_audio:
                self.temp_raw_file.unlink()

        # Transcribe the final WAV file.
        logging.info("Transcribing...")
        transcription_start = time.time()
        
        text = self.engine.transcribe(self.temp_audio_file)
        
        transcription_time = time.time() - transcription_start
        logging.info(f"Transcription completed in {transcription_time:.2f} seconds")
        logging.info(f"Transcription result: '{text}'")
        
        # ... (rest of method: autopaste, cleanup)
    ```

6.  **Simplify `validate_device()`**:
    Device validation is simpler as it only needs to test recording to a single, standard format.

    ```python
    def validate_device(self) -> bool:
        """Validate that the audio device exists and is accessible."""
        # The test now always uses the .wav extension.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as test_file:
            test_file_path = test_file.name
        
        try:
            if self._is_alsa_device():
                # ... (ALSA validation using arecord with -t wav) ...
            else:
                # Use the engine's declared sample format for consistency.
                pw_format = self.engine.get_pipewire_format()
                # ... (PipeWire validation with pw-record) ...
        # ... (rest of validation logic) ...
    ```
**Removed Attributes**:
- `self.engine` (string) → replaced with `self.engine` (TranscriptionEngine)
- `self.model_path`
- `self.parakeet_onnx_dir`
- `self.parakeet_onnx_model_id`
- `self.parakeet_onnx_cache_dir`
- `self.onnx_provider`
- `self.onnx_threads`
- `self.model` → removed; all transcription goes through `self.engine.transcribe()`

### 7. Update Main Entry Point

**File**: `whispypy-daemon.py` (main function)

**Changes**:

```python
def main():
    # ... argument parsing ...
    
    # Validate engine availability
    if args.engine == "parakeet":
        if not NEMO_AVAILABLE:
            logging.error("Parakeet engine selected but NeMo is not available.")
            sys.exit(1)
    
    if args.engine == "parakeet_onnx_int8":
        if not SHERPA_ONNX_AVAILABLE:
            logging.error("parakeet_onnx_int8 engine selected but sherpa-onnx is not available.")
            sys.exit(1)
    
    # Create engine using factory
    from src.whispypy.engines.factory import create_engine
    
    engine = create_engine(
        engine_type=args.engine,
        model_path=args.model,
        parakeet_onnx_dir=args.parakeet_onnx_dir,
        parakeet_onnx_model_id=args.parakeet_onnx_model_id,
        parakeet_onnx_cache_dir=args.parakeet_onnx_cache_dir,
        onnx_provider=args.onnx_provider,
        onnx_threads=args.onnx_threads,
    )
    
    # Load the model
    engine.load_model()
    
    # Create daemon with engine
    daemon = WhispypyDaemon(
        engine=engine,
        device_name=device,
        keep_audio=args.keep_audio,
        autopaste=args.autopaste,
    )
    
    # Run daemon
    daemon.run()
```

**Key Changes**:
- Engine creation moved to factory
- Model loading happens before daemon creation
- Daemon constructor simplified
- Engine-specific parameters passed to factory

## Benefits of This Refactoring

The standardized WAV-based approach provides even greater benefits:

### 1. Superior Separation of Concerns
- **Engines are transcription-only**: Engines are completely decoupled from audio capture methods (ALSA/PipeWire) and file formats. Their single responsibility is to transcribe a standard WAV file.
- **Daemon as the Audio Hub**: The daemon exclusively manages the complexities of audio recording and format conversion, providing a clean, consistent input to the engines.

### 2. Easier Testing
- Engines can be unit-tested simply by feeding them WAV files, with no need to mock recording environments.
- The daemon's new audio conversion logic can be tested in isolation.

### 3. Enhanced Maintainability & Extensibility
- Adding a new engine is trivial: simply implement the two-method interface (`load_model`, `transcribe`) and specify a PipeWire format. No audio format expertise is needed.
- Future changes to audio recording (e.g., supporting a new sound server) only require modifications to the daemon, not every engine.

### 4. Cleaner and More Robust Code
- Eliminates a whole class of potential bugs related to audio format mismatches between recording and transcription.
- The data flow is linear and predictable: Record -> Convert to WAV -> Transcribe.

## Backward Compatibility

### CLI Interface & Configuration File
- **No changes**: All command-line arguments and configuration file settings remain fully backward compatible.

### Functionality
- **No changes**: All existing transcription functionality is preserved.

### Dependencies
- **New Dependency**: This refactoring introduces a new Python dependency, `soundfile` (and its dependency, `numpy`), which is required for handling audio from PipeWire sources. This is a well-maintained and standard library for audio processing.

### Breaking Changes
- **None**: This is a pure internal refactoring with no user-facing breaking changes.

## Testing Strategy

The testing strategy remains the same, with the addition of a new unit test for the `_convert_raw_to_wav` method in the daemon to ensure reliable audio conversion.

## Risks and Mitigations

### Risk 1: New Dependency (`soundfile`)
- **Risk**: The new dependency might fail to install on some systems or introduce conflicts.
- **Mitigation**: 
    1. Add `soundfile` and `numpy` to the `pyproject.toml` dependencies to ensure automatic installation.
    2. The daemon will feature a runtime check for the library's presence and provide a clear, user-friendly error message with installation instructions if it's missing.

### Risk 2: Performance of WAV Conversion
- **Risk**: The on-the-fly conversion from raw audio to WAV for PipeWire recordings could introduce a noticeable delay.
- **Mitigation**:
    1. The conversion is very fast for short audio clips and is performed in memory and on disk using highly optimized libraries (`numpy`, `soundfile`).
    2. Benchmark the conversion step to confirm its performance impact is negligible for typical command durations.

### Risk 3: Breaking Existing Functionality
- **Mitigation**: Comprehensive regression testing across all engines and both ALSA and PipeWire devices to ensure the new WAV-based flow works identically to the old one.

## Future Enhancements

After this refactoring, the following enhancements become easier:

1. **Plugin System**: Load engines dynamically from external modules
2. **Streaming Transcription**: Add streaming interface to base class
3. **Multi-Engine Support**: Run multiple engines in parallel
4. **Engine Benchmarking**: Compare engines easily
5. **Custom Engines**: Users can implement their own engines
6. **Engine Configuration**: Per-engine configuration files
7. **Hot-Swapping**: Switch engines without restarting daemon

## Conclusion

This refactoring will significantly improve the codebase's maintainability, testability, and extensibility while preserving all existing functionality and maintaining backward compatibility. The clear separation of concerns and interface-based design will make future development much easier.
