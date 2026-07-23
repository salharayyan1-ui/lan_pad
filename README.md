# LAN Pad

A highly optimized app that turns your phone into a low-latency drawing pad for an infinite, pan/zoomable canvas on your desktop.

## How it Works
The app uses a Python backend with `PySide6` for the desktop GUI and `websockets` (via `asyncio`) for real-time communication. Your phone connects to a local HTTP server to load the drawing interface, and then sends touch events over WebSockets back to the desktop app. It features a thread-safe bridge to prevent GUI blocking.

## Setup & Connection (USB Recommended)
For the lowest latency and highest security, it is strongly recommended to connect your phone via a physical USB cable and use **USB Tethering**.

1. Connect your phone to your PC via USB.
2. Enable **USB Tethering** on your phone (Settings > Network & Internet > Hotspot & Tethering).
3. Run the application (`dist/sketchpad.exe` or `python sketchpad.py`).
4. The desktop canvas will open. Look at the top-left corner of the canvas for your phone connection URL and your 4-digit PIN.
5. Open that URL in your phone's Chrome browser, enter the PIN, and start sketching!

## The Phone Interface (100% Pure Touch)
The phone acts as a pure, UI-free trackpad. All tools are controlled via multi-touch gestures:

**Basic Drawing:**
- **1 Finger Drag:** Draw

**Tools & Canvas Control:**
- **2 Finger Tap:** Toggle between Pen and Eraser
- **2 Finger Drag:** Pan around the infinite canvas
- **2 Finger Pinch:** Zoom in and out

**Advanced Control:**
- **3 Finger Tap:** Undo last stroke
- **3 Finger Vertical Drag:** Smoothly adjust the pen/eraser size! (Swipe up to increase, down to decrease). 
- **4 Finger Tap:** Clear the entire canvas and snap the camera back to center at 100% zoom.

## Files
- `sketchpad.py`: The main desktop GUI application (PySide6) and WebSocket/HTTP server.
- `index.html`: The mobile web interface served to the phone.
