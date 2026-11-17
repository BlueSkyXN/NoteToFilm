#!/usr/bin/env python3
"""本机审阅服务器，支持视频拖动需要的单段 byte range；由 ntf serve 调用。"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def parse_range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError('无效或不支持的范围')
    first, last = match.groups()
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise ValueError('后缀范围必须为正数')
        return max(0, size - suffix), size - 1
    start, end = int(first), int(last) if last else size - 1
    if start >= size or end < start:
        raise ValueError('范围超出文件')
    return start, min(end, size - 1)


class ReviewHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        # 启动时返回地址即可；逐条媒体请求无需刷屏。
        pass

    def send_head(self):
        self.remaining = None
        root = Path(self.directory).resolve()
        try:
            requested = unquote(urlsplit(self.path).path)
            candidate = root / requested.lstrip('/')
            path = candidate.resolve()
            if not path.is_relative_to(root):
                self.send_error(403, 'Outside review directory')
                return None
            if path.is_dir():
                # 支持导出的 review.html；不提供目录列表。
                path = next((path / name for name in ('review.html', 'index.html')
                             if (path / name).is_file()), path)
                path = path.resolve()
            if not path.is_relative_to(root):
                self.send_error(403, 'Outside review directory')
                return None
            if not path.is_file():
                self.send_error(404, 'Review file not found')
                return None
            handle = path.open('rb')
        except (OSError, ValueError, RuntimeError):
            self.send_error(404, 'Review file not found')
            return None

        stat = os.fstat(handle.fileno())
        size = stat.st_size
        start, end, status = 0, size - 1, 200
        # HEAD 忽略 Range；If-Range 无匹配验证器时退回完整响应。
        if self.command == 'GET' and 'Range' in self.headers and 'If-Range' not in self.headers:
            try:
                start, end = parse_range(self.headers['Range'], size)
                status = 206
            except ValueError:
                handle.close()
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                return None
        self.remaining = max(0, end - start + 1)
        self.send_response(status)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Length', str(self.remaining))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Last-Modified', self.date_time_string(stat.st_mtime))
        self.send_header('Cache-Control', 'no-cache')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        handle.seek(start)
        return handle

    def copyfile(self, source, outputfile) -> None:
        remaining = self.remaining
        try:
            while remaining:
                block = source.read(min(64 * 1024, remaining))
                if not block:
                    break
                outputfile.write(block)
                remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            # 播放器切换播放位置时会关闭旧请求。
            pass


def serve(directory: Path, port: int = 0) -> dict:
    directory = directory.expanduser().resolve()
    if not directory.is_dir() or not 0 <= port <= 65535:
        raise ValueError('directory 须为已有目录，port 须在 0 至 65535 之间。')
    with ThreadingHTTPServer(('127.0.0.1', port), partial(ReviewHandler, directory=str(directory))) as server:
        print(json.dumps({'status': 'serving', 'url': f'http://127.0.0.1:{server.server_port}/',
                          'directory': str(directory)}, ensure_ascii=False), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return {'status': 'stopped', 'directory': str(directory)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True, help='ntf preview 导出的独立目录')
    parser.add_argument('--port', type=int, default=0, help='本机端口，0 自动分配')
    args = parser.parse_args()
    try:
        serve(args.directory, args.port)
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
