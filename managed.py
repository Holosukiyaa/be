from __future__ import annotations

from pathlib import Path


class ChainBroken(Exception):
    pass


def be_home() -> Path:
    return Path.home() / ".be"


def cases_dir() -> Path:
    path = be_home() / "cases"
    path.mkdir(parents=True, exist_ok=True)
    return path
