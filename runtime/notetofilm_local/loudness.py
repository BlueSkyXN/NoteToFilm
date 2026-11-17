#!/usr/bin/env python3
"""双遍校准成片响度，复制视频码流并保留源文件；由 ntf normalize 调用。"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


def run(argv: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"{Path(argv[0]).name} 执行失败：{result.stderr[-2000:].strip()}")
    return result


def loudnorm_result(stderr: str) -> dict:
    start = stderr.rfind('{')
    try:
        value, _ = json.JSONDecoder().raw_decode(stderr[start:])
        numbers = {key: float(value[key]) for key in
                   ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')}
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('无法读取 FFmpeg loudnorm 测量结果。') from exc
    if not all(math.isfinite(number) for number in numbers.values()):
        raise ValueError('音轨为静音或响度无法测量；请检查实际音频。')
    return {**numbers, 'normalization_type': value.get('normalization_type')}


def measure(path: Path, filters: str, ffmpeg: str) -> dict:
    result = run([ffmpeg, '-hide_banner', '-nostats', '-nostdin', '-i', str(path),
                  '-map', '0:a:0', '-vn', '-sn', '-dn', '-af', filters,
                  '-f', 'null', '-'])
    return loudnorm_result(result.stderr)


def require_new(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f'输出已存在，请选择新路径：{path}')
    if not path.parent.is_dir():
        raise ValueError(f'输出父目录不存在：{path.parent}')


def normalize(input_path: Path, output_path: Path, *, lufs: float = -17,
              true_peak: float = -2, lra: float = 11, report: Path | None = None,
              ffmpeg: str = 'ffmpeg', ffprobe: str = 'ffprobe') -> dict:
    source = input_path.expanduser().resolve(strict=True)
    output = output_path.expanduser().absolute()
    report = report.expanduser().absolute() if report else None
    if not source.is_file():
        raise ValueError('输入必须是可读取的媒体文件。')
    if output.resolve() == source:
        raise ValueError('输出不能覆盖源文件，请选择新的 MP4 路径。')
    if output.suffix.lower() != '.mp4':
        raise ValueError('输出文件扩展名须为 .mp4。')
    require_new(output)
    if report:
        if report.resolve() in (source, output.resolve()):
            raise ValueError('报告路径须与输入、输出视频不同。')
        require_new(report)
    for name, value, low, high in (('lufs', lufs, -70, -5),
                                  ('true_peak', true_peak, -9, 0),
                                  ('lra', lra, 1, 50)):
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} 必须在 {low} 至 {high} 之间。')

    probe = json.loads(run([ffprobe, '-v', 'error', '-show_entries',
                            'stream=index,codec_type,codec_name', '-of', 'json', str(source)]).stdout)
    streams = probe.get('streams', [])
    videos = [stream for stream in streams if stream.get('codec_type') == 'video']
    audios = [stream for stream in streams if stream.get('codec_type') == 'audio']
    if not videos or not audios:
        raise ValueError('输入须同时包含视频和音轨；请先完成合成。')

    target = f'I={lufs}:TP={true_peak}:LRA={lra}'
    analysis_filter = f'loudnorm={target}:print_format=json'
    initial = measure(source, analysis_filter, ffmpeg)
    apply_filter = (f'loudnorm={target}:measured_I={initial["input_i"]}'
                    f':measured_TP={initial["input_tp"]}:measured_LRA={initial["input_lra"]}'
                    f':measured_thresh={initial["input_thresh"]}:offset={initial["target_offset"]}'
                    ':linear=true:print_format=json')

    with tempfile.TemporaryDirectory(prefix='.ntf-loudness-', dir=output.parent) as directory:
        staged = Path(directory) / 'normalized.mp4'
        encoded = run([ffmpeg, '-hide_banner', '-nostats', '-nostdin', '-n', '-i', str(source),
                       '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-af', apply_filter,
                       '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                       '-movflags', '+faststart', str(staged)])
        applied = loudnorm_result(encoded.stderr)
        final = measure(staged, analysis_filter, ffmpeg)
        result = {
            'status': 'completed', 'input': str(source), 'output': str(output),
            'video_stream': 'copy first video', 'audio_stream': 'first audio to AAC 192k 48kHz',
            'target': {'lufs': lufs, 'true_peak_dbtp': true_peak, 'lra_lu': lra},
            'source_measurement': initial,
            'second_pass_normalization_type': applied['normalization_type'],
            'final_measurement': {'integrated_lufs': final['input_i'],
                                  'true_peak_dbtp': final['input_tp'], 'lra_lu': final['input_lra']},
            'deviation_lufs': round(final['input_i'] - lufs, 3),
        }
        # 同目录临时文件以硬链接发布，已有目标（包括并发创建）不会被覆盖。
        os.link(staged, output)
        if report:
            try:
                with tempfile.TemporaryDirectory(prefix='.ntf-report-', dir=report.parent) as report_dir:
                    staged_report = Path(report_dir) / 'report.json'
                    staged_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                    os.link(staged_report, report)
            except OSError:
                output.unlink()
                raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='已有成片，读取第一条视频和音轨')
    parser.add_argument('--output', required=True, type=Path, help='新 MP4 文件，不覆盖已有文件')
    parser.add_argument('--lufs', type=float, default=-17, help='整体响度目标，默认 -17 LUFS')
    parser.add_argument('--true-peak', type=float, default=-2, help='真峰值上限，默认 -2 dBTP')
    parser.add_argument('--lra', type=float, default=11, help='响度范围目标，默认 11 LU')
    parser.add_argument('--report', type=Path, help='可选的新 JSON 报告路径')
    parser.add_argument('--ffmpeg', default='ffmpeg', help='现有 ffmpeg 命令或路径')
    parser.add_argument('--ffprobe', default='ffprobe', help='现有 ffprobe 命令或路径')
    args = parser.parse_args()
    try:
        result = normalize(args.input, args.output, lufs=args.lufs, true_peak=args.true_peak,
                           lra=args.lra, report=args.report, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
