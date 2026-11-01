"""Compatibility entrypoint for `uvicorn main:app`.

The application implementation lives in `src/clinical_trial_matcher/main.py`.
This shim keeps existing run commands and deployment scripts working while the
project uses a proper src layout.
"""

from clinical_trial_matcher.main import app

__all__ = ["app"]
