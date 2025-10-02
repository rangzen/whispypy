# whispypy

A signal-controlled audio transcription daemon using OpenAI Whisper. Record audio on-demand and get real-time transcription with automatic clipboard integration.

> **Note:** This tool is designed for Linux systems only.

## About

This project is a Python rewrite of the original [whispy](https://github.com/daaku/whispy) by [@daaku](https://github.com/daaku). The name "whispypy" comes from the original "whispy" + "py" for Python. Special thanks to daaku for the original implementation and inspiration.

## Features

- 🎙️ Signal-controlled recording (start/stop with SIGUSR2)
- 🎯 Audio device discovery and testing
- 🤖 Multiple Whisper model support
- 📋 Automatic clipboard integration (Wayland/X11)
- 🔧 Configurable audio input devices with persistent configuration
- 📝 Optional text output and audio file retention

## Requirements

- Python 3.13+
- OpenAI Whisper
- **Audio system:**
  - PipeWire (preferred): `pw-record`, `pw-cli`
  - ALSA (fallback): `arecord`
- **Clipboard tools:**
  - Wayland: `wl-copy`
  - X11: `xclip` or `xsel`

## Installation

```bash
# Clone the repository
git clone git@github.com:rangzen/whispypy.git
cd whispypy

# Install dependencies using UV (recommended)
uv sync

# Or install UV first if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

## Usage

### Quick Start

1. **Discover audio devices:**

   ```bash
   uv run python test_audio_devices.py
   ```

2. **Start the daemon:**

   ```bash
   # First time - saves device to config file
   uv run python whispypy-daemon.py -d "your_device_name"
   
   # Subsequent runs - automatically uses saved device
   uv run python whispypy-daemon.py
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

On Ubuntu, you can create a custom shortcut in Settings > Keyboard > Keyboard Shortcuts > View and Customize Shortcuts > Custom Shortcuts. Click the "+" button, name it "Whispypy Toggle Recording", and set the command to the full path of `send_signal.sh` or the pkill command. Then assign your desired key combination, e.g., Ctrl+Shit+t (like talk).

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

#### Step 2: Run Whisper Daemon with Your Device

Copy the working device name from step 1 and use it with the whisper daemon:

```bash
# First time - specify device and save to config
uv run python whispypy-daemon.py --device "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source"

# Subsequent runs - device loaded automatically from config
uv run python whispypy-daemon.py

# Or with short flag for first time
uv run python whispypy-daemon.py -d "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source"

# With specific model (loads device from config)
uv run python whispypy-daemon.py base

# With additional options (loads device from config)
uv run python whispypy-daemon.py --print-text --keep-audio

# Update to different device
uv run python whispypy-daemon.py --device "new_device_name_here"
```

> **Note:** When you specify a device with `--device`, it's automatically saved to `~/.whispypy.conf`. Future runs without `--device` will use the saved device configuration.

#### Step 3: Control Recording

The daemon will show its PID and wait for signals:

```text
Script PID: 12345
To send signal from another terminal: kill -USR2 12345
Using audio device: alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source
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
usage: whispypy-daemon.py [-h] [--device DEVICE] [--print-text] [--keep-audio] [model_path]

Arguments:
  model_path           Whisper model (tiny, base, small, medium, large, large-v2, large-v3) - default: base
  
Options:
  --device, -d DEVICE  Audio input device name. If not provided, loads from ~/.whispypy.conf
  --print-text         Print transcribed text to stdout
  --keep-audio         Keep temporary audio files
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

#### Advanced Usage

```bash
# First setup with larger model (saves device config)
uv run python whispypy-daemon.py large-v3 -d "your_device" --print-text

# Subsequent runs with same config
uv run python whispypy-daemon.py large-v3 --print-text

# Keep audio files for debugging (uses saved device)
uv run python whispypy-daemon.py --keep-audio
```

### Configuration File

The daemon automatically saves your audio device configuration to `~/.whispypy.conf` when you specify `--device`. This allows you to run the daemon without specifying the device every time.

**Configuration behavior:**

- **First run:** Use `--device "your_device_name"` to save the device
- **Subsequent runs:** Simply run `uv run python whispypy-daemon.py` - device loads automatically
- **Change device:** Use `--device "new_device_name"` to update the saved configuration

**Config file format:**

```ini
[DEFAULT]
device = your_device_name_here
```

**Manual config management:**

```bash
# View current config
cat ~/.whispypy.conf

# Remove config (forces device specification on next run)
rm ~/.whispypy.conf
```

## Troubleshooting

If the whisper daemon fails to record:

1. Make sure you used the exact device name from `uv run python test_audio_devices.py`
2. Verify the device is not in use by another application
3. Check audio permissions
4. Re-run `uv run python test_audio_devices.py` to confirm the device still works
5. Make sure `send_signal.sh` is executable: `chmod +x send_signal.sh`

The transcribed text is automatically copied to your clipboard using the appropriate tool for your display server (wl-copy for Wayland, xclip/xsel for X11).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Add your license information here]
