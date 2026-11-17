"""验证技能资料可从入口到达、共享引用同步和正式分镜示例可执行。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ntf_sync_references_test', ROOT / 'scripts/sync_skill_references.py')
sync_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_module)


class SkillLayoutTests(unittest.TestCase):
    def test_reference_graph_is_self_contained_and_reachable(self):
        for entry in (ROOT / '.agents/skills').glob('*/SKILL.md'):
            skill = entry.parent.resolve()
            visited, pending = set(), [entry.resolve()]
            while pending:
                path = pending.pop()
                if path in visited:
                    continue
                visited.add(path)
                for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                    if re.match(r'^[a-z]+:', link) or link.startswith('#'):
                        continue
                    target = (path.parent / link.split('#')[0]).resolve()
                    self.assertTrue(target.is_relative_to(skill), f'{path}: link outside skill: {link}')
                    self.assertTrue(target.is_file(), f'{path}: missing link: {link}')
                    if target.suffix == '.md':
                        pending.append(target)
            expected = {path.resolve() for path in (skill / 'references').rglob('*.md')}
            self.assertFalse(expected - visited, f'{skill.name}: unreachable references: {expected - visited}')

    def make_source(self, base: str) -> Path:
        root = Path(base)
        (root / 'shared').mkdir()
        for name in sync_module.COMMON:
            (root / 'shared' / name).write_text(f'# {name}\nShared source\n')
        for name in ('skill-a', 'skill-b'):
            skill = root / '.agents/skills' / name
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('# Fixture skill\n')
        return root

    def test_shared_sync_check_is_readonly_and_write_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='ntf-shared-test-') as directory:
            root = self.make_source(directory)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            result = sync_module.sync(root)
            self.assertEqual(result['status'], 'drift')
            self.assertEqual(before, {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()})
            sync_module.sync(root, write=True)
            for skill in (root / '.agents/skills').iterdir():
                for name in sync_module.COMMON:
                    self.assertEqual((skill / 'references' / name).read_bytes(), (root / 'shared' / name).read_bytes())
            self.assertEqual(sync_module.sync(root)['status'], 'current')
            self.assertEqual(sync_module.sync(root, write=True)['files'], [])

    def test_shared_sync_preserves_installed_runtime_locator(self):
        with tempfile.TemporaryDirectory(prefix='ntf-shared-installed-test-') as directory:
            root = self.make_source(directory)
            sync_module.sync(root, write=True)
            runtime = root / '.agents/skills/skill-b/references/runtime.md'
            installed = b'{"ntf_command":"LOCAL_TEST_COMMAND"}'
            runtime.write_bytes(installed)
            (root / 'shared/commands.md').write_text('new commands')
            previous = (root / '.agents/skills/skill-a/references/commands.md').read_bytes()
            with self.assertRaises(ValueError):
                sync_module.sync(root, write=True)
            self.assertEqual(runtime.read_bytes(), installed)
            self.assertEqual((root / '.agents/skills/skill-a/references/commands.md').read_bytes(), previous)

    def test_storyboard_example_can_be_saved_and_planned(self):
        text = (ROOT / '.agents/skills/notetofilm-direct/references/examples.md').read_text()
        example = json.loads(re.search(r'```json\n(.*?)\n```', text, re.DOTALL).group(1))
        with tempfile.TemporaryDirectory(prefix='ntf-design-example-') as directory:
            source, project = Path(directory) / 'storyboard.json', Path(directory) / 'project'
            source.write_text(json.dumps(example, ensure_ascii=False))
            for args in (['init', str(project), '--title', 'Design example'],
                         ['storyboard', str(project), '--file', str(source)], ['plan', str(project)]):
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/ntf.py'), *args],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            saved = json.loads((project / 'storyboard.json').read_text())
            self.assertEqual([scene['id'] for scene in saved['scenes']], ['s01', 's02'])
            self.assertTrue((project / 'workflow.json').is_file())


if __name__ == '__main__':
    unittest.main()
