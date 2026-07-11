# AGENTS.md

## Project Overview

**whispypy** is a signal-controlled audio transcription daemon written in Python. It enables on-demand audio recording triggered by system signals (SIGUSR2) and provides instant transcription using locally-running AI models. The transcribed text is automatically copied to the clipboard and can optionally be auto-pasted.

This is a Python rewrite of the original [whispy](https://github.com/daaku/whispy) by [@daaku](https://github.com/daaku).

### Key Capabilities

- Signal-controlled recording (SIGUSR2 to start/stop)
- Multiple transcription engines (Whisper, NVIDIA Parakeet, Parakeet INT8)
- Audio device discovery and validation
- Clipboard integration (Wayland/X11)
- Auto-paste functionality
- Persistent configuration management
- State file management for external indicators (e.g., Waybar)

## Architecture

### Core Components

#### 1. **WhispypyDaemon** (`whispypy-daemon.py:843`)
The main daemon class that orchestrates the entire transcription workflow.

**Responsibilities:**
- Signal handling (SIGINT, SIGUSR2)
- Audio recording lifecycle management
- Model loading and transcription
- Clipboard integration
- State file management
- Audio device validation

**Key Methods:**
- `_handle_sigusr2()`: Toggle recording on/off
- `_start_recording()`: Initialize audio capture
- `_stop_recording()`: Stop capture and trigger transcription
- `_transcribe_audio()`: Process audio through selected engine
- `_copy_to_clipboard()`: Copy transcribed text to clipboard
- `_autopaste_text()`: Automatically paste transcribed text

#### 2. **ConfigManager** (`whispypy-daemon.py:294`)
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

#### 3. **SherpaOnnxParakeetInt8Transcriber** (`whispypy-daemon.py:164`)
Wrapper for NVIDIA Parakeet INT8 model using Sherpa-ONNX runtime.

**Responsibilities:**
- ONNX model initialization
- Audio preprocessing for Parakeet
- Transcription via Sherpa-ONNX recognizer
- Thread management for ONNX inference

**Key Methods:**
- `transcribe()`: Process audio file and return transcription
- `_load_audio()`: Load and preprocess WAV audio

### Transcription Engines

#### 1. **Whisper** (Default)
- **Models:** tiny, base, small, medium, large, large-v2, large-v3
- **Format:** .au files (Sun Audio format)
- **Dependencies:** openai-whisper
- **Use Case:** General-purpose, works out of the box

#### 2. **NVIDIA Parakeet**
- **Model:** nvidia/parakeet-tdt-0.6b-v3
- **Format:** .wav files
- **Dependencies:** nemo_toolkit[asr]
- **Use Case:** High-performance ASR with GPU support

#### 3. **NVIDIA Parakeet INT8 (Sherpa-ONNX)**
- **Model:** sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8
- **Format:** .wav files
- **Dependencies:** sherpa-onnx
- **Use Case:** CPU-friendly quantized model
- **Auto-download:** Model bundle downloaded on first run

### Audio Pipeline

#### Recording Flow
1. **Device Selection:**
   - PipeWire (preferred): Uses `pw-record` and `pw-cli`
   - ALSA (fallback): Uses `arecord`
   - Device validation before recording

2. **Audio Capture:**
   - Sample rate: 16000 Hz (Whisper's expected rate)
   - Channels: 1 (mono)
   - Format: f32 (32-bit float for PipeWire) or S16_LE (ALSA)

3. **Audio Processing:**
   - Whisper: Direct .au file processing
   - Parakeet: WAV file with proper headers
   - Parakeet INT8: WAV file loaded as float32 numpy array

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
- **Core:** openai-whisper
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

1. Add engine detection in `WhispypyDaemon.__init__()`
2. Implement `_load_<engine>_model()` method
3. Update `_transcribe_audio()` to handle new engine
4. Add appropriate audio format handling
5. Update README.md with installation instructions

#### Modifying Audio Pipeline

1. Check constants at top of `whispypy-daemon.py`:
   - `SAMPLE_RATE`, `CHANNELS`, `AUDIO_FORMAT`
2. Update recording methods: `_start_recording()`, `_stop_recording()`
3. Ensure compatibility with all transcription engines
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

- **whispypy-daemon.py**: Main daemon implementation (1402 lines)
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
- Engine-specific format selection (.au vs .wav)
- Proper WAV headers for Parakeet engines
- Float32 conversion for ONNX models

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

1. **Audio Format Mismatch:** Ensure engine-specific format handling
2. **Device Validation:** Always validate before recording
3. **Signal Handling:** Proper cleanup in signal handlers
4. **Model Loading:** Handle ImportError for optional dependencies
5. **Clipboard Tools:** Check availability before use
6. **State Files:** Clean up on shutdown

### Extension Points

- **New Engines:** Add to engine selection logic
- **Audio Backends:** Extend device discovery
- **Clipboard Backends:** Add new clipboard tools
- **Configuration:** Extend ConfigManager
- **State Indicators:** Add new state files or protocols

## Project Structure

```
whispypy/
├── whispypy-daemon.py          # Main daemon implementation
├── test_audio_devices.py       # Device testing utility
├── config.conf.example         # Configuration template
├── pyproject.toml              # Project metadata
├── README.md                   # User documentation
├── AGENTS.md                   # This file
├── assets/                     # Audio beeps and resources
├── docs/                       # Additional documentation
└── src/whispypy/              # Package structure (currently empty)
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
