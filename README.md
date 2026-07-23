# LAN Pad

Turn your phone (or a touchscreen laptop) into a low-latency drawing pad for an
infinite, pan/zoomable canvas on your desktop. Everything runs on your local
network — no cloud, no accounts, no native phone app (the phone just opens a web
page).

## How It Works

A Python desktop app (`PySide6`) hosts two servers on your machine:

- an **HTTP server** (port `8000`) that serves the phone's drawing page, and
- a **WebSocket server** (port `8765`) for real-time, two-way sync.

The phone loads the page and streams touch input to the desktop; the desktop
streams the shared canvas state (strokes, camera, tools) back. Both sides render
the **same infinite world** through a shared "look-at + zoom" camera, so the
surface you touch is the surface you see. Strokes are stored as **vectors in world
coordinates** (not pixels), which is what makes the canvas infinite and zoomable,
and makes undo/save clean. A thread-safe bridge marshals data between the network
thread and the GUI thread so the interface never blocks.

## Quick Start

Run the app — either the packaged exe or the script:

- **Exe:** double-click `dist/LANSketchpad.exe` (no Python needed).
- **Script:** `python sketchpad.py` (needs `PySide6` and `websockets`).

The desktop canvas opens. In the **top-left** you'll see your **phone URL(s)** and a
**4-digit PIN**. On your phone (see connection options below), open that URL in
Chrome, enter the PIN, and start sketching.

### Connecting the phone

**Option A — Same Wi-Fi (easiest):** put the phone on the *same* Wi-Fi network as
the laptop and open the shown `http://<laptop-ip>:8000`. Avoid "guest" networks —
they often block device-to-device traffic.

**Option B — USB tethering (lowest latency / most reliable):** connect the phone by
cable, enable **USB Tethering** (Settings → Network → Hotspot & Tethering), then
open the shown URL.

### Firewall (first run only)

Windows blocks incoming connections by default, so the phone may fail to connect
until you allow the ports **once** (run in an **Administrator** PowerShell):

```powershell
New-NetFirewallRule -DisplayName "LAN Sketchpad" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000,8765 -Profile Private
```

This rule is **port-based**, so it covers both `python.exe` and the exe. It applies
to **Private** networks — make sure your Wi-Fi is set to Private, not Public.

## Desktop Controls (laptop)

You can draw on the desktop directly (mouse, trackpad, or a touchscreen laptop),
and it stays in sync with the phone.

**Drawing**
- **Left-click / touch drag:** draw (or erase, in eraser mode)
- **Hover (mouse/trackpad):** a translucent ring previews the brush position & size

**Canvas navigation**
- **Two-finger scroll** (or **middle-mouse drag**): pan
- **Shift + scroll:** pan horizontally
- **Ctrl + scroll:** zoom toward the cursor
- **Arrow keys:** pan · **`+` / `-`:** zoom · **`0`:** reset view to origin @ 100%

**Tools (keyboard)**
- **`E`:** eraser · **`B`** or **`D`:** back to drawing (pen)
- **`[` / `]`:** decrease / increase brush (or eraser) size
- **`Ctrl+Z`:** undo · **`Delete`:** clear canvas · **`Ctrl+S`:** save as PNG / JPG / PDF

**Toolbar** (bottom-center of the window): Grid toggle, Pen, Eraser, Pen **Color**,
**BG** (background) color, and a size slider.

## Phone Interface (100% Pure Touch)

The phone is a UI-free trackpad — every tool is a multi-touch gesture:

**Basic Drawing**
- **1-Finger Drag:** Draw

**Tools & Canvas Control**
- **2-Finger Tap:** Toggle Pen ↔ Eraser
- **2-Finger Drag:** Pan the infinite canvas
- **2-Finger Pinch:** Zoom in/out

**Advanced Control**
- **3-Finger Tap:** Undo last stroke
- **3-Finger Vertical Drag:** Adjust pen/eraser size (swipe up = bigger, down = smaller)
- **4-Finger Tap:** Clear the canvas and snap the camera back to center @ 100%

## Building the Exe

Requires `pyinstaller` (`pip install pyinstaller`). From the project folder:

```
python -m PyInstaller --onefile --windowed --add-data "index.html;." --name LANSketchpad --noconfirm sketchpad.py
```

- `--add-data "index.html;."` bundles the phone page so the HTTP server can serve
  it from inside the exe (it's unpacked to a temp dir at runtime).
- `--windowed` hides the console. The app routes the (now missing) `stdout`/`stderr`
  to a null sink at startup so background `print()`s can't crash the server thread.
- The result is `dist/LANSketchpad.exe`. First launch is slightly slow (a one-file
  exe unpacks itself each run); use `--onedir` instead for instant startup.
- Unsigned exe → SmartScreen may warn "unknown publisher": **More info → Run anyway**.

## Files

- `sketchpad.py` — desktop GUI app (PySide6) + WebSocket/HTTP servers.
- `index.html` — the mobile/touch web interface served to clients.
