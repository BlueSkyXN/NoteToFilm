#!/usr/bin/env python3
"""Install this skill suite into explicitly selected, isolated local directories."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
import venv


PLUGIN_NAME = "notetofilm-local"
SKILL_NAMES = (
    "notetofilm-workflow", "notetofilm-prepare", "notetofilm-direct",
    "notetofilm-image", "notetofilm-video", "notetofilm-audio",
    "notetofilm-compose",
)
SKILL_MARKER = Path("agents/notetofilm-install.json")
RUNTIME_MARKER = Path("installation.json")
SOURCE_ROOT = Path(__file__).resolve().parent.parent


class InstallError(Exception):
    pass


def json_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def absolute_path(value: str) -> Path:
    # Preserve the final path component so a symlink is not mistaken for an owned directory.
    path = Path(value).expanduser().absolute()
    return path.parent.resolve() / path.name


def owned_target(path: Path, marker: Path, upgrade: bool) -> None:
    if path.is_symlink():
        raise InstallError(f"Refusing to replace a symbolic-link target: {path}")
    if not path.exists():
        return
    if not path.is_dir():
        raise InstallError(f"Install target is not a directory: {path}")
    if not any(path.iterdir()):
        return
    try:
        record = json.loads((path / marker).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InstallError(f"Existing directory is not an installation of this plugin: {path}") from None
    if record.get("plugin") != PLUGIN_NAME:
        raise InstallError(f"Existing directory belongs to another installation: {path}")
    if not upgrade:
        raise InstallError(f"Plugin is already installed at {path}; use --upgrade to replace this installation")


def reject_source_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise InstallError(f"Source component contains a symbolic link: {path.relative_to(SOURCE_ROOT)}")


def ignore_generated(_path: str, names: list[str]) -> set[str]:
    local_names = {"local", "private", "secrets", "credentials"}
    patterns = (".env*", "*.private.*", "*.local.*", "*.key", "*.pem", "*.p12", "*.pfx", "credentials.json", "secrets.json")
    return {name for name in names if name in {"__pycache__", ".pytest_cache", ".DS_Store"}
            or name.endswith((".pyc", ".pyo")) or name.lower() in local_names
            or any(fnmatch.fnmatch(name.lower(), pattern) for pattern in patterns)}


def run_checked(args: list[str], label: str) -> str:
    completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode:
        # Do not echo package-index URLs or environment-derived connection strings.
        raise InstallError(f"{label} failed (exit {completed.returncode})")
    return completed.stdout.strip()


def write_runtime_reference(skill: Path, command: Path, python: Path, locations: dict[str, str], version: str) -> None:
    source = (SOURCE_ROOT / "shared/runtime.md").read_text(encoding="utf-8")
    data = {
        "plugin": PLUGIN_NAME,
        "version": version,
        "ntf_command": str(command),
        "python_module_argv": [str(python), "-I", "-m", "notetofilm_local"],
        "skill_locations": locations,
    }
    text = "# 已安装的本机入口\n\n使用下面的实际位置。调用时把命令与参数作为独立参数传入。\n\n```json\n"
    text += json.dumps(data, ensure_ascii=False, indent=2) + "\n```\n\n"
    text += source.split("\n", 1)[1]
    (skill / "references/runtime.md").write_text(text, encoding="utf-8")


def write_metadata(directory: Path, version: str, extras: dict) -> None:
    directory.mkdir()
    metadata = f"Metadata-Version: 2.1\nName: notetofilm-local\nVersion: {version}\nRequires-Python: >=3.11\n"
    for extra, requirements in extras.items():
        metadata += f'Provides-Extra: {extra}\n'
        metadata += ''.join(f'Requires-Dist: {requirement}; extra == "{extra}"\n' for requirement in requirements)
    (directory/'METADATA').write_text(metadata,encoding='utf-8')
    (directory/'INSTALLER').write_text('notetofilm-local-isolated-installer\n',encoding='utf-8')
    (directory/'entry_points.txt').write_text('[console_scripts]\nntf = notetofilm_local.cli:main\n',encoding='utf-8')
    (directory/'RECORD').write_text('',encoding='utf-8')


def update_runtime_code(runtime_dir: Path) -> dict:
    """Replace owned CLI code and package metadata while preserving its interpreter and dependencies."""
    if runtime_dir == SOURCE_ROOT or runtime_dir in SOURCE_ROOT.parents or SOURCE_ROOT in runtime_dir.parents:
        raise InstallError('Runtime update target must be separate from the plugin source.')
    owned_target(runtime_dir,RUNTIME_MARKER,True)
    marker=runtime_dir/RUNTIME_MARKER
    previous_marker=marker.read_bytes()
    record=json.loads(previous_marker)
    if not record.get('runtime_only') or record.get('skills'):
        raise InstallError('--code-only applies to a runtime-only installation; registered skills require the ordinary upgrade path.')
    python=runtime_dir/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.is_file(): raise InstallError('The existing runtime interpreter is missing.')
    location=json.loads(run_checked([str(python),'-I','-c',
        'import json,sys,sysconfig; print(json.dumps({"purelib":sysconfig.get_path("purelib"),"prefix":sys.prefix}))'],
        'Checking the existing runtime'))
    purelib=Path(location['purelib']).resolve()
    if not purelib.is_relative_to(runtime_dir.resolve()) or Path(location['prefix']).resolve() != (runtime_dir/'venv').resolve():
        raise InstallError('The interpreter does not belong to this runtime directory.')
    installed=purelib/'notetofilm_local'
    if not installed.is_dir() or installed.is_symlink(): raise InstallError('The owned runtime package is missing or is a symlink.')
    manifest=json.loads((SOURCE_ROOT/'plugin.json').read_text())
    project=tomllib.loads((SOURCE_ROOT/'pyproject.toml').read_text())['project']
    if manifest.get('name') != PLUGIN_NAME or project['version'] != manifest['version']:
        raise InstallError('Source package identity or version is inconsistent.')
    version=manifest['version']
    source=SOURCE_ROOT/'runtime/notetofilm_local'
    reject_source_symlinks(source)
    for name in ('__init__.py','__main__.py','cli.py'):
        if not (source/name).is_file(): raise InstallError('Source runtime is incomplete.')
    old_metadata=list(purelib.glob('notetofilm_local-*.dist-info'))
    if any(p.is_symlink() or not p.is_dir() for p in old_metadata):
        raise InstallError('Package metadata must be real directories.')
    new_metadata=purelib/f'notetofilm_local-{version}.dist-info'
    backup=runtime_dir/'code-backups'/('code_'+uuid.uuid4().hex[:12])
    installed_new=[];moved=[]
    with tempfile.TemporaryDirectory(prefix='.ntf-code-update-',dir=purelib) as temporary:
        staging=Path(temporary)
        shutil.copytree(source,staging/'new-package',ignore=ignore_generated)
        write_metadata(staging/'new-metadata',version,project.get('optional-dependencies',{}))
        old=staging/'previous';old.mkdir()
        (old/'installation.json').write_bytes(previous_marker)
        try:
            for target in [installed,*old_metadata]:
                saved=old/target.name;target.rename(saved);moved.append((target,saved))
            (staging/'new-package').rename(installed);installed_new.append(installed)
            (staging/'new-metadata').rename(new_metadata);installed_new.append(new_metadata)
            run_checked([str(python),'-I','-m','notetofilm_local','--help'],'Starting updated CLI')
            for module,enabled in (('edge_tts',record.get('with_audio')),('PIL',record.get('with_render'))):
                if enabled: run_checked([str(python),'-I','-c',f'import {module}'],f'Checking preserved {module}')
            updated={**record,'version':version,'last_update':'code_only'}
            json_write(marker,updated)
            backup.parent.mkdir(exist_ok=True)
            old.rename(backup)
        except BaseException:
            for target in reversed(installed_new):
                if target.exists(): shutil.rmtree(target)
            for target,saved in reversed(moved):
                if saved.exists(): saved.rename(target)
            marker.write_bytes(previous_marker)
            raise
    return {'status':'updated',**updated,'environment_reused':True,'dependencies_changed':False,
            'backup':str(backup),'client_registration':'none'}


def install(skills_dir: Path | None, runtime_dir: Path, *, upgrade: bool, with_audio: bool,
            with_render: bool = False, runtime_only: bool = False, code_only: bool = False) -> dict:
    if code_only:
        if not upgrade or not runtime_only or skills_dir is not None or with_audio or with_render:
            raise InstallError('Use --code-only with --runtime-only --upgrade, without skills-dir or dependency installation flags.')
        return update_runtime_code(runtime_dir)
    if sys.version_info < (3, 11):
        raise InstallError("Python 3.11 or later is required")
    if not runtime_only and skills_dir is None:
        raise InstallError("Select --skills-dir or use --runtime-only for a CLI-only installation")
    if runtime_only and skills_dir is not None:
        raise InstallError("Use --runtime-only without --skills-dir")
    skill_names = () if runtime_only else SKILL_NAMES
    if skills_dir is not None and (skills_dir == runtime_dir or skills_dir in runtime_dir.parents or runtime_dir in skills_dir.parents):
        raise InstallError("Use separate, non-nested skills and runtime directories")
    for target in [p for p in (skills_dir, runtime_dir) if p is not None]:
        if target == SOURCE_ROOT or target in SOURCE_ROOT.parents or SOURCE_ROOT in target.parents:
            raise InstallError("Installation targets must be separate from the plugin source directory")
    if skills_dir is not None and (skills_dir.is_symlink() or (skills_dir.exists() and not skills_dir.is_dir())):
        raise InstallError("The skills directory must be a real directory")
    manifest = json.loads((SOURCE_ROOT / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != PLUGIN_NAME:
        raise InstallError("Unexpected source plugin name")
    version = manifest["version"]
    extras = tomllib.loads((SOURCE_ROOT / 'pyproject.toml').read_text())['project'].get('optional-dependencies', {})
    dependencies = []
    for name, enabled in (('audio', with_audio), ('render', with_render)):
        if enabled:
            if not extras.get(name):
                raise InstallError(f'Missing optional dependency declaration: {name}')
            dependencies.extend(extras[name])
    package_source = SOURCE_ROOT / "runtime/notetofilm_local"
    for required in ("__init__.py", "__main__.py", "cli.py"):
        if not (package_source / required).is_file():
            raise InstallError(f"Runtime source is incomplete: {required}")
    reject_source_symlinks(package_source)
    targets = [(runtime_dir, RUNTIME_MARKER)]
    for name in skill_names:
        source = SOURCE_ROOT / ".agents/skills" / name
        if not (source / "SKILL.md").is_file():
            raise InstallError(f"Missing skill source: {name}")
        reject_source_symlinks(source)
        targets.append((skills_dir / name, SKILL_MARKER))
    for target, marker in targets:
        owned_target(target, marker, upgrade)

    backups: list[tuple[Path, Path]] = []
    created: list[Path] = []
    try:
        if skills_dir is not None:
            skills_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir.parent.mkdir(parents=True, exist_ok=True)
        for target, _marker in targets:
            if target.exists():
                backup = Path(tempfile.mkdtemp(prefix=f".{target.name}-previous-", dir=target.parent))
                target.rename(backup / "contents")
                backups.append((target, backup))

        runtime_dir.mkdir()
        created.append(runtime_dir)
        env_dir = runtime_dir / "venv"
        venv.EnvBuilder(with_pip=bool(dependencies), symlinks=os.name != "nt").create(env_dir)
        python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        purelib = Path(run_checked([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], "Reading the isolated Python environment"))
        if not purelib.is_relative_to(runtime_dir):
            raise InstallError("The selected Python environment did not resolve inside the runtime directory")
        purelib.mkdir(parents=True, exist_ok=True)
        installed_package = purelib / "notetofilm_local"
        shutil.copytree(package_source, installed_package, ignore=ignore_generated)
        info_dir = purelib / f"notetofilm_local-{version}.dist-info"
        write_metadata(info_dir,version,extras)

        bin_dir = runtime_dir / "bin"
        bin_dir.mkdir()
        if os.name == "nt":
            command = bin_dir / "ntf.cmd"
            command.write_text(f'@"{python}" -I -m notetofilm_local %*\r\n', encoding="utf-8")
        else:
            command = bin_dir / "ntf"
            command.write_text(f'#!/bin/sh\nexec {shlex.quote(str(python))} -I -m notetofilm_local "$@"\n', encoding="utf-8")
            command.chmod(0o755)
        if dependencies:
            run_checked([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", *dependencies], "Installing selected runtime dependencies")
        for module, enabled in (('edge_tts', with_audio), ('PIL', with_render)):
            if enabled:
                run_checked([str(python), '-I', '-c', f'import {module}'], f'Checking {module} in the installed runtime')

        locations = {name: str(skills_dir / name) for name in skill_names}
        record = {"plugin": PLUGIN_NAME, "version": version, "runtime_dir": str(runtime_dir), "ntf_command": str(command)}
        for name in skill_names:
            target = skills_dir / name
            created.append(target)
            shutil.copytree(SOURCE_ROOT / ".agents/skills" / name, target, ignore=ignore_generated)
            write_runtime_reference(target, command, python, locations, version)
            json_write(target / SKILL_MARKER, record)
        json_write(runtime_dir / RUNTIME_MARKER, {**record, "skills_dir": str(skills_dir) if skills_dir else None,
                   "skills": list(skill_names), "with_audio": with_audio, "with_render": with_render, "runtime_only": runtime_only})
        # This checks the installed code, not the source checkout.
        run_checked([str(python), "-I", "-m", "notetofilm_local", "--help"], "Starting the installed runtime")
    except Exception:
        for target in reversed(created):
            if target.exists():
                shutil.rmtree(target)
        for target, backup in reversed(backups):
            (backup / "contents").rename(target)
            backup.rmdir()
        raise
    for _target, backup in backups:
        shutil.rmtree(backup)
    return {"status": "installed", **record, "skills_dir": str(skills_dir) if skills_dir else None,
            "skills": list(skill_names), "with_audio": with_audio, "with_render": with_render,
            "client_registration": "none" if runtime_only else "skills_directory_only"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", help="Explicit skill discovery directory; unrelated entries are preserved")
    parser.add_argument("--runtime-dir", required=True, help="Separate directory for this plugin's isolated Python environment")
    parser.add_argument("--with-audio", action="store_true", help="Install Edge TTS in the isolated environment (requires package-source access)")
    parser.add_argument("--with-render", action="store_true", help="Install Pillow for captions and timed text")
    parser.add_argument("--runtime-only", action="store_true", help="Install only the ntf CLI; do not register or copy skills")
    parser.add_argument("--upgrade", action="store_true", help="Replace only directories already owned by this plugin")
    parser.add_argument('--code-only',action='store_true',help='升级已安装的独立 CLI 代码，复用解释器与依赖并保存旧代码备份')
    args = parser.parse_args(argv)
    try:
        result = install(absolute_path(args.skills_dir) if args.skills_dir else None, absolute_path(args.runtime_dir),
                         upgrade=args.upgrade, with_audio=args.with_audio, with_render=args.with_render,
                         runtime_only=args.runtime_only, code_only=args.code_only)
    except (InstallError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "code": "installation_failed", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
