import ctypes as C
import os
import platform
import sys
from typing import Callable, Optional

def platform_subdir() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "x64"):
        arch = "x86_64"
    elif m in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = m or "unknown"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return os.path.join("windows", arch)
    return os.path.join("linux", arch)

def library_filename() -> str:
    if sys.platform.startswith("win"):
        return "ssconverter.dll"
    if sys.platform == "darwin":
        return "libssconverter.dylib"
    return "libssconverter.so"

def default_library_path(base_dir: str | None = None) -> str:
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "libs")
    name = library_filename()
    layered = os.path.join(base_dir, platform_subdir(), name)
    if os.path.exists(layered):
        return os.path.normpath(layered)
    flat = os.path.join(base_dir, name)
    if os.path.exists(flat):
        return os.path.normpath(flat)
    return os.path.normpath(layered)

# Enums
class ConverterResult:
    Success = 0
    ErrorIo = -1
    ErrorSspj = -2
    ErrorConversion = -3
    ErrorNotYetStarted = -4
    ErrorAborted = -5
    ErrorUnknown = -99

_LOG_CB_TYPE = C.CFUNCTYPE(None, C.c_char_p)
_log_cb_ref = None

def _declare(lib: C.CDLL) -> None:
    P = C.c_void_p
    f = lib
    
    f.ss_converter_version.argtypes = []
    f.ss_converter_version.restype = P
    f.ss_converter_version_free.argtypes = [P]
    f.ss_converter_version_free.restype = None
    
    f.ss_converter_create.argtypes = []
    f.ss_converter_create.restype = P
    f.ss_converter_destroy.argtypes = [P]
    f.ss_converter_destroy.restype = None
    
    f.ss_converter_convert.argtypes = [P, C.c_char_p, C.c_char_p, _LOG_CB_TYPE]
    f.ss_converter_convert.restype = None
    
    f.ss_converter_is_running.argtypes = [P]
    f.ss_converter_is_running.restype = C.c_bool
    
    f.ss_converter_is_finished.argtypes = [P]
    f.ss_converter_is_finished.restype = C.c_bool
    
    f.ss_converter_abort.argtypes = [P]
    f.ss_converter_abort.restype = None
    
    f.ss_converter_get_result.argtypes = [P]
    f.ss_converter_get_result.restype = C.c_int32
    
    f.ss_converter_get_error.argtypes = [P, C.POINTER(C.c_char_p), C.POINTER(C.c_size_t)]
    f.ss_converter_get_error.restype = None

class SsConverter:
    """Python binding for libssconverter."""
    
    def __init__(self, lib_path: Optional[str] = None):
        if lib_path is None:
            lib_path = default_library_path()
        
        self._lib = C.CDLL(lib_path)
        _declare(self._lib)
        self._ctx = self._lib.ss_converter_create()
        
    def __del__(self):
        if hasattr(self, "_ctx") and self._ctx:
            self._lib.ss_converter_destroy(self._ctx)
            self._ctx = None

    def convert(self, sspj_path: str, output_dir: str, on_log: Optional[Callable[[str], None]] = None):
        """Starts the conversion process in a background thread."""
        global _log_cb_ref
        if on_log:
            def cb(msg_ptr):
                if msg_ptr:
                    on_log(msg_ptr.decode('utf-8', errors='replace'))
            _log_cb_ref = _LOG_CB_TYPE(cb)
        else:
            _log_cb_ref = C.cast(None, _LOG_CB_TYPE)
            
        sspj_bytes = sspj_path.encode('utf-8')
        out_bytes = output_dir.encode('utf-8')
        self._lib.ss_converter_convert(self._ctx, sspj_bytes, out_bytes, _log_cb_ref)

    def is_running(self) -> bool:
        """Checks if the converter is currently running."""
        return self._lib.ss_converter_is_running(self._ctx)

    def is_finished(self) -> bool:
        """Checks if the converter has finished."""
        return self._lib.ss_converter_is_finished(self._ctx)

    def abort(self):
        """Aborts the conversion process."""
        self._lib.ss_converter_abort(self._ctx)

    def get_result(self) -> int:
        """Gets the result code (ConverterResult)."""
        return self._lib.ss_converter_get_result(self._ctx)

    def get_error(self) -> str:
        """Gets the error message if the conversion failed."""
        ptr = C.c_char_p()
        length = C.c_size_t()
        self._lib.ss_converter_get_error(self._ctx, C.byref(ptr), C.byref(length))
        if ptr.value:
            return ptr.value.decode('utf-8', errors='replace')
        return ""
