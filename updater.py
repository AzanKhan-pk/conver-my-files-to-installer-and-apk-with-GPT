"""Apply verified changed-file SaveVido updates outside the running app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def replace_with_retry(source: Path, target: Path, timeout: int = 120) -> None:
    """Replace an installed file safely, retrying temporary Windows file locks."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(f".{target.name}.savevido-update.tmp")
    shutil.copy2(source, pending)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(pending, target)
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                pending.unlink(missing_ok=True)
                raise TimeoutError(
                    f"Windows is still using {target.name}. Close SaveVido and retry the update."
                ) from exc
            time.sleep(1)


def delete_with_retry(target: Path, timeout: int = 120) -> None:
    """Delete an obsolete installed file after transient Windows locks clear."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            target.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Windows is still using {target.name}; the update could not remove it."
                ) from exc
            time.sleep(1)


def wait_for_parent(pid: int) -> None:
    if not pid:
        return
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: the parent already exited.
                return
            raise OSError(error, "Could not safely wait for SaveVido to close; update was not applied.")
        try:
            result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            if result != 0:
                raise OSError(ctypes.get_last_error(), "Could not confirm that SaveVido has closed; update was not applied.")
        finally:
            kernel32.CloseHandle(handle)
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

    def write_status(status: str, message: str = "", percent: int = 0) -> bool:
        if not args.status_file:
            return False
        status_path = Path(args.status_file)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "status": status, "message": message, "version": version,
            "percent": max(0, min(100, int(percent)))
        })
        # Publish complete JSON atomically so the UI never reads a half-written file.
        temp_status = status_path.with_name(status_path.name + ".tmp")
        with temp_status.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_status, status_path)
        return True

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
        final_files = {}
        for entry in manifest_chain[-1].get("files") or []:
            name = str(entry.get("path") or "")
            digest = str(entry.get("sha256") or "").lower()
            safe_target(root, name)
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError(f"Release manifest contains an invalid file hash: {name}")
            final_files[name] = digest
        if not final_files or "build_info.json" not in final_files:
            raise ValueError("The latest release manifest is missing its verified file list or build_info.json.")

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

        write_status("ready", "Update files verified. Waiting for you to close SaveVido manually.", 90)
        wait_for_parent(args.wait_pid)

        # The parent process has exited. Do not use an append-open probe on the
        # EXE: Windows security scanners can temporarily deny that probe even
        # after SaveVido has closed. Retry the actual atomic replacements below.

        all_targets = {safe_target(root, name) for name in staged} | {safe_target(root, name) for name in deleted}
        # build_info.json is part of the release payload and must be rolled back too.
        all_targets.add(safe_target(root, "build_info.json"))
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
                replace_with_retry(source, target)
            for name in sorted(deleted):
                target = safe_target(root, name)
                if target.is_file():
                    delete_with_retry(target)
            # Verify every file listed by the final release manifest before reporting success.
            for name, expected_hash in final_files.items():
                target = safe_target(root, name)
                if not target.is_file():
                    raise RuntimeError(f"Update verification failed: {name} is missing.")
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if digest != expected_hash:
                    raise RuntimeError(f"Update verification failed: {name} does not match the release.")
            installed_info = json.loads((root / "build_info.json").read_text(encoding="utf-8-sig"))
            if str(installed_info.get("version") or "") != version:
                raise RuntimeError("Update verification failed: installed version does not match the release.")
        except Exception:
            # Restore the exact pre-update files, including build_info.json.
            rollback_errors = []
            for target, backup in backups.items():
                try:
                    if backup and backup.exists():
                        replace_with_retry(backup, target)
                    elif target.exists() and target.is_file():
                        delete_with_retry(target)
                except Exception as rollback_error:
                    rollback_errors.append(f"{target.name}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError("Update failed and rollback needs attention: " + "; ".join(rollback_errors))
            raise

        if not write_status("installed", "Update completed and all installed files were verified. Open SaveVido again to use the new version.", 100):
            raise RuntimeError("Update was applied, but the success status could not be saved.")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "SaveVido update completed successfully. You can open SaveVido now.", "SaveVido Updater", 0x40)
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
