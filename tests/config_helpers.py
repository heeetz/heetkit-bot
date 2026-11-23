"""Write and read one section of a synthetic ``config.json``."""

import json
from pathlib import Path


def write_section(path, name, payload):
    path = Path(path)
    document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1}
    document[name] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def read_section(path, name):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))[name]
