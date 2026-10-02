"""PyInstaller GUI entry point for Windows packaged client."""
import sys

from client.main import main
from client.network import metadata_child_invocation_phase, metadata_child_main

# F3: an owned metadata child re-executes THIS executable; dispatch the
# exact private shape against the RAW OS argv BEFORE wrapping it with
# `--gui`, so the child never opens a GUI, a run or a queue and no
# position-anchored check has to understand the wrapper's rewrite.
if metadata_child_invocation_phase(sys.argv) is not None:
    raise SystemExit(metadata_child_main())

raise SystemExit(main([sys.argv[0], "--gui", *sys.argv[1:]]))