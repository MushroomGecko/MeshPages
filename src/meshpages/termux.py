import sys

_real_platform = sys.platform
if _real_platform == "android":
    print("Android detected. Running in Termux compatibility mode.")
    sys.platform = "linux"
    import serial.tools.list_ports_posix
    sys.platform = _real_platform