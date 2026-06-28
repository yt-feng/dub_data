"""A local plain-HTTP CONNECT proxy that forwards through an upstream node.

Chromium/Playwright can't use the subscription's proxies directly: they are
HTTPS-scheme proxies or SOCKS5 proxies *with authentication*, neither of which
Chromium's --proxy-server handles. So we run a tiny local proxy on 127.0.0.1
that Chromium *can* use (plain http, no auth), and forward each CONNECT tunnel
through the upstream node (doing the TLS-to-proxy / SOCKS5 auth ourselves).

Only CONNECT is implemented — enough for HTTPS browsing, which is all dubizzle
needs.
"""

from __future__ import annotations

import base64
import contextlib
import select
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def _open_upstream(upstream: str, host: str, port: int, timeout: int = 20) -> socket.socket:
    u = urlsplit(upstream)
    if u.scheme in ("socks5", "socks5h"):
        import socks  # PySocks

        s = socks.socksocket()
        s.set_proxy(socks.SOCKS5, u.hostname, u.port, rdns=True,
                    username=u.username, password=u.password)
        s.settimeout(timeout)
        s.connect((host, port))
        return s

    # http / https proxy: TCP connect (+TLS if https), then CONNECT.
    raw = socket.create_connection((u.hostname, u.port), timeout=timeout)
    if u.scheme == "https":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw, server_hostname=u.hostname)
    else:
        sock = raw
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if u.username:
        tok = base64.b64encode(f"{u.username}:{u.password}".encode()).decode()
        req += f"Proxy-Authorization: Basic {tok}\r\n"
    req += "\r\n"
    sock.sendall(req.encode())
    # read status line + headers
    buf = b""
    sock.settimeout(timeout)
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    status = buf.split(b"\r\n", 1)[0]
    if b" 200" not in status:
        sock.close()
        raise RuntimeError(f"upstream CONNECT failed: {status[:120]!r}")
    return sock


def _pipe(a: socket.socket, b: socket.socket) -> None:
    socks_ = [a, b]
    with contextlib.suppress(Exception):
        while True:
            r, _, x = select.select(socks_, [], socks_, 60)
            if x or not r:
                break
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)


def _make_handler(upstream: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_CONNECT(self):  # noqa: N802
            try:
                host, port = self.path.rsplit(":", 1)
                up = _open_upstream(upstream, host, int(port))
            except Exception as exc:
                with contextlib.suppress(Exception):
                    self.send_error(502, str(exc)[:100])
                return
            self.send_response(200, "Connection Established")
            self.end_headers()
            _pipe(self.connection, up)
            with contextlib.suppress(Exception):
                up.close()

        def log_message(self, *a):  # silence
            pass

    return Handler


class _QuietServer(ThreadingHTTPServer):
    # Browsers reset idle CONNECT tunnels constantly; don't spew tracebacks.
    def handle_error(self, request, client_address):
        pass


class LocalForwarder:
    """Start a local CONNECT proxy forwarding to `upstream`. Use as a context
    manager; `.endpoint` is the http://127.0.0.1:PORT Chromium should use."""

    def __init__(self, upstream: str):
        self.upstream = upstream
        self.server = _QuietServer(("127.0.0.1", 0), _make_handler(upstream))
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "LocalForwarder":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        with contextlib.suppress(Exception):
            self.server.shutdown()
            self.server.server_close()
