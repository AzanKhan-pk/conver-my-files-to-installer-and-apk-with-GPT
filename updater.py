"""Apply a verified SaveVido delta package outside the running application."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def fetch(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SaveVido-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def safe_target(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or "\\" in name or ":" in name:
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
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--status-file", default="")
    args = parser.parse_args()

    root = Path(args.app_root).resolve()
    exe = root / "SaveVido.exe"
    temp = Path(tempfile.mkdtemp(prefix="savevido-update-"))
    backup = temp / "backup"
    backup.mkdir()
    changed = []
    created = []
    deleted_backups = []

    def write_status(status: str, message: str = "", version: str = "", percent: int = 0) -> None:
        if not args.status_file:
            return
        try:
            status_path = Path(args.status_file)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({
                "status": status, "message": message, "version": version, "percent": int(percent),
            }), encoding="utf-8")
        except Exception:
            pass

    def wait_for_parent() -> None:
        if not args.wait_pid:
            return
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(0x00100000, False, args.wait_pid)
            if handle:
                try:
                    result = kernel32.WaitForSingleObject(handle, 120000)
                    if result == 0x00000102:
                        raise TimeoutError("SaveVido did not close in time. Please close it and try again.")
                finally:
                    kernel32.CloseHandle(handle)
            else:
                # The parent may already have exited before this helper started.
                time.sleep(1)
        else:
            time.sleep(2)

    try:
        write_status("downloading", message="Getting update information", percent=0)
        manifest_file = temp / "manifest.json"
        fetch(args.manifest_url, manifest_file)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        version = str(manifest.get("version", ""))
        patch_url = str(manifest.get("patch_url", ""))
        expected = str(manifest.get("patch_sha256", "")).lower()
        if not version or not patch_url.startswith("https://") or len(expected) != 64:
            raise ValueError("The update manifest is incomplete or invalid")

        patch = temp / "update.zip"
        request = urllib.request.Request(patch_url, headers={"User-Agent": "SaveVido-Updater"})
        with urllib.request.urlopen(request, timeout=60) as response, patch.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                percent = int(downloaded * 100 / total) if total else 0
                write_status("downloading", message="Downloading update files", version=version, percent=min(percent, 99))
        write_status("verifying", message="Verifying update package", version=version, percent=100)
        hasher = hashlib.sha256()
        with patch.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != expected:
            raise ValueError("Update package verification failed")

        write_status("ready", message="Update downloaded and verified", version=version, percent=100)
        wait_for_parent()

        # Wait for Windows to release the running executable before replacing files.
        for _ in range(90):
            try:
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
                    deleted_backups.append((target, saved))
                    target.unlink()

            (root / "build_info.json").write_text(
                json.dumps({"version": version}, indent=2), encoding="utf-8"
            )
        except Exception:
            for target, saved in deleted_backups:
                if saved.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
            for target, _ in reversed(changed):
                saved = backup / target.relative_to(root)
                if saved.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, target)
                elif target in created and target.exists():
                    target.unlink()
            raise

        write_status("installed", message="Update completed successfully. Restart SaveVido to apply it.", version=version, percent=100)
        if args.restart and exe.exists():
            subprocess.Popen([str(exe)], cwd=str(root), close_fds=True)
        return 0

    except Exception as exc:
        write_status("failed", message=str(exc))
        if args.restart and exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(root), close_fds=True)
            except Exception:
                pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"SaveVido update could not be installed. Your previous files were preserved.\n\n{exc}",
                "SaveVido Updater",
                0x10,
            )
        except Exception:
            print(f"Update failed: {exc}", file=sys.stderr)
        return 1
    finally:
        # Preserve the backup directory for manual recovery if an update needs inspection.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
