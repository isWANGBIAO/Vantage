"""Register an optional packaged CJK font with this process's fontconfig only."""
import ctypes
import ctypes.util
from pathlib import Path


def register_bundled_fonts(root):
    fonts = list((Path(root) / 'fonts').glob('*.ttc')) + list((Path(root) / 'fonts').glob('*.otf'))
    if not fonts:
        return False
    library = ctypes.util.find_library('fontconfig')
    if not library:
        return False
    fontconfig = ctypes.CDLL(library)
    fontconfig.FcConfigGetCurrent.restype = ctypes.c_void_p
    fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    fontconfig.FcConfigAppFontAddFile.restype = ctypes.c_int
    config = fontconfig.FcConfigGetCurrent()
    return all(fontconfig.FcConfigAppFontAddFile(config, str(path.resolve()).encode()) for path in fonts)
