#!/usr/bin/env python3
"""用 PyInstaller 把 ntf 打成可执行程序：dist/ntf 指向 dist/ntf-runtime/ntf。

在已安装运行依赖的环境执行，例如：
    python3 -m pip install -e '.[audio,render,build]'
    python3 scripts/build_binary.py
当前环境可导入的可选依赖（edge-tts、Pillow、PyYAML）会一并打包；网页动画渲染需要的 Playwright 不打包。
程序与依赖库以目录形式存放，库文件只在首次启动时被系统检查，之后每次启动不再解包。
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
OPTIONAL = {'edge_tts': 'audio', 'PIL': 'render', 'yaml': 'yaml'}
NAME = 'ntf'


def build(dist):
    if importlib.util.find_spec('PyInstaller') is None:
        raise SystemExit("当前 Python 没有 PyInstaller；在含运行依赖的环境执行 pip install -e '.[audio,render,build]'。")
    included = {extra: importlib.util.find_spec(module) is not None for module, extra in OPTIONAL.items()}
    work = ROOT / 'build/pyinstaller'
    command = [sys.executable, '-m', 'PyInstaller', '--onedir', '--noconfirm', '--clean', '--log-level', 'WARN',
               '--name', NAME, '--distpath', str(work / 'dist'), '--workpath', str(work), '--specpath', str(work),
               '--paths', str(ROOT / 'runtime'),
               '--collect-submodules', 'notetofilm_local',
               '--add-data', os.pathsep.join([str(ROOT / 'runtime/notetofilm_local/data'), 'notetofilm_local/data']),
               '--exclude-module', 'playwright', '--exclude-module', 'tkinter']
    if included['audio']:
        command += ['--collect-submodules', 'edge_tts']
    command.append(str(ROOT / 'scripts/ntf.py'))
    subprocess.run(command, check=True, cwd=ROOT)
    runtime, link = dist / f'{NAME}-runtime', dist / NAME
    dist.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.is_file():
        link.unlink()
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.move(str(work / 'dist' / NAME), runtime)
    if os.name == 'nt':
        entry = runtime / f'{NAME}.exe'
    else:
        link.symlink_to(Path(runtime.name) / NAME)
        entry = link
    version = subprocess.run([str(entry), '--version'], capture_output=True, text=True, check=True, timeout=120).stdout.strip()
    info = json.loads(subprocess.run([str(entry), 'install-info'], capture_output=True, text=True, check=True, timeout=120).stdout)
    size = sum(path.stat().st_size for path in runtime.rglob('*') if path.is_file())
    return {'command': str(entry), 'runtime_dir': str(runtime), 'size_bytes': size, 'version': version,
            'included_extras': included, 'ffmpeg': info.get('ffmpeg'), 'edge_tts': info.get('edge_tts'),
            'text_rendering': info.get('text_rendering')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dist', default=str(ROOT / 'dist'), help='输出目录，默认仓库根目录的 dist/')
    args = parser.parse_args()
    print(json.dumps(build(Path(args.dist).resolve()), ensure_ascii=False, indent=2))
