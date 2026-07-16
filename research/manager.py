from datetime import datetime, timezone
import json
from pathlib import Path

import db
from .artifacts import ArtifactStore
from .hashing import configuration_fingerprint, source_hash
from .runner import VibeRunner, parse_runner_json
from .schemas import ResearchResult
from .validation import validate_result

class ResearchManager:
    def __init__(self, cfg, store=None, runner=None, audit_db=None):
        self.cfg = cfg; self.store = store or ArtifactStore(cfg.get("RESEARCH_DATA_PATH", "data/research"))
        self.runner = runner or VibeRunner(timeout=int(cfg.get("RESEARCH_TIMEOUT_SECONDS", 180)), output_limit=int(cfg.get("RESEARCH_OUTPUT_LIMIT", 1_000_000)))
        self.audit_db = audit_db
    def audit(self, event, detail=""):
        if self.audit_db: db.save_event(self.audit_db, "INFO", f"RESEARCH {event} {detail}".strip())
    def run(self, request, strategy=None):
        fingerprint = configuration_fingerprint(request, strategy); self.audit("REQUESTED", request.request_id)
        self.store.status({"state": "RUNNING", "request_id": request.request_id}); self.audit("STARTED", request.request_id)
        output = self.runner.execute(request)
        bound_request = request.to_dict()
        if strategy: bound_request["strategy_source_hash"] = source_hash(strategy)
        raw = {"request": bound_request, "configuration_fingerprint": fingerprint, "exit_code": output.exit_code,
               "stdout": output.stdout, "stderr": output.stderr, "runner_error": output.error,
               "captured_at": datetime.now(timezone.utc).isoformat()}
        self.store.immutable("raw", request.request_id, raw)
        try:
            result = ResearchResult.parse(parse_runner_json(output))
            approval = validate_result(request, result, fingerprint, self.cfg)
            path = self.store.immutable("validated", approval["approval_id"], approval)
            self.store.current(approval); self.store.status({"state": "VALID", "approval_id": approval["approval_id"], "last_refresh_result": "success"})
            self.audit("APPROVAL_CREATED", approval["approval_id"]); return approval
        except Exception as exc:
            rejection = {"request_id": request.request_id, "error": str(exc), "rejected_at": datetime.now(timezone.utc).isoformat()}
            self.store.immutable("rejected", request.request_id, rejection)
            # Deliberately do not replace current_approval.json.
            state = "ERROR" if output.error or output.exit_code not in (0,) else "REJECTED"
            self.store.status({"state": state, "request_id": request.request_id, "last_refresh_result": str(exc)})
            self.audit("REFRESH_FAILED" if state == "ERROR" else "REJECTED", f"{request.request_id} {exc}"); raise
    def validate_file(self, path, request=None, strategy=None):
        raw = json.loads(Path(path).read_text(encoding="utf-8")); payload = raw.get("stdout", raw)
        if isinstance(payload, str): payload = json.loads(payload)
        if request is None and isinstance(raw.get("request"), dict):
            from .schemas import ResearchRequest
            request = ResearchRequest(**raw["request"])
        if request is None: raise ValueError("artifact does not contain its bound research request")
        result = ResearchResult.parse(payload); fingerprint = configuration_fingerprint(request, strategy)
        return validate_result(request, result, fingerprint, self.cfg)
    def status(self):
        try: status = json.loads((self.store.root / "status.json").read_text(encoding="utf-8"))
        except Exception: status = {"state": "MISSING"}
        try:
            from .schemas import utc
            approval = self.store.read_current(); now = datetime.now(timezone.utc)
            artifact_state = "EXPIRED" if utc(approval["expires_at"]) <= now else ("EXPIRING" if utc(approval["refresh_after"]) <= now else "VALID")
            # A failed refresh preserves and reports an unexpired approval as usable.
            if artifact_state != "EXPIRED" and status.get("state") == "ERROR": status["previous_approval_state"] = artifact_state
            elif status.get("state") not in ("RUNNING", "REJECTED", "ERROR"): status["state"] = artifact_state
        except Exception: pass
        return status
