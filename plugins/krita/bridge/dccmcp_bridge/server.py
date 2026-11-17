"""Local TCP server inside Krita. Socket signals arrive on the Qt main thread, so commands do too."""
from __future__ import annotations

import json
import os
import secrets

from PyQt5.QtCore import QObject
from PyQt5.QtNetwork import QHostAddress, QTcpServer

from .commands import respond, state_file

MAX_LINE = 16 * 1024 * 1024  # a krita.python script larger than this is a mistake


class BridgeServer(QObject):
    def __init__(self, bridge, parent=None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.token = secrets.token_hex(16)
        self.buffers = {}
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        if not self.server.listen(QHostAddress.LocalHost, 0):  # localhost only, port picked by the OS
            raise RuntimeError(f"DCC-MCP bridge could not listen: {self.server.errorString()}")
        self.path = state_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"port": self.server.serverPort(), "token": self.token,
                                         "pid": os.getpid()}), encoding="utf-8")

    def close(self) -> None:
        self.server.close()
        try:
            self.path.unlink()
        except OSError:
            pass

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self.buffers.pop(s, None))

    def _read(self, sock) -> None:
        buf = self.buffers.get(sock, b"") + bytes(sock.readAll())
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            reply = respond(self.bridge, self.token, line)
            sock.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            sock.flush()
        if len(buf) > MAX_LINE:
            sock.disconnectFromHost()
            buf = b""
        self.buffers[sock] = buf
