#!/usr/bin/env python3

from pathlib import Path
import re
import struct
import subprocess
import time
from typing import Dict, List, Tuple, TypedDict, Union


class WorkingDevice(TypedDict):
    device_name: str
    display_name: str
    rms: float


def load_audio_f32(filepath: Union[str, Path]) -> List[float]:
    """Load audio file as float32 samples."""
    with open(filepath, "rb") as f:
        data = f.read()

    # Convert bytes to float32
    num_floats = len(data) // 4
    if num_floats == 0:
        return []
    floats = struct.unpack(f"<{num_floats}f", data)
    return list(floats)


def analyze_audio_samples(samples: List[float]) -> str:
    """Analyze audio samples for basic statistics."""
    if not samples:
        return "No audio data"

    max_val = max(samples)
    min_val = min(samples)
    avg_val = sum(samples) / len(samples)

    # Calculate RMS (root mean square) for volume estimation
    rms = (sum(x * x for x in samples) / len(samples)) ** 0.5

    return f"Samples: {len(samples)}, RMS: {rms:.6f}, Range: [{min_val:.6f}, {max_val:.6f}], Avg: {avg_val:.6f}"


def discover_audio_devices() -> List[Dict[str, str]]:
    """Discover available audio input devices using pw-cli."""
    print("Discovering available audio devices...")

    try:
        # Use pw-cli to list nodes and find audio sources
        result = subprocess.run(
            ["pw-cli", "list-objects"], capture_output=True, text=True, check=True
        )

        devices = []
        current_device: Dict[str, str] = {}

        # Parse pw-cli output to find audio input devices
        for line in result.stdout.split("\n"):
            line = line.strip()

            # Look for Node objects
            if line.startswith("id ") and "type PipeWire:Interface:Node" in line:
                # Save previous device if it was an input device
                node_name = current_device.get("node_name")
                if (
                    current_device.get("media_class") == "Audio/Source"
                    and node_name
                    and not node_name.endswith(".monitor")
                ):
                    devices.append(current_device)
                current_device = {"id": line.split()[1].rstrip(",")}

            # Extract device properties (they appear as direct attributes, not in a properties section)
            elif "=" in line and current_device:
                if "node.name = " in line:
                    name = line.split("=", 1)[1].strip(' "')
                    current_device["node_name"] = name
                elif "node.description = " in line:
                    desc = line.split("=", 1)[1].strip(' "')
                    current_device["description"] = desc
                elif "media.class = " in line:
                    media_class = line.split("=", 1)[1].strip(' "')
                    current_device["media_class"] = media_class
                elif "node.nick = " in line:
                    nick = line.split("=", 1)[1].strip(' "')
                    current_device["nick"] = nick

        # Don't forget the last device
        node_name = current_device.get("node_name")
        if (
            current_device.get("media_class") == "Audio/Source"
            and node_name
            and not node_name.endswith(".monitor")
        ):
            devices.append(current_device)

        # Clean up and format devices
        valid_devices = []
        for device in devices:
            display_name = (
                device.get("description")
                or device.get("nick")
                or device.get("node_name", "Unknown Device")
            )

            valid_devices.append(
                {
                    "node_name": device["node_name"],
                    "display_name": display_name,
                    "id": device.get("id", "unknown"),
                }
            )

        if valid_devices:
            return valid_devices
        else:
            print("No devices found with pw-cli, trying arecord fallback...")
            return discover_audio_devices_arecord()

    except subprocess.CalledProcessError as e:
        print(f"Error running pw-cli: {e}")
        print("Falling back to arecord...")
        return discover_audio_devices_arecord()
    except FileNotFoundError:
        print("pw-cli not found, trying arecord...")
        return discover_audio_devices_arecord()


def discover_audio_devices_arecord() -> List[Dict[str, str]]:
    """Fallback method using arecord to discover audio devices."""
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, check=True
        )

        devices = []

        # Parse arecord output
        for line in result.stdout.split("\n"):
            if "card" in line and "device" in line:
                # Example: card 0: sofhdadsp [sof-hda-dsp], device 0: HDA Analog (*) []
                parts = line.split(":")
                if len(parts) >= 3:
                    card_info = parts[0].strip()  # "card 0"
                    card_name = parts[1].strip().split("[")[0].strip()  # card name

                    # Extract card and device numbers
                    card_match = re.search(r"card (\d+)", card_info)
                    device_match = re.search(r"device (\d+)", line)

                    if card_match and device_match:
                        card_num = card_match.group(1)
                        device_num = device_match.group(1)

                        # Generate device name for ALSA
                        node_name = f"hw:{card_num},{device_num}"
                        display_name = (
                            f"{card_name} (Card {card_num}, Device {device_num})"
                        )

                        devices.append(
                            {
                                "node_name": node_name,
                                "display_name": display_name,
                                "id": f"{card_num}_{device_num}",
                            }
                        )

        return devices

    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error discovering devices with arecord: {e}")
        return []


