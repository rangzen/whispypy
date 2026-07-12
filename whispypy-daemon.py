#!/usr/bin/env python3

import argparse
import configparser
from contextlib import contextmanager
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Generator, Optional

from src.whispypy.engines.base import SAMPLE_RATE, TranscriptionEngine
from src.whispypy.engines.parakeet_onnx_engine import (
    DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL,
)

# Audio file constants
BEEP_START_FILENAME = "BEEPTimer_Montre_numerique_bip_2_ID_2255_LS.wav"
BEEP_COMPLETE_FILENAME = "BEEPTimer_Montre_numerique_bip_1_ID_2254_LS.wav"

# Audio recording constants
CHANNELS = 1  # Mono audio

# Timing and validation constants
DEVICE_TEST_DURATION = 1.0  # seconds - Duration for device validation test

# File paths (will be replaced with proper temp files)
TEMP_AUDIO_FILENAME = "whispy_recording"  # Base filename for temporary audio; all recordings are standardized to WAV

# Terminal detection constants
TERMINAL_KEYWORDS = [
    "term",
    "konsole",
    "kitty",
    "alacritty",
    "ghostty",
    "wezterm",
    "foot",
    "gnome-terminal",
    "xterm",
    "urxvt",
    "st",
]  # Common terminal identifiers for window class/title matching

# State files for external indicators (e.g., Waybar)
RECORDING_STATE_FILE = Path("/tmp/whispypy_recording")
READY_STATE_FILE = Path("/tmp/whispypy_ready")


