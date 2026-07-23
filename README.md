# LAN Sketchpad

A **vibecoded** app that turns your phone into a drawing pad for an infinite, pan/zoomable canvas on your desktop.

## How it Works
The app uses a Python backend with `PySide6` for the desktop GUI and `websockets` for real-time communication. Your phone connects to a local HTTP server to load the drawing interface, and then sends touch events over WebSockets back to the desktop app.

## Running the App

1. Ensure you have the required dependencies installed (e.g., `PySide6`, `websockets`).
2. Run the application:
   ```bash
   python sketchpad.py
   ```
3. Look at your terminal output. It will display a local IP address and port (e.g., `http://<laptop-ip>:8000`).
4. Make sure your phone is on the same WiFi network as your laptop.
5. Open that URL in your phone's web browser and start sketching!

## Files
- `sketchpad.py`: The main desktop GUI application (PySide6) and WebSocket/HTTP server.
- `server.py`: A simpler milestone version that just prints touch events (for testing).
- `index.html`: The mobile web interface served to the phone.

---
*This is a vibecoded app.*
