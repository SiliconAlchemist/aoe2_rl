"""Project-relative paths and read-only resolution of pre-move replay references.

Historical metadata is evidence: do not rewrite it just to change a directory,
because capture reports hash those exact bytes.
"""
import os
from pathlib import Path, PureWindowsPath


def project_root():
    override = os.environ.get("AOE2RL_PROJECT_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root/"pyproject.toml").is_file():
            raise ValueError("AOE2RL_PROJECT_ROOT must identify the project containing pyproject.toml")
        return root
    for start in (Path(__file__).resolve().parent, Path.cwd()):
        for candidate in (start, *start.parents):
            if (candidate/"pyproject.toml").is_file() and (candidate/"src"/"aoe2rl").is_dir():
                return candidate
    raise ValueError("Cannot locate the checkout. Set AOE2RL_PROJECT_ROOT to the aoe2_rl folder.")


def project_path(value):
    """Resolve a command's relative path from the checkout root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root()/path


def recorded_path(value):
    """Resolve portable references, including historical absolute data/replays paths.

    Rebase only the dataset subtree and only when its relocated file exists.
    Callers retain their existing hash checks. External source recordings are
    not searched, relocated or substituted by filename.
    """
    path = Path(value).expanduser()
    windows = PureWindowsPath(str(value))
    if not path.is_absolute() and not windows.is_absolute():
        return project_path(path)
    parts = windows.parts if windows.is_absolute() else path.parts
    for index in range(len(parts)-1):
        if tuple(part.lower() for part in parts[index:index+2]) == ("data", "replays"):
            root = project_root()
            candidate = root.joinpath(*parts[index:]).resolve()
            if candidate.is_relative_to(root) and candidate.exists():
                return candidate
    return path


def portable_path(value):
    """Save new in-project references relative to the root, external paths absolute."""
    path = project_path(value).resolve()
    root = project_root()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
