"""Keep exact replaceable LGPL Python sources outside the frozen archive."""

hiddenimports = ["pystray._win32"]
excludedimports = ["pystray._darwin", "pystray._appindicator", "pystray._gtk", "pystray._xorg"]
module_collection_mode = "py"
