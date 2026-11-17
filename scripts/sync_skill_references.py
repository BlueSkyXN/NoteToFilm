#!/usr/bin/env python3
"""检查或同步源码技能的公共引用；不改已安装的定位文件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
COMMON = ('runtime.md', 'project-format.md', 'commands.md')


def sync(root: Path, *, write: bool = False) -> dict:
    shared = {name: (root / 'shared' / name).read_bytes() for name in COMMON}
    skills = sorted(path.parent for path in (root / '.agents/skills').glob('*/SKILL.md'))
    if not skills:
        raise ValueError('未找到源码技能目录。')
    targets = []
    for skill in skills:
        runtime = skill / 'references/runtime.md'
        if (skill / 'agents/notetofilm-install.json').exists() or (runtime.exists() and b'"ntf_command"' in runtime.read_bytes()):
            raise ValueError('检测到已安装技能；请在未安装的技能源目录运行。')
        for name, content in shared.items():
            target = skill / 'references' / name
            if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
                raise ValueError('公共引用须位于源码目录内且不能是符号链接。')
            if not target.is_file() or target.read_bytes() != content:
                targets.append((target, content))
    if write:
        for path, content in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return {'status': 'synchronized' if write else ('drift' if targets else 'current'),
            'skill_count': len(skills), 'reference_count': len(skills) * len(COMMON),
            'files': [path.relative_to(root).as_posix() for path, _ in targets]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='只检查差异；默认行为')
    mode.add_argument('--write', action='store_true', help='同步三份公共引用到源码技能')
    args = parser.parse_args()
    try:
        result = sync(ROOT, write=args.write)
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['status'] == 'drift' else 0


if __name__ == '__main__':
    raise SystemExit(main())
