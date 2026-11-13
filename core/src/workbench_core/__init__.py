# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""ECG Source List core.

Plain Python package shared by the desktop sidecar (FastAPI) and the SaaS
(Django/Celery). It must never import a web framework.
"""

from .hello import engine_info, greet
from .model import Equipment, demo_equipment

__version__ = "0.1.0"
__all__ = ["Equipment", "demo_equipment", "engine_info", "greet", "__version__"]
