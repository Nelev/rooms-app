"""`python -m eval run ...`: the eval runner (runner.py). Tracing is off before langchain is imported, so eval runs stay out of
LangSmith; nothing else leaves the process but the model calls (no object storage: the photos are read from the repo)."""

import os
import sys

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ.pop("STORAGE_ENDPOINT_URL", None)

from runner import main  # noqa: E402

sys.exit(main())
