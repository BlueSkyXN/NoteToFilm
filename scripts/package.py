#!/usr/bin/env python3
"""打包可独立安装的 CLI 与 Skill 源码，输出 ZIP 或 tar.gz。"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import fnmatch
from pathlib import Path
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
ROOT_FILES = {"plugin.json", "README.md", "CHANGELOG.md", ".gitignore", "pyproject.toml", "LICENSE", "LICENSE.md", "THIRD_PARTY_NOTICES.md"}
SKILL_NAMES = tuple(f"notetofilm-{name}" for name in ("workflow", "prepare", "direct", "image", "video", "audio", "compose"))
COMPONENTS = (
    *[f".agents/skills/{name}" for name in SKILL_NAMES],
    "runtime", "shared", "configs", "docs", "tests/cli",
    "scripts/ntf.py", "scripts/install.py", "scripts/package.py",
    "scripts/sync_skill_references.py", "scripts/check_cli.py", "scripts/build_binary.py",
    "examples/create_media_fixture.py", "examples/MEDIA_FIXTURE.md",
)
OMIT_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv", "node_modules", "dist", "build", "work"}
LOCAL_PARTS = {"local", "private", "secrets", "credentials"}
LOCAL_PATTERNS = (".env*", "*.private.*", "*.local.*", "*.key", "*.pem", "*.p12", "*.pfx", "credentials.json", "secrets.json")


def included_files(root: Path) -> list[Path]:
    result = []
    candidates = []
    for name in sorted(ROOT_FILES) + list(COMPONENTS):
        component = root / name
        if component.is_symlink():
            raise ValueError(f"Cannot package a symbolic link: {name}")
        if component.is_file():
            candidates.append(component)
        elif component.is_dir():
            candidates.extend(component.rglob("*"))
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if any(part in OMIT_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if any(part.lower() in LOCAL_PARTS for part in relative.parts) or any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in LOCAL_PATTERNS):
            continue
        if path.name.startswith(".env") or path.name in {".DS_Store", ".ntf.lock", "notetofilm-install.json", "installation.json"} or path.suffix in {".pyc", ".pyo"}:
            continue
        if relative.parts[0] in {"config", "configs"} and path.is_file() and ".example." not in path.name:
            continue
        if path.is_symlink():
            raise ValueError(f"Cannot package a symbolic link: {relative}")
        if path.is_file():
            result.append(path)
    return result


def check_components(root: Path) -> dict:
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("$schema") != SCHEMA or manifest.get("name") != "notetofilm-local":
        raise ValueError("Unexpected plugin manifest")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project["name"] != manifest["name"] or project["version"] != manifest["version"]:
        raise ValueError("Python package and plugin identity or version differ")
    interface = manifest.get("extensions", {}).get("com.openai", {}).get("interface", {})
    if len(interface.get("shortDescription", "")) > 30:
        raise ValueError("Plugin shortDescription exceeds 30 characters")
    for name in SKILL_NAMES:
        skill = root / ".agents/skills" / name
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        if not text.startswith("---\n") or f"name: {name}\n" not in text:
            raise ValueError(f"Invalid skill frontmatter: {skill.name}")
        if "TODO" in text:
            raise ValueError(f"Unfinished skill: {skill.name}")
        if not (skill / "agents/openai.yaml").is_file():
            raise ValueError(f"Missing skill metadata: {skill.name}")
        for name in ("runtime.md", "project-format.md", "commands.md"):
            if not (skill / "references" / name).is_file():
                raise ValueError(f"Missing self-contained reference: {skill.name}/{name}")
        # Source packages must not include generated, machine-specific install locations.
        if '"ntf_command"' in (skill / "references/runtime.md").read_text(encoding="utf-8"):
            raise ValueError(f"Installed runtime locator found in source package: {skill.name}")
    for name in ("__init__.py", "__main__.py", "cli.py"):
        if not (root / "runtime/notetofilm_local" / name).is_file():
            raise ValueError(f"Missing runtime source: {name}")
    return manifest


def build(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root) and not output.is_relative_to(root / "dist"):
        raise ValueError("Write the archive under dist/ or outside the plugin source directory")
    manifest = check_components(root)
    files = included_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = manifest["name"]
    if output.name.endswith(".zip"):
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                info = zipfile.ZipInfo(f"{prefix}/{path.relative_to(root).as_posix()}", (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100644 << 16)
                archive.writestr(info, path.read_bytes())
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError("Archive member failed to read")
            count = len(archive.infolist())
    elif output.name.endswith(".tar.gz"):
        with output.open("wb") as handle, gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in files:
                    data = path.read_bytes()
                    info = tarfile.TarInfo(f"{prefix}/{path.relative_to(root).as_posix()}")
                    info.size, info.mode, info.mtime = len(data), 0o644, 0
                    archive.addfile(info, io.BytesIO(data))
        with tarfile.open(output, "r:gz") as archive:
            count = len(archive.getmembers())
    else:
        raise ValueError("Output must end in .zip or .tar.gz")
    return {"status": "packaged", "plugin": prefix, "version": manifest["version"], "archive": str(output), "files": count, "bytes": output.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = build(ROOT, Path(args.output))
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
