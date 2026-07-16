import hashlib
import inspect
import json


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def source_hash(strategy) -> str:
    try: source = inspect.getsource(strategy)
    except (OSError, TypeError): source = repr(strategy)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def configuration_fingerprint(request, strategy=None) -> str:
    value = request.fingerprint_payload()
    value["strategy_source_hash"] = source_hash(strategy) if strategy else request.strategy_source_hash
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
