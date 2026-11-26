#!/usr/bin/env python3
"""量成片或参考片的运动量：镜头运动、画内运动和近乎静止的区间，供不同来源的片子对照。

在 Agent 当前使用的 Python 里运行，需要 FFmpeg/ffprobe、OpenCV 和 NumPy；只读视频，不写项目。
"""

import argparse
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys


FPS = 10
WIDTH = 320
GRID = 16
STILL_LEVEL = 0.5
CUT_DIFF = 25.0
MIN_RUN = 1.5
INSTALL_HINT = ('需要 OpenCV 和 NumPy。先征得用户同意，再在独立环境里安装：'
                'python3 -m venv ENV && ENV/bin/python -m pip install opencv-python-headless numpy，'
                '然后用 ENV/bin/python 运行本脚本。同一环境里不要同时装 opencv-python 和 opencv-python-headless。')
EPILOG = ('镜头运动是光流的整体平移、缩放和旋转，画内运动是去掉镜头运动后剩下的部分，'
          '含叠加的字和线条动画；单位都是每秒移动占画面宽度的百分比。'
          '镜头数和镜长用 ntf inspect --scan 的 pace。')


class MeasureError(Exception):
    pass


def scaled_size(width, height, rotation=0):
    """按显示方向缩到 WIDTH 宽，高取偶数。"""
    if round(abs(rotation)) % 180 == 90:
        width, height = height, width
    return WIDTH, max(2, round(WIDTH * height / width / 2) * 2)


def still_runs(flags, fps, min_seconds):
    runs, start = [], None
    for index, flag in enumerate(list(flags) + [False]):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            if (index - start) / fps >= min_seconds:
                runs.append({'start_seconds': round(start / fps, 1), 'end_seconds': round(index / fps, 1)})
            start = None
    return runs


def _p75(values):
    return values[0] if len(values) < 2 else statistics.quantiles(values, n=4, method='inclusive')[2]


def summarize(steps, *, fps=FPS, still_level=STILL_LEVEL, cut_diff=CUT_DIFF, min_run=MIN_RUN):
    """steps 是相邻两帧的 (镜头运动, 画内运动, 平均灰度差)，运动已换算成每秒占画宽的百分比。"""
    if not steps:
        raise MeasureError('没有读到两帧以上的画面。')
    jumps = [diff > cut_diff for _, _, diff in steps]
    still = [not jump and camera < still_level and local < still_level
             for (camera, local, _), jump in zip(steps, jumps)]
    camera = [c for (c, _, _), jump in zip(steps, jumps) if not jump]
    local = [l for (_, l, _), jump in zip(steps, jumps) if not jump]
    runs = still_runs(still, fps, min_run)
    span = len(steps) / fps
    return {
        'measured_seconds': round(span, 1),
        'camera_motion_median': round(statistics.median(camera), 2) if camera else None,
        'in_frame_motion_median': round(statistics.median(local), 2) if local else None,
        'in_frame_motion_p75': round(_p75(local), 2) if local else None,
        'still_share': round(sum(still) / len(still), 3),
        'still_runs': runs,
        'still_runs_share': round(sum(r['end_seconds'] - r['start_seconds'] for r in runs) / span, 3),
        'jump_steps': sum(jumps),
    }


def _require_tools():
    missing = [name for name in ('ffmpeg', 'ffprobe') if shutil.which(name) is None]
    if missing:
        raise MeasureError(f'找不到 {"、".join(missing)}，先安装 FFmpeg。')
    try:
        import cv2
        import numpy
    except ImportError as exc:
        raise MeasureError(INSTALL_HINT) from exc
    return cv2, numpy


def _probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                             'stream=width,height:stream_side_data=rotation', '-of', 'json', str(path)],
                            capture_output=True, text=True)
    streams = json.loads(result.stdout or '{}').get('streams') if result.returncode == 0 else None
    if not streams:
        raise MeasureError(f'{path}: 读不到视频流。{result.stderr.strip()}')
    stream = streams[0]
    rotation = next((item.get('rotation', 0) for item in stream.get('side_data_list', []) if 'rotation' in item), 0)
    return scaled_size(stream['width'], stream['height'], rotation)


def _frames(path, width, height, numpy):
    command = ['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:v:0', '-an', '-vf',
               f'fps={FPS},scale={width}:{height}:flags=area,format=gray', '-f', 'rawvideo', '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    size = width * height
    while True:
        buffer = process.stdout.read(size)
        if len(buffer) < size:
            break
        yield numpy.frombuffer(buffer, numpy.uint8).reshape(height, width)
    error = process.stderr.read().decode(errors='replace').strip()
    if process.wait() != 0:
        raise MeasureError(f'{path}: FFmpeg 解码失败。{error}')


def measure(path, *, still_level=STILL_LEVEL, cut_diff=CUT_DIFF, min_run=MIN_RUN):
    cv2, numpy = _require_tools()
    width, height = _probe(path)
    ys, xs = numpy.mgrid[GRID // 2:height:GRID, GRID // 2:width:GRID]
    points = numpy.stack([xs.ravel(), ys.ravel(), numpy.ones(xs.size)], 1)
    scale = FPS / width * 100
    steps, previous = [], None
    for frame in _frames(path, width, height, numpy):
        if previous is not None:
            flow = cv2.calcOpticalFlowFarneback(previous, frame, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            vectors = flow[ys, xs].reshape(-1, 2)
            affine, *_ = numpy.linalg.lstsq(points, vectors, rcond=None)
            fitted = points @ affine
            steps.append((float(numpy.mean(numpy.linalg.norm(fitted, axis=1))) * scale,
                          float(numpy.mean(numpy.linalg.norm(vectors - fitted, axis=1))) * scale,
                          float(numpy.mean(cv2.absdiff(frame, previous)))))
        previous = frame
    return {'file': str(path), 'frame': f'{width}x{height}@{FPS}fps',
            **summarize(steps, still_level=still_level, cut_diff=cut_diff, min_run=min_run)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=EPILOG)
    parser.add_argument('files', nargs='+', type=Path, metavar='FILM', help='要量的视频，可一次给多支')
    parser.add_argument('--output', type=Path, help='另存 JSON 结果')
    parser.add_argument('--still-level', type=float, default=STILL_LEVEL,
                        help=f'镜头运动和画内运动都低于它算近乎静止，默认 {STILL_LEVEL}（%%画宽/秒）')
    parser.add_argument('--cut-diff', type=float, default=CUT_DIFF,
                        help=f'相邻帧平均灰度差超过它算跳变，不计入运动统计，默认 {CUT_DIFF:g}（0–255）')
    parser.add_argument('--min-run', type=float, default=MIN_RUN,
                        help=f'近乎静止至少持续多少秒才列入 still_runs，默认 {MIN_RUN}')
    args = parser.parse_args(argv)
    try:
        for path in args.files:
            if not path.is_file():
                raise MeasureError(f'{path}: 文件不存在。')
        films = [measure(path, still_level=args.still_level, cut_diff=args.cut_diff, min_run=args.min_run)
                 for path in args.files]
    except MeasureError as exc:
        print(f'measure_motion: {exc}', file=sys.stderr)
        return 2
    report = {'films': films,
              'method': {'units': '%画宽/秒', 'sample_fps': FPS, 'sample_width': WIDTH, 'grid': GRID,
                         'still_level': args.still_level, 'cut_diff': args.cut_diff, 'min_run_seconds': args.min_run}}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
