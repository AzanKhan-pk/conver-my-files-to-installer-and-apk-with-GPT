"""Apply verified changed-file SaveVido updates outside the running app."""
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


def fetch(url: str, destination: Path, progress=None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SaveVido-Updater"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)
            if progress:
                progress(downloaded, total)


def safe_target(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unsafe update path: {name}")
    target = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    if target != resolved_root and resolved_root not in target.parents:
        raise ValueError(f"Update path escapes installation folder: {name}")
    return target


def wait_for_parent(pid: int) -> None:
    if not pid:
        return
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                result = kernel32.WaitForSingleObject(handle, 120000)
                if result == 0x00000102:
                    raise TimeoutError("SaveVido did not close in time. Close it and try again.")
            finally:
                kernel32.CloseHandle(handle)
        else:
            time.sleep(1)
    else:
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-urls", nargs="+", required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--status-file", default="")
    args = parser.parse_args()

    root = Path(args.app_root).resolve()
    exe = root / "SaveVido.exe"
    temp = Path(tempfile.mkdtemp(prefix="savevido-update-"))
    stage_root = temp / "staged"
    backup_root = temp / "backup"
    stage_root.mkdir()
    backup_root.mkdir()
    staged: dict[str, Path] = {}
    deleted: set[str] = set()
    backups: dict[Path, Path | None] = {}
    version = ""

    def write_status(status: str, message: str = "", percent: int = 0) -> None:
        if not args.status_file:
            return
        try:
            status_path = Path(args.status_file)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps({
                "status": status, "message": message, "version": version,
                "percent": max(0, min(100, int(percent)))
            }), encoding="utf-8")
        except Exception:
            pass

    try:
        expected_base = str(args.base_version)
        manifest_chain = []
        for index, manifest_url in enumerate(args.manifest_urls):
            manifest_path = temp / f"manifest-{index}.json"
            write_status("downloading", f"Checking update package {index + 1}/{len(args.manifest_urls)}", int(index * 100 / len(args.manifest_urls)))
            fetch(manifest_url, manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            item_version = str(manifest.get("version") or "")
            if not item_version or str(manifest.get("base_version") or "") != expected_base:
                raise ValueError("Update chain does not match the installed SaveVido version.")
            patch_url = str(manifest.get("patch_url") or "")
            patch_hash = str(manifest.get("patch_sha256") or "").lower()
            if not patch_url.startswith("https://") or len(patch_hash) != 64:
                raise ValueError("This release does not contain a valid incremental update.")
            manifest_chain.append(manifest)
            expected_base = item_version
        if not manifest_chain:
            raise ValueError("No update manifests were provided.")
        version = str(manifest_chain[-1]["version"])

        for patch_index, manifest in enumerate(manifest_chain):
            patch = temp / f"patch-{patch_index}.zip"
            def report_patch_progress(downloaded: int, total: int) -> None:
                if total > 0:
                    fraction = min(1.0, downloaded / total)
                    percent = int(((patch_index + fraction) / len(manifest_chain)) * 78)
                    label = f"Downloading changed files ({downloaded // 1024} KB / {total // 1024} KB)"
                else:
                    percent = int((patch_index / len(manifest_chain)) * 78)
                    label = f"Downloading changed files ({downloaded // 1024} KB)"
                write_status("downloading", label, percent)
            fetch(str(manifest["patch_url"]), patch, report_patch_progress)
            write_status("verifying", f"Verifying update package {patch_index + 1}/{len(manifest_chain)}", 80 + int((patch_index / len(manifest_chain)) * 8))
            digest = hashlib.sha256(patch.read_bytes()).hexdigest()
            if digest != str(manifest["patch_sha256"]).lower():
                raise ValueError(f"Update package {patch_index + 1} failed SHA-256 verification.")

            payload = stage_root / str(patch_index)
            payload.mkdir()
            actual_files = set()
            with zipfile.ZipFile(patch) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    target = safe_target(payload, name)
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise ValueError("Symbolic links are not allowed in update packages.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    actual_files.add(PurePosixPath(name).as_posix())

            expected_files = {PurePosixPath(str(name)).as_posix() for name in (manifest.get("patch_files") or [])}
            if actual_files != expected_files:
                raise ValueError("Update package contents do not match its signed-off file list.")
            for name in actual_files:
                staged[name] = safe_target(payload, name)
                deleted.discard(name)
            for name in manifest.get("delete") or []:
                safe_target(root, str(name))
                deleted.add(PurePosixPath(str(name)).as_posix())
                staged.pop(PurePosixPath(str(name)).as_posix(), None)
            write_status("downloading", f"Downloaded and verified package {patch_index + 1}/{len(manifest_chain)}", int((patch_index + 1) * 80 / len(manifest_chain)))

        write_status("ready", "Update files verified. SaveVido is closing before files are replaced.", 90)
        wait_for_parent(args.wait_pid)

        # Ensure the executable is no longer locked before touching installed files.
        for _ in range(30):
            try:
                with exe.open("ab"):
                    pass
                break
            except OSError:
                time.sleep(1)
        else:
            raise TimeoutError("SaveVido is still running. Close it and try again.")

        all_targets = {safe_target(root, name) for name in staged} | {safe_target(root, name) for name in deleted}
        for target in all_targets:
            if target.exists() and target.is_file():
                backup = backup_root / target.relative_to(root)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None

        try:
            for name, source in staged.items():
                target = safe_target(root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            for name in sorted(deleted):
                target = safe_target(root, name)
                if target.is_file():
                    target.unlink()
            (root / "build_info.json").write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
        except Exception:
            for target, backup in backups.items():
                if backup and backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                elif target.exists() and target.is_file():
                    target.unlink()
            raise

        write_status("installed", "Update completed successfully. Close SaveVido and open it again.", 100)
        return 0

    except Exception as exc:
        write_status("failed", str(exc), 0)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"SaveVido update could not be installed. Previous files were preserved.\\n\\n{exc}", "SaveVido Updater", 0x10)
        except Exception:
            print(f"SaveVido update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
