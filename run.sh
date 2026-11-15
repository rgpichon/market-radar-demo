#!/bin/bash

# Market Events Radar - Quick Start Script
# This script starts the Flask server and opens the interface in your browser

cd "$(dirname "$0")/backend"

# Check if port 5001 is available, if not try 5002, 5003, etc.
PORT=5001
while lsof -ti:$PORT > /dev/null 2>&1; do
    echo "Port $PORT is in use, trying next port..."
    PORT=$((PORT + 1))
done

echo "Starting Market Events Radar on port $PORT..."
echo "Opening browser at http://127.0.0.1:$PORT"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start Flask server
python app.py --port $PORT &
SERVER_PID=$!

# Wait a moment for server to start
sleep 2

# Open browser
open "http://127.0.0.1:$PORT"

# Wait for server process
wait $SERVER_PID
