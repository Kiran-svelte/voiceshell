import sys

from .cli import main

try:
    sys.exit(main())
except KeyboardInterrupt:          # Ctrl+C while starting up or loading: exit quietly, no traceback
    print("\nStopped.")
    sys.exit(130)
