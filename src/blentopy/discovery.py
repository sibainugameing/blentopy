"""Locate and inspect a Blender executable."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class BlenderNotFoundError(RuntimeError):
    pass


def find_blender(explicit: str | None = None) -> str:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("BLENTOPY_BLENDER"):
        candidates.append(os.environ["BLENTOPY_BLENDER"])

    located = shutil.which("blender")
    if located:
        candidates.append(located)

    if os.name == "posix":
        candidates.extend([
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "/opt/homebrew/bin/blender",
            "/usr/local/bin/blender",
            "/usr/bin/blender",
        ])
        app_root = Path("/Applications")
        if app_root.exists():
            candidates.extend(
                str(path / "Contents" / "MacOS" / "Blender")
                for path in sorted(app_root.glob("Blender*.app"))
            )

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved = shutil.which(candidate) if not Path(candidate).exists() else candidate
        if resolved and Path(resolved).is_file() and os.access(resolved, os.X_OK):
            return str(Path(resolved).resolve())

    raise BlenderNotFoundError(
        "Blender executable was not found. Install Blender or pass --blender "
        "with its executable path, or set BLENTOPY_BLENDER."
    )


def blender_version(executable: str) -> str:
    try:
        completed = subprocess.run(
            [executable, "--version"], check=False, capture_output=True,
            text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BlenderNotFoundError(f"Could not run Blender at {executable}: {exc}") from exc

    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        raise BlenderNotFoundError(
            f"Blender returned exit code {completed.returncode}: {output[:500]}"
        )
    first_line = output.splitlines()[0] if output else "Blender (version unknown)"
    match = re.search(r"Blender\s+(\d+(?:\.\d+){1,3})", first_line)
    return match.group(1) if match else first_line
