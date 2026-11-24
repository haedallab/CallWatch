import os
import tempfile

# The fictional demo companies are test fixtures only; production runs with ALLOW_DEMO unset.
os.environ.setdefault("ALLOW_DEMO", "1")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("WARM_FEATURED", "0")
