"""Tests run in sample mode: generated fixtures in the real source formats, no network."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["FINN_SAMPLE"] = "1"
os.environ["FINN_DATA"] = tempfile.mkdtemp(prefix="finn-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
