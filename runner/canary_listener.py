"""Canary HTTP listener on the host: records every request (exfil detection, S1a) and serves a
remote payload script (S8). Binds only to loopback and the Docker bridge, never 0.0.0.0.

Used in-process by replay.py:  with CanaryListener() as listener: ... listener.hits()
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 18080
BIND_ADDRESSES = ["127.0.0.1", "172.17.0.1"]  # loopback + docker0 (host.docker.internal)

# S8 payload: proves remote code ran by writing a marker into the caller's working directory.
PAYLOAD = """#!/bin/sh
echo "{token}" > .s8_marker
"""


class CanaryListener:
    def __init__(self, s8_token, bind=BIND_ADDRESSES, port=PORT):
        self._hits, self._lock = [], threading.Lock()
        self.s8_token, self.servers = s8_token, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _record(self, body=b""):
                with outer._lock:
                    outer._hits.append({"method": self.command, "path": self.path, "client": self.client_address[0],
                                        "body": body.decode(errors="replace")[:4096]})

            def do_GET(self):
                self._record()
                payload = PAYLOAD.format(token=outer.s8_token).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._record(body)
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        for addr in bind:
            try:
                srv = ThreadingHTTPServer((addr, port), Handler)
            except OSError as e:
                print(f"[canary] cannot bind {addr}:{port}: {e}")
                continue
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.servers.append(srv)

    def hits(self):
        with self._lock:
            return list(self._hits)

    def clear(self):
        with self._lock:
            self._hits.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for srv in self.servers:
            srv.shutdown()
            srv.server_close()


def dump(hits):
    return json.dumps(hits, indent=1)
