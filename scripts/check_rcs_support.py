import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.formats.rcs_native import native_available
print("Native available:", native_available())

from scan2bim.formats.rcs import converter_status
print("Converter status:", converter_status())
