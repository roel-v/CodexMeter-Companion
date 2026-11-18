"""Generate firmware release metadata inside PlatformIO's configured build directory."""
Import("env")
from pathlib import Path
import sys

root = Path(env.subst("$PROJECT_DIR")).parent
sys.path.insert(0, str(root / "scripts"))
from release_version import firmware_header

header = firmware_header(root, Path(env.subst("$BUILD_DIR")) / "release_metadata")
env.Append(CPPPATH=[str(header.parent)])
