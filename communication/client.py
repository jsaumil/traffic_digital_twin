"""Small RFC6455 loopback client for Blender's standard library.

Validates upgrade, handles extended lengths, fragmentation, ping/pong and close.
Deliberately negotiates no compression, TLS, or remote hosts.
"""
import base64
import hashlib
import os
import socket
import struct
from urllib.parse import urlsplit

from communication.protocol import MAX_BYTES, dumps, loads


class WebSocketClient:
    def __init__(self, url, timeout=2):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Only loopback ws:// endpoints are supported")
        self.socket = socket.create_connection((parsed.hostname, parsed.port or 80), timeout)
        self.buffer = bytearray()
        self.fragments = bytearray()
        self.fragmented = False
        key = base64.b64encode(os.urandom(16)).decode()
        path = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        host = f"{parsed.hostname}:{parsed.port or 80}"
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        try:
            self.socket.sendall(request.encode())
            while b"\r\n\r\n" not in self.buffer:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Server closed handshake")
                self.buffer.extend(chunk)
                if len(self.buffer) > 8192:
                    raise ValueError("Oversized WebSocket handshake")
            header, remainder = bytes(self.buffer).split(b"\r\n\r\n", 1)
            self.buffer = bytearray(remainder)
            lines = header.decode("ascii").split("\r\n")
            headers = {key.lower():value for key,value in
                       (line.split(":",1) for line in lines[1:] if ":" in line)}
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if (not lines[0].startswith("HTTP/1.1 101 ") or
                    headers.get("sec-websocket-accept", "").strip() != expected or
                    headers.get("upgrade", "").strip().lower() != "websocket"):
                raise ValueError("Invalid WebSocket upgrade")
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def _read(self, count):
        while len(self.buffer) < count:
            chunk = self.socket.recv(max(4096, count - len(self.buffer)))
            if not chunk:
                raise ConnectionError("WebSocket disconnected")
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def _send(self, opcode, payload):
        size = len(payload)
        if size > MAX_BYTES:
            raise ValueError("Frame too large")
        header = bytes([0x80 | opcode])
        header += bytes([0x80 | size]) if size < 126 else (bytes([0x80 | 126]) + struct.pack("!H", size) if size < 65536 else bytes([0x80 | 127]) + struct.pack("!Q", size))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.socket.sendall(header + mask + masked)

    def send(self, message):
        self._send(1, dumps(message).encode())

    def receive(self):
        while True:
            first, second = self._read(2)
            final, opcode = bool(first & 128), first & 15
            if first & 112 or second & 128:
                raise ValueError("Unsupported compressed/masked server frame")
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > MAX_BYTES or (opcode >= 8 and (length > 125 or not final)):
                raise ValueError("Invalid frame size/control frame")
            payload = self._read(length)
            if opcode == 8:
                raise ConnectionError("WebSocket closed by server")
            if opcode == 9:
                self._send(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 1:
                if self.fragmented:
                    raise ValueError("Nested fragmented message")
                self.fragments = bytearray(payload)
                self.fragmented = not final
            elif opcode == 0 and self.fragmented:
                self.fragments.extend(payload)
                self.fragmented = not final
            else:
                raise ValueError("Expected text WebSocket frame")
            if len(self.fragments) > MAX_BYTES:
                raise ValueError("Message too large")
            if final:
                message = loads(bytes(self.fragments))
                self.fragments.clear()
                return message
