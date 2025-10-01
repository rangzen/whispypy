# Copilot Instructions for whispypy

## Project Overview

This is a Python rewrite of [whispy](https://github.com/daaku/whispy) - a signal-controlled audio transcription daemon using OpenAI Whisper. The system records audio on SIGUSR2 signals and provides real-time transcription with automatic clipboard integration.

## Architecture & Core Components

### Signal-Based Recording Flow

- **Main daemon**: `whispypy-daemon.py` - signal-driven audio recording and transcription
- **Device testing**: `test_audio_devices.py` - discovers and validates audio input devices
- **Signal helper**: `send_signal.sh` - convenience script for sending SIGUSR2 signals

### Audio Pipeline

1. **Device Discovery**: Uses `pw-cli` (PipeWire) with `arecord` fallback for ALSA
2. **Recording**: `pw-record` captures raw f32 audio at 16kHz mono to `/tmp/a.au`
3. **Transcription**: OpenAI Whisper processes the audio file directly
4. **Output**: Text copied to clipboard via `wl-copy` (Wayland) or `xclip`/`xsel` (X11)

### Signal Handling Pattern

```python
# SIGUSR2 toggles recording state - first signal starts, second stops & transcribes
# SIGINT/Ctrl+C cleanly shuts down daemon and stops ongoing recordings
signal.signal(signal.SIGUSR2, handle_sigusr2)
signal.signal(signal.SIGINT, handle_sigint)
```

## Development Patterns

### Error Handling Conventions

- Audio errors logged to stderr with contextual details (file size, sample count, RMS)
- Graceful fallbacks: PipeWire → ALSA, wl-copy → xclip → xsel
- Device validation through actual recording tests, not just enumeration

### Audio Data Processing

- Raw f32 format: `struct.unpack(f"<{num_floats}f", data)` for little-endian floats
- RMS threshold `0.001` distinguishes signal from silence
- Files auto-cleaned unless `--keep-audio` flag used

### Type Safety & Configuration

- Strict mypy configuration with `disallow_untyped_defs = True`
- TypedDict for structured data: `WorkingDevice`, etc.
- UV package management with lockfile (`uv.lock`)

## Critical Development Workflows

### Testing Audio Setup

```bash
# ALWAYS run device discovery first - audio device names are system-specific
uv run python test_audio_devices.py
# Copy exact device name output for daemon --device parameter
```

### Running & Debugging

```bash
# Start daemon with specific device (required for most systems)
uv run python whispypy-daemon.py -d "device_name_from_test_script"

# Send recording signals
kill -USR2 <pid>  # or use send_signal.sh

# Debug with verbose output
uv run python whispypy-daemon.py --print-text --keep-audio -d "device_name"
```

### Package Management & Environment

```bash
# Use UV for dependency management (replaces pip/pip-tools)
uv sync               # Install dependencies from uv.lock
uv add <package>      # Add new dependency
uv run python script.py  # Run script in UV environment
```

### Linting & Type Checking

```bash
# The project uses strict linting/typing - run before commits
uv run ruff check .   # Code style (88 char line length)
uv run ruff format .  # Black-compatible formatting
uv run mypy .         # Strict type checking (Python 3.13+)
```

## Key Integration Points

### Audio System Dependencies

- **PipeWire**: Primary audio backend (`pw-record`, `pw-cli`)
- **ALSA**: Fallback for device discovery (`arecord -l`)
- **Clipboard**: Display server detection via `$WAYLAND_DISPLAY` / `$DISPLAY`

### External Command Dependencies

All audio/clipboard operations use subprocess calls - ensure these tools are available:

- `pw-record`, `pw-cli` (PipeWire)
- `wl-copy` (Wayland clipboard)
- `xclip`, `xsel` (X11 clipboard)

### File System Patterns

- Temporary audio: `/tmp/a.au` (hardcoded path)
- Device testing: `/tmp/test_<device_name>.raw` (auto-cleaned)
- No persistent configuration files - all via CLI args

## Common Gotchas

### Device Name Sensitivity

Audio device names are **exact strings** that vary by hardware/drivers. The `test_audio_devices.py` script is essential - device enumeration ≠ device functionality.

### Signal Timing

SIGUSR2 is a toggle - rapid successive signals can cause race conditions. The daemon tracks recording state internally but external callers should wait for "Recording started/stopped" stderr output.

### Python Version Requirement

Requires Python 3.13+ (specified in pyproject.toml). The project uses modern typing features and f-string formatting patterns.

### Audio Format Assumptions

Hardcoded to 16kHz mono f32 format for Whisper compatibility. Changing sample rate/format requires updates to both recording command and Whisper transcription call.
