"""TUI persistent config — load/save ~/.config/deepsearch/tui.toml.

Round-trip-safe for the small set of options the TUI exposes. Plain
stdlib (tomllib on 3.11+, tomli as fallback). Deliberately small —
the TUI doesn't need a full settings framework.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "deepsearch"
CONFIG_PATH = CONFIG_DIR / "tui.toml"


@dataclass
class TUIConfig:
    """TUI configuration. Mirrors the CLI/env-var options."""

    base_url: str = "http://localhost:8083"
    llm_base_url: Optional[str] = None
    default_model: str = "virtual/free-coder"
    default_providers: list[str] = field(
        default_factory=lambda: ["searxng", "wikipedia", "github", "hackernews"]
    )
    history_limit: int = 200
    auto_save_history: bool = True

    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url
        # Infer from base_url (port swap to 8005)
        if self.base_url.rsplit(":", 1)[-1].isdigit():
            return self.base_url.rsplit(":", 1)[0] + ":8005"
        return self.base_url

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "TUIConfig":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
        except Exception:
            # Corrupt config — start fresh but don't blow up.
            return cls()
        # Only accept known fields
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def save(self, path: Path = CONFIG_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        # tomllib requires dumping via tomli-w; stdlib doesn't have a writer.
        # Hand-roll a small, safe encoder for our flat schema.
        body = self._to_toml(payload)
        # Atomic write: tmp + rename
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=".tui.toml.", delete=False
        ) as f:
            tmp = Path(f.name)
            f.write(body)
        try:
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _to_toml(d: dict, indent: int = 0) -> str:
        """Tiny TOML serializer for our flat+list schema (stdlib lacks writer)."""
        lines = []
        pad = "  " * indent
        for k, v in d.items():
            if isinstance(v, dict):
                lines.append(f"{pad}[{k}]")
                lines.append(TUIConfig._to_toml(v, indent + 1))
            elif isinstance(v, list):
                if all(isinstance(x, str) for x in v):
                    inline = ", ".join(f'"{x}"' for x in v)
                    lines.append(f"{pad}{k} = [{inline}]")
                else:
                    lines.append(f"{pad}{k} = {v!r}")
            elif isinstance(v, str):
                # Escape backslashes and quotes
                esc = v.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{pad}{k} = "{esc}"')
            elif isinstance(v, bool):
                lines.append(f"{pad}{k} = {str(v).lower()}")
            elif v is None:
                # TOML has no null — use empty string
                lines.append(f'{pad}{k} = ""')
            else:
                lines.append(f"{pad}{k} = {v}")
        return "\n".join(lines) + "\n"


def config_from_env() -> TUIConfig:
    """Build a TUIConfig from env vars (CLI defaults)."""
    providers_env = os.environ.get("AGGREGATE_PROVIDERS", "")
    providers = (
        [p.strip() for p in providers_env.split(",") if p.strip()]
        if providers_env
        else ["searxng", "wikipedia", "github", "hackernews"]
    )
    return TUIConfig(
        base_url=os.environ.get("DEEPSEARCH_BASE_URL", "http://localhost:8083"),
        llm_base_url=os.environ.get("DEEPSEARCH_LLM_URL") or None,
        default_model=os.environ.get("DEEPSEARCH_MODEL", "virtual/free-coder"),
        default_providers=providers,
    )


def load_or_default() -> TUIConfig:
    """Load from disk, fallback to env-var defaults."""
    cfg = TUIConfig.load()
    # If config file is empty, layer env-var defaults on top
    if not CONFIG_PATH.exists():
        env_cfg = config_from_env()
        # Only adopt env defaults for fields the user hasn't set
        # (in this case, none — so adopt everything)
        return env_cfg
    return cfg
