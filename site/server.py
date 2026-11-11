#!/usr/bin/env python3
"""Serve the local SongCut player with single byte-range support."""

import argparse
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).resolve().parent
BYTE_RANGE = re.compile(r"bytes=([0-9]{0,20})-([0-9]{0,20})")


class LimitedFile:
    """Read at most the bytes selected by a range request."""

    def __init__(self, file, remaining):
        self.file = file
        self.remaining = remaining

    def read(self, size):
        data = self.file.read(min(size, self.remaining))
        self.remaining -= len(data)
        return data

    def close(self):
        self.file.close()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def list_directory(self, path):
        self.send_error(404)

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if not path.resolve().is_relative_to(SITE):
            self.send_error(404)
            return None

        value = self.headers.get("Range", "")
        match = BYTE_RANGE.fullmatch(value)
        if self.command != "GET" or not match or not any(match.groups()) or not path.is_file():
            return super().send_head()

        try:
            file = path.open("rb")
        except OSError:
            self.send_error(404)
            return None

        size = os.fstat(file.fileno()).st_size
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
        else:
            start = max(0, size - int(last))
            end = size - 1

        if start > end:
            file.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        file.seek(start)
        length = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        return LimitedFile(file, length)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=18081)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        print(f"SongCut player: http://{args.host}:{server.server_port}/web/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
