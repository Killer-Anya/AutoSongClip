#!/usr/bin/env python3
"""Serve the local SongCut player with single byte-range support."""

import argparse
import errno
import os
import re
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

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
    parser.add_argument("--open", action="store_true", help="open the player in the default browser")
    args = parser.parse_args()

    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
            parser.exit(1, f"Port {args.port} is already in use. Close its server or specify a different port.\n")
        parser.exit(1, f"SongCut could not start: {error}\n")

    with server:
        browser_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        url = f"http://{browser_host}:{server.server_port}/web/"
        print(f"SongCut player: {url}", flush=True)
        if args.open:
            Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nSongCut preview stopped.")


if __name__ == "__main__":
    main()