def get_config_file() -> Path:
    """Get the configuration file path following XDG Base Directory specification."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    config_dir = Path(xdg_config_home) / "whispypy"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.conf"


# Configuration
CONFIG_FILE = get_config_file()


class ConfigManager:
    """Manages configuration file operations with cached config parsing."""

    def __init__(self, config_file: Path = CONFIG_FILE):
        self.config_file = config_file
        self._config: Optional[configparser.ConfigParser] = None
        self._config_mtime: Optional[float] = None

    def _get_config(self) -> Optional[configparser.ConfigParser]:
        """Get cached config, reloading if file changed."""
        if not self.config_file.exists():
            self._config = None
            self._config_mtime = None
            return None

        current_mtime = self.config_file.stat().st_mtime
        if self._config is None or self._config_mtime != current_mtime:
            self._config = configparser.ConfigParser()
            self._config.read(self.config_file)
            self._config_mtime = current_mtime

        return self._config

    def _invalidate_cache(self) -> None:
        """Invalidate cached config after writes."""
        self._config = None
        self._config_mtime = None

    def _load_config_value(
        self, key: str, log_msg: Optional[str] = None, log_level: str = "info"
    ) -> Optional[str]:
        """Generic method to load a config value."""
        config = self._get_config()
        if config is None:
            return None

        try:
            value = config.get("DEFAULT", key, fallback=None)
            if value and log_msg:
                getattr(logging, log_level)(log_msg.format(value=value))
            return value
        except Exception as e:
            logging.debug(f"Error reading {key} from config: {e}")
            return None

    def save_device(self, device: str) -> None:
        """Save device configuration to config file."""
        config = self._get_config() or configparser.ConfigParser()

        if "DEFAULT" not in config:
            config.add_section("DEFAULT")

        config.set("DEFAULT", "device", device)

        with open(self.config_file, "w") as f:
            config.write(f)

        self._invalidate_cache()
        logging.info(f"Device '{device}' saved to {self.config_file}")

    def load_device(self) -> Optional[str]:
        """Load device configuration from config file."""
        return self._load_config_value(
            "device", "Using device from config: {value}", "info"
        )

    def load_dotool_layout(self) -> Optional[str]:
        """Load DOTOOL_XKB_LAYOUT configuration from config file."""
        return self._load_config_value(
            "dotool_xkb_layout", "Using dotool XKB layout from config: {value}", "debug"
        )

    def load_dotool_variant(self) -> Optional[str]:
        """Load DOTOOL_XKB_VARIANT configuration from config file."""
        return self._load_config_value(
            "dotool_xkb_variant",
            "Using dotool XKB variant from config: {value}",
            "debug",
        )

    def validate_config(self) -> bool:
        """Validate configuration file format and values."""
        config = self._get_config()
        if config is None:
            return True  # No config file is valid (will use defaults)

        try:
            # Check if DEFAULT section exists
            if "DEFAULT" not in config:
                logging.warning("Configuration file missing DEFAULT section")
                return False

            # Validate device if present
            device = config.get("DEFAULT", "device", fallback=None)
            if device:
                # Basic validation - device name should not be empty
                if not device.strip():
                    logging.warning("Device name in config is empty")
                    return False

                # Validate device name format (basic checks)
                if len(device.strip()) < 3:
                    logging.warning("Device name appears too short, may be invalid")
                    return False

            # Validate other audio-related settings if present
            # Validate sample_rate if present
            sample_rate_value = config.get("DEFAULT", "sample_rate", fallback=None)
            if sample_rate_value is not None:
                try:
                    sample_rate = int(sample_rate_value)
                    valid_sample_rates = [8000, 16000, 22050, 44100, 48000]
                    if sample_rate not in valid_sample_rates:
                        logging.warning(
                            f"Invalid sample_rate value '{sample_rate}'. "
                            f"Valid values: {valid_sample_rates}"
                        )
                        return False
                except ValueError:
                    logging.warning(
                        f"Invalid sample_rate value '{sample_rate_value}' - not an integer"
                    )
                    return False

            # Validate channels if present
            channels_value = config.get("DEFAULT", "channels", fallback=None)
            if channels_value is not None:
                try:
                    channels = int(channels_value)
                    valid_channels = [1, 2]
                    if channels not in valid_channels:
                        logging.warning(
                            f"Invalid channels value '{channels}'. "
                            f"Valid values: {valid_channels}"
                        )
                        return False
                except ValueError:
                    logging.warning(
                        f"Invalid channels value '{channels_value}' - not an integer"
                    )
                    return False

            # Validate audio_format if present
            audio_format_value = config.get("DEFAULT", "audio_format", fallback=None)
            if audio_format_value is not None:
                audio_format = audio_format_value.strip()
                valid_formats = ["f32", "s16", "s24", "s32"]
                if audio_format not in valid_formats:
                    logging.warning(
                        f"Invalid audio_format value '{audio_format}'. "
                        f"Valid values: {valid_formats}"
                    )
                    return False

            # Validate dotool_xkb_layout if present
            dotool_layout_value = config.get(
                "DEFAULT", "dotool_xkb_layout", fallback=None
            )
            if dotool_layout_value is not None:
                dotool_layout = dotool_layout_value.strip()
                if not dotool_layout:
                    logging.warning("dotool_xkb_layout value is empty")
                    return False

            # Validate dotool_xkb_variant if present
            dotool_variant_value = config.get(
                "DEFAULT", "dotool_xkb_variant", fallback=None
            )
            if dotool_variant_value is not None:
                dotool_variant = dotool_variant_value.strip()
                if not dotool_variant:
                    logging.warning("dotool_xkb_variant value is empty")
                    return False

            logging.debug("Configuration validation successful")
            return True

        except Exception as e:
            logging.error(f"Configuration validation failed: {e}")
            return False


def _play_beep_file(filename: str, beep_type: str) -> None:
    """Play a beep sound file with fallback options.

    Args:
        filename: The beep sound filename (from the assets directory)
        beep_type: Description of the beep type for logging (e.g., "start", "completion")
    """
    # Construct path to beep sound file
    beep_file = Path(__file__).parent / "assets" / filename

    if not beep_file.exists():
        logging.debug(f"Beep file not found: {beep_file}")
        _try_terminal_beep_fallback(beep_type)
        return

    # Audio players to try, in order of preference
    audio_players = [
        "aplay",  # ALSA player
        "paplay",  # PulseAudio player
        "pw-play",  # PipeWire player
    ]

    for player in audio_players:
        if _try_audio_player(player, str(beep_file), beep_type):
            return

    # All audio players failed, try terminal beep
    _try_terminal_beep_fallback(beep_type)


def _try_audio_player(player: str, audio_file: str, beep_type: str) -> bool:
    """Try to play audio with a specific player.

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            [player, audio_file],
            capture_output=True,
            text=True,
            timeout=10,  # 10 second timeout
            check=False,  # Don't raise exception on non-zero exit
        )

        if result.returncode == 0:
            logging.debug(f"{beep_type.capitalize()} beep played via {player}")
            return True
        else:
            # Log the actual error for debugging
            error_parts = [f"exit code {result.returncode}"]
            if result.stderr.strip():
                error_parts.append(f"stderr: {result.stderr.strip()}")
            logging.debug(f"{player} failed: {', '.join(error_parts)}")
            return False

    except subprocess.TimeoutExpired:
        logging.debug(f"{player} timed out after 10 seconds")
        return False
    except FileNotFoundError:
        logging.debug(f"{player} command not found")
        return False
    except PermissionError:
        logging.debug(f"{player} permission denied")
        return False
    except Exception as e:
        logging.debug(f"{player} failed with exception: {e}")
        return False