def test_audio_device(
    device_name: str, display_name: str, duration: int = 3
) -> Tuple[bool, float, str]:
    """Test recording from a specific audio device. Returns (success, rms_value, details)."""
    print(f"\n=== Testing {display_name} ===")
    print(f"Device: {device_name}")

    test_file = (
        f"/tmp/test_{display_name.replace(' ', '_').replace('/', '_').lower()}.raw"
    )

    try:
        # Start recording
        print(
            f"🎙️  Recording for {duration} seconds... Please speak into the microphone!"
        )

        cmd = [
            "pw-record",
            "--target",
            device_name,
            "--format=f32",
            "--rate=16000",
            "--channels=1",
            test_file,
        ]

        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        # Let it record for the specified duration
        time.sleep(duration)

        # Stop recording
        proc.terminate()
        proc.wait()

        # Check if file was created and analyze it
        if Path(test_file).exists():
            file_size = Path(test_file).stat().st_size
            print(f"✅ Audio file created: {file_size} bytes")

            if file_size > 0:
                samples = load_audio_f32(test_file)
                analysis = analyze_audio_samples(samples)
                print(f"   Audio analysis: {analysis}")

                # Check if audio seems to contain meaningful signal
                if samples:
                    rms = (sum(x * x for x in samples) / len(samples)) ** 0.5
                    if rms > 0.001:  # Threshold for meaningful audio
                        print(f"   ✅ Audio appears to contain signal (RMS: {rms:.6f})")
                        print("   🎯 This device seems to be working!")
                        # Cleanup
                        Path(test_file).unlink(missing_ok=True)
                        return True, rms, f"Working device (RMS: {rms:.6f})"
                    else:
                        print(
                            f"   ⚠️  Audio appears to be mostly silence (RMS: {rms:.6f})"
                        )
                        print(
                            "   💡 Try speaking louder or checking if this is the right device"
                        )
                        # Cleanup
                        Path(test_file).unlink(missing_ok=True)
                        return False, rms, f"Mostly silence (RMS: {rms:.6f})"
                else:
                    print("   ❌ No audio samples found")
                    # Cleanup
                    Path(test_file).unlink(missing_ok=True)
                    return False, 0.0, "No audio samples found"
            else:
                print("   ❌ Audio file is empty - device may not be working")
                # Cleanup
                Path(test_file).unlink(missing_ok=True)
                return False, 0.0, "Empty audio file"

        else:
            print("   ❌ Audio file was not created - device may not be accessible")
            return False, 0.0, "Audio file not created"

    except Exception as e:
        print(f"   ❌ Error: {e}")
        print(
            "   💡 Try checking if the device is available and not in use by another application"
        )
        return False, 0.0, f"Error: {str(e)}"


def main() -> None:
    print("Audio Device Test Script")
    print("========================")

    # Discover available audio devices
    devices = discover_audio_devices()

    if not devices:
        print("❌ No audio input devices found!")
        print(
            "Make sure you have audio devices connected and PipeWire/PulseAudio is running."
        )
        return

    print(f"\n🎤 Found {len(devices)} audio input device(s):")
    for i, device in enumerate(devices, 1):
        print(f"  {i}. {device['display_name']}")
        print(f"     Device: {device['node_name']}")

    print("\nOptions:")
    print("  a) Test all devices")
    print(f"  1-{len(devices)}) Test specific device")
    print("  q) Quit")

    while True:
        try:
            choice = (
                input(f"\nEnter your choice (a/1-{len(devices)}/q): ").lower().strip()
            )

            if choice == "q":
                print("Exiting...")
                return
            elif choice == "a":
                # Test all devices
                devices_to_test = [
                    (dev["node_name"], dev["display_name"]) for dev in devices
                ]
                break
            elif choice.isdigit():
                device_num = int(choice)
                if 1 <= device_num <= len(devices):
                    selected_device = devices[device_num - 1]
                    devices_to_test = [
                        (selected_device["node_name"], selected_device["display_name"])
                    ]
                    break
                else:
                    print(f"❌ Please enter a number between 1 and {len(devices)}")
            else:
                print("❌ Invalid choice. Please enter 'a', a device number, or 'q'")
        except KeyboardInterrupt:
            print("\nExiting...")
            return
        except ValueError:
            print("❌ Invalid input. Please enter 'a', a device number, or 'q'")

    # Test the selected devices and track results
    test_results = []
    working_devices: List[WorkingDevice] = []

    for i, (device_name, display_name) in enumerate(devices_to_test):
        success, rms, details = test_audio_device(device_name, display_name, duration=3)

        test_results.append(
            {
                "device_name": device_name,
                "display_name": display_name,
                "success": success,
                "rms": rms,
                "details": details,
            }
        )

        if success:
            working_devices.append(
                {"device_name": device_name, "display_name": display_name, "rms": rms}
            )

        # Give user time to read results, but don't prompt for last device
        if i < len(devices_to_test) - 1:
            print("\nPress Enter to test the next device, or Ctrl+C to exit...")
            try:
                input()
            except KeyboardInterrupt:
                print("\nExiting...")
                break

    print("\n=== Test Results Summary ===")

    if working_devices:
        print(f"🎉 Found {len(working_devices)} working device(s):")
        print()

        # Sort working devices by RMS (higher RMS = stronger signal)
        working_devices.sort(key=lambda x: x["rms"], reverse=True)

        for i, working_device in enumerate(working_devices, 1):
            print(f"  {i}. ✅ {working_device['display_name']}")
            print(f"     📱 Device: {working_device['device_name']}")
            print(f"     📊 Signal strength (RMS): {working_device['rms']:.6f}")
            print()

        print("🏆 Recommended: Use the device with the highest signal strength")
        print("🔧 Copy this device name for your whisper daemon:")
        print(f"    {working_devices[0]['device_name']}")
    else:
        print("❌ No working devices found!")
        print()
        print("📋 All tested devices and their issues:")
        for result in test_results:
            print(f"  • {result['display_name']}: {result['details']}")
        print()

    print("\n💡 If no devices worked:")
    print("   • Check your microphone is connected and not muted")
    print("   • Verify audio permissions for the terminal/application")
    print("   • Try running: pactl list sources | grep -E 'Name:|Description:'")
    print("   • Consider testing with: arecord -l  or  pw-cli list-objects")


if __name__ == "__main__":
    main()
