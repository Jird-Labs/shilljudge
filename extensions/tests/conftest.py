import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_EXTENSIONS_DIR = _TESTS_DIR.parent
_REPO_ROOT = _EXTENSIONS_DIR.parent

# shilljudge_core lives in core/src
sys.path.insert(0, str(_REPO_ROOT / "core" / "src"))
# loader.py lives at the extensions/ root
sys.path.insert(0, str(_EXTENSIONS_DIR))
