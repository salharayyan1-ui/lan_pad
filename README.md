# LAN Sketchpad

A **vibecoded** app that turns your phone into a drawing pad for an infinite, pan/zoomable canvas on your desktop.

## How it Works
The app uses a Python backend with `PySide6` for the desktop GUI and `websockets` for real-time communication. Your phone connects to a local HTTP server to load the drawing interface, and then sends touch events over WebSockets back to the desktop app.

## Running the App

You can either run the pre-packaged standalone executable or run it from the Python source.

### Option 1: Standalone Executable (Windows)
1. Locate and double-click `dist/sketchpad.exe`.
2. The desktop canvas will open. Look at the top-left corner of the canvas for your phone connection URL (e.g., `Phone URL: http://192.168.x.x:8000`).
3. Make sure your phone is on the same WiFi network as your laptop.
4. Open that URL in your phone's web browser and start sketching!

### Option 2: Running from Source
1. Ensure you have the required dependencies installed (e.g., `PySide6`, `websockets`).
2. Run the application:
   ```bash
   python sketchpad.py
   ```
3. The connection URL will be printed in the terminal (and on the canvas). Connect your phone on the same WiFi to that URL.

## Files
- `sketchpad.py`: The main desktop GUI application (PySide6) and WebSocket/HTTP server.
- `server.py`: A simpler milestone version that just prints touch events (for testing).
- `index.html`: The mobile web interface served to the phone.

---
*This is a vibecoded app.*
