"""LAN Sketchpad - Milestone 5 (infinite page)
PySide6 app: smooth strokes on an INFINITE, pan/zoom-able page (laptop controls).

Run:  python sketchpad.py
Then on the phone (same WiFi):  http://<laptop-ip>:8000

Architecture note (the "glue"):
  - The WebSocket + HTTP servers run in a BACKGROUND thread with their own asyncio loop.
  - Qt widgets are NOT thread-safe: you may only touch them from the thread that created
    them (the GUI thread). So the network thread never draws anything directly. Instead it
    emits a Qt SIGNAL. Qt sees the emit came from another thread and QUEUES the call onto the
    GUI thread's event loop, where the connected SLOT runs safely. That queued hand-off is the
    whole reason we use signals/slots here instead of a shared variable + locks.
"""

import asyncio
import json
import socket
import sys
import threading
import random
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget, QColorDialog, QHBoxLayout, QPushButton, QSlider

# In a PyInstaller --windowed build there is NO console, so sys.stdout/stderr are
# None. Any print() would then raise and kill its thread — which is why the
# WebSocket server appears not to start (the phone can't connect). Route the
# missing streams to a throwaway sink so every print() is harmless.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

HTTP_PORT = 8000
WS_PORT = 8765
if getattr(sys, 'frozen', False):
    # PyInstaller unpacks bundled data (index.html) into this temp dir at runtime.
    ROOT = Path(sys._MEIPASS)
else:
    ROOT = Path(__file__).parent


def get_all_ips() -> list:
    ips = []
    try:
        hostname = socket.gethostname()
        _, _, ip_addresses = socket.gethostbyname_ex(hostname)
        for ip in ip_addresses:
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip.startswith("172."):
                parts = ip.split(".")
                if len(parts) == 4 and 16 <= int(parts[1]) <= 31:
                    continue  # Skip WSL/Hyper-V/Docker defaults
            ips.append(ip)
    except Exception:
        pass
    if not ips:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
        except OSError:
            ips.append("127.0.0.1")
        finally:
            s.close()
    return ips

APP_PIN = f"{random.randint(0, 9999):04d}"


# ---------------------------------------------------------------------------
# Network layer: runs entirely off the GUI thread. It carries touch data IN via
# the `touch` signal, and pushes scene state OUT (strokes/camera/tool) to every
# connected web client. Outbound sends are marshalled from the GUI thread onto
# the asyncio loop with call_soon_threadsafe (the reverse of the touch signal).
# ---------------------------------------------------------------------------
class NetworkBridge(QObject):
    touch = Signal(object)      # decoded inbound touch dict -> GUI thread

    def __init__(self):
        super().__init__()
        self._clients = set()
        self._loop = None
        # Cached scene, so a client connecting later gets the full picture.
        self._cam_msg = None
        self._tool_msg = None
        self._strokes = []      # list of committed stroke messages (dicts)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _serve_http(self):
        handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
        ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler).serve_forever()

    async def _ws_handler(self, websocket):
        print(f"[ws] client connected: {websocket.remote_address}")
        
        try:
            # Enforce PIN Auth (First message must be auth)
            auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(auth_msg)
            if data.get("type") != "auth" or data.get("pin") != APP_PIN:
                print(f"[ws] Auth failed for {websocket.remote_address}")
                await websocket.close(1008, "Invalid PIN")
                return
        except Exception as e:
            print(f"[ws] Auth error: {e}")
            await websocket.close(1008, "Auth required")
            return
            
        print(f"[ws] Auth success for {websocket.remote_address}!")
        
        # Enforce Single Device Limit
        for old_ws in list(self._clients):
            try:
                await old_ws.close(1000, "New device connected")
            except Exception:
                pass
        self._clients.clear()
        
        self._clients.add(websocket)
        try:
            await self._send_snapshot(websocket)  # replay current scene
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue
                self.touch.emit(data)             # cross-thread -> GUI
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            print("[ws] client disconnected")

    async def _send_snapshot(self, ws):
        if self._cam_msg:
            await ws.send(json.dumps(self._cam_msg))
        if self._tool_msg:
            await ws.send(json.dumps(self._tool_msg))
        for s in list(self._strokes):
            await ws.send(json.dumps(s))

    def _run(self):
        async def main():
            threading.Thread(target=self._serve_http, daemon=True).start()
            self._loop = asyncio.get_running_loop()
            print("=" * 48)
            print("LAN Sketchpad - Milestone 8 (Auth & USB)")
            print(f"  PIN: {APP_PIN}")
            print("=" * 48)
            async with websockets.serve(self._ws_handler, "0.0.0.0", WS_PORT):
                await asyncio.Future()  # run forever

        asyncio.run(main())

    # ---- outbound API, called from the GUI thread ------------------------
    def push_stroke(self, msg):
        self._strokes.append(msg)
        self._broadcast(msg)

    def set_camera(self, msg):
        self._cam_msg = msg
        self._broadcast(msg)

    def set_tool(self, msg):
        self._tool_msg = msg
        self._broadcast(msg)

    def clear(self):
        self._strokes.clear()
        self._broadcast({"t": "clear"})

    def undo(self):
        if self._strokes:
            self._strokes.pop()
        self._broadcast({"t": "undo"})

    def _broadcast(self, msg):
        """Schedule a send to all clients on the asyncio loop thread."""
        if self._loop is None:
            return
        text = json.dumps(msg)
        self._loop.call_soon_threadsafe(self._fanout, text)

    def _fanout(self, text):
        for ws in list(self._clients):
            asyncio.create_task(self._safe_send(ws, text))

    async def _safe_send(self, ws, text):
        try:
            await ws.send(text)
        except Exception:
            self._clients.discard(ws)


