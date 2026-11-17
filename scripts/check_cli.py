#!/usr/bin/env python3
"""运行 CLI、Skill 和真实本地媒体处理的严格离线回归。"""

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent


def run():
    if sys.version_info < (3, 11):
        raise SystemExit('需要 Python 3.11 或更高版本。')
    for module in ('PIL', 'yaml', 'edge_tts'):
        if importlib.util.find_spec(module) is None:
            raise SystemExit('缺少 CLI 测试依赖；在测试环境安装 .[audio,render,test]。')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise SystemExit(f'需要 {tool}；媒体测试不能跳过。')
    encoders = subprocess.check_output(['ffmpeg', '-hide_banner', '-encoders'], text=True)
    available = {line.split()[1] for line in encoders.splitlines() if len(line.split()) > 1}
    for encoder in ('libx264', 'libmp3lame', 'aac', 'png'):
        if encoder not in available:
            raise SystemExit(f'FFmpeg 缺少编码器：{encoder}')
    synchronized = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'scripts/sync_skill_references.py'), '--check'],
        check=False,
    )
    if synchronized.returncode:
        return synchronized.returncode
    # Keep tests away from real credentials: no project .env, an empty Codex home.
    import os, tempfile
    os.environ['NTF_ENV_FILE'] = os.devnull
    os.environ['CODEX_HOME'] = tempfile.mkdtemp(prefix='ntf-test-codex-')
    for name in [key for key in os.environ if key.startswith(('NTF_CPA_', 'NTF_UNIAPI_', 'NTF_COMPANY_'))]:
        os.environ.pop(name)
    sys.path.insert(0, str(ROOT / 'runtime'))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests/cli'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {'tests': result.testsRun, 'failures': len(result.failures),
               'errors': len(result.errors), 'skipped': len(result.skipped),
               'unexpected_successes': len(result.unexpectedSuccesses)}
    print(json.dumps(summary), flush=True)
    return 0 if result.testsRun and result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(run())
