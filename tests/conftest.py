"""Test-local temporary paths that avoid locked Windows temp directories."""
from pathlib import Path
import os
import re
import uuid

import pytest


@pytest.fixture
def tmp_path(request):
    """Return a unique path without pytest's numbered-dir cleanup machinery.

    Some Windows/VS Code combinations deny pytest permission while it scans,
    locks, or removes its standard numbered temporary directories. These tests
    only require an empty writable directory, so a UUID directory is enough.
    It is intentionally left for normal workspace cleanup and is git-ignored.
    """
    project_root = Path(__file__).resolve().parents[1]
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", request.node.name)[:60]
    path = project_root / ".test-artifacts" / f"{safe_name}-{os.getpid()}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
