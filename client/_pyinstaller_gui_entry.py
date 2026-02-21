"""PyInstaller GUI entry point for Windows packaged client."""
import sys

from client.main import main

raise SystemExit(main([sys.argv[0], "--gui", *sys.argv[1:]]))