BG_COLOR = QColor("#1c1c22")
STROKE_COLOR = QColor("#e8e8f0")
STROKE_WIDTH = 3.0          # constant for M3; pressure-driven width is M4
ERASER_WIDTH = 28.0         # eraser is a fat pen painted in the background color
EMA_ALPHA = 0.5             # jitter damping: higher = snappier, lower = smoother


PAN_STEP = 60.0             # pixels moved per arrow-key press
ZOOM_STEP = 1.15            # multiplicative zoom per keypress / wheel notch
MIN_SCALE, MAX_SCALE = 0.1, 20.0


def smooth_path(pts):
    """Build one midpoint-smoothed QPainterPath through a list of points."""
    n = len(pts)
    path = QPainterPath()
    if n == 0:
        return path
    path.moveTo(pts[0])
    if n == 1:
        # A single tap: nudge so round-cap renders a dot.
        path.lineTo(pts[0].x() + 0.01, pts[0].y())
        return path
    # Quadratic through the midpoints; each raw point is a control point.
    for i in range(1, n - 1):
        mid = QPointF((pts[i].x() + pts[i + 1].x()) / 2,
                      (pts[i].y() + pts[i + 1].y()) / 2)
        path.quadTo(pts[i], mid)
    path.lineTo(pts[-1])
    return path


