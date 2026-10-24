"""TraceByte Forensic Workbench entry point.

Run from the project root with ``python app.py``. The local web interface is
served by the standard-library HTTP adapter in :mod:`server` and uses the
existing forensic engine in :mod:`src`.
"""

from __future__ import annotations

from server import main


if __name__ == "__main__":
    main()
