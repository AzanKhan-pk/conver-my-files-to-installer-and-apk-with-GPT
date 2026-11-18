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
    parser.add_argument("--manifest-urls", nargs="+", required=True)
    parser.add_argument("--base-version", required=True)
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
        manifest_chain = []
        expected_base = str(args.base_version)
        for manifest_index, manifest_url in enumerate(args.manifest_urls):
            manifest_file = temp / f"manifest-{manifest_index}.json"
            write_status("downloading", message=f"Getting update information ({manifest_index + 1}/{len(args.manifest_urls)})", percent=int(manifest_index * 100 / len(args.manifest_urls)))
            fetch(manifest_url, manifest_file)
            item = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
            item_version = str(item.get("version") or "")
            item_base = str(item.get("base_version") or "")
            patch_url = str(item.get("patch_url") or "")
            expected_hash = str(item.get("patch_sha256") or "").lower()
            if not item_version or item_base != expected_base or not patch_url.startswith("https://") or len(expected_hash) != 64:
                raise ValueError("The incremental update chain is incomplete or does not match this SaveVido version")
            manifest_chain.append(item)
            expected_base = item_version

        version = str(manifest_chain[-1]["version"])
        staged_files = {}
        deleted = set()
        for patch_index, item in enumerate(manifest_chain):
            patch_url = str(item["patch_url"])
            expected_hash = str(item["patch_sha256"]).lower()
            patch = temp / f"update-{patch_index}.zip"
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
                    local_percent = int(downloaded * 100 / total) if total else 0
                    overall = int((patch_index + min(local_percent, 99) / 100) * 100 / len(manifest_chain))
                    write_status("downloading", message=f"Downloading update package {patch_index + 1}/{len(manifest_chain)}", version=version, percent=overall)
            write_status("verifying", message=f"Verifying update package {patch_index + 1}/{len(manifest_chain)}", version=version, percent=int((patch_index + 1) * 100 / len(manifest_chain)))
            hasher = hashlib.sha256()
            with patch.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != expected_hash:
                raise ValueError(f"Update package {patch_index + 1} failed SHA-256 verification")

            payload_root = temp / f"payload-{patch_index}"
            with zipfile.ZipFile(patch) as archive:
                names = archive.namelist()
                for name in names:
                    safe_target(root, name)
                for name in names:
                    source = payload_root / Path(*PurePosixPath(name).parts)
                    source.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as src, source.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    staged_files[name] = source
                    deleted.discard(name)
            for name in item.get("delete", []):
                safe_target(root, name)
                staged_files.pop(name, None)
                deleted.add(name)

        changed = [(safe_target(root, name), source) for name, source in staged_files.items()]
        created = []
        deleted_backups = []
        write_status("ready", message="All update files downloaded and verified", version=version, percent=100)

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

            for name in sorted(deleted):
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