# ---------------------------------------------------------------------------
# Canvas: an INFINITE page. Strokes are stored as vectors in WORLD coordinates
# (an unbounded space). A camera (pan offset + scale) maps world -> screen each
# frame:  screen = pan + scale * world.  Panning/zooming just moves the camera;
# the strokes themselves never change. This is what makes the page infinite and
# also makes future undo/save trivial.
# ---------------------------------------------------------------------------
class HUDToolbar(QWidget):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 40, 200);
                border-radius: 15px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 20);
                color: white;
                border: None;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: bold;
                font-family: sans-serif;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 40);
            }
            QPushButton:checked {
                background-color: #4a90e2;
            }
            QSlider::groove:horizontal {
                background: rgba(255, 255, 255, 30);
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: white;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(10)
        
        self.btn_grid = QPushButton("Grid")
        self.btn_grid.setCheckable(True)
        self.btn_grid.setChecked(True)
        self.btn_grid.clicked.connect(self.toggle_grid)
        
        self.btn_pen = QPushButton("Pen")
        self.btn_pen.setCheckable(True)
        self.btn_pen.setChecked(True)
        self.btn_pen.clicked.connect(lambda: self.set_mode("draw"))
        
        self.btn_erase = QPushButton("Eraser")
        self.btn_erase.setCheckable(True)
        self.btn_erase.clicked.connect(lambda: self.set_mode("erase"))
        
        self.btn_color = QPushButton("Color")
        self.btn_color.clicked.connect(self.choose_color)
        
        self.btn_bg = QPushButton("BG")
        self.btn_bg.clicked.connect(self.choose_bg)
        
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 50)
        self.slider.setValue(int(STROKE_WIDTH))
        self.slider.setFixedWidth(100)
        self.slider.valueChanged.connect(self.change_width)
        
        layout.addWidget(self.btn_grid)
        layout.addWidget(self.btn_pen)
        layout.addWidget(self.btn_erase)
        layout.addWidget(self.btn_color)
        layout.addWidget(self.btn_bg)
        layout.addWidget(self.slider)
        
    def sync_ui(self):
        is_erase = self.canvas._mode == "erase"
        self.btn_erase.setChecked(is_erase)
        self.btn_pen.setChecked(not is_erase)
        self.btn_grid.setChecked(self.canvas.show_grid)
        w = self.canvas._erase_width if is_erase else self.canvas._draw_width
        self.slider.blockSignals(True)
        self.slider.setValue(int(w))
        self.slider.blockSignals(False)
        self.update_color_btn()
        
    def update_color_btn(self):
        c = self.canvas.stroke_color.name()
        self.btn_color.setStyleSheet(f"QPushButton {{ border-bottom: 4px solid {c}; }}")
        b = self.canvas.bg_color.name()
        self.btn_bg.setStyleSheet(f"QPushButton {{ border-bottom: 4px solid {b}; }}")
        
    def toggle_grid(self, checked):
        self.canvas.show_grid = checked
        self.canvas._emit_tool()
        self.canvas.update()
        
    def set_mode(self, mode):
        self.canvas._mode = mode
        self.sync_ui()
        self.canvas._emit_tool()
        self.canvas.update()
        
    def choose_color(self):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(self.canvas.stroke_color, self.canvas, "Choose Pen Color")
        if color.isValid():
            self.canvas.stroke_color = color
            self.update_color_btn()
            self.canvas._emit_tool()
            self.canvas.update()
            
    def choose_bg(self):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(self.canvas.bg_color, self.canvas, "Choose Background Color")
        if color.isValid():
            self.canvas.bg_color = color
            self.update_color_btn()
            self.canvas._emit_tool()
            self.canvas.update()
            
    def change_width(self, val):
        if self.canvas._mode == "erase":
            self.canvas._erase_width = val
        else:
            self.canvas._draw_width = val
        self.canvas._emit_tool()
        self.canvas.update()


class Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self._ips = get_all_ips()
        self.setMinimumSize(800, 600)
        # StrongFocus: a QWidget only receives key events when it has focus.
        self.setFocusPolicy(Qt.StrongFocus)
        # Mouse tracking: deliver mouseMoveEvent even with no button pressed, so
        # the cursor ring can follow the trackpad on hover (a phone can't hover).
        self.setMouseTracking(True)
        self._panning = False       # middle-drag pan in progress
        self._pan_last = None       # last mouse pos during a pan drag

        self._strokes = []      # committed strokes: {"points":[world QPointF], "width","color"}
        self._cur = None        # in-progress stroke dict, or None
        self._ema = None        # running EMA position in SCREEN px, or None

        self._mode = "draw"     # "draw" or "erase"
        self._draw_width = STROKE_WIDTH    # screen px; adjustable with [ ]
        self._erase_width = ERASER_WIDTH
        self.stroke_color = QColor(STROKE_COLOR)
        self.bg_color = QColor(BG_COLOR)
        self.show_grid = True
        
        self.toolbar = HUDToolbar(self)
        self.toolbar.move(20, 20)
        self.toolbar.sync_ui()

        self._pan = QPointF(0, 0)   # camera translation (screen px)
        self._scale = 1.0           # camera zoom

        self._cursor = None     # last finger position in SCREEN px (for the ring)
        self._touching = False

        self.bridge = None      # set in main(); used to broadcast to web clients

    # ---- coordinate transforms -------------------------------------------
    def _screen_to_world(self, p):
        return QPointF((p.x() - self._pan.x()) / self._scale,
                       (p.y() - self._pan.y()) / self._scale)

    def _world_to_screen(self, p):
        return QPointF(self._pan.x() + self._scale * p.x(),
                       self._pan.y() + self._scale * p.y())

    def _active_width(self):
        return self._erase_width if self._mode == "erase" else self._draw_width

    # ---- outbound sync to web clients ------------------------------------
    def _emit_camera(self):
        # Share the camera as look-at (world point at screen center) + zoom, so
        # each device can center the same world point on its own screen.
        if not self.bridge:
            return
        look = self._screen_to_world(self._viewport_center())
        self.bridge.set_camera({"t": "camera", "zoom": self._scale,
                                "lax": round(look.x(), 2), "lay": round(look.y(), 2)})

    def _emit_tool(self):
        if not self.bridge:
            return
        color = self.bg_color if self._mode == "erase" else self.stroke_color
        self.bridge.set_tool({
            "t": "tool",
            "mode": self._mode,
            "color": color.name(),
            "bg_color": self.bg_color.name(),
            "w": self._active_width() / self._scale,
            "show_grid": self.show_grid
        })

    def _stroke_msg(self, stroke):
        return {"t": "stroke", "origin": stroke.get("origin", "laptop"),
                "w": stroke["width"], "color": stroke["color"].name(),
                "is_eraser": stroke.get("is_eraser", False),
                "pts": [[round(p.x(), 1), round(p.y(), 1)] for p in stroke["points"]]}

    # ---- keyboard: mode, brush size, pan, zoom ---------------------------
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if mods & Qt.ControlModifier and key == Qt.Key_Z:
            self._undo()
        elif key == Qt.Key_Delete:
            self._clear()
        elif mods & Qt.ControlModifier and key == Qt.Key_S:
            self._save_canvas()
        elif key == Qt.Key_E:
            self._mode = "erase"
            self._emit_tool()
        elif key in (Qt.Key_B, Qt.Key_D):
            self._mode = "draw"
            self._emit_tool()
        elif key == Qt.Key_BracketRight:
            self._adjust_width(+2)
            self._emit_tool()
        elif key == Qt.Key_BracketLeft:
            self._adjust_width(-2)
            self._emit_tool()
        elif key == Qt.Key_Left:
            self._pan.setX(self._pan.x() + PAN_STEP)
            self._emit_camera()
        elif key == Qt.Key_Right:
            self._pan.setX(self._pan.x() - PAN_STEP)
            self._emit_camera()
        elif key == Qt.Key_Up:
            self._pan.setY(self._pan.y() + PAN_STEP)
            self._emit_camera()
        elif key == Qt.Key_Down:
            self._pan.setY(self._pan.y() - PAN_STEP)
            self._emit_camera()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self._zoom_at(ZOOM_STEP, self._viewport_center())
        elif key == Qt.Key_Minus:
            self._zoom_at(1 / ZOOM_STEP, self._viewport_center())
        elif key == Qt.Key_0:
            self._pan = QPointF(0, 0)   # reset view to origin, 100%
            self._scale = 1.0
            self._emit_camera()
        else:
            super().keyPressEvent(event)
            return
        self.update()

    def _adjust_width(self, delta):
        w = max(1.0, min(160.0, self._active_width() + delta))
        if self._mode == "erase":
            self._erase_width = w
        else:
            self._draw_width = w

    def _viewport_center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    def _zoom_at(self, factor, center):
        """Zoom about a screen point, keeping the world point under it fixed."""
        new_scale = max(MIN_SCALE, min(MAX_SCALE, self._scale * factor))
        f = new_scale / self._scale
        # pan' = center - f * (center - pan)   -> keeps `center` anchored
        self._pan = QPointF(center.x() - f * (center.x() - self._pan.x()),
                            center.y() - f * (center.y() - self._pan.y()))
        self._scale = new_scale
        self._emit_camera()

    # ---- trackpad / wheel: pan, or Ctrl+wheel to zoom --------------------
    def wheelEvent(self, event):
        d = event.angleDelta()
        mods = event.modifiers()
        if mods & Qt.ControlModifier:
            factor = ZOOM_STEP if d.y() > 0 else 1 / ZOOM_STEP
            self._zoom_at(factor, QPointF(event.position()))
        elif mods & Qt.ShiftModifier:
            self._pan.setX(self._pan.x() + d.y() / 2)   # shift = horizontal pan
            self._emit_camera()
        else:
            self._pan.setX(self._pan.x() + d.x() / 2)
            self._pan.setY(self._pan.y() + d.y() / 2)
            self._emit_camera()
        self.update()

    # ---- shared stroke pipeline (source-agnostic: phone OR mouse) ---------
    def _begin_stroke(self, origin="laptop", color=None, width=None, is_eraser=None):
        # Width is stored in WORLD units so it renders at the intended on-screen
        # thickness at the current zoom (and scales correctly if zoomed later).
        if is_eraser is None:
            is_eraser = (self._mode == "erase")
        if color is None:
            # Use the INSTANCE colors (updated by the toolbar), not the module
            # constants — otherwise laptop strokes ignore the chosen color.
            c = self.bg_color if is_eraser else self.stroke_color
        else:
            c = QColor(color)

        if width is None:
            w = self._active_width() / self._scale
        else:
            w = float(width)

        self._cur = {"points": [], "width": w, "color": c,
                     "origin": origin, "is_eraser": is_eraser}
        self._ema = None

    def _extend_stroke(self, screen_pt):
        # For MOUSE input: EMA jitter damping in SCREEN space, then to world.
        sx, sy = screen_pt.x(), screen_pt.y()
        if self._ema is None:
            self._ema = (sx, sy)
        else:
            ax, ay = self._ema
            self._ema = (EMA_ALPHA * sx + (1 - EMA_ALPHA) * ax,
                         EMA_ALPHA * sy + (1 - EMA_ALPHA) * ay)
        smoothed = QPointF(*self._ema)
        self._cursor = smoothed
        self._touching = True
        if self._cur is None:
            self._begin_stroke()
        self._cur["points"].append(self._screen_to_world(smoothed))
        self.update()

    def _extend_stroke_world(self, world_pt):
        # For PHONE input: it already smoothed and converted to world coords.
        if self._cur is None:
            self._begin_stroke()
        self._cur["points"].append(world_pt)
        self._cursor = self._world_to_screen(world_pt)
        self._touching = True
        self.update()

    def _end_stroke(self):
        if self._cur and self._cur["points"]:
            self._strokes.append(self._cur)
            if self.bridge:
                self.bridge.push_stroke(self._stroke_msg(self._cur))
        self._cur = None
        self._ema = None
        self._touching = False
        self.update()

    def _cancel_stroke(self):
        self._cur = None
        self._ema = None
        self._touching = False
        self.update()

    def _undo(self):
        if not self._strokes:
            return
        self._strokes.pop()
        if self.bridge:
            self.bridge.undo()
        self.update()

    def _clear(self):
        self._strokes.clear()
        if self.bridge:
            self.bridge.clear()
        self.update()

    # ---- touch input from the phone (SLOT, runs on the GUI thread) --------
    def on_touch(self, data: dict):
        if data.get("type") == "camera":
            zoom = data.get("zoom", 1.0)
            lax = data.get("lax", 0.0)
            lay = data.get("lay", 0.0)
            self._scale = zoom
            c = self._viewport_center()
            self._pan = QPointF(c.x() - zoom * lax, c.y() - zoom * lay)
            # Do NOT emit_camera() here! Bouncing it back causes the phone's 
            # local camera state to momentarily revert, causing flickers.
            self.update()
            return
        if data.get("type") == "undo":
            self._undo()
            return
        if data.get("type") == "clear":
            self._clear()
            return
        if data.get("type") == "tool":
            # Phone speaks "pen"/"eraser"; the laptop uses "draw"/"erase".
            m = data.get("mode", "draw")
            self._mode = "erase" if m in ("erase", "eraser") else "draw"
            # Phone sends width in WORLD units; convert back to screen px.
            w = float(data.get("width", 3.0)) * self._scale
            if self._mode == "erase":
                self._erase_width = w
            else:
                self._draw_width = w
            self.toolbar.sync_ui()
            self.update()
            return
        if data.get("type") == "start":
            self._begin_stroke(
                origin=data.get("id", "phone"),
                color=data.get("color"),
                width=data.get("w"),
                is_eraser=data.get("is_eraser", False),
            )
            self._extend_from_points(data)
            return
        if data.get("type") == "move":
            self._extend_from_points(data)
            return
        if data.get("type") == "end":
            self._end_stroke()
            return
        if data.get("type") == "cancel":
            self._cancel_stroke()
            return

    def _extend_from_points(self, data):
        """Pull the first world point out of a phone start/move message."""
        pts = data.get("points")
        if not pts:
            return
        p = pts[0]
        if "wx" in p:                       # phone sends world coords
            self._extend_stroke_world(QPointF(p["wx"], p["wy"]))
        elif "nx" in p:                     # legacy fallback (normalized coords)
            self._extend_stroke(QPointF(p["nx"] * self.width(), p["ny"] * self.height()))

    # ---- mouse / trackpad input (same pipeline) --------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_stroke()
            self._extend_stroke(event.position())
        elif event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_last = event.position()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._panning:
            self._pan = self._pan + (pos - self._pan_last)  # drag the camera
            self._pan_last = pos
            self._emit_camera()
            self.update()
        elif event.buttons() & Qt.LeftButton:
            self._extend_stroke(pos)
        else:
            self._cursor = pos          # hover: move the ring, don't draw
            self._touching = False
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._end_stroke()
        elif event.button() == Qt.MiddleButton:
            self._panning = False

    # ---- rendering -------------------------------------------------------
    def _draw_stroke(self, painter, stroke):
        # Eraser strokes always paint the CURRENT background, so changing the
        # background re-colors them too (rather than showing a stale baked color).
        color = self.bg_color if stroke.get("is_eraser") else stroke["color"]
        pen = QPen(color, stroke["width"])
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(smooth_path(stroke["points"]))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toolbar.move((self.width() - self.toolbar.width()) // 2,
                          self.height() - self.toolbar.height() - 30)
        # The screen center moved, so the shared look-at point changed; re-sync.
        self._emit_camera()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.bg_color)
        
        if getattr(self, "show_grid", True):
            grid_size = int(40 * self._scale)
            if grid_size > 5:
                painter.setPen(QColor(255, 255, 255, 10))
                offset_x = int(self._pan.x()) % grid_size
                offset_y = int(self._pan.y()) % grid_size
                for x in range(offset_x, self.width(), grid_size):
                    painter.drawLine(x, 0, x, self.height())
                for y in range(offset_y, self.height(), grid_size):
                    painter.drawLine(0, y, self.width(), y)
        painter.setRenderHint(QPainter.Antialiasing)

        # Apply the camera, then draw every stroke in world coordinates.
        painter.save()
        painter.translate(self._pan)
        painter.scale(self._scale, self._scale)

        for stroke in self._strokes:
            self._draw_stroke(painter, stroke)
        if self._cur and self._cur["points"]:
            self._draw_stroke(painter, self._cur)

        # --- Premium Dot Grid (Drawn ON TOP of strokes so eraser doesn't hide it) ---
        w_top_left = self._screen_to_world(QPointF(0, 0))
        w_bottom_right = self._screen_to_world(QPointF(self.width(), self.height()))
        spacing = 40
        start_x = int(w_top_left.x() // spacing)
        end_x = int(w_bottom_right.x() // spacing) + 1
        start_y = int(w_top_left.y() // spacing)
        end_y = int(w_bottom_right.y() // spacing) + 1
        
        if (end_x - start_x) * (end_y - start_y) < 15000:
            dot_size = max(2.0, 3.0 / self._scale)
            painter.setPen(QPen(QColor(255, 255, 255, 50), dot_size, Qt.SolidLine, Qt.RoundCap))
            points = []
            for ix in range(start_x, end_x):
                for iy in range(start_y, end_y):
                    points.append(QPointF(ix * spacing, iy * spacing))
            if points:
                painter.drawPoints(points)
        # ------------------------
        painter.restore()

        # Live cursor ring (screen space, sized to the on-screen brush width).
        if self._cursor is not None:
            r = max(self._active_width() / 2, 5.0)
            fill = QColor(255, 255, 255, 60 if self._touching else 30)
            edge = QColor(255, 255, 255, 200 if self._touching else 110)
            painter.setBrush(fill)
            painter.setPen(QPen(edge, 1.5))
            painter.drawEllipse(self._cursor, r, r)

        # HUD.
        mode_txt = "ERASE  (B: draw)" if self._mode == "erase" else "DRAW  (E: erase)"
        label = (f"{mode_txt}   size {int(self._active_width())} [ / ]   "
                 f"zoom {int(self._scale * 100)}%  (arrows pan · +/- zoom · 0 reset · Ctrl+Z undo · Ctrl+S save)")
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor("#9aa0b4"))
        painter.drawText(12, 24, label)
        ip_str = "  ".join(f"http://{ip}:{HTTP_PORT}" for ip in self._ips)
        painter.drawText(12, 44, f"Phone URLs: {ip_str}")
        
        painter.setPen(QColor("#ffffff"))
        painter.drawText(12, 64, f"PIN: {APP_PIN}")

    # ---- save canvas as PNG or PDF ----------------------------------------
    def _save_canvas(self):
        if not self._strokes:
            return
        # Bounding box of all strokes in world coordinates.
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for stroke in self._strokes:
            for pt in stroke["points"]:
                min_x = min(min_x, pt.x())
                max_x = max(max_x, pt.x())
                min_y = min(min_y, pt.y())
                max_y = max(max_y, pt.y())
        # Padding for stroke width.
        max_w = max(s["width"] for s in self._strokes)
        pad = max_w + 40
        min_x -= pad; min_y -= pad
        max_x += pad; max_y += pad
        w = max(1, int(max_x - min_x))
        h = max(1, int(max_y - min_y))
        
        # File dialog.
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Canvas", "sketchpad.png",
            "PNG Image (*.png);;JPEG Image (*.jpg);;PDF Document (*.pdf)")
        if not path:
            return

        if path.lower().endswith('.pdf'):
            from PySide6.QtGui import QPdfWriter, QPageSize
            from PySide6.QtCore import QSizeF
            writer = QPdfWriter(path)
            writer.setPageSize(QPageSize(QSizeF(w, h), QPageSize.Point))
            pdf_painter = QPainter(writer)
            pdf_painter.setRenderHint(QPainter.Antialiasing)
            pdf_painter.translate(-min_x, -min_y)
            for stroke in self._strokes:
                self._draw_stroke(pdf_painter, stroke)
            pdf_painter.end()
            print(f"[save] exported to {path}  ({w}×{h} px)")
        else:
            # Render to QImage.
            img = QImage(w, h, QImage.Format_ARGB32)
            img.fill(BG_COLOR)
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.translate(-min_x, -min_y)
            for stroke in self._strokes:
                self._draw_stroke(painter, stroke)
            painter.end()
            img.save(path)
            print(f"[save] exported to {path}  ({w}×{h} px)")


def main():
    app = QApplication(sys.argv)

    canvas = Canvas()
    canvas.setWindowTitle("LAN Sketchpad")

    bridge = NetworkBridge()
    # Connect BEFORE starting the network thread. Default (auto) connection type
    # detects the cross-thread emit and queues it onto the GUI thread.
    bridge.touch.connect(canvas.on_touch)
    canvas.bridge = bridge      # lets the canvas broadcast scene state outward
    bridge.start()

    canvas.resize(900, 650)
    canvas.show()
    canvas.setFocus()  # ensure the canvas receives key events immediately
    canvas._emit_camera()       # seed the scene cache so new clients get state
    canvas._emit_tool()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
