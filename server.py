"""LAN Sketchpad - Milestone 1
Serves the phone page over HTTP and prints touch events received over WebSocket.

Run:  python server.py
Then on the phone (same WiFi):  http://<laptop-ip>:8000
"""

import asyncio
import json
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets

HTTP_PORT = 8000
WS_PORT = 8765
ROOT = Path(__file__).parent


def get_lan_ip() -> str:
    """Best-effort local IP by opening a dummy UDP socket to a public address.
    No packets are actually sent; this just makes the OS pick the outbound NIC."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def serve_http():
    """Blocking HTTP server, run in its own thread. Serves index.html from ROOT."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler)
    httpd.serve_forever()


async def ws_handler(websocket):
    """One coroutine per connected phone. Just print whatever arrives."""
    print(f"[ws] phone connected: {websocket.remote_address}")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(f"[ws] non-JSON: {message!r}")
                continue
            print(f"[touch] {data}")
    except websockets.ConnectionClosed:
        pass
    finally:
        print("[ws] phone disconnected")


async def main():
    threading.Thread(target=serve_http, daemon=True).start()
    ip = get_lan_ip()
    print("=" * 48)
    print("LAN Sketchpad - Milestone 1")
    print(f"  On your phone, open:  http://{ip}:{HTTP_PORT}")
    print(f"  (WebSocket on port {WS_PORT})")
    print("=" * 48)

    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
