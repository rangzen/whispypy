#!/bin/bash

# Helper script to send SIGUSR2 to whispypy-daemon.py

# Find the PID of the whispypy-daemon.py process
PID=$(pgrep -f "whispypy-daemon.py")

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