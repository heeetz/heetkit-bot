"""Copy installed license evidence to the explicit staging directory."""

import importlib.metadata
from pathlib import Path
import shutil
import sys

stage = Path(sys.argv[1])
for distribution in importlib.metadata.distributions():
    name = distribution.metadata["Name"]
    for entry in distribution.files or ():
        text = entry.as_posix()
        if ".dist-info/licenses/" in text or (
            ".dist-info/" in text and entry.name.lower().startswith(("license", "copying", "notice", "authors"))
        ):
            target = stage / "licenses/installed" / name / Path(text.split(".dist-info/", 1)[1])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(distribution.locate_file(entry), target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if not python_license.is_file():
    raise SystemExit("Python's license collection is missing")
target = stage / "licenses/Python-LICENSE.txt"
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(python_license, target)
