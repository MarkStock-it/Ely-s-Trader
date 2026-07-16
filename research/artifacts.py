import json
import os
from pathlib import Path
import tempfile


class ArtifactStore:
    def __init__(self, root="data/research"):
        self.root = Path(root)
        for name in ("raw", "validated", "rejected"): (self.root / name).mkdir(parents=True, exist_ok=True)

    def immutable(self, section, name, value):
        path = self.root / section / f"{name}.json"
        if path.exists(): raise FileExistsError(f"artifact already exists: {path}")
        self._atomic(path, value); return path

    def current(self, value): self._atomic(self.root / "current_approval.json", value)
    def status(self, value): self._atomic(self.root / "status.json", value)
    def read_current(self): return json.loads((self.root / "current_approval.json").read_text(encoding="utf-8"))

    def _atomic(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
