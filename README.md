# whispypy

A signal-controlled audio transcription daemon in Python powered by locally-running OpenAI Whisper or NVIDIA Parakeet. Record audio on demand with system signals and get transcribed text instantly copied to your clipboard.

> **Note:** This tool is designed for Linux systems only.

## Original Project

This project is a Python rewrite of the original [whispy](https://github.com/daaku/whispy) by [@daaku](https://github.com/daaku). The name "whispypy" comes from the original "whispy" + "py" for Python. Special thanks to daaku for the original implementation and inspiration.

Beeps are from [LaSonotheque of Joseph Sardin](https://lasonotheque.org).

![whispypy logo](whispypy-logo.png)
> Whispypy sounds like "ouistiti" (French for marmoset)

<img src="./assets/qr-code.svg" alt="whispypy qrcode" width="200">

## Features

- 🎙️ Signal-controlled recording (start/stop with SIGUSR2)
- 🎯 Audio device discovery and testing
- 🤖 Multiple transcription engines:
  - **OpenAI Whisper** (default): Multiple model sizes (tiny to large-v3)
  - **NVIDIA Parakeet**: High-performance ASR model (nvidia/parakeet-tdt-0.6b-v3)
  - **NVIDIA Parakeet INT8 (Sherpa-ONNX)**: CPU-friendly ONNX engine (auto-downloads a prebuilt model bundle on first run)
- 📋 Automatic clipboard integration (Wayland/X11)
- � Auto-paste functionality (automatically paste transcribed text)
- �🔧 Configurable audio input devices with persistent configuration
- 📝 Optional audio file retention

## Requirements

- Python 3.13+
- **Transcription engines:**
  - OpenAI Whisper (default, always available)
  - NVIDIA Parakeet (optional): Requires `nemo_toolkit[asr]`
  - NVIDIA Parakeet INT8 (optional): Requires `sherpa-onnx`
- **Audio system:**
  - PipeWire (preferred): `pw-record`, `pw-cli`
  - ALSA (fallback): `arecord`
- **Clipboard tools:**
  - Wayland: `wl-copy`
  - X11: `xclip` or `xsel`
- **Auto-paste tools (optional, for `--autopaste` feature):**
  - Wayland: `wtype` or `ydotool`
  - X11: `xdotool`

- **Auto-download tools (optional, for Parakeet INT8 bundle download):**
  - `curl` (preferred) or `wget`, plus `tar`

## Installation

```bash
# Clone the repository
git clone git@github.com:rangzen/whispypy.git
cd whispypy

# Install dependencies using UV (recommended)
uv sync

# Install UV first if you don't have it installed
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### Optional: Install Parakeet Engine

To use NVIDIA Parakeet for transcription, install the NeMo toolkit:

```bash
# Install PyTorch and related packages for CPU-only systems (or with CUDA if you have a GPU)
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
# Install NeMo toolkit with ASR support (required for Parakeet)
uv pip install nemo_toolkit[asr]
# Install specific ONNX version to avoid compatibility issues
uv pip install onnx==1.18.0
```

> **Note:** NeMo installation is large (~2GB) and may take some time. Whisper works out of the box without additional dependencies.
> See <https://github.com/onnx/onnx/issues/7249> for ONNX installation issues.

### Optional: Install Parakeet INT8 (Sherpa-ONNX) Engine

This engine runs Parakeet using Sherpa-ONNX and an INT8 ONNX model bundle.

**Install:**

```bash
# Install optional extra
uv sync --extra parakeet-onnx

# Alternative
uv pip install ".[parakeet-onnx]"
```

**Verify (recommended):**

This will load the model (and auto-download it on first run) and then exit.

```bash
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 --check-model
```

**First-run download behavior:**

- If you do not pass `--parakeet-onnx-dir`, `whispypy` downloads the bundle from the
  `k2-fsa/sherpa-onnx` GitHub Releases (tag `asr-models`) using `curl` (or `wget`) and extracts it with `tar`.
- Default bundle id: `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`
- Cache location:

  ```text
  ${XDG_CACHE_HOME:-~/.cache}/whispypy/models/
  ```

> `--parakeet-onnx-dir` is optional and intended as an override to use a pre-downloaded bundle.

**Selecting a different bundle:**

```bash
# Use a specific Sherpa-ONNX bundle id as the positional argument
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 sherpa-onnx-... -d "your_device_name"

# Or via flag (when not using positional)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 --parakeet-onnx-model-id sherpa-onnx-...
```

**CUDA (optional):**

If your `sherpa-onnx` installation includes CUDA support, you can request it with:

```bash
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 --onnx-provider cuda
```

If CUDA isn't available, `whispypy` will fall back to CPU.

## Usage

### Quick Start

1. **Discover audio devices:**

   ```bash
   uv run python test_audio_devices.py
   ```

2. **Start the daemon:**

   ```bash
   # Default (Whisper engine) - first time saves device to config file
   uv run python whispypy-daemon.py -d "your_device_name"

   # Subsequent runs - automatically uses saved device
   uv run python whispypy-daemon.py

   # Use Parakeet engine (requires NeMo installation)
   uv run python whispypy-daemon.py --engine parakeet nvidia/parakeet-tdt-0.6b-v3 -d "your_device_name"

   # Use Parakeet INT8 via Sherpa-ONNX (auto-download model bundle on first run)
   uv run python whispypy-daemon.py --engine parakeet_onnx_int8 -d "your_device_name"
   ```

3. **Control recording:**

   ```bash
   # Start/stop recording (manual)
   kill -USR2 <daemon_pid>

   # Or use the convenience script (automatic PID detection)
   ./send_signal.sh

   # Stop daemon
   kill -SIGINT <daemon_pid>
   ```

4. **Add a shortcut key:**

   Use your desktop environment's keyboard settings to bind a key combination to run `./send_signal.sh` or `pkill -SIGUSR2 -f whispypy-daemon.py`.

On Ubuntu, you can create a custom shortcut in Settings > Keyboard > Keyboard Shortcuts > View and Customize Shortcuts > Custom Shortcuts. Click the "+" button, name it "Whispypy Toggle Recording", and set the command to the full path of `send_signal.sh` or the pkill command.
E.g. for me, `sh -c -- "~/sources/whispypy/send_signal.sh"`.
Then assign your desired key combination, e.g., Ctrl+Shift+t (t like talk).

### Step-by-Step Guide

#### Step 1: Find Your Audio Device

Run the audio device test script to discover and test available audio devices:

```bash
uv run python test_audio_devices.py
```

This will:

- Automatically discover all available audio input devices
- Let you test specific devices or all devices
- Show which devices are working and their signal strength
- Provide the exact device name to copy

Example output:

```text
🎤 Found 2 audio input device(s):
  1. Raptor Lake-P/U/H cAVS Headphones Stereo Microphone
     Device: alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp__source
  2. Raptor Lake-P/U/H cAVS Digital Microphone
     Device: alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source

=== Test Results Summary ===
🎉 Found 1 working device(s):

  1. ✅ Raptor Lake-P/U/H cAVS Digital Microphone
     📋 Device: alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source
     📊 Signal strength (RMS): 0.003627

🔧 Copy this device name for your whisper daemon:
    alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source
```

#### Step 2: Run Daemon with Your Device

Copy the working device name from step 1 and use it with the daemon:

```bash
# First time - specify device and save to config (default Whisper engine)
uv run python whispypy-daemon.py --device "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source"

# Subsequent runs - device loaded automatically from config
uv run python whispypy-daemon.py

# Or with short flag for first time
uv run python whispypy-daemon.py -d "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source"

# Use Parakeet engine (requires NeMo installation)
uv run python whispypy-daemon.py --engine parakeet nvidia/parakeet-tdt-0.6b-v3 -d "your_device_name"

# Use Parakeet INT8 via Sherpa-ONNX (auto-download model bundle on first run)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 -d "your_device_name"

# Select a specific Sherpa-ONNX bundle id (positional argument)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 -d "your_device_name"

# With specific Whisper model (loads device from config)
uv run python whispypy-daemon.py large-v3

# With additional options (loads device from config)
uv run python whispypy-daemon.py --keep-audio

# Update to different device
uv run python whispypy-daemon.py --device "new_device_name_here"
```

> **Note:** When you specify a device with `--device`, it's automatically saved to `~/.config/whispypy/config.conf`. Future runs without `--device` will use the saved device configuration.

#### Step 3: Control Recording

The daemon will show its PID and wait for signals:

```text
Script PID: 12345
To send signal from another terminal: kill -USR2 12345
Using audio device: alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source
Using transcription engine: whisper
Ready. Send SIGUSR2 to start/stop recording.
```

From another terminal, send signals to control recording:

```bash
# Start recording
kill -USR2 12345

# Stop recording and transcribe (send same signal again)
kill -USR2 12345

# Or use the convenience script (finds PID automatically)
./send_signal.sh

# Stop the daemon
kill -SIGINT 12345
# or press Ctrl+C in the daemon terminal
```

### Command Line Options

#### test_audio_devices.py

- No arguments needed - automatically discovers and tests devices
- Interactive menu for device selection

#### whispypy-daemon.py

```text
usage: whispypy-daemon.py [-h] [--engine {whisper,parakeet,parakeet_onnx_int8}] [--parakeet-onnx-dir PARAKEET_ONNX_DIR] [--parakeet-onnx-model-id PARAKEET_ONNX_MODEL_ID] [--parakeet-onnx-cache-dir PARAKEET_ONNX_CACHE_DIR] [--onnx-provider {cpu,cuda}] [--onnx-threads ONNX_THREADS] [--check-model] [--device DEVICE] [--keep-audio] [--autopaste] [--verbose] [model_path]

Arguments:
  model_path           Model path or name. For Whisper: tiny, base, small, medium, large, large-v2, large-v3. For Parakeet: nvidia/parakeet-tdt-0.6b-v3. For parakeet_onnx_int8: optional sherpa-onnx bundle id (omit or use "base" to use default from --parakeet-onnx-model-id)

Options:
  --engine, -e {whisper,parakeet,parakeet_onnx_int8}  Transcription engine to use (default: whisper)
  --parakeet-onnx-dir PARAKEET_ONNX_DIR                Directory with encoder/decoder/joiner/tokens (advanced; bypass auto-download)
  --parakeet-onnx-model-id PARAKEET_ONNX_MODEL_ID      Sherpa-ONNX bundle id to download (default: sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8)
  --parakeet-onnx-cache-dir PARAKEET_ONNX_CACHE_DIR    Override cache directory for auto-downloaded bundles
  --onnx-provider {cpu,cuda}                           Execution provider for sherpa-onnx (cuda falls back to cpu if unavailable)
  --onnx-threads ONNX_THREADS                          Number of threads for sherpa-onnx (default: auto)
  --check-model                                       Load the selected model and exit
  --device, -d DEVICE              Audio input device name. If not provided, loads from ~/.config/whispypy/config.conf
  --keep-audio                     Keep temporary audio files
  --autopaste                      Automatically paste transcribed text after copying to clipboard
  --verbose, -v                    Enable verbose logging
```

### Examples

#### Quick Setup

```bash
# 1. Test devices
uv run python test_audio_devices.py

# 2. Copy the working device name and run daemon (saves config)
uv run python whispypy-daemon.py -d "your_working_device_name"

# 3. Next time, just run without device (uses saved config)
uv run python whispypy-daemon.py
```

#### Engine Selection

```bash
# Default Whisper engine with base model
uv run python whispypy-daemon.py

# Whisper with larger model
uv run python whispypy-daemon.py large-v3

# Parakeet engine (requires NeMo installation)
uv run python whispypy-daemon.py --engine parakeet nvidia/parakeet-tdt-0.6b-v3

# Parakeet with device specification (first time)
uv run python whispypy-daemon.py -e parakeet nvidia/parakeet-tdt-0.6b-v3 -d "your_device"

# Parakeet INT8 via Sherpa-ONNX (auto-download model bundle on first run)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8

# Parakeet INT8 via Sherpa-ONNX (explicit bundle id as positional argument)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8

# Parakeet INT8 via Sherpa-ONNX (prefer CUDA; falls back to CPU)
uv run python whispypy-daemon.py --engine parakeet_onnx_int8 --onnx-provider cuda
```

#### Advanced Usage

```bash
# First setup with larger model (saves device config)
uv run python whispypy-daemon.py large-v3 -d "your_device" --verbose

# Subsequent runs with same config
uv run python whispypy-daemon.py large-v3 --verbose

# Keep audio files for debugging (uses saved device)
uv run python whispypy-daemon.py --keep-audio

# Auto-paste transcribed text directly (copies to clipboard AND pastes automatically)
uv run python whispypy-daemon.py --autopaste

# Combine autopaste with other options
uv run python whispypy-daemon.py large-v3 --autopaste --verbose

# Parakeet with verbose logging
uv run python whispypy-daemon.py -e parakeet nvidia/parakeet-tdt-0.6b-v3 --verbose
```

#### Auto-Paste Feature

The `--autopaste` flag enables automatic pasting of transcribed text directly into the currently focused application:

- **Normal mode**: Text is copied to clipboard only
- **Auto-paste mode**: Text is copied to clipboard AND automatically pasted

**Requirements for auto-paste:**

- **Wayland**: Install `wtype`, `ydotool`, or `dotool`

  ```bash
  # Debian/Ubuntu
  sudo apt install wtype ydotool

  # Arch Linux
  sudo pacman -S wtype ydotool

  # dotool (from source)
  # See: https://git.sr.ht/~geb/dotool
  ```

- **X11**: Install `xdotool`

  ```bash
  # Debian/Ubuntu
  sudo apt install xdotool

  # Arch Linux
  sudo pacman -S xdotool
  ```

**Usage example:**

1. Focus the application where you want the text (text editor, terminal, browser, etc.)
2. Start recording with `./send_signal.sh` through your shortcut to not lose focus
3. Speak your text
4. Stop recording with `./send_signal.sh` through your shortcut again...
5. Text is automatically pasted in the focused application

> **Note:** Auto-paste simulates `Ctrl+V` keypress. If auto-paste fails, the text is still available in the clipboard for manual pasting.

### Configuration File

The daemon automatically saves your audio device configuration to `~/.config/whispypy/config.conf` when you specify `--device`. This allows you to run the daemon without specifying the device every time.

**Configuration behavior:**

- **First run:** Use `--device "your_device_name"` to save the device
- **Subsequent runs:** Simply run `uv run python whispypy-daemon.py` - device loads automatically
- **Change device:** Use `--device "new_device_name"` to update the saved configuration

**Config file format:**

You can check an example configuration file with `config.conf.example`.

```ini
[DEFAULT]
device = your_device_name_here
# Optional: Configure dotool keyboard layout for autopaste (Wayland only)
dotool_xkb_layout = fr
dotool_xkb_variant = bepo
```

**Supported configuration options:**

- `device`: Audio input device name
- `dotool_xkb_layout`: XKB keyboard layout for dotool (used in Wayland autopaste fallback)
- `dotool_xkb_variant`: XKB keyboard variant for dotool (used in Wayland autopaste fallback)

> **Note:** The dotool settings are only used as a fallback when primary paste tools (wtype, ydotool) are not available on Wayland systems.

**Manual config management:**

```bash
# View current config
cat ~/.config/whispypy/config.conf

# Remove config (forces device specification on next run)
rm ~/.config/whispypy/config.conf
```

## Troubleshooting

### General Issues

If the daemon fails to record:

1. Make sure you used the exact device name from `uv run python test_audio_devices.py`
2. Verify the device is not in use by another application
3. Check audio permissions
4. Re-run `uv run python test_audio_devices.py` to confirm the device still works
5. Make sure `send_signal.sh` is executable: `chmod +x send_signal.sh`

### Engine-Specific Issues

#### Whisper Engine

- **Model download fails**: Check internet connection; models are downloaded on first use
- **Slow transcription**: Try smaller models (`tiny`, `base`) for faster processing
- **Memory issues**: Use smaller models or check available RAM

#### Parakeet Engine

- **Model download timeout**: Parakeet models are large (~600MB); ensure stable internet connection
- **CUDA warnings**: Parakeet will use CPU if CUDA isn't available (slower but functional)
- **Import warnings**: NeMo may show warnings about missing optional dependencies; these are usually harmless

### Audio Format Issues

The daemon automatically handles different audio formats:

- **Whisper**: Uses raw f32 audio data (`.au` files)
- **Parakeet**: Uses standard audio files (`.wav` files)

### Performance Comparison

- **Whisper**: Better for general use, multiple languages, smaller models available
- **Parakeet**: Optimized for English, potentially faster with GPU acceleration

The transcribed text is automatically copied to your clipboard using the appropriate tool for your display server (wl-copy for Wayland, xclip/xsel for X11).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

Do as you wish. Have fun.
