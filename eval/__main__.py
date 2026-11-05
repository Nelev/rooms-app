"""`python -m eval run ...`: the eval runner (runner.py, which turns tracing and object storage off on import)."""

import sys

from runner import main

sys.exit(main())