def _try_terminal_beep_fallback(beep_type: str) -> None:
    """Try to play terminal beep as fallback."""
    try:
        result = subprocess.run(
            ["printf", "\\a"], capture_output=True, text=True, timeout=5, check=False
        )

        if result.returncode == 0:
            logging.debug(f"{beep_type.capitalize()} beep played via printf (fallback)")
        else:
            logging.debug(f"Terminal beep failed with exit code {result.returncode}")
            logging.debug(f"Could not play {beep_type} beep")

    except Exception as e:
        logging.debug(f"Terminal beep failed with exception: {e}")
        logging.debug(f"Could not play {beep_type} beep")


def play_start_beep() -> None:
    """Play a start beep sound to indicate recording is starting."""
    _play_beep_file(BEEP_START_FILENAME, "start")


def play_completion_beep() -> None:
    """Play a completion beep sound to indicate transcription is ready."""
    _play_beep_file(BEEP_COMPLETE_FILENAME, "completion")


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using the appropriate tool for the current display server."""
    # Check if we're on Wayland
    if os.getenv("WAYLAND_DISPLAY"):
        # Use wl-copy for Wayland
        try:
            subprocess.run(["wl-copy", text], check=True)
            logging.info("Text copied to clipboard (wl-copy)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.warning(f"wl-copy failed: {e}")

    # Check if we're on X11
    if os.getenv("DISPLAY"):
        # Try xclip first (more common)
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"], input=text, text=True, check=True
            )
            logging.info("Text copied to clipboard (xclip)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to xsel
            try:
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text,
                    text=True,
                    check=True,
                )
                logging.info("Text copied to clipboard (xsel)")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logging.warning(f"X11 clipboard tools failed: {e}")

    # Fallback: try to detect clipboard tools
    clipboard_tools = [
        (["xclip", "-selection", "clipboard"], True),  # input via stdin
        (["xsel", "--clipboard", "--input"], True),  # input via stdin
        (["wl-copy"], False),  # text as argument
    ]

    for cmd, use_stdin in clipboard_tools:
        try:
            if use_stdin:
                subprocess.run(cmd, input=text, text=True, check=True)
            else:
                subprocess.run(cmd + [text], check=True)
            tool_name = cmd[0]
            logging.info(f"Text copied to clipboard ({tool_name})")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    logging.error("Failed to copy to clipboard: no suitable clipboard tool found")
    return False


def _detect_terminal_window() -> bool:
    """Detect if the focused window is a terminal application.

    Returns True if terminal detected, False otherwise (including on detection failure).
    """
    # Try Wayland (Hyprland) detection first
    if os.getenv("WAYLAND_DISPLAY"):
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                check=True,
            )
            window_info = json.loads(result.stdout)
            window_class = window_info.get("class", "").lower()
            window_title = window_info.get("title", "").lower()
            is_terminal = any(
                keyword in window_class or keyword in window_title
                for keyword in TERMINAL_KEYWORDS
            )
            logging.debug(f"Window class: {window_class}, is_terminal: {is_terminal}")
            return is_terminal
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
            pass

    # Try X11 detection
    if os.getenv("DISPLAY"):
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowclassname"],
                capture_output=True,
                text=True,
                check=True,
            )
            window_class = result.stdout.strip().lower()
            window_title = ""
            try:
                title_result = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                window_title = title_result.stdout.strip().lower()
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

            is_terminal = any(
                keyword in window_class or keyword in window_title
                for keyword in TERMINAL_KEYWORDS
            )
            logging.debug(f"Window class: {window_class}, is_terminal: {is_terminal}")
            return is_terminal
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    logging.debug("Could not detect window type, defaulting to GUI paste")
    return False


def paste_from_clipboard() -> bool:
    """Paste text from clipboard using the appropriate tool for the current display server."""
    # Check if we're on Wayland
    if os.getenv("WAYLAND_DISPLAY"):
        logging.debug("Detected Wayland display server for pasting")
        is_terminal = _detect_terminal_window()

        # Use wtype for Wayland (simulates typing)
        # Use Ctrl+Shift+V for terminals, Ctrl+V for GUI apps
        try:
            if is_terminal:
                logging.debug(
                    "Attempting to paste using wtype with Ctrl+Shift+V (terminal)"
                )
                subprocess.run(["wtype", "-M", "ctrl", "-M", "shift", "v"], check=True)
                logging.info("Pasted from clipboard (wtype with Ctrl+Shift+V)")
            else:
                logging.debug("Attempting to paste using wtype with Ctrl+V (GUI)")
                subprocess.run(["wtype", "-M", "ctrl", "v"], check=True)
                logging.info("Pasted from clipboard (wtype with Ctrl+V)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # If wtype failed, try ydotool
        try:
            # Add small delay before paste to let window manager settle
            time.sleep(0.1)
            # Use key codes: 29 is left ctrl, 42 is left shift, 47 is v
            # Format: "keycode:state" where :1 = key down, :0 = key up
            if is_terminal:
                logging.debug(
                    "Attempting to paste using ydotool with Ctrl+Shift+V (terminal)"
                )
                subprocess.run(
                    ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
                    check=True,
                )
                logging.info("Pasted from clipboard (ydotool with Ctrl+Shift+V)")
            else:
                logging.debug("Attempting to paste using ydotool with Ctrl+V (GUI)")
                subprocess.run(
                    ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], check=True
                )
                logging.info("Pasted from clipboard (ydotool with Ctrl+V)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Final fallback: try wl-paste + dotool with layout settings
            try:
                logging.debug("Attempting to paste using dotool with layout settings")
                # Load dotool configuration
                config_manager = ConfigManager()
                dotool_layout = config_manager.load_dotool_layout()
                dotool_variant = config_manager.load_dotool_variant()

                # Build command with optional environment variables
                env_vars = []
                if dotool_layout:
                    env_vars.append(f"DOTOOL_XKB_LAYOUT={dotool_layout}")
                if dotool_variant:
                    env_vars.append(f"DOTOOL_XKB_VARIANT={dotool_variant}")

                env_prefix = " ".join(env_vars)
                if env_prefix:
                    command = f"wl-paste | sed 's/^/type /' | {env_prefix} dotool"
                else:
                    command = "wl-paste | sed 's/^/type /' | dotool"

                subprocess.run(
                    command,
                    shell=True,
                    check=True,
                )
                logging.info("Pasted from clipboard (dotool)")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass

    # Check if we're on X11
    if os.getenv("DISPLAY"):
        is_terminal = _detect_terminal_window()

        # Use xdotool for X11 - Ctrl+Shift+V for terminals, Ctrl+V for GUI apps
        try:
            if is_terminal:
                logging.debug(
                    "Attempting to paste using xdotool with Ctrl+Shift+V (terminal)"
                )
                subprocess.run(["xdotool", "key", "ctrl+shift+v"], check=True)
                logging.info("Pasted from clipboard (xdotool with Ctrl+Shift+V)")
            else:
                logging.debug("Attempting to paste using xdotool with Ctrl+V (GUI)")
                subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
                logging.info("Pasted from clipboard (xdotool with Ctrl+V)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.warning(f"xdotool failed: {e}")

    # Fallback: try all available paste tools
    time.sleep(0.1)
    paste_tools = [
        ["xdotool", "key", "ctrl+v"],  # X11
        ["wtype", "-M", "ctrl", "v"],  # Wayland
        [
            "ydotool",
            "key",
            "29:1",
            "47:1",
            "47:0",
            "29:0",
        ],  # Wayland alternative (ctrl+v)
    ]

    for cmd in paste_tools:
        try:
            subprocess.run(cmd, check=True)
            tool_name = cmd[0]
            logging.info(f"Pasted from clipboard ({tool_name})")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue

    logging.error("Failed to paste from clipboard: no suitable paste tool found")
    logging.error("Available tools: xdotool (X11), wtype/ydotool (Wayland)")
    return False


@contextmanager
def managed_subprocess(
    args: list[str],
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Context manager for subprocess handling with proper cleanup."""
    proc = None
    try:
        proc = subprocess.Popen(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        yield proc
    finally:
        if proc:
            proc.terminate()
            proc.wait()


class WhispypyDaemon:
    """Signal-controlled audio transcription daemon."""

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

        # All recordings are standardized to WAV format.
        self.temp_audio_file = Path(tempfile.gettempdir()) / (
            TEMP_AUDIO_FILENAME + ".wav"
        )
        self.temp_raw_file: Optional[Path] = None

        # State
        self.recording = False
        self.running = True
        self.pw_record_proc: Optional[subprocess.Popen[bytes]] = None

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

    def _is_alsa_device(self) -> bool:
        """Return True if device_name looks like a raw ALSA device."""
        return self.device_name.startswith(("hw:", "plughw:"))

    def _get_alsa_device(self) -> str:
        """Get ALSA device name, converting hw: to plughw: for format conversion."""
        if self.device_name.startswith("hw:"):
            return self.device_name.replace("hw:", "plughw:", 1)
        return self.device_name

    def validate_device(self) -> bool:
        """Validate that the audio device exists and is accessible."""
        try:
            # ALSA records a WAV container directly; PipeWire records raw samples.
            suffix = ".wav" if self._is_alsa_device() else ".raw"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as test_file:
                test_file_path = test_file.name

            if self._is_alsa_device():
                # ALSA: use arecord with the same device transformation as recording
                with managed_subprocess(
                    [
                        "arecord",
                        "-D",
                        self._get_alsa_device(),
                        "-f",
                        "S16_LE",
                        "-r",
                        str(SAMPLE_RATE),
                        "-c",
                        str(CHANNELS),
                        "-t",
                        "wav",
                        test_file_path,
                    ]
                ) as _:
                    time.sleep(DEVICE_TEST_DURATION)
            else:
                # PipeWire: use pw-record with the engine's declared sample format
                pw_format = self.engine.get_pipewire_format()
                with managed_subprocess(
                    [
                        "pw-record",
                        f"--target={self.device_name}",
                        f"--format={pw_format}",
                        f"--rate={SAMPLE_RATE}",
                        f"--channels={CHANNELS}",
                        test_file_path,
                    ]
                ) as _:
                    # Let it record for the test duration then it will be terminated
                    time.sleep(DEVICE_TEST_DURATION)

            size = Path(test_file_path).stat().st_size
            # Clean up test file
            Path(test_file_path).unlink(missing_ok=True)

            if size == 0:
                logging.debug("Device validation produced empty audio file")
                return False

            # If we got here without exception, the device is accessible
            return True

        except Exception as e:
            logging.debug(f"Device validation failed: {e}")
            return False

    def _handle_sigint(self, signum: int, frame: Any) -> None:
        """Handle SIGINT (Ctrl+C) for clean shutdown."""
        logging.info("Received SIGINT (Ctrl+C). Shutting down...")

        # Stop any ongoing recording
        if self.recording and self.pw_record_proc:
            logging.info("Stopping ongoing recording...")
            self.pw_record_proc.terminate()
            self.pw_record_proc.wait()

        # Remove ready state file
        try:
            READY_STATE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        self.running = False

    def _handle_sigusr2(self, signum: int, frame: Any) -> None:
        """Handle SIGUSR2 signal to toggle recording state."""
        try:
            logging.info(
                f"Received SIGUSR2 signal! Current recording state: {self.recording}"
            )

            if not self.recording:
                self._start_recording()
            else:
                self._stop_recording_and_transcribe()

        except Exception as e:
            logging.error(f"Error in signal handler: {e}")
            import traceback

            traceback.print_exc()

    def _start_recording(self) -> None:
        """Start audio recording."""
        logging.info("Starting recording...")
        play_start_beep()

        if self._is_alsa_device():
            # ALSA can record directly to a WAV file.
            self.temp_raw_file = None
            cmd = [
                "arecord",
                "-D",
                self._get_alsa_device(),
                "-f",
                "S16_LE",
                "-r",
                str(SAMPLE_RATE),
                "-c",
                str(CHANNELS),
                "-t",
                "wav",
                str(self.temp_audio_file),
            ]
        else:
            # PipeWire records raw samples, which we'll convert to WAV afterward.
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

        self.pw_record_proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        self.recording = True
        # Create state file for external indicators (e.g., Waybar)
        try:
            RECORDING_STATE_FILE.touch()
        except Exception as e:
            # State file creation failed, but recording is already started
            # Log warning but don't abort - recording is more important
            logging.warning(
                f"Failed to create recording state file: {e}", exc_info=True
            )
        logging.info("Recording started successfully")

    def _convert_raw_to_wav(
        self, raw_path: Path, wav_path: Path, sample_format: str
    ) -> bool:
        """Convert a raw audio file to WAV format. Returns True on success, False on failure."""
        try:
            import numpy as np
            import soundfile as sf
        except ImportError:
            logging.error(
                "The 'soundfile' and 'numpy' libraries are required for PipeWire recordings."
            )
            logging.error("Please install them with: pip install soundfile numpy")
            return False

        dtype = np.float32 if sample_format == "f32" else np.int16
        try:
            data = np.fromfile(raw_path, dtype=dtype)
            # Use FLOAT subtype for f32 sources to avoid a lossy f32->PCM_16->f32 roundtrip.
            # PCM_16 is required for s16 sources because SherpaOnnxParakeetInt8Transcriber
            # validates sampwidth == 2 and raises ValueError otherwise.
            subtype = "FLOAT" if sample_format == "f32" else "PCM_16"
            sf.write(wav_path, data, SAMPLE_RATE, subtype=subtype)
            logging.info(f"Successfully converted {raw_path} to {wav_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to convert raw audio to WAV: {e}")
            return False

    def _stop_recording_and_transcribe(self) -> None:
        """Stop recording, convert if necessary, and transcribe."""
        logging.info("Stopping recording...")
        if self.pw_record_proc:
            self.pw_record_proc.terminate()
            self.pw_record_proc.wait()
            self.pw_record_proc = None
        self.recording = False
        # Remove state file for external indicators (e.g., Waybar)
        try:
            RECORDING_STATE_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        logging.info("Recording stopped")

        # Check if the recorded audio file exists and has content.
        recorded_file = (
            self.temp_raw_file if self.temp_raw_file else self.temp_audio_file
        )
        if not recorded_file.exists():
            logging.error(f"Audio file {recorded_file} not found!")
            return

        file_size = recorded_file.stat().st_size
        logging.info(f"Audio file size: {file_size} bytes")

        if file_size == 0:
            logging.warning("Audio file is empty!")
            return

        # If we recorded from PipeWire, convert the raw file to WAV.
        if self.temp_raw_file:
            pw_format = self.engine.get_pipewire_format()
            converted = self._convert_raw_to_wav(
                self.temp_raw_file, self.temp_audio_file, pw_format
            )
            if not self.keep_audio:
                self.temp_raw_file.unlink()
            if not converted:
                return

        # Transcribe the final WAV file.
        logging.info("Transcribing...")
        transcription_start = time.time()

        text = self.engine.transcribe(self.temp_audio_file)

        transcription_time = time.time() - transcription_start

        logging.info(f"Transcription completed in {transcription_time:.2f} seconds")
        logging.info(f"Transcription result: '{text}'")

        if not self.keep_audio:
            self.temp_audio_file.unlink(missing_ok=True)

        # Copy text to clipboard
        copy_to_clipboard(text)

        # Auto-paste if enabled
        if self.autopaste:
            logging.info("Auto-pasting transcribed text...")
            # Small delay to ensure clipboard is ready
            time.sleep(0.1)
            paste_success = paste_from_clipboard()
            if not paste_success:
                logging.warning("Auto-paste failed, but text is still in clipboard")
        else:
            # Play completion beep only when autopaste is disabled
            # When autopaste is enabled, the text is automatically pasted so no beep needed
            # to know when it's ready
            play_completion_beep()

    def run(self) -> None:
        """Run the daemon main loop."""
        # Print PID for easy signal sending
        pid = os.getpid()
        logging.info(f"Script PID: {pid}")
        logging.info(
            f"To send signal start/stop from another terminal: kill -USR2 {pid}"
        )
        logging.info(f"To send signal exit from another terminal: kill -SIGINT {pid}")
        logging.info(f"Using audio device: {self.device_name}")
        logging.info(f"Using transcription engine: {type(self.engine).__name__}")
        if self.autopaste:
            logging.info(
                "Auto-paste is enabled - transcribed text will be pasted automatically"
            )
        else:
            logging.info(
                "Auto-paste is disabled - transcribed text will only be copied to clipboard"
            )

        # Validate device before starting
        if not self.validate_device():
            logging.error(
                f"Audio device '{self.device_name}' is not accessible or working"
            )
            logging.error("Please run test_audio_devices.py to find a working device")
            sys.exit(1)

        logging.info("Device validation successful")
        logging.info("Ready. Send SIGUSR2 to start/stop recording.")
        logging.info("Press Ctrl+C to exit.")

        # Create ready state file for external indicators (e.g., Waybar)
        try:
            READY_STATE_FILE.touch()
        except Exception as e:
            logging.warning(f"Could not create ready state file: {e}")

        # Initial beep to indicate readiness
        play_completion_beep()

        # Wait for signals
        try:
            while self.running:
                signal.pause()
        except KeyboardInterrupt:
            # This shouldn't happen since we handle SIGINT, but just in case
            self.running = False

        logging.info("Daemon stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audio transcription with signal control using Whisper or Parakeet"
    )
    parser.add_argument(
        "model_path",
        nargs="?",
        default="base",
        help=(
            "Path to the model or model name. "
            "For Whisper: tiny, base, small, medium, large, large-v2, large-v3. "
            "For Parakeet (NeMo): nvidia/parakeet-tdt-0.6b-v3. "
            "For Parakeet INT8 (Sherpa-ONNX): optionally pass a sherpa-onnx bundle id as the positional argument (default: base)"
        ),
    )
    parser.add_argument(
        "--engine",
        "-e",
        choices=["whisper", "parakeet", "parakeet_onnx_int8"],
        default="whisper",
        help="Transcription engine to use (default: whisper)",
    )

    parser.add_argument(
        "--parakeet-onnx-dir",
        default=None,
        help="Directory containing encoder.int8.onnx/decoder.int8.onnx/joiner.int8.onnx/tokens.txt. If omitted, whispypy will auto-download the model bundle.",
    )
    parser.add_argument(
        "--parakeet-onnx-model-id",
        default=DEFAULT_SHERPA_ONNX_PARAKEET_INT8_MODEL,
        help="Sherpa-ONNX model bundle ID to download when --parakeet-onnx-dir is omitted",
    )
    parser.add_argument(
        "--parakeet-onnx-cache-dir",
        default=None,
        help="Override cache directory for auto-downloaded sherpa-onnx models (defaults to XDG cache)",
    )
    parser.add_argument(
        "--onnx-provider",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Execution provider for sherpa-onnx (default: cpu). If cuda is unavailable, it will fall back to cpu.",
    )
    parser.add_argument(
        "--onnx-threads",
        type=int,
        default=None,
        help="Number of threads for sherpa-onnx (default: auto)",
    )
    parser.add_argument(
        "--check-model",
        action="store_true",
        help="Load the selected model and exit (useful for verifying parakeet_onnx_int8 setup)",
    )
    parser.add_argument(
        "--device",
        "-d",
        default=None,
        help="Audio input device name. If not provided, will try to load from XDG config (~/.config/whispypy/config.conf). Use test_audio_devices.py to find working devices.",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the temporary audio file after transcription",
    )
    parser.add_argument(
        "--autopaste",
        action="store_true",
        help="Automatically paste transcribed text after copying to clipboard",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Validate engine availability
    if args.engine == "parakeet":
        if importlib.util.find_spec("nemo.collections.asr") is None:
            logging.error("Parakeet engine selected but NeMo is not available.")
            logging.error("Please see README for installation instructions.")
            sys.exit(1)

    if args.engine == "parakeet_onnx_int8":
        if importlib.util.find_spec("sherpa_onnx") is None:
            logging.error(
                "parakeet_onnx_int8 engine selected but sherpa-onnx is not available."
            )
            sys.exit(1)

        model_id = args.parakeet_onnx_model_id

        # Mimic the whisper/nemo flow: positional argument selects model.
        if args.model_path != "base":
            if not args.model_path.startswith("sherpa-onnx-"):
                logging.error(
                    "For --engine parakeet_onnx_int8, the positional model must be a sherpa-onnx model bundle id starting with 'sherpa-onnx-' (got: %s). "
                    "Either omit the positional argument to use the default, or use --parakeet-onnx-model-id, or use --parakeet-onnx-dir.",
                    args.model_path,
                )
                sys.exit(1)
            model_id = args.model_path

        # Persist selected bundle id so the daemon can auto-download when --parakeet-onnx-dir is omitted.
        args.parakeet_onnx_model_id = model_id

    # Create engine using factory
    from src.whispypy.engines.factory import create_engine

    engine = create_engine(
        engine_type=args.engine,
        model_path=args.model_path,
        parakeet_onnx_dir=args.parakeet_onnx_dir,
        parakeet_onnx_model_id=args.parakeet_onnx_model_id,
        parakeet_onnx_cache_dir=args.parakeet_onnx_cache_dir,
        onnx_provider=args.onnx_provider,
        onnx_threads=args.onnx_threads,
    )

    if args.check_model:
        try:
            engine.load_model()
        except Exception as e:
            logging.error("Failed to load model: %s", e)
            sys.exit(1)
        logging.info("Model loaded successfully")
        return

    # Handle device configuration
    config_manager = ConfigManager()

    # Validate configuration file
    if not config_manager.validate_config():
        logging.warning("Configuration file has issues, continuing with caution...")

    device_name = args.device
    if device_name:
        # Device provided via command line, save it to config
        config_manager.save_device(device_name)
    else:
        # No device provided, try to load from config
        device_name = config_manager.load_device()
        if not device_name:
            logging.error("No device specified and no saved configuration found.")
            logging.error(
                "Please run with --device option first, or use test_audio_devices.py to find a working device."
            )
            sys.exit(1)

    # Load the model
    engine.load_model()

    # Create and run daemon
    daemon = WhispypyDaemon(
        engine=engine,
        device_name=device_name,
        keep_audio=args.keep_audio,
        autopaste=args.autopaste,
    )

    daemon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)
