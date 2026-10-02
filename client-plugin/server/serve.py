"""Source-plugin launcher. Requires an installed Python 3.11+ interpreter."""
from pathlib import Path
import sys
base = Path(__file__).resolve().parents[1]
source = base / "server" / "src"
if not (source / "gather" / "client_mcp.py").is_file():
    sys.stderr.write("gather: the server code is missing from the plugin folder. Reinstall the plugin.\n")
    raise SystemExit(1)
sys.path.insert(0, str(source))
from gather.client_mcp import main
if __name__ == "__main__":
    raise SystemExit(main())
