"""`python -m eval run ...`: the eval runner (runner.py, which turns tracing and object storage off on import); `python -m eval ablate ...`:
several variants in one report with charts (ablation.py)."""

import sys

import ablation
from runner import main

sys.exit(ablation.main(sys.argv[1:]) if sys.argv[1:2] == ["ablate"] else main())
