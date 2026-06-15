"""Tiny YAML config loader shared by all DSS services.

Pattern: each service drops `<service-name>.yaml` into
`infra/config/services/`, the compose file bind-mounts that directory at
`/app/config/`, and the service calls `load_service_config(...)` at
startup to read its tunables.

Why a new file instead of extending `libs/common/config.py`:
  `config.py` is for *service discovery* (where do I find the crawler?).
  This file is for *per-service tunables* (what quality threshold do I
  enforce on ingest?). Same project, different concerns — easier to
  reason about with separate modules.

Behavior:
  - Missing file → returns the `defaults` dict unchanged. Logs once at
    INFO so operators see "no config, using built-in defaults".
  - Malformed YAML → logs ERROR + returns defaults. Don't crash a
    service over a typo.
  - User-supplied keys deep-merge with defaults. Unknown keys are kept
    so callers can ship new knobs without bumping this loader.
  - Lists are replaced wholesale (avoids the surprise of
    `excludes: [a,b,c]` silently appending to the default list).
  - Path override via env: `<SVC>_CONFIG_PATH` (e.g.
    `KNOWLEDGE_WAREHOUSE_CONFIG_PATH=/etc/dss/foo.yaml`) wins over the
    default `/app/config/<service-name>.yaml`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

_log = logging.getLogger("dss.config")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_service_config(
    service_name: str,
    defaults: Dict[str, Any] | None = None,
    config_dir: str | os.PathLike = "/app/config",
) -> Dict[str, Any]:
    """Load `<service_name>.yaml` from the mounted config dir.

    Returns a fresh dict — safe to mutate without affecting `defaults`.
    """
    defaults = dict(defaults or {})

    env_var = f"{service_name.upper().replace('-', '_')}_CONFIG_PATH"
    override_path = os.environ.get(env_var)
    path = Path(override_path) if override_path else Path(config_dir) / f"{service_name}.yaml"

    if not path.exists():
        _log.info("config_missing service=%s path=%s — using built-in defaults",
                  service_name, path)
        return defaults

    if yaml is None:
        _log.error("config_yaml_missing service=%s — pyyaml not installed, "
                   "using defaults", service_name)
        return defaults

    try:
        with path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except Exception as e:
        _log.error("config_parse_failed service=%s path=%s err=%s — using defaults",
                   service_name, path, e)
        return defaults

    if not isinstance(loaded, dict):
        _log.error("config_shape_invalid service=%s path=%s type=%s — using defaults",
                   service_name, path, type(loaded).__name__)
        return defaults

    merged = _deep_merge(defaults, loaded)
    _log.info("config_loaded service=%s path=%s keys=%s",
              service_name, path, sorted(merged.keys()))
    return merged
