# AGENTS.md

## Project Overview

**whispypy** is a signal-controlled audio transcription daemon written in Python. It enables on-demand audio recording triggered by system signals (SIGUSR2) and provides instant transcription using locally-running AI models. The transcribed text is automatically copied to the clipboard and can optionally be auto-pasted.

This is a Python rewrite of the original [whispy](https://github.com/daaku/whispy) by [@daaku](https://github.com/daaku).

### Key Capabilities

- Signal-controlled recording (SIGUSR2 to start/stop)
- Multiple transcription engines (Whisper, NVIDIA Parakeet, Parakeet INT8), each an independent `TranscriptionEngine` implementation
- Audio device discovery and validation
- Clipboard integration (Wayland/X11)
- Auto-paste functionality
- Persistent configuration management
- State file management for external indicators (e.g., Waybar)

## Architecture

The engine-separation refactoring described in `docs/refactoring-plan-engine-separation.md` has been implemented.
Transcription engines live under `src/whispypy/engines/` as independent `TranscriptionEngine` implementations, and `WhispypyDaemon` is a pure orchestrator: it records audio, standardizes it to WAV, and delegates transcription to whichever engine it was given.

### Core Components

#### 1. **WhispypyDaemon** (`whispypy-daemon.py`)
The main daemon class that orchestrates the recording/transcription workflow.
It holds a `TranscriptionEngine` instance and never contains engine-specific logic.

**Responsibilities:**
- Signal handling (SIGINT, SIGUSR2)
- Audio recording lifecycle management (ALSA and PipeWire)
- Converting PipeWire's raw samples to WAV before handing off to the engine
- Clipboard integration
- State file management
- Audio device validation

**Key Methods:**
- `_handle_sigusr2()`: Toggle recording on/off
- `_start_recording()`: Initialize audio capture (WAV via ALSA, raw samples via PipeWire)
- `_convert_raw_to_wav()`: Convert PipeWire's raw samples to a standard WAV file
- `_stop_recording_and_transcribe()`: Stop capture, convert if needed, and call `self.engine.transcribe()`
- `validate_device()`: Verify the configured audio device is accessible

#### 2. **ConfigManager** (`whispypy-daemon.py`)
Manages persistent configuration with caching and validation.

**Responsibilities:**
- Configuration file I/O
- Config caching with mtime-based invalidation
- Device configuration persistence
- Dotool layout/variant configuration
- Configuration validation

**Key Methods:**
- `save_device()`: Persist audio device selection
- `load_device()`: Retrieve saved device
- `load_dotool_layout()`: Get keyboard layout for dotool
- `validate_config()`: Validate configuration format and values

#### 3. **Transcription Engines** (`src/whispypy/engines/`)
Each engine is an independent implementation of the `TranscriptionEngine` ABC (`src/whispypy/engines/base.py`), with just three methods: `load_model()`, `transcribe(audio_file: Path) -> str`, and `get_pipewire_format()`.
`src/whispypy/engines/factory.py` builds the right engine from `--engine` and its associated CLI args.
`SherpaOnnxParakeetInt8Transcriber` and the sherpa-onnx model auto-download helpers live in `src/whispypy/engines/parakeet_onnx_engine.py`, since they're only ever used by that engine.

### Transcription Engines

#### 1. **Whisper** (Default) - `src/whispypy/engines/whisper_engine.py`
- **Models:** tiny, base, small, medium, large, large-v2, large-v3
- **Dependencies:** openai-whisper
- **PipeWire format:** f32
- **Use Case:** General-purpose, works out of the box

#### 2. **NVIDIA Parakeet** - `src/whispypy/engines/parakeet_engine.py`
- **Model:** nvidia/parakeet-tdt-0.6b-v3
- **Dependencies:** nemo_toolkit[asr]
- **PipeWire format:** f32
- **Use Case:** High-performance ASR with GPU support

#### 3. **NVIDIA Parakeet INT8 (Sherpa-ONNX)** - `src/whispypy/engines/parakeet_onnx_engine.py`
- **Model:** sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8
- **Dependencies:** sherpa-onnx
- **PipeWire format:** s16
- **Use Case:** CPU-friendly quantized model
- **Auto-download:** Model bundle downloaded on first run

All engines receive a standardized WAV file; none of them deal with ALSA/PipeWire or raw sample formats directly.

### Audio Pipeline

#### Recording Flow
1. **Device Selection:**
   - PipeWire (preferred): Uses `pw-record` and `pw-cli`
   - ALSA (fallback): Uses `arecord`
   - Device validation before recording

2. **Audio Capture:**
   - Sample rate: 16000 Hz (Whisper's expected rate)
   - Channels: 1 (mono)
   - ALSA records S16_LE directly into a WAV container
   - PipeWire records raw samples in the engine's declared format (`f32` or `s16`, via `engine.get_pipewire_format()`)

3. **Audio Processing:**
   - ALSA recordings are already WAV; passed straight to `engine.transcribe()`
   - PipeWire recordings are converted to WAV by `WhispypyDaemon._convert_raw_to_wav()` (requires `soundfile` and `numpy`) before being passed to `engine.transcribe()`

#### State Management
- **Recording State:** `/tmp/whispypy_recording`
- **Ready State:** `/tmp/whispypy_ready`
- Used by external indicators (e.g., Waybar modules)

### Configuration

#### Config File Location
- `~/.config/whispypy/config.conf`
- INI format with `[DEFAULT]` section

#### Supported Settings
- `device`: Audio input device name
- `dotool_xkb_layout`: Keyboard layout for dotool
- `dotool_xkb_variant`: Keyboard variant for dotool

### Clipboard & Auto-paste

#### Clipboard Integration
- **Wayland:** `wl-copy`
- **X11:** `xclip` or `xsel`

#### Auto-paste Tools
- **Wayland:** `wtype`, `ydotool`, or `dotool`
- **X11:** `xdotool`
- Terminal detection to avoid pasting in terminal windows

## Development Guidelines

### Code Style
- Python 3.13+
- Type hints throughout
- Logging for debugging and user feedback
- Error handling with graceful fallbacks

### Testing
- `test_audio_devices.py`: Audio device discovery and validation
- Manual testing with `--check-model` flag

### Linting & Type Checking
- **Ruff:** Code formatting and linting (`ruff.toml`)
- **MyPy:** Static type checking (`mypy.ini`)

### Dependencies
- **Core:** openai-whisper, soundfile, numpy
- **Optional:** nemo_toolkit[asr], sherpa-onnx
- **Dev:** mypy, ruff, types-requests

## Working with AI Agents

### Understanding the Codebase

When working with this project, AI agents should:

1. **Start with the README.md** to understand features and requirements
2. **Review whispypy-daemon.py** for the main implementation
3. **Check config.conf.example** for configuration format
4. **Examine test_audio_devices.py** for device handling patterns

### Common Tasks

#### Adding a New Transcription Engine

1. Create a new module in `src/whispypy/engines/` implementing the `TranscriptionEngine` ABC (`load_model()`, `transcribe()`, `get_pipewire_format()`)
2. Register it in `src/whispypy/engines/factory.py`'s `create_engine()`
3. Add any engine-specific CLI arguments in `main()` and thread them through to the factory call
4. Add an availability check in `main()` if the engine has optional dependencies (see the `nemo`/`sherpa_onnx` `importlib.util.find_spec` checks)
5. Update README.md with installation instructions

No changes to `WhispypyDaemon` are needed: it only calls `engine.load_model()`, `engine.transcribe()`, and `engine.get_pipewire_format()`.

#### Modifying Audio Pipeline

1. Check constants at top of `whispypy-daemon.py`:
   - `SAMPLE_RATE`, `CHANNELS`
2. Update recording methods: `_start_recording()`, `_stop_recording_and_transcribe()`, `_convert_raw_to_wav()`
3. Ensure compatibility with all transcription engines (they only ever see the final WAV file)
4. Test with both PipeWire and ALSA

#### Adding Configuration Options

1. Add to `ConfigManager` class
2. Implement `load_<option>()` method
3. Update `validate_config()` if needed
4. Document in `config.conf.example`
5. Update README.md

#### Improving Device Detection

1. Modify device discovery functions:
   - `discover_pipewire_devices()`
   - `discover_alsa_devices()`
2. Update `test_audio_devices.py` for testing
3. Ensure backward compatibility with saved devices

### Key Files

- **whispypy-daemon.py**: Main daemon implementation (recording, device handling, orchestration)
- **src/whispypy/engines/base.py**: `TranscriptionEngine` ABC
- **src/whispypy/engines/whisper_engine.py**, **parakeet_engine.py**, **parakeet_onnx_engine.py**: Engine implementations
- **src/whispypy/engines/factory.py**: `create_engine()` factory
- **test_audio_devices.py**: Device discovery and testing utility
- **config.conf.example**: Configuration template
- **pyproject.toml**: Project metadata and dependencies
- **README.md**: User-facing documentation

### Important Patterns

#### Signal Handling
```python
signal.signal(signal.SIGUSR2, self._handle_sigusr2)
```
- SIGUSR2 toggles recording
- SIGINT for graceful shutdown

#### Model Loading
- Lazy loading on daemon initialization
- Timing logged for performance monitoring
- Graceful error handling with ImportError

#### Audio Format Handling
- All recordings are standardized to WAV before reaching an engine
- ALSA records WAV directly; PipeWire records raw samples that get converted via `_convert_raw_to_wav()`
- Each engine declares its preferred PipeWire sample format (`f32` or `s16`) via `get_pipewire_format()`

#### State Files
- Created/removed to signal recording state
- Used by external tools (Waybar, etc.)
- Atomic operations for reliability

### Testing Approach

1. **Device Testing:**
   ```bash
   python test_audio_devices.py
   ```

2. **Model Verification:**
   ```bash
   python whispypy-daemon.py --engine <engine> --check-model
   ```

3. **Integration Testing:**
   - Start daemon
   - Send SIGUSR2 signal
   - Verify recording and transcription
   - Check clipboard content

### Common Pitfalls

1. **Audio Format Mismatch:** The daemon must record in the format the active engine declares via `get_pipewire_format()`
2. **Device Validation:** Always validate before recording
3. **Signal Handling:** Proper cleanup in signal handlers
4. **Model Loading:** Handle ImportError for optional dependencies
5. **Clipboard Tools:** Check availability before use
6. **State Files:** Clean up on shutdown

### Extension Points

- **New Engines:** Add a new module under `src/whispypy/engines/` and register it in `factory.py`
- **Audio Backends:** Extend device discovery
- **Clipboard Backends:** Add new clipboard tools
- **Configuration:** Extend ConfigManager
- **State Indicators:** Add new state files or protocols

## Project Structure

```
whispypy/
├── whispypy-daemon.py          # Main daemon implementation (orchestration, recording, CLI)
├── test_audio_devices.py       # Device testing utility
├── config.conf.example         # Configuration template
├── pyproject.toml              # Project metadata
├── README.md                   # User documentation
├── AGENTS.md                   # This file
├── assets/                     # Audio beeps and resources
├── docs/                       # Additional documentation
│   └── refactoring-plan-engine-separation.md  # Engine-separation refactoring plan (implemented)
└── src/whispypy/engines/       # TranscriptionEngine implementations
    ├── base.py                 # TranscriptionEngine ABC
    ├── whisper_engine.py
    ├── parakeet_engine.py
    ├── parakeet_onnx_engine.py # Also hosts SherpaOnnxParakeetInt8Transcriber + model auto-download helpers
    └── factory.py               # create_engine()
```

## Contributing

When contributing to this project:

1. Follow existing code style (Ruff + MyPy)
2. Add type hints to all functions
3. Update README.md for user-facing changes
4. Update AGENTS.md for architectural changes
5. Test with multiple engines and audio backends
6. Ensure backward compatibility with existing configs

## Resources

- **Original Project:** https://github.com/daaku/whispy
- **OpenAI Whisper:** https://github.com/openai/whisper
- **NVIDIA NeMo:** https://github.com/NVIDIA/NeMo
- **Sherpa-ONNX:** https://github.com/k2-fsa/sherpa-onnx
