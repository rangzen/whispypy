#!/usr/bin/env python3

import argparse
import configparser
import importlib.util
import logging
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional, Union

import numpy as np
import whisper

# Audio file constants
BEEP_START_FILENAME = "BEEPTimer_Montre_numerique_bip_2_ID_2255_LS.wav"
BEEP_COMPLETE_FILENAME = "BEEPTimer_Montre_numerique_bip_1_ID_2254_LS.wav"

# Audio recording constants
SAMPLE_RATE = 16000  # Hz - Whisper's expected sample rate
CHANNELS = 1  # Mono audio
AUDIO_FORMAT = "f32"  # 32-bit float format for PipeWire
FLOAT32_BYTE_SIZE = 4  # Size of f32 in bytes

# Audio processing constants
RMS_SILENCE_THRESHOLD = 0.001  # Minimum RMS to distinguish signal from silence

# Timing and validation constants
DEVICE_TEST_DURATION = 1.0  # seconds - Duration for device validation test
PROCESS_TERMINATION_TIMEOUT = 2.0  # seconds - Timeout for process cleanup

# File paths (will be replaced with proper temp files)
TEMP_AUDIO_FILENAME = "whispy_recording"  # Base filename for temporary audio (extension will be added based on engine)


def get_config_file() -> Path:
    """Get the configuration file path following XDG Base Directory specification."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    config_dir = Path(xdg_config_home) / "whispypy"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.conf"


# Configuration
CONFIG_FILE = get_config_file()


class ConfigManager:
    """Manages configuration file operations."""

    def __init__(self, config_file: Path = CONFIG_FILE):
        self.config_file = config_file

    def save_device(self, device: str) -> None:
        """Save device configuration to config file."""
        config = configparser.ConfigParser()

        # Load existing config if it exists
        if self.config_file.exists():
            config.read(self.config_file)

        # Ensure [DEFAULT] section exists
        if "DEFAULT" not in config:
            config.add_section("DEFAULT")

        # Save device
        config.set("DEFAULT", "device", device)

        # Write config file
        with open(self.config_file, "w") as f:
            config.write(f)

        logging.info(f"Device '{device}' saved to {self.config_file}")

    def load_device(self) -> Optional[str]:
        """Load device configuration from config file."""
        if not self.config_file.exists():
            return None

        config = configparser.ConfigParser()
        try:
            config.read(self.config_file)
            device = config.get("DEFAULT", "device", fallback=None)
            if device:
                logging.info(f"Using device from config: {device}")
            return device
        except Exception as e:
            logging.error(f"Error reading config file {self.config_file}: {e}")
            return None

    def validate_config(self) -> bool:
        """Validate configuration file format and values."""
        if not self.config_file.exists():
            return True  # No config file is valid (will use defaults)

        try:
            config = configparser.ConfigParser()
            config.read(self.config_file)

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

            logging.debug("Configuration validation successful")
            return True

        except Exception as e:
            logging.error(f"Configuration validation failed: {e}")
            return False


def load_audio_f32(filepath: Union[str, Path]) -> np.ndarray:
    """Load audio file as float32 samples."""
    with open(filepath, "rb") as f:
        data = f.read()

    # Convert bytes to float32
    num_floats = len(data) // FLOAT32_BYTE_SIZE
    floats = struct.unpack(f"<{num_floats}f", data)
    return np.array(floats, dtype=np.float32)


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
    """Signal-controlled audio transcription daemon using OpenAI Whisper or NVIDIA Parakeet."""

    def __init__(
        self,
        model_path: str,
        device_name: str,
        engine: str = "whisper",
        keep_audio: bool = False,
    ):
        self.model_path = model_path
        self.device_name = device_name
        self.engine = engine
        self.keep_audio = keep_audio

        # Create temporary file for audio recording with appropriate extension
        audio_extension = ".wav" if engine == "parakeet" else ".au"
        self.temp_audio_file = Path(tempfile.gettempdir()) / (
            TEMP_AUDIO_FILENAME + audio_extension
        )

        # State
        self.recording = False
        self.running = True
        self.pw_record_proc: Optional[subprocess.Popen[bytes]] = None

        # Load the appropriate model
        if self.engine == "whisper":
            self._load_whisper_model()
        elif self.engine == "parakeet":
            self._load_parakeet_model()
        else:
            raise ValueError(f"Unsupported engine: {self.engine}")

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

    def _load_whisper_model(self) -> None:
        """Load Whisper model."""
        logging.info(f"Loading Whisper model from {self.model_path}...")
        model_load_start = time.time()
        self.model = whisper.load_model(self.model_path)
        model_load_time = time.time() - model_load_start
        logging.info(f"Whisper model loaded in {model_load_time:.2f} seconds")

    def _load_parakeet_model(self) -> None:
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

    def validate_device(self) -> bool:
        """Validate that the audio device exists and is accessible."""
        try:
            # Test device by attempting a very short recording
            audio_extension = ".wav" if self.engine == "parakeet" else ".au"
            with tempfile.NamedTemporaryFile(
                suffix=audio_extension, delete=False
            ) as test_file:
                test_file_path = test_file.name

            # Use managed_subprocess for proper cleanup
            with managed_subprocess(
                [
                    "pw-record",
                    f"--target={self.device_name}",
                    f"--format={AUDIO_FORMAT}",
                    f"--rate={SAMPLE_RATE}",
                    f"--channels={CHANNELS}",
                    test_file_path,
                ]
            ) as _:
                # Let it record for the test duration then it will be terminated
                time.sleep(DEVICE_TEST_DURATION)

            # Clean up test file
            Path(test_file_path).unlink(missing_ok=True)

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
        self.pw_record_proc = subprocess.Popen(
            [
                "pw-record",
                f"--target={self.device_name}",
                f"--format={AUDIO_FORMAT}",
                f"--rate={SAMPLE_RATE}",
                f"--channels={CHANNELS}",
                str(self.temp_audio_file),
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        self.recording = True
        logging.info("Recording started successfully")

    def _stop_recording_and_transcribe(self) -> None:
        """Stop recording and perform transcription."""
        logging.info("Stopping recording...")
        if self.pw_record_proc:
            self.pw_record_proc.terminate()
            self.pw_record_proc.wait()
            self.pw_record_proc = None
        self.recording = False
        logging.info("Recording stopped")

        # Check if audio file exists and has content
        if not self.temp_audio_file.exists():
            logging.error(f"Audio file {self.temp_audio_file} not found!")
            return

        file_size = self.temp_audio_file.stat().st_size
        logging.info(f"Audio file size: {file_size} bytes")

        if file_size == 0:
            logging.warning("Audio file is empty!")
            return

        # Load audio samples for Whisper or keep file path for Parakeet
        if self.engine == "whisper":
            logging.info("Loading audio samples...")
            samples = load_audio_f32(self.temp_audio_file)
            logging.info(f"Loaded {len(samples)} audio samples")

        # Transcribe with appropriate engine
        logging.info(f"Transcribing with {self.engine.capitalize()}...")
        transcription_start = time.time()

        if self.engine == "whisper":
            result = self.model.transcribe(
                samples, fp16=False, language=None, task="transcribe"
            )
            text = result["text"].strip()
        elif self.engine == "parakeet":
            # Parakeet expects a list of file paths
            result = self.model.transcribe([str(self.temp_audio_file)])
            text = result[0].text.strip()
        else:
            raise ValueError(f"Unsupported engine: {self.engine}")

        transcription_time = time.time() - transcription_start

        logging.info(f"Transcription completed in {transcription_time:.2f} seconds")
        logging.info(f"Transcription result: '{text}'")

        if not self.keep_audio:
            self.temp_audio_file.unlink(missing_ok=True)

        # Copy text to clipboard
        copy_to_clipboard(text)

        # Play completion beep to indicate transcription is ready in clipboard
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
        logging.info(f"Using transcription engine: {self.engine}")

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
        help="Path to the model or model name. For Whisper: tiny, base, small, medium, large, large-v2, large-v3. For Parakeet: nvidia/parakeet-tdt-0.6b-v3 (default: base)",
    )
    parser.add_argument(
        "--engine",
        "-e",
        choices=["whisper", "parakeet"],
        default="whisper",
        help="Transcription engine to use (default: whisper)",
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

    # Create and run daemon
    daemon = WhispypyDaemon(
        model_path=args.model_path,
        device_name=device_name,
        engine=args.engine,
        keep_audio=args.keep_audio,
    )

    daemon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)
