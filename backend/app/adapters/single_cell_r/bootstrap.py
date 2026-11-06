"""Pin native C++ ABI before any numerical extension is imported."""
import ctypes
from pathlib import Path

R_PREFIX=Path('/opt/paperassist-single-cell-r')
_handles=[]


def preload_runtime_libraries():
    if _handles:return True
    if not R_PREFIX.is_dir():return False
    # Conda's R/ICU requires a newer C++ ABI than the base Debian runtime.
    # Exact fixed-prefix paths only; no system library replacement or search.
    for name in ('libgcc_s.so.1','libstdc++.so.6','libcrypto.so.3','libssl.so.3'):
        _handles.append(ctypes.CDLL(str(R_PREFIX/'lib'/name),mode=ctypes.RTLD_GLOBAL))
    return True
