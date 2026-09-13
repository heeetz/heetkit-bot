"""Application configuration and access to the root user configuration."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_ROOT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.py"
_ROOT_CONFIG_SPEC = spec_from_file_location("_twitch_bot_user_config", _ROOT_CONFIG_PATH)
if _ROOT_CONFIG_SPEC is None or _ROOT_CONFIG_SPEC.loader is None:
    raise ImportError(f"Could not load user configuration from {_ROOT_CONFIG_PATH}")

_root_config = module_from_spec(_ROOT_CONFIG_SPEC)
_ROOT_CONFIG_SPEC.loader.exec_module(_root_config)


def __getattr__(name: str):
    try:
        return getattr(_root_config, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_root_config)))
