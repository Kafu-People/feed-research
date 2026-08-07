"""Root conftest: environment only. Unit tests must do no I/O."""

from __future__ import annotations

import os

os.environ.setdefault("TT_AI_FAKE", "true")
os.environ.setdefault("TT_ENV", "local")
os.environ.setdefault("TT_JWT_SECRET", "test-secret")
