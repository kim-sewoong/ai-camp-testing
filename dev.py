#!/usr/bin/env python3
"""로컬 개발 서버: 정적 파일 + /api/weather (Vercel 함수와 같은 코드).

실행: python3 dev.py  →  http://localhost:3000
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "api"))
import weather  # noqa: E402

PORT = int(os.environ.get("PORT", "3000"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        if self.path.startswith("/api/weather"):
            return weather.handler.do_GET(self)
        return super().do_GET()


if __name__ == "__main__":
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
