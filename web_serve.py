"""Minimal static server for the pygbag build (build/web).

Avoids ``os.getcwd()`` (blocked in some sandboxes) by chdir-ing to an
absolute directory and passing it explicitly to the request handler.
Sends the cross-origin isolation headers pygbag prefers.
"""

import http.server
import os
import socketserver

ROOT = "/Users/demetrius/Desktop/bass_rpg/build/web"
PORT = 8000

os.chdir(ROOT)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(socketserver.TCPServer):
    allow_reuse_address = True


with Server(("0.0.0.0", PORT), Handler) as httpd:
    print(f"serving {ROOT} on 0.0.0.0:{PORT}")
    httpd.serve_forever()
