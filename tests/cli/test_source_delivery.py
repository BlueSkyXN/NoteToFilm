"""从正式源码包安装实际 CLI 与 Skill，移走源码后完成离线制片。"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ntf_source_delivery_package', ROOT / 'scripts/package.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class SourceDeliveryTests(unittest.TestCase):
    def execute(self, *args):
        environment = os.environ.copy()
        for name in ('PYTHONPATH', 'PYTHONHOME'):
            environment.pop(name, None)
        result = subprocess.run([str(arg) for arg in args], cwd=self.directory,
                                env=environment, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    @unittest.skipIf(os.name == 'nt', '独立运行验收当前覆盖 POSIX 启动器')
    def test_archive_installs_real_skills_and_composes_without_source(self):
        with tempfile.TemporaryDirectory(prefix='ntf-source-delivery-') as temporary:
            self.directory = Path(temporary).resolve()
            archive = self.directory / 'delivery.zip'
            if (ROOT / '.git').exists():
                components = [path.relative_to(ROOT).as_posix() for path in packager.included_files(ROOT)]
                ignored = subprocess.run(['git', 'check-ignore', '--stdin'], cwd=ROOT,
                                         input='\n'.join(components) + '\n',
                                         capture_output=True, text=True, timeout=20)
                self.assertEqual(ignored.returncode, 1, ignored.stdout + ignored.stderr)
            packager.build(ROOT, archive)
            with zipfile.ZipFile(archive) as source_zip:
                names = {Path(name).relative_to('notetofilm-local').as_posix()
                         for name in source_zip.namelist()}
                self.assertIn('runtime/notetofilm_local/cli.py', names)
                self.assertIn('scripts/check_cli.py', names)
                self.assertIn('configs/company.example.json', names)
                self.assertIn('tests/cli/test_source_delivery.py', names)
                self.assertEqual(sum(name.endswith('/SKILL.md') for name in names), 7)
                self.assertFalse(any(name.startswith(('app/', 'local/', 'data/', 'config/')) for name in names))
                self.assertFalse({'requirements.txt', 'scripts/check_tests.py', 'scripts/migrate_config.py'} & names)
                source_zip.extractall(self.directory)
            source = self.directory / 'notetofilm-local'
            self.assertFalse((source / 'local').exists())
            self.execute(sys.executable, source / 'scripts/ntf.py', '--help')
            self.execute(sys.executable, source / 'scripts/sync_skill_references.py', '--check')

            installed = json.loads(self.execute(
                sys.executable, source / 'scripts/install.py',
                '--skills-dir', self.directory / 'installed skills',
                '--runtime-dir', self.directory / 'installed runtime',
            ))
            command = installed['ntf_command']
            self.assertEqual(len(installed['skills']), 7)
            self.execute(command, 'init', self.directory / 'project', '--title', 'Offline delivery')
            self.execute(sys.executable, source / 'examples/create_media_fixture.py',
                         '--output', self.directory / 'project')
            project = self.directory / 'project'
            manifest_path = project / 'compose.json'
            self.assertEqual(json.loads(manifest_path.read_text())['output']['subtitles_mode'], 'sidecar')
            originals = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (project / 'assets').iterdir() if path.is_file()}

            # 移动后保持原源码路径不存在，启动器和媒体处理只能使用安装包。
            source.rename(self.directory / 'source-moved-away')
            self.assertFalse(source.exists())
            version = self.execute(command, '--version').strip()
            self.assertEqual(version, f"NoteToFilm CLI {installed['version']}")
            information = json.loads(self.execute(command, 'install-info'))
            self.assertTrue(Path(information['package']).is_relative_to(Path(installed['runtime_dir'])))
            self.assertIsNone(information['edge_tts'])
            for name in installed['skills']:
                skill = Path(installed['skills_dir']) / name
                text = (skill / 'references/runtime.md').read_text()
                locator = json.loads(re.search(r'```json\n(.*?)\n```', text, re.DOTALL).group(1))
                self.assertEqual(locator['ntf_command'], command)
                self.assertEqual(set(locator['skill_locations']), set(installed['skills']))
                self.assertTrue(all((Path(path) / 'SKILL.md').is_file()
                                    for path in locator['skill_locations'].values()))
                self.assertNotIn('local/bin/ntf', text)

            rendered = json.loads(self.execute(command, 'compose', project, '--manifest', manifest_path))
            video = project / rendered['video_path']
            self.assertTrue(video.is_file())
            inspected = json.loads(self.execute(
                command, 'inspect', video, '--decode', '--expect-width', '640',
                '--expect-height', '360', '--expect-fps', '15',
                '--expect-duration', '4.6', '--expect-audio', 'yes',
            ))
            self.assertTrue(inspected['verification']['passed'])
            self.assertEqual(inspected['full_decode'], 'passed')
            self.assertTrue(json.loads(self.execute(command, 'status', project))['complete'])
            self.execute(command, 'preview', project, '--video', video, '--output', self.directory / 'review')
            self.assertTrue((self.directory / 'review/review.html').is_file())
            self.assertEqual(originals, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in (project / 'assets').iterdir() if path.is_file()})


if __name__ == '__main__':
    unittest.main()
