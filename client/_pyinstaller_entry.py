"""PyInstaller entry point. Uses absolute imports which PyInstaller resolves natively."""
import sys
from client.main import main

raise SystemExit(main(sys.argv))
