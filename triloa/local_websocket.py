"""Small RFC 6455 client for loopback-only NeMo-Speech service use.

This implements the WebSocket features needed by the local transcription
endpoint and has no third-party dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import socket
import struct
from typing import Any


class WebSocketError(ConnectionError):
    """The local WebSocket connection failed or violated the expected protocol."""


class WebSocketClosed(WebSocketError):
    """The server closed the WebSocket connection."""


class LocalWebSocket:
    """A compact text/binary WebSocket client for a trusted local endpoint."""

    _GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    _MAX_FRAME_BYTES = 32 * 1024 * 1024

    def __init__(self, sock: socket.socket, incoming: bytes = b"") -> None:
        self._socket = sock
        self._incoming = bytearray(incoming)
        self._fragment_opcode: int | None = None
        self._fragment_payload = bytearray()
        self._close_sent = False
        self._closed = False

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        path: str,
        *,
        timeout: float = 10.0,
    ) -> "LocalWebSocket":
        if not path.startswith("/"):
            raise ValueError("WebSocket path must begin with '/'")
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: http://{host}:{port}\r\n"
            "\r\n"
        ).encode("ascii")

        try:
            sock.sendall(request)
            response = bytearray()
            header_end = -1
            while header_end < 0:
                chunk = sock.recv(4096)
                if not chunk:
                    raise WebSocketError("server closed during the WebSocket handshake")
                response.extend(chunk)
                if len(response) > 65_536:
                    raise WebSocketError("WebSocket handshake headers are too large")
                header_end = response.find(b"\r\n\r\n")

            header_bytes = bytes(response[:header_end])
            trailing = bytes(response[header_end + 4 :])
            lines = header_bytes.decode("latin-1").split("\r\n")
            status = lines[0].split()
            if len(status) < 2 or status[1] != "101":
                detail = lines[0] if lines else "empty response"
                raise WebSocketError(f"WebSocket handshake was rejected: {detail}")

            headers: dict[str, str] = {}
            for line in lines[1:]:
                name, separator, value = line.partition(":")
                if separator:
                    headers[name.strip().lower()] = value.strip()

            expected_accept = base64.b64encode(
                hashlib.sha1((key + cls._GUID).encode("ascii")).digest()
            ).decode("ascii")
            if headers.get("sec-websocket-accept") != expected_accept:
                raise WebSocketError("invalid Sec-WebSocket-Accept in handshake")
            if headers.get("upgrade", "").lower() != "websocket":
                raise WebSocketError("server did not confirm the WebSocket upgrade")
            if "upgrade" not in {
                token.strip().lower()
                for token in headers.get("connection", "").split(",")
            }:
                raise WebSocketError("server response is missing Connection: Upgrade")

            # Reads are preceded by select(), so a partial TCP read remains buffered.
            sock.settimeout(1.0)
            return cls(sock, trailing)
        except Exception:
            sock.close()
            raise

    def send_json(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self._send_frame(0x1, payload)

    def send_binary(self, payload: bytes) -> None:
        self._send_frame(0x2, payload)

    def receive_json(self, timeout: float = 0.0) -> list[dict[str, Any]]:
        """Return all complete JSON events available before timeout expires."""
        self._read_available(max(0.0, timeout))
        events: list[dict[str, Any]] = []
        for final, opcode, payload in self._take_frames():
            if opcode == 0x9:  # ping
                self._send_control(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                if not self._close_sent:
                    try:
                        self._send_control(0x8, payload[:125])
                    except OSError:
                        pass
                    self._close_sent = True
                self._closed = True
                raise WebSocketClosed("server closed the WebSocket connection")

            message = self._accept_data_frame(final, opcode, payload)
            if message is None:
                continue
            message_opcode, message_payload = message
            if message_opcode != 0x1:
                continue
            try:
                decoded = json.loads(message_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WebSocketError(f"server sent an invalid JSON event: {exc}") from exc
            if not isinstance(decoded, dict):
                raise WebSocketError("server event must be a JSON object")
            events.append(decoded)
        return events

    def close(self) -> None:
        if self._closed:
            try:
                self._socket.close()
            except OSError:
                pass
            return
        try:
            if not self._close_sent:
                self._send_control(0x8, struct.pack("!H", 1000))
                self._close_sent = True
        except OSError:
            pass
        self._closed = True
        try:
            self._socket.close()
        except OSError:
            pass

    def _read_available(self, timeout: float) -> None:
        if self._closed:
            raise WebSocketClosed("WebSocket connection is closed")
        readable, _, _ = select.select([self._socket], [], [], timeout)
        if not readable:
            return

        while readable:
            try:
                chunk = self._socket.recv(65_536)
            except socket.timeout:
                break
            except OSError as exc:
                self._closed = True
                raise WebSocketClosed(f"WebSocket read failed: {exc}") from exc
            if not chunk:
                self._closed = True
                raise WebSocketClosed("server closed the WebSocket connection")
            self._incoming.extend(chunk)
            readable, _, _ = select.select([self._socket], [], [], 0.0)

    def _take_frames(self) -> list[tuple[bool, int, bytes]]:
        frames: list[tuple[bool, int, bytes]] = []
        while len(self._incoming) >= 2:
            first, second = self._incoming[0], self._incoming[1]
            final = bool(first & 0x80)
            opcode = first & 0x0F
            if first & 0x70:
                raise WebSocketError("server set unsupported WebSocket extension bits")

            masked = bool(second & 0x80)
            length = second & 0x7F
            offset = 2
            if length == 126:
                if len(self._incoming) < offset + 2:
                    break
                length = int.from_bytes(self._incoming[offset : offset + 2], "big")
                offset += 2
            elif length == 127:
                if len(self._incoming) < offset + 8:
                    break
                length = int.from_bytes(self._incoming[offset : offset + 8], "big")
                offset += 8

            if length > self._MAX_FRAME_BYTES:
                raise WebSocketError("server WebSocket frame exceeds the local size limit")
            if opcode >= 0x8 and (not final or length > 125):
                raise WebSocketError("invalid fragmented or oversized control frame")

            mask = b""
            if masked:
                if len(self._incoming) < offset + 4:
                    break
                mask = bytes(self._incoming[offset : offset + 4])
                offset += 4
            frame_end = offset + length
            if len(self._incoming) < frame_end:
                break

            payload = bytes(self._incoming[offset:frame_end])
            del self._incoming[:frame_end]
            if masked:
                payload = bytes(
                    value ^ mask[index & 3] for index, value in enumerate(payload)
                )
            frames.append((final, opcode, payload))
        return frames

    def _accept_data_frame(
        self, final: bool, opcode: int, payload: bytes
    ) -> tuple[int, bytes] | None:
        if opcode in {0x1, 0x2}:
            if self._fragment_opcode is not None:
                raise WebSocketError("new data frame arrived before fragmented message ended")
            if final:
                return opcode, payload
            self._fragment_opcode = opcode
            self._fragment_payload = bytearray(payload)
            return None

        if opcode != 0x0:
            raise WebSocketError(f"unsupported WebSocket opcode {opcode}")
        if self._fragment_opcode is None:
            raise WebSocketError("unexpected WebSocket continuation frame")
        if len(self._fragment_payload) + len(payload) > self._MAX_FRAME_BYTES:
            raise WebSocketError("fragmented WebSocket message exceeds the local size limit")
        self._fragment_payload.extend(payload)
        if not final:
            return None

        message = self._fragment_opcode, bytes(self._fragment_payload)
        self._fragment_opcode = None
        self._fragment_payload.clear()
        return message

    def _send_control(self, opcode: int, payload: bytes) -> None:
        if len(payload) > 125:
            raise WebSocketError("WebSocket control payload exceeds 125 bytes")
        self._send_frame(opcode, payload)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise WebSocketClosed("WebSocket connection is closed")
        length = len(payload)
        first = 0x80 | opcode
        if length < 126:
            header = bytes((first, 0x80 | length))
        elif length <= 65_535:
            header = bytes((first, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((first, 0x80 | 127)) + struct.pack("!Q", length)

        mask = os.urandom(4)
        masked = bytes(value ^ mask[index & 3] for index, value in enumerate(payload))
        try:
            self._socket.sendall(header + mask + masked)
        except OSError as exc:
            self._closed = True
            raise WebSocketClosed(f"WebSocket write failed: {exc}") from exc
