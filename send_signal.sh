#!/bin/bash

# Helper script to send SIGUSR2 to whispypy-daemon.py

# Find the PID of the whispypy-daemon.py process (exclude uv wrapper)
PID=$(ps aux | grep "whispypy-daemon.py" | grep -v "uv run" | grep -v grep | awk '{print $2}' | head -1)

if [ -z "$PID" ]; then
    echo "Error: whispypy-daemon.py process not found!"
    echo "Make sure the script is running first."
    exit 1
fi

echo "Found whispypy-daemon.py process with PID: $PID"
echo "Sending SIGUSR2 signal..."

kill -USR2 "$PID"

if [ $? -eq 0 ]; then
    echo "Signal sent successfully!"
else
    echo "Failed to send signal!"
    exit 1
fi