"""Apply a verified SaveVido delta package outside the running application."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile
from pathlib import Path, PurePosixPath

def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SaveVido-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)

def safe_target(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or "\\\\" in name or ":" in name:
        raise ValueError("Unsafe update path")
    target = (root / Path(*relative.parts)).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError("Update path escapes installation folder")
    return target

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    root = Path(args.app_root).resolve()
    exe = root / "SaveVido.exe"
    temp = Path(tempfile.mkdtemp(prefix="savevido-update-"))
    backup = temp / "backup"
    backup.mkdir()
    changed = []
    created = []
    try:
        manifest_file = temp / "manifest.json"
        fetch(args.manifest_url, manifest_file)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        version = str(manifest.get("version", ""))
        patch_url = str(manifest.get("patch_url", ""))
        expected = str(manifest.get("patch_sha256", "")).lower()
        if not version or not patch_url.startswith("https://") or len(expected) != 64:
            raise ValueError("The update manifest is incomplete or invalid")
        patch = temp / "update.zip"
        fetch(patch_url, patch)
        hasher = hashlib.sha256()\n        with patch.open("rb") as stream:\n            for chunk in iter(lambda: stream.read(1024 * 1024), b""):\n                hasher.update(chunk)\n        digest = hasher.hexdigest()
        if digest != expected:
            raise ValueError("Update package verification failed")
        # Wait until SaveVido has exited before touching installed files.
        for _ in range(90):
            try:
                import ctypes
                # Windows file lock is the reliable signal that the app is still running.
                with open(exe, "ab"):
                    pass
                break
            except OSError:
                time.sleep(1)
        else:
            raise TimeoutError("SaveVido is still running. Close it and try again.")
        with zipfile.ZipFile(patch) as archive:
            names = archive.namelist()
            for name in names:
                safe_target(root, name)
            for name in names:
                target = safe_target(root, name)
                source = temp / "payload" / Path(*PurePosixPath(name).parts)
                source.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, source.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                if target.exists():
                    saved = backup / Path(*PurePosixPath(name).parts)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                else:
                    created.append(target)
                changed.append((target, source))
        try:
            for target, source in changed:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            for name in manifest.get("delete", []):
                target = safe_target(root, name)
                if target.is_file():
                    saved = backup / Path(*PurePosixPath(name).parts)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                    target.unlink()
        except Exception:
            for target, saved in deleted_backups:\n                if saved.exists():\n                    target.parent.mkdir(parents=True, exist_ok=True)\n                    shutil.copy2(saved, target)\n            for target, _ in reversed(changed):
                saved = backup / target.relative_to(root)
                if saved.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
                elif target in created and target.exists():
                    target.unlink()
            raise
        (root / "build_info.json").write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
        if args.restart and exe.exists():
            subprocess.Popen([str(exe)], cwd=str(root), close_fds=True)
        return 0
    except Exception as exc:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"SaveVido update could not be installed. Your previous files were preserved.\n\n{exc}", "SaveVido Updater", 0x10)
        except Exception:
            print(f"Update failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # Keep the backup until a later successful update; it is small and useful for recovery.
        pass

if __name__ == "__main__":
    raise SystemExit(main())
