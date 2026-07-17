"""
System Manager
Requires administrator privileges for full hardware access.
"""

import ctypes
import ctypes.wintypes
import winreg
import subprocess
import threading
import json
import os
import sys
import tempfile
import urllib.request
import shutil

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QDialog, QLineEdit, QSystemTrayIcon, QMenu, QMessageBox, QInputDialog,
    QGraphicsDropShadowEffect, QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QRect
from PyQt6.QtGui import (
    QIcon, QColor, QPixmap, QPainter, QBrush, QFont, QPen,
)

# ── Windows API constants ──────────────────────────────────────────────────────
MONITORINFOF_PRIMARY        = 0x00000001
WM_SYSCOMMAND               = 0x0112
SC_MONITORPOWER             = 0xF170
HWND_BROADCAST              = 0xFFFF
ENUM_CURRENT_SETTINGS       = 0xFFFFFFFF

DM_POSITION                 = 0x00000020
DM_PELSWIDTH                = 0x00080000
DM_PELSHEIGHT               = 0x00100000
DM_DISPLAYFREQUENCY         = 0x00400000
CDS_UPDATEREGISTRY          = 0x00000001
CDS_NORESET                 = 0x10000000
CDS_SET_PRIMARY             = 0x00000010
DISP_CHANGE_SUCCESSFUL      = 0

DISPLAY_DEVICE_ACTIVE       = 0x00000001
CREATE_NO_WINDOW            = 0x08000000

QDC_ONLY_ACTIVE_PATHS       = 0x00000002
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9

# ── Structures ─────────────────────────────────────────────────────────────────
class RECT(ctypes.Structure):
    _fields_ = [
        ("left",   ctypes.c_long),
        ("top",    ctypes.c_long),
        ("right",  ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork",    RECT),
        ("dwFlags",   ctypes.c_ulong),
        ("szDevice",  ctypes.c_wchar * 32),
    ]

class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb",           ctypes.c_ulong),
        ("DeviceName",   ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags",   ctypes.c_ulong),
        ("DeviceID",     ctypes.c_wchar * 128),
        ("DeviceKey",    ctypes.c_wchar * 128),
    ]

class DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName",         ctypes.c_wchar * 32),
        ("dmSpecVersion",        ctypes.c_ushort),
        ("dmDriverVersion",      ctypes.c_ushort),
        ("dmSize",               ctypes.c_ushort),
        ("dmDriverExtra",        ctypes.c_ushort),
        ("dmFields",             ctypes.c_ulong),
        ("dmPositionX",          ctypes.c_long),
        ("dmPositionY",          ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor",              ctypes.c_short),
        ("dmDuplex",             ctypes.c_short),
        ("dmYResolution",        ctypes.c_short),
        ("dmTTOption",           ctypes.c_short),
        ("dmCollate",            ctypes.c_short),
        ("dmFormName",           ctypes.c_wchar * 32),
        ("dmLogPixels",          ctypes.c_ushort),
        ("dmBitsPerPel",         ctypes.c_ulong),
        ("dmPelsWidth",          ctypes.c_ulong),
        ("dmPelsHeight",         ctypes.c_ulong),
        ("dmDisplayFlags",       ctypes.c_ulong),
        ("dmDisplayFrequency",   ctypes.c_ulong),
    ]

# ── System RAM via Windows API ────────────────────────────────────────────────
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength",                ctypes.c_ulong),
        ("dwMemoryLoad",            ctypes.c_ulong),
        ("ullTotalPhys",            ctypes.c_ulonglong),
        ("ullAvailPhys",            ctypes.c_ulonglong),
        ("ullTotalPageFile",        ctypes.c_ulonglong),
        ("ullAvailPageFile",        ctypes.c_ulonglong),
        ("ullTotalVirtual",         ctypes.c_ulonglong),
        ("ullAvailVirtual",         ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual",ctypes.c_ulonglong),
    ]

class XINPUT_BATTERY_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BatteryType",  ctypes.c_ubyte),
        ("BatteryLevel", ctypes.c_ubyte),
    ]

def get_ram_usage():
    """Returns (used_gb, total_gb) for system RAM."""
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    total = mem.ullTotalPhys / (1024 ** 3)
    used  = (mem.ullTotalPhys - mem.ullAvailPhys) / (1024 ** 3)
    return round(used, 1), round(total)


def get_xbox_battery():
    """Return battery level string for first connected wireless Xbox controller, or None."""
    BATTERY_DEVTYPE_GAMEPAD   = 0x00
    BATTERY_TYPE_DISCONNECTED = 0x00
    BATTERY_TYPE_WIRED        = 0x01
    _LEVELS = ("0%", "33%", "67%", "100%")
    try:
        try:
            xinput = ctypes.WinDLL("XInput1_4.dll")
        except OSError:
            xinput = ctypes.WinDLL("xinput1_3.dll")
        fn = xinput.XInputGetBatteryInformation
        fn.restype  = ctypes.c_ulong
        fn.argtypes = [ctypes.c_ulong, ctypes.c_ubyte,
                       ctypes.POINTER(XINPUT_BATTERY_INFORMATION)]
        for i in range(4):
            info = XINPUT_BATTERY_INFORMATION()
            if fn(i, BATTERY_DEVTYPE_GAMEPAD, ctypes.byref(info)) != 0:
                continue
            if info.BatteryType == BATTERY_TYPE_DISCONNECTED:
                continue
            if info.BatteryType == BATTERY_TYPE_WIRED:
                return "USB"
            return _LEVELS[min(info.BatteryLevel, 3)]
    except Exception:
        pass
    return None


# ── Temperature reading via bundled TempReader.exe (LHM / C#) ─────────────────

def _tempreader_path():
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "tempreader", "TempReader.exe")


def _round(v, digits=1):
    return round(float(v), digits) if v is not None else None


def get_temperatures():
    """
    Returns ((cpu_temp, cpu_load, cpu_power, gpu_temp, gpu_load, gpu_power,
              gpu_mem_used_mb, gpu_mem_total_mb), fans_list, sensors).
    fans_list: [{"name": str, "rpm": int}, ...].
    sensors: granular per-component readouts for the Sensors tab. Any field
    can be None/missing if that sensor isn't exposed on this board/GPU.
    Calls bundled TempReader.exe.
    """
    try:
        exe = _tempreader_path()
        result = subprocess.run(
            [exe], capture_output=True, text=True,
            timeout=10, creationflags=CREATE_NO_WINDOW
        )
        data          = json.loads(result.stdout.strip())
        cpu           = data.get("cpu")
        cpu_load      = data.get("cpu_load")
        cpu_power     = data.get("cpu_power")
        gpu           = data.get("gpu")
        gpu_load      = data.get("gpu_load")
        gpu_power     = data.get("gpu_power")
        gpu_mem_used  = data.get("gpu_mem_used")
        gpu_mem_total = data.get("gpu_mem_total")
        fans          = [{"name": f["name"], "rpm": int(f["rpm"])}
                         for f in data.get("fans", []) if f.get("rpm", 0) > 0]
        # DEBUG: write hardware list to temp file for diagnosis
        try:
            import tempfile, pathlib
            pathlib.Path(tempfile.gettempdir(), "mm_debug_hw.txt").write_text(
                "\n".join(data.get("debug_hw", [])), encoding="utf-8"
            )
        except Exception:
            pass
        temps = (
            round(float(cpu),           1) if cpu           is not None else None,
            round(float(cpu_load),      1) if cpu_load      is not None else None,
            round(float(cpu_power),     1) if cpu_power     is not None else None,
            round(float(gpu),           1) if gpu           is not None else None,
            round(float(gpu_load),      1) if gpu_load      is not None else None,
            round(float(gpu_power),     1) if gpu_power     is not None else None,
            round(float(gpu_mem_used),  0) if gpu_mem_used  is not None else None,
            round(float(gpu_mem_total), 0) if gpu_mem_total is not None else None,
        )
        sensors = {
            "cpu_voltage": _round(data.get("cpu_voltage"), 3),
            "cpu_cores": [
                {
                    "index": c.get("index"),
                    "clock": _round(c.get("clock"), 0),
                    "load":  _round(c.get("load"), 0),
                }
                for c in data.get("cpu_cores", [])
            ],
            "gpu_hotspot":      _round(data.get("gpu_hotspot")),
            "gpu_mem_junction": _round(data.get("gpu_mem_junction")),
            "gpu_core_clock":   _round(data.get("gpu_core_clock"), 0),
            "gpu_mem_clock":    _round(data.get("gpu_mem_clock"), 0),
            "gpu_fan_pct":      _round(data.get("gpu_fan_pct"), 0),
            "gpu_pcie_load":    _round(data.get("gpu_pcie_load"), 0),
            "mb_chipset_temp":  _round(data.get("mb_chipset_temp")),
            "mb_vrm_temp":      _round(data.get("mb_vrm_temp")),
            "mb_voltages": {
                k: _round(v, 2) for k, v in data.get("mb_voltages", {}).items()
            },
        }
        return temps, fans, sensors
    except Exception:
        return (None, None, None, None, None, None, None, None), [], {}

# ── Monitor helpers ─────────────────────────────────────────────────────────────
_MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(RECT),
    ctypes.c_long,
)

def get_active_monitors():
    monitors = []
    counter  = [0]

    def _cb(hMonitor, hdc, lprc, _):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        r = info.rcMonitor

        dm = DEVMODE()
        dm.dmSize = ctypes.sizeof(DEVMODE)
        ctypes.windll.user32.EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))

        counter[0] += 1
        monitors.append({
            "index":   counter[0],
            "device":  info.szDevice,
            "left":    r.left,
            "top":     r.top,
            "width":   dm.dmPelsWidth,
            "height":  dm.dmPelsHeight,
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        })
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
    monitors.sort(key=lambda m: (not m["primary"], m["index"]))
    return monitors


def get_disabled_devices(active_names: set) -> list:
    disabled = []
    dd = DISPLAY_DEVICE()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
    i = 0
    while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
        is_active = bool(dd.StateFlags & DISPLAY_DEVICE_ACTIVE)
        device    = dd.DeviceName
        if not is_active and device not in active_names:
            dm = DEVMODE()
            dm.dmSize = ctypes.sizeof(DEVMODE)
            if ctypes.windll.user32.EnumDisplaySettingsW(device, 0, ctypes.byref(dm)):
                disabled.append({
                    "device":      device,
                    "description": dd.DeviceString,
                })
        i += 1
    return disabled

# ── Display actions ────────────────────────────────────────────────────────────
def turn_off_all():
    ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


def disable_monitor(device: str, primary: bool) -> tuple:
    """Returns (success, error_message)."""
    if primary:
        return False, ("The primary monitor cannot be disabled.\n"
                       "Set another monitor as primary first.")

    dm = DEVMODE()
    dm.dmSize       = ctypes.sizeof(DEVMODE)
    dm.dmFields     = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth  = 0
    dm.dmPelsHeight = 0

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL, ""


def enable_monitor(device: str, active_monitors: list) -> bool:
    best_w, best_h = 1920, 1080
    dm_q = DEVMODE()
    dm_q.dmSize = ctypes.sizeof(DEVMODE)
    i = 0
    while ctypes.windll.user32.EnumDisplaySettingsW(device, i, ctypes.byref(dm_q)):
        if dm_q.dmPelsWidth * dm_q.dmPelsHeight > best_w * best_h:
            best_w = dm_q.dmPelsWidth
            best_h = dm_q.dmPelsHeight
        i += 1

    rightmost = max((m["left"] + m["width"] for m in active_monitors), default=0)

    dm = DEVMODE()
    dm.dmSize       = ctypes.sizeof(DEVMODE)
    dm.dmFields     = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth  = best_w
    dm.dmPelsHeight = best_h
    dm.dmPositionX  = rightmost
    dm.dmPositionY  = 0

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


def make_primary(device: str, monitors: list) -> bool:
    """
    Make the given monitor the primary display.
    Shifts all other monitors so the new primary sits at (0, 0).
    """
    target = next((m for m in monitors if m["device"] == device), None)
    if target is None:
        return False

    offset_x = target["left"]
    offset_y = target["top"]

    for mon in monitors:
        dm = DEVMODE()
        dm.dmSize   = ctypes.sizeof(DEVMODE)
        dm.dmFields = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT

        dm.dmPelsWidth  = mon["width"]
        dm.dmPelsHeight = mon["height"]
        dm.dmPositionX  = mon["left"] - offset_x
        dm.dmPositionY  = mon["top"]  - offset_y

        flags = CDS_UPDATEREGISTRY | CDS_NORESET
        if mon["device"] == device:
            flags |= CDS_SET_PRIMARY

        ctypes.windll.user32.ChangeDisplaySettingsExW(
            mon["device"], ctypes.byref(dm), None, flags, None
        )

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


# ── Refresh rate helpers ───────────────────────────────────────────────────────
def get_available_refresh_rates(device: str) -> list:
    rates = set()
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    i = 0
    while ctypes.windll.user32.EnumDisplaySettingsW(device, i, ctypes.byref(dm)):
        if dm.dmDisplayFrequency > 1:
            rates.add(int(dm.dmDisplayFrequency))
        i += 1
    return sorted(rates)


def get_current_refresh_rate(device: str) -> int:
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    ctypes.windll.user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    return int(dm.dmDisplayFrequency)


def set_refresh_rate(device: str, hz: int) -> bool:
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    ctypes.windll.user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
    dm.dmFields = DM_DISPLAYFREQUENCY
    dm.dmDisplayFrequency = hz
    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None
    )
    return result == DISP_CHANGE_SUCCESSFUL


# ── HDR state structures ───────────────────────────────────────────────────────
class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]

class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint), ("Denominator", ctypes.c_uint)]

class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId",    LUID),
        ("id",           ctypes.c_uint),
        ("modeInfoIdx",  ctypes.c_uint),
        ("statusFlags",  ctypes.c_uint),
    ]

class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId",        LUID),
        ("id",               ctypes.c_uint),
        ("modeInfoIdx",      ctypes.c_uint),
        ("outputTechnology", ctypes.c_int),
        ("rotation",         ctypes.c_int),
        ("scaling",          ctypes.c_int),
        ("refreshRate",      DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", ctypes.c_int),
        ("targetAvailable",  ctypes.c_bool),
        ("statusFlags",      ctypes.c_uint),
    ]

class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags",      ctypes.c_uint),
    ]

class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # Padded to 80 bytes — we only need this array to satisfy QueryDisplayConfig
    _fields_ = [("_data", ctypes.c_byte * 80)]

class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type",       ctypes.c_int),
        ("size",       ctypes.c_ulong),
        ("adapterId",  LUID),
        ("id",         ctypes.c_uint),
    ]

class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header",             DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value",              ctypes.c_uint),   # bit 1 = advancedColorEnabled
        ("colorEncoding",      ctypes.c_int),
        ("bitsPerColorChannel",ctypes.c_uint),
    ]

def get_hdr_state() -> bool:
    """Returns True if HDR (Advanced Color) is enabled on any active display."""
    try:
        num_paths = ctypes.c_uint(0)
        num_modes = ctypes.c_uint(0)
        if ctypes.windll.user32.GetDisplayConfigBufferSizes(
                QDC_ONLY_ACTIVE_PATHS,
                ctypes.byref(num_paths), ctypes.byref(num_modes)) != 0:
            return False

        paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()
        if ctypes.windll.user32.QueryDisplayConfig(
                QDC_ONLY_ACTIVE_PATHS,
                ctypes.byref(num_paths), paths,
                ctypes.byref(num_modes), modes, None) != 0:
            return False

        for path in paths:
            info = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
            info.header.type      = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
            info.header.size      = ctypes.sizeof(DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO)
            info.header.adapterId = path.targetInfo.adapterId
            info.header.id        = path.targetInfo.id
            if ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) == 0:
                return bool(info.value & 0x2)  # advancedColorEnabled bit
    except Exception:
        pass
    return False


def toggle_hdr():
    """Toggle HDR via Win+Alt+B (Windows 11 built-in shortcut)."""
    KEYEVENTF_KEYUP = 0x0002
    VK_LWIN         = 0x5B
    VK_MENU         = 0x12   # Alt
    VK_B            = 0x42

    kbe = ctypes.windll.user32.keybd_event
    kbe(VK_LWIN, 0, 0, 0)
    kbe(VK_MENU, 0, 0, 0)
    kbe(VK_B,    0, 0, 0)
    kbe(VK_B,    0, KEYEVENTF_KEYUP, 0)
    kbe(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    kbe(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)


def start_screensaver() -> str:
    """Launch screensaver. Returns error string or empty string on success."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            path, _ = winreg.QueryValueEx(key, "SCRNSAVE.EXE")
        if path:
            subprocess.Popen([path, "/s"])
            return ""
        return "No screensaver is configured in Windows Settings."
    except (FileNotFoundError, OSError):
        return "No screensaver is configured in Windows Settings."

# ── Autostart (Start with Windows) ────────────────────────────────────────────
# Uses Task Scheduler with "run with highest privileges" so the app
# starts elevated at login — the HKCU\Run key doesn't support elevation.
_TASK_NAME = "SystemManager"


def _app_launch_cmd() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'{sys.executable} "{os.path.abspath(__file__)}"'


def get_autostart() -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", _TASK_NAME],
        capture_output=True, creationflags=CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def set_autostart(enable: bool) -> tuple:
    """Returns (success, error_message)."""
    if enable:
        result = subprocess.run(
            [
                "schtasks", "/create",
                "/tn", _TASK_NAME,
                "/tr", f"{_app_launch_cmd()} --minimized",
                "/sc", "onlogon",
                "/rl", "highest",
                "/f",
            ],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
        )
    else:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", _TASK_NAME, "/f"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
        )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""

# ── Fan naming persistence ────────────────────────────────────────────────────
_FAN_NAMES_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                               "SystemManager")
_FAN_NAMES_FILE = os.path.join(_FAN_NAMES_DIR, "fan_names.json")

def load_fan_names() -> dict:
    try:
        with open(_FAN_NAMES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_fan_names(names: dict):
    os.makedirs(_FAN_NAMES_DIR, exist_ok=True)
    with open(_FAN_NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2)

# ── RTSS FPS cap ──────────────────────────────────────────────────────────────
def _find_rtss_path() -> str:
    for key_path in [
        r"SOFTWARE\WOW6432Node\Unwinder\RTSS",
        r"SOFTWARE\Unwinder\RTSS",
    ]:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                path, _ = winreg.QueryValueEx(key, "InstallPath")
                if os.path.exists(path):
                    return path
        except OSError:
            pass
    default = r"C:\Program Files (x86)\RivaTuner Statistics Server"
    return default if os.path.exists(default) else ""


def _rtss_global_profile() -> str:
    rtss = _find_rtss_path()
    return os.path.join(rtss, "Profiles", "Global") if rtss else ""


def get_rtss_fps_limit() -> int:
    profile = _rtss_global_profile()
    if not profile or not os.path.exists(profile):
        return 0
    try:
        with open(profile, "r") as f:
            for line in f:
                if line.startswith("FramerateLimit="):
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return 0


def set_rtss_fps_limit(fps: int) -> bool:
    profile = _rtss_global_profile()
    if not profile or not os.path.exists(profile):
        return False
    try:
        with open(profile, "r") as f:
            lines = f.readlines()
        us = round(1_000_000 / fps) if fps > 0 else 0
        new_lines = []
        found_fps, found_us = False, False
        for line in lines:
            if line.startswith("FramerateLimit="):
                new_lines.append(f"FramerateLimit={fps}\n")
                found_fps = True
            elif line.startswith("FramerateLimitUs="):
                new_lines.append(f"FramerateLimitUs={us}\n")
                found_us = True
            else:
                new_lines.append(line)
        if not found_fps:
            new_lines.append(f"FramerateLimit={fps}\n")
        if not found_us:
            new_lines.append(f"FramerateLimitUs={us}\n")
        with open(profile, "w") as f:
            f.writelines(new_lines)
        return True
    except Exception:
        return False


# ── Audio output management (COM / IPolicyConfig) ─────────────────────────────
# No extra dependencies — uses registry for listing and raw COM vtable calls
# for default-device detection (IMMDeviceEnumerator) and switching (IPolicyConfig).
# IPolicyConfig is undocumented but stable since Vista; used by EarTrumpet, SoundSwitch, etc.

try:
    ctypes.windll.ole32.CoInitialize(None)
except Exception:
    pass


class _COGUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]

    @classmethod
    def from_str(cls, s: str) -> "_COGUID":
        s = s.strip("{}")
        p = s.split("-")
        g = cls()
        g.Data1 = int(p[0], 16)
        g.Data2 = int(p[1], 16)
        g.Data3 = int(p[2], 16)
        raw = bytes.fromhex(p[3] + p[4])
        g.Data4 = (ctypes.c_uint8 * 8)(*raw)
        return g


def _com_create(clsid: str, iid: str):
    c = _COGUID.from_str(clsid)
    i = _COGUID.from_str(iid)
    ptr = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(
        ctypes.byref(c), None, 1, ctypes.byref(i), ctypes.byref(ptr)
    )
    return ptr if hr == 0 else None


def _vtcall(ptr, idx, restype, *argtypes):
    """Return a bound callable for COM vtable method at index idx."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn   = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[idx])
    return lambda *args: fn(ptr, *args)


def _com_release(ptr):
    if ptr:
        _vtcall(ptr, 2, ctypes.c_ulong)()


_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator  = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_CLSID_PolicyConfig       = "{294935CE-F637-4E7C-A41B-AB255460B862}"
_IID_IPolicyConfig        = "{568b9108-44bf-40b4-9006-86afe520171f}"


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _COGUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    # vt + 3 reserved WORDs + 8-byte union (pointer on 64-bit)
    _fields_ = [
        ("vt",  ctypes.c_ushort),
        ("r1",  ctypes.c_ushort),
        ("r2",  ctypes.c_ushort),
        ("r3",  ctypes.c_ushort),
        ("val", ctypes.c_void_p),
        ("_hi", ctypes.c_void_p),   # padding to full 16 bytes
    ]


_PKEY_DEVICE_FRIENDLY_NAME = _PROPERTYKEY()
_PKEY_DEVICE_FRIENDLY_NAME.fmtid = _COGUID.from_str("{a45c254e-df1c-4efd-8020-67d146a850e0}")
_PKEY_DEVICE_FRIENDLY_NAME.pid   = 14


def get_audio_outputs() -> list:
    """Return [(friendly_name, device_id), ...] via IMMDeviceEnumerator + IPropertyStore."""
    enum = _com_create(_CLSID_MMDeviceEnumerator, _IID_IMMDeviceEnumerator)
    if not enum:
        return []
    devices = []
    try:
        coll = ctypes.c_void_p()
        # IMMDeviceEnumerator::EnumAudioEndpoints(eRender=0, DEVICE_STATE_ACTIVE=1) @ vtbl[3]
        hr = _vtcall(enum, 3, ctypes.HRESULT,
                     ctypes.c_int, ctypes.c_uint,
                     ctypes.POINTER(ctypes.c_void_p))(0, 1, ctypes.byref(coll))
        if hr != 0 or not coll:
            return []
        try:
            count = ctypes.c_uint(0)
            # IMMDeviceCollection::GetCount @ vtbl[3]
            _vtcall(coll, 3, ctypes.HRESULT,
                    ctypes.POINTER(ctypes.c_uint))(ctypes.byref(count))
            for i in range(count.value):
                dev = ctypes.c_void_p()
                # IMMDeviceCollection::Item @ vtbl[4]
                if _vtcall(coll, 4, ctypes.HRESULT,
                           ctypes.c_uint,
                           ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(dev)) != 0:
                    continue
                try:
                    # IMMDevice::GetId @ vtbl[5]
                    id_ptr = ctypes.c_wchar_p()
                    dev_id = ""
                    if _vtcall(dev, 5, ctypes.HRESULT,
                               ctypes.POINTER(ctypes.c_wchar_p))(ctypes.byref(id_ptr)) == 0:
                        dev_id = id_ptr.value or ""
                        if id_ptr.value:
                            ctypes.windll.ole32.CoTaskMemFree(id_ptr)

                    # IMMDevice::OpenPropertyStore(STGM_READ=0) @ vtbl[4]
                    store = ctypes.c_void_p()
                    name  = ""
                    if _vtcall(dev, 4, ctypes.HRESULT,
                               ctypes.c_uint,
                               ctypes.POINTER(ctypes.c_void_p))(0, ctypes.byref(store)) == 0 and store:
                        try:
                            pv = _PROPVARIANT()
                            # IPropertyStore::GetValue(REFPROPERTYKEY, PROPVARIANT*) @ vtbl[5]
                            if _vtcall(store, 5, ctypes.HRESULT,
                                       ctypes.POINTER(_PROPERTYKEY),
                                       ctypes.POINTER(_PROPVARIANT))(
                                           ctypes.byref(_PKEY_DEVICE_FRIENDLY_NAME),
                                           ctypes.byref(pv)) == 0:
                                if pv.vt == 31 and pv.val:  # VT_LPWSTR
                                    name = ctypes.wstring_at(pv.val)
                            try:
                                ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))
                            except Exception:
                                pass
                        finally:
                            _com_release(store)

                    if dev_id:
                        devices.append((name or dev_id, dev_id))
                finally:
                    _com_release(dev)
        finally:
            _com_release(coll)
    finally:
        _com_release(enum)
    return devices


def get_default_audio_output_id() -> str:
    """Return the device ID of the current default render endpoint."""
    enum = _com_create(_CLSID_MMDeviceEnumerator, _IID_IMMDeviceEnumerator)
    if not enum:
        return ""
    try:
        dev_ptr = ctypes.c_void_p()
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eConsole=0) @ vtbl[4]
        hr = _vtcall(enum, 4, ctypes.HRESULT,
                     ctypes.c_int, ctypes.c_int,
                     ctypes.POINTER(ctypes.c_void_p))(0, 0, ctypes.byref(dev_ptr))
        if hr != 0 or not dev_ptr:
            return ""
        try:
            id_ptr = ctypes.c_wchar_p()
            # IMMDevice::GetId(**ppstrId) @ vtbl[5]
            hr2 = _vtcall(dev_ptr, 5, ctypes.HRESULT,
                          ctypes.POINTER(ctypes.c_wchar_p))(ctypes.byref(id_ptr))
            result = (id_ptr.value or "") if hr2 == 0 else ""
            if id_ptr.value:
                ctypes.windll.ole32.CoTaskMemFree(id_ptr)
            return result
        finally:
            _com_release(dev_ptr)
    finally:
        _com_release(enum)


def _audioswitch_path() -> str:
    """Path to the bundled AudioSwitch.exe."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "audioswitch", "AudioSwitch.exe")
    return os.path.join(os.path.dirname(__file__), "audioswitch_out", "AudioSwitch.exe")


_IID_IUnknown = "{00000000-0000-0000-C000-000000000046}"

def set_default_audio_output(device_id: str) -> tuple:
    """Switch default audio endpoint.
    Tries native Python COM call first (two IID variants); falls back to AudioSwitch.exe.
    Returns (success: bool, error: str)."""
    # vtable layout (IUnknown base + IPolicyConfig methods):
    # IUnknown(0-2) + GetMixFormat(3) GetDeviceFormat(4) ResetDeviceFormat(5)
    # SetDeviceFormat(6) GetProcessingPeriod(7) SetProcessingPeriod(8)
    # GetShareMode(9) SetShareMode(10) GetPropertyValue(11) SetPropertyValue(12)
    # SetDefaultEndpoint(13)
    #
    # On newer Windows, QueryInterface for IPolicyConfig IID fails, so we also
    # try IUnknown (always succeeds) and call vtable[13] directly — the vtable
    # pointer returned by CoCreateInstance IS the full interface vtable.
    for iid in (_IID_IPolicyConfig, _IID_IUnknown):
        try:
            clsid_g = _COGUID.from_str(_CLSID_PolicyConfig)
            iid_g   = _COGUID.from_str(iid)
            pcc     = ctypes.c_void_p()
            hr = ctypes.windll.ole32.CoCreateInstance(
                ctypes.byref(clsid_g), None, 23,   # CLSCTX_ALL
                ctypes.byref(iid_g), ctypes.byref(pcc)
            )
            if hr != 0 or not pcc:
                continue
            try:
                for role in range(3):
                    last_hr = _vtcall(pcc, 13, ctypes.HRESULT,
                                      ctypes.c_wchar_p,
                                      ctypes.c_uint)(device_id, role)
                    # HRESULT: bit 31 set = failure; positive values = success
                    if last_hr < 0:
                        break
                else:
                    return True, ""  # all 3 roles succeeded
            finally:
                _com_release(pcc)
        except Exception:
            pass

    # --- Fallback: AudioSwitch.exe ---
    exe = _audioswitch_path()
    if not os.path.exists(exe):
        return False, "AudioSwitch.exe not found."
    try:
        result = subprocess.run(
            [exe, device_id],
            capture_output=True, timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        def _dec(b):
            for enc in ('utf-8', 'cp1252', 'cp850', 'latin-1'):
                try:
                    return b.decode(enc).strip()
                except Exception:
                    pass
            return repr(b)
        stderr = _dec(result.stderr)
        stdout = _dec(result.stdout)
        if result.returncode == 0:
            return True, ""
        return False, stderr or stdout or f"exit code {result.returncode}"
    except Exception as e:
        return False, str(e)


# ── Auto-update ────────────────────────────────────────────────────────────────
_GITHUB_RELEASE_URL = (
    "https://api.github.com/repos/maximilianermert-stack/system-manager"
    "/releases/tags/latest"
)
_DETACHED_PROCESS = 0x00000008


def download_update(progress_cb=None) -> tuple:
    """Download latest exe from GitHub. Returns (ok, tmp_exe_path_or_error).
    progress_cb(pct: int) is called periodically with 0-100 during download.
    """
    if not getattr(sys, "frozen", False):
        return False, "Auto-update only works when running as .exe"
    try:
        req = urllib.request.Request(
            _GITHUB_RELEASE_URL, headers={"User-Agent": "SystemManager"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        assets = [a for a in data.get("assets", []) if a["name"].endswith(".exe")]
        if not assets:
            return False, "No .exe found in latest release."
        download_url = assets[0]["browser_download_url"]
        tmp_exe = os.path.join(tempfile.gettempdir(), "SystemManager_new.exe")
        dl_req = urllib.request.Request(
            download_url, headers={"User-Agent": "SystemManager-Updater/1.0"}
        )
        with urllib.request.urlopen(dl_req, timeout=120) as dl:
            total = int(dl.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(tmp_exe, "wb") as f:
                while True:
                    chunk = dl.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        if total:
                            progress_cb(f"{min(99, downloaded * 100 // total)}%")
                        else:
                            progress_cb(f"{downloaded / (1024 * 1024):.1f} MB")
        return True, tmp_exe
    except Exception as e:
        return False, str(e)


def apply_update(tmp_exe: str):
    """Swap exe files and relaunch.
    Windows locks a running .exe against overwrite but allows rename,
    so we rename the current exe out of the way, move the new one in,
    then start the new process. A cleanup batch removes the .old file later.
    """
    import shutil
    current_exe = sys.executable
    old_exe     = current_exe + ".old"
    try:
        # Remove leftover .old from a previous update if present
        if os.path.exists(old_exe):
            try:
                os.unlink(old_exe)
            except Exception:
                pass
        # Rename the running exe (rename is allowed while exe is running)
        os.rename(current_exe, old_exe)
        # Place the downloaded exe at the original path
        shutil.move(tmp_exe, current_exe)
        # Start the new version (inherits elevated token, no UAC prompt needed)
        subprocess.Popen([current_exe], creationflags=_DETACHED_PROCESS)
        # Small cleanup batch: delete the .old file after old process exits
        bat = os.path.join(tempfile.gettempdir(), "mm_cleanup.bat")
        with open(bat, "w") as f:
            f.write(
                f"@echo off\n"
                f"ping -n 5 127.0.0.1 >NUL\n"
                f"del \"{old_exe}\" >NUL 2>&1\n"
                f"del \"%~f0\"\n"
            )
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=CREATE_NO_WINDOW | _DETACHED_PROCESS,
        )
    except Exception:
        pass


# ── Theme ──────────────────────────────────────────────────────────────────────
BG      = "#0d0f14"
SURFACE = "#151820"
CARD    = "#1c2030"
BORDER  = "#252a3d"
ACCENT  = "#7c8cf8"
ACCENT_DIM = "#2a2a4a"
TEXT    = "#e2e8f0"
SUBTEXT = "#64748b"
GREEN   = "#4ade80"
RED     = "#f87171"
AMBER   = "#fbbf24"
PEACH   = "#fb923c"
BLUE    = "#60a5fa"

APP_QSS = f"""
* {{
    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
    font-size: 10pt;
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; background: transparent; }}

QFrame#statsChip {{
    background: {CARD};
    border-radius: 8px;
    border: 1px solid {BORDER};
}}
QFrame#monitorCard {{
    background: {CARD};
    border-radius: 10px;
    border: 1px solid {BORDER};
}}
QFrame#fanTile {{
    background: {CARD};
    border-radius: 12px;
    border: 1px solid {BORDER};
}}
QFrame#sensorCell {{
    background: {SURFACE};
    border-radius: 6px;
    border: 1px solid {BORDER};
}}
QPushButton#sensorHead {{
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
    text-align: left;
}}
QPushButton#sensorHead:hover {{ background: {SURFACE}; }}
QWidget#scrollContent {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    width: 5px; background: transparent; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 2px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0; background: none;
}}

QPushButton {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 16px;
}}
QPushButton:hover  {{ background: #252a3d; border-color: #3a4060; }}
QPushButton:pressed {{ background: #13172a; }}

QPushButton#btnGreen  {{ color: {GREEN}; border-color: #1e3d2a; }}
QPushButton#btnGreen:hover  {{ background: #162a1e; border-color: {GREEN}; }}
QPushButton#btnRed    {{ color: {RED};   border-color: #3d1e1e; }}
QPushButton#btnRed:hover    {{ background: #2a1616; border-color: {RED}; }}
QPushButton#btnAmber  {{ color: {AMBER}; border-color: #3d2e1a; }}
QPushButton#btnAmber:hover  {{ background: #2a2010; border-color: {AMBER}; }}
QPushButton#btnBlue   {{ color: {BLUE};  border-color: #1e2a3d; }}
QPushButton#btnBlue:hover   {{ background: #162030; border-color: {BLUE}; }}
QPushButton#btnAccent {{ color: {ACCENT}; border-color: #2a2a4a; }}
QPushButton#btnAccent:hover {{ background: #1e1e3a; border-color: {ACCENT}; }}

QMenu {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    color: {TEXT};
}}
QMenu::item {{ padding: 7px 22px; border-radius: 5px; margin: 1px 3px; }}
QMenu::item:selected {{ background: {BORDER}; }}
QMenu::item:disabled {{ color: {SUBTEXT}; }}
QMenu::separator {{
    height: 1px; background: {BORDER}; margin: 4px 10px;
}}
QMenu::indicator {{ width: 14px; height: 14px; left: 5px; }}

QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}

QMessageBox {{ background: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QInputDialog {{ background: {BG}; }}

QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabWidget {{ background: transparent; }}
QTabBar {{
    background: {BG};
}}
QTabBar::tab {{
    background: {BG};
    color: {SUBTEXT};
    padding: 8px 22px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 10pt;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
    background: {SURFACE};
}}
"""


# ── Tray icon (drawn with QPainter — no Pillow dependency) ─────────────────────
def _make_tray_icon() -> QIcon:
    px = QPixmap(64, 64)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    # Monitor body
    p.setBrush(QBrush(QColor(ACCENT)))
    p.drawRoundedRect(4, 8, 56, 38, 5, 5)
    # Screen
    p.setBrush(QBrush(QColor(BG)))
    p.drawRoundedRect(9, 13, 46, 28, 3, 3)
    # Stand neck
    p.setBrush(QBrush(QColor(ACCENT)))
    p.drawRect(28, 46, 8, 8)
    # Stand base
    p.drawRoundedRect(18, 54, 28, 6, 3, 3)
    p.end()
    return QIcon(px)


# ── Stats chip widget ───────────────────────────────────────────────────────────
class StatsChip(QFrame):
    def __init__(self, label: str, value_color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statsChip")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)

        name_lbl = QLabel(label)
        name_lbl.setStyleSheet(f"color: {SUBTEXT}; font-size: 8pt;")

        self._val = QLabel("—")
        self._val.setStyleSheet(
            f"color: {value_color}; font-size: 11pt; font-weight: 700;"
        )
        lay.addWidget(name_lbl)
        lay.addWidget(self._val)

    def set_value(self, text: str):
        self._val.setText(text)


# ── Monitor card widgets ────────────────────────────────────────────────────────
class MonitorCard(QFrame):
    sig_disable      = pyqtSignal(str, bool)
    sig_make_primary = pyqtSignal(str)

    def __init__(self, mon: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("monitorCard")
        self._build(mon)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

    def _build(self, mon: dict):
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        accent = QFrame()
        accent.setFixedWidth(3)
        accent.setStyleSheet(
            f"background:{ACCENT}; border-radius:0;" if mon["primary"]
            else f"background:{BORDER}; border-radius:0;"
        )
        row.addWidget(accent)

        body = QWidget()
        body.setObjectName("cardContent")
        col = QVBoxLayout(body)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(6)

        # Title row
        top = QHBoxLayout()
        top.setSpacing(8)

        title = QLabel(f"Monitor {mon['index']}")
        title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        top.addWidget(title)

        badge = QLabel("Primary" if mon["primary"] else "Secondary")
        badge.setStyleSheet(
            f"color:{ACCENT}; font-size:9pt;" if mon["primary"]
            else f"color:{SUBTEXT}; font-size:9pt;"
        )
        top.addWidget(badge)
        top.addStretch()

        if not mon["primary"]:
            b = QPushButton("Make Primary")
            b.setObjectName("btnGreen")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda: self.sig_make_primary.emit(mon["device"]))
            top.addWidget(b)

        bd = QPushButton("Disable")
        bd.setObjectName("btnAmber")
        bd.setCursor(Qt.CursorShape.PointingHandCursor)
        bd.clicked.connect(
            lambda: self.sig_disable.emit(mon["device"], mon["primary"])
        )
        top.addWidget(bd)
        col.addLayout(top)

        # Info row
        info = QHBoxLayout()
        res = QLabel(f"{mon['width']} × {mon['height']}")
        res.setStyleSheet("font-size: 10pt; font-weight: 700;")
        info.addWidget(res)
        det = QLabel(f"  ·  ({mon['left']}, {mon['top']})  ·  {mon['device']}")
        det.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        info.addWidget(det)
        info.addStretch()
        col.addLayout(info)

        row.addWidget(body)


class DisabledCard(QFrame):
    sig_enable = pyqtSignal(str, list)

    def __init__(self, dev: dict, active: list, parent=None):
        super().__init__(parent)
        self.setObjectName("monitorCard")
        self._build(dev, active)

    def _build(self, dev: dict, active: list):
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        accent = QFrame()
        accent.setFixedWidth(3)
        accent.setStyleSheet(f"background:{SUBTEXT}; border-radius:0;")
        row.addWidget(accent)

        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel(dev["device"])
        title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        top.addWidget(title)
        badge = QLabel("Disabled")
        badge.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        top.addWidget(badge)
        top.addStretch()

        be = QPushButton("Enable")
        be.setObjectName("btnGreen")
        be.setCursor(Qt.CursorShape.PointingHandCursor)
        be.clicked.connect(lambda: self.sig_enable.emit(dev["device"], active))
        top.addWidget(be)
        col.addLayout(top)

        desc = QLabel(dev["description"])
        desc.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        col.addWidget(desc)

        row.addWidget(body)


# ── Fan RPM ring gauge ────────────────────────────────────────────────────────
class RingGauge(QWidget):
    """Circular fill gauge: arc length = rpm / ref_max, with the value drawn
    in the center. Reference scale is decorative (LHM doesn't report a fan's
    true max RPM), not a measured bound."""

    def __init__(self, ref_max: int = 2000, parent=None):
        super().__init__(parent)
        self._rpm = 0
        self._ref_max = ref_max
        self.setFixedSize(74, 74)

    def set_rpm(self, rpm: int):
        self._rpm = rpm
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen_w = 6
        rect = self.rect().adjusted(
            pen_w // 2 + 1, pen_w // 2 + 1, -(pen_w // 2 + 1), -(pen_w // 2 + 1)
        )
        pct = max(0.0, min(100.0, self._rpm / self._ref_max * 100)) if self._ref_max else 0.0

        pen = QPen(QColor(BORDER))
        pen.setWidth(pen_w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, -360 * 16)

        pen.setColor(QColor(ACCENT))
        p.setPen(pen)
        span = int(360 * 16 * pct / 100)
        p.drawArc(rect, 90 * 16, -span)

        inner = rect.adjusted(pen_w, pen_w, -pen_w, -pen_w)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(CARD)))
        p.drawEllipse(inner)

        p.setPen(QColor(TEXT))
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        num_rect = QRect(inner.left(), inner.top() + 8, inner.width(), 18)
        p.drawText(num_rect, Qt.AlignmentFlag.AlignCenter, f"{self._rpm:,}" if self._rpm else "—")

        p.setPen(QColor(SUBTEXT))
        f2 = QFont()
        f2.setPointSize(6)
        p.setFont(f2)
        unit_rect = QRect(inner.left(), inner.top() + 26, inner.width(), 12)
        p.drawText(unit_rect, Qt.AlignmentFlag.AlignCenter, "RPM")

        p.end()


# ── Fan tile widget ──────────────────────────────────────────────────────────
class FanTile(QFrame):
    renamed = pyqtSignal(str, str)   # sensor_name, new_display_name

    def __init__(self, sensor_name: str, rpm: int, display_name: str, parent=None):
        super().__init__(parent)
        self._sensor_name = sensor_name
        self.setObjectName("fanTile")
        self.setFixedSize(150, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Double-click to rename")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        col = QVBoxLayout(self)
        col.setContentsMargins(10, 16, 10, 12)
        col.setSpacing(8)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._ring = RingGauge(parent=self)
        self._ring.set_rpm(rpm)
        col.addWidget(self._ring, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._name_lbl = QLabel(display_name)
        self._name_lbl.setStyleSheet("font-weight:600; font-size:9pt;")
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self._name_lbl)

    def update_rpm(self, rpm: int):
        self._ring.set_rpm(rpm)

    def mouseDoubleClickEvent(self, event):
        name, ok = QInputDialog.getText(
            self, "Rename Fan", "Fan name:",
            text=self._name_lbl.text()
        )
        if ok and name.strip():
            self._name_lbl.setText(name.strip())
            self.renamed.emit(self._sensor_name, name.strip())


# ── Sensor cell + card widgets ──────────────────────────────────────────────────
class SensorCell(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sensorCell")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(2)

        name_lbl = QLabel(label)
        name_lbl.setStyleSheet(f"color:{SUBTEXT}; font-size:7pt;")
        self._val = QLabel("—")
        self._val.setStyleSheet(f"color:{TEXT}; font-size:9pt; font-weight:600;")
        lay.addWidget(name_lbl)
        lay.addWidget(self._val)

    def set_value(self, text: str):
        self._val.setText(text)


class SensorCard(QFrame):
    """Collapsible per-component card: header shows a mono badge, the
    component name, and a headline summary; the body reveals a grid of
    granular readouts on click. Cells not present at construction time
    (e.g. CPU cores, whose count is unknown until the first data pull)
    are created on demand via set_value()."""

    _COLS = 4

    def __init__(self, mono: str, name: str, static_labels=(), parent=None):
        super().__init__(parent)
        self.setObjectName("monitorCard")
        self._cells: dict = {}
        self._cell_count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle = QPushButton()
        self._toggle.setObjectName("sensorHead")
        self._toggle.setCheckable(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self._on_toggle)

        head = QHBoxLayout(self._toggle)
        head.setContentsMargins(16, 12, 16, 12)
        head.setSpacing(10)

        mono_lbl = QLabel(mono)
        mono_lbl.setStyleSheet(
            f"color:{ACCENT}; background:{ACCENT_DIM}; font-size:7.5pt; "
            f"font-weight:700; padding:4px 6px; border-radius:5px;"
        )
        head.addWidget(mono_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-weight:700; font-size:10.5pt;")
        head.addWidget(name_lbl)
        head.addStretch()

        self._summary_lbl = QLabel("—")
        self._summary_lbl.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        head.addWidget(self._summary_lbl)

        self._chevron = QLabel("▾")
        self._chevron.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        head.addWidget(self._chevron)

        outer.addWidget(self._toggle)

        self._body = QWidget()
        self._body_lay = QGridLayout(self._body)
        self._body_lay.setContentsMargins(16, 4, 16, 14)
        self._body_lay.setSpacing(7)
        self._body.setVisible(False)
        outer.addWidget(self._body)

        for label in static_labels:
            self._add_cell(label)

    def _add_cell(self, label: str) -> SensorCell:
        cell = SensorCell(label)
        self._cells[label] = cell
        row, col = divmod(self._cell_count, self._COLS)
        self._body_lay.addWidget(cell, row, col)
        self._cell_count += 1
        return cell

    def _on_toggle(self, checked: bool):
        self._body.setVisible(checked)
        self._chevron.setText("▴" if checked else "▾")

    def set_summary(self, text: str):
        self._summary_lbl.setText(text)

    def set_value(self, label: str, text: str):
        cell = self._cells.get(label) or self._add_cell(label)
        cell.set_value(text)


# ── Background worker ───────────────────────────────────────────────────────────
class TempWorker(QThread):
    ready = pyqtSignal(tuple, tuple, object, bool, list, dict)

    def run(self):
        temps, fans, sensors = get_temperatures()
        ram         = get_ram_usage()
        battery     = get_xbox_battery()
        hdr         = get_hdr_state()
        self.ready.emit(temps, ram, battery, hdr, fans, sensors)


# ── RTSS FPS cap dialog ─────────────────────────────────────────────────────────
class RTSSCapDialog(QDialog):
    _PRESETS = [0, 30, 60, 120, 144, 165, 240]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RTSS FPS Cap")
        self.setModal(True)
        self.setMinimumWidth(400)

        current = get_rtss_fps_limit()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        title = QLabel("Global FPS Cap")
        title.setStyleSheet("font-size:13pt; font-weight:700;")
        lay.addWidget(title)

        # Preset buttons
        presets_row = QHBoxLayout()
        presets_row.setSpacing(6)
        for fps in self._PRESETS:
            lbl = "Unlimited" if fps == 0 else str(fps)
            btn = QPushButton(lbl)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if fps == current:
                btn.setObjectName("btnGreen")
            btn.clicked.connect(lambda _, v=fps: self._apply(v))
            presets_row.addWidget(btn)
        lay.addLayout(presets_row)

        # Custom row
        custom_row = QHBoxLayout()
        custom_row.setSpacing(8)
        custom_lbl = QLabel("Custom:")
        custom_lbl.setStyleSheet(f"color:{SUBTEXT};")
        custom_row.addWidget(custom_lbl)

        self._entry = QLineEdit()
        self._entry.setPlaceholderText("e.g. 90")
        self._entry.setFixedWidth(80)
        if current not in self._PRESETS and current > 0:
            self._entry.setText(str(current))
        custom_row.addWidget(self._entry)

        set_btn = QPushButton("Set")
        set_btn.setObjectName("btnAccent")
        set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        set_btn.clicked.connect(self._apply_custom)
        custom_row.addWidget(set_btn)
        custom_row.addStretch()
        lay.addLayout(custom_row)

        cur_text = "Unlimited" if current == 0 else f"{current} FPS"
        cur_lbl = QLabel(f"Current: {cur_text}")
        cur_lbl.setStyleSheet(f"color:{SUBTEXT}; font-size:9pt;")
        lay.addWidget(cur_lbl)

    def _apply(self, fps: int):
        if set_rtss_fps_limit(fps):
            self.accept()
        else:
            QMessageBox.critical(self, "System Manager",
                                 "Could not write RTSS profile.")

    def _apply_custom(self):
        try:
            fps = int(self._entry.text())
            if fps < 0:
                raise ValueError
            self._apply(fps)
        except ValueError:
            QMessageBox.critical(self, "System Manager",
                                 "Enter a valid number (0 = unlimited).")


# ── Main window ─────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    _temps_signal = pyqtSignal(tuple, tuple, object, bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Manager")
        self.setMinimumSize(620, 320)
        self.resize(760, 520)

        self._fan_names = load_fan_names()
        self._fan_rows: dict  = {}

        self._worker  = TempWorker()
        self._worker.ready.connect(self._apply_temps)

        self._setup_ui()
        self._setup_tray()
        self._apply_dark_titlebar()

        self.refresh_monitors()
        self._worker.start()

        # Clean up leftover .old exe from a previous update
        if getattr(sys, "frozen", False):
            old_exe = sys.executable + ".old"
            if os.path.exists(old_exe):
                try:
                    os.unlink(old_exe)
                except Exception:
                    pass

        self._temp_timer = QTimer(self)
        self._temp_timer.timeout.connect(self._kick_worker)
        self._temp_timer.start(3000)

        if "--minimized" in sys.argv:
            QTimer.singleShot(0, self.hide)

    # ── Dark title bar (Windows 11) ───────────────────────────────────────────
    def _apply_dark_titlebar(self):
        try:
            hwnd  = int(self.winId())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass

    # ── UI setup ─────────────────────────────────────────────────────────────
    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"background:{BG};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{BG};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 14, 20, 14)
        title = QLabel("System Manager")
        title.setStyleSheet("font-size:15pt; font-weight:700;")
        hl.addWidget(title)
        hl.addStretch()
        root.addWidget(hdr)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"background:{BORDER}; border:none; max-height:1px;")
        root.addWidget(sep1)

        # ── Stats chips ───────────────────────────────────────────────────
        stats_w = QWidget()
        stats_w.setStyleSheet(f"background:{BG};")
        sl = QHBoxLayout(stats_w)
        sl.setContentsMargins(16, 10, 16, 10)
        sl.setSpacing(8)

        self._chip_cpu  = StatsChip("CPU",        PEACH)
        self._chip_gpu  = StatsChip("GPU",        BLUE)
        self._chip_sys  = StatsChip("System",     AMBER)
        self._chip_ctrl = StatsChip("Controller", TEXT)

        for chip in (self._chip_cpu, self._chip_gpu, self._chip_sys, self._chip_ctrl):
            chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            sl.addWidget(chip)

        root.addWidget(stats_w)

        # ── Tabs (Monitors / Fans / Sensors) ────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Monitors tab
        mon_scroll = QScrollArea()
        mon_scroll.setWidgetResizable(True)
        mon_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        mon_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_content = QWidget()
        self._scroll_content.setObjectName("scrollContent")
        self._monitor_layout = QVBoxLayout(self._scroll_content)
        self._monitor_layout.setContentsMargins(16, 12, 16, 12)
        self._monitor_layout.setSpacing(10)
        self._monitor_layout.addStretch()
        mon_scroll.setWidget(self._scroll_content)
        self._tabs.addTab(mon_scroll, "Monitors")

        # Fans tab — 2-column grid of ring-gauge tiles
        fan_scroll = QScrollArea()
        fan_scroll.setWidgetResizable(True)
        fan_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fan_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fans_content = QWidget()
        self._fans_content.setObjectName("scrollContent")
        fans_outer = QVBoxLayout(self._fans_content)
        fans_outer.setContentsMargins(16, 12, 16, 12)
        fans_outer.setSpacing(0)

        self._fans_grid_host = QWidget()
        self._fans_layout = QGridLayout(self._fans_grid_host)
        self._fans_layout.setContentsMargins(0, 0, 0, 0)
        self._fans_layout.setSpacing(10)
        fans_outer.addWidget(self._fans_grid_host, alignment=Qt.AlignmentFlag.AlignTop)
        fans_outer.addStretch()

        fan_scroll.setWidget(self._fans_content)
        self._tabs.addTab(fan_scroll, "Fans")

        # Sensors tab — expandable per-component readouts (HWiNFO-style)
        sensors_scroll = QScrollArea()
        sensors_scroll.setWidgetResizable(True)
        sensors_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sensors_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sensors_content = QWidget()
        sensors_content.setObjectName("scrollContent")
        sensors_layout = QVBoxLayout(sensors_content)
        sensors_layout.setContentsMargins(16, 12, 16, 12)
        sensors_layout.setSpacing(10)

        self._sensor_cpu = SensorCard("CPU", "Processor", ["Package", "Power", "Voltage"])
        self._sensor_gpu = SensorCard(
            "GPU", "Graphics",
            ["Core", "Hotspot", "Mem Junction", "Core Clock", "Mem Clock", "Power", "Fan", "VRAM", "PCIe Load"],
        )
        self._sensor_ram = SensorCard("RAM", "Memory", ["Used", "Available"])
        self._sensor_mb  = SensorCard("MB", "Motherboard", ["Chipset", "VRM"])
        for card in (self._sensor_cpu, self._sensor_gpu, self._sensor_ram, self._sensor_mb):
            sensors_layout.addWidget(card)
        sensors_layout.addStretch()

        sensors_scroll.setWidget(sensors_content)
        self._tabs.addTab(sensors_scroll, "Sensors")

        root.addWidget(self._tabs, 1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background:{BORDER}; border:none; max-height:1px;")
        root.addWidget(sep2)

        # ── Bottom bar ────────────────────────────────────────────────────
        bar = QWidget()
        bar.setStyleSheet(f"background:{BG};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(6)

        def _btn(label, obj_name, slot):
            b = QPushButton(label)
            b.setObjectName(obj_name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        bl.addWidget(_btn("Turn Off All", "btnRed",  self._on_turn_off))
        bl.addWidget(_btn("Screensaver",  "btnBlue", self._on_screensaver))

        self._hdr_btn = QPushButton("HDR")
        self._hdr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hdr_btn.clicked.connect(self._on_toggle_hdr)
        bl.addWidget(self._hdr_btn)

        self._misc_btn = QPushButton("Misc  ▾")
        self._misc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._misc_btn.clicked.connect(self._show_misc_menu)
        bl.addWidget(self._misc_btn)

        bl.addStretch()

        bl.addWidget(_btn("↻  Refresh", "btnGreen", self.refresh_monitors))
        root.addWidget(bar)

        self._build_misc_menu()
        self._refresh_hdr_btn()

    # ── Misc popup menu ───────────────────────────────────────────────────────
    def _build_misc_menu(self):
        m = QMenu(self)

        m.addAction("Extend displays",
            lambda: subprocess.Popen(["DisplaySwitch.exe", "/extend"]))
        m.addAction("Duplicate displays",
            lambda: subprocess.Popen(["DisplaySwitch.exe", "/clone"]))
        m.addAction("PC screen only",
            lambda: subprocess.Popen(["DisplaySwitch.exe", "/internal"]))
        m.addAction("Second screen only",
            lambda: subprocess.Popen(["DisplaySwitch.exe", "/external"]))
        m.addSeparator()

        self._rate_menu  = m.addMenu("Refresh Rate")
        self._rate_menu.aboutToShow.connect(self._rebuild_rate_menu)
        m.addAction("RTSS FPS Cap…", self._on_rtss_cap)

        self._sound_menu = m.addMenu("Sound Output")
        self._sound_menu.aboutToShow.connect(self._rebuild_sound_menu)

        m.addAction("Snipping Tool",
            lambda: subprocess.Popen(["SnippingTool.exe"]))
        m.addSeparator()
        m.addAction("Open Display Settings",
            lambda: subprocess.Popen(["start", "ms-settings:display"], shell=True))
        m.addSeparator()

        self._autostart_action = m.addAction("Start with Windows")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(get_autostart())
        self._autostart_action.triggered.connect(self._on_toggle_autostart)
        m.addSeparator()
        m.addAction("Check for Updates", self._on_check_update)

        self._misc_menu = m

    def _show_misc_menu(self):
        pos = self._misc_btn.mapToGlobal(
            QPoint(0, self._misc_btn.height() + 2)
        )
        self._misc_menu.exec(pos)

    def _rebuild_rate_menu(self):
        self._rate_menu.clear()
        monitors = get_active_monitors()
        if not monitors:
            return
        primary = next((m for m in monitors if m["primary"]), monitors[0])
        device  = primary["device"]
        current = get_current_refresh_rate(device)
        for hz in get_available_refresh_rates(device):
            a = self._rate_menu.addAction(
                f"✓  {hz} Hz" if hz == current else f"    {hz} Hz"
            )
            a.triggered.connect(lambda _, h=hz: self._apply_rate(device, h))
        self._rate_menu.addSeparator()
        self._rate_menu.addAction("Custom…",
            lambda: self._custom_rate(device))

    def _rebuild_sound_menu(self):
        self._sound_menu.clear()
        devices = get_audio_outputs()
        if not devices:
            a = self._sound_menu.addAction("No devices found")
            a.setEnabled(False)
            return
        current = get_default_audio_output_id().lower()
        for name, did in devices:
            label = f"✓  {name}" if did.lower() == current else f"    {name}"
            a = self._sound_menu.addAction(label)
            a.triggered.connect(lambda _, d=did: self._set_audio_output(d))

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon())
        self._tray.setToolTip("System Manager")

        tray_menu = QMenu()
        tray_menu.addAction("Show System Manager", self._show_window)
        tray_menu.addSeparator()
        tray_menu.addAction("Exit", self._quit)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._apply_dark_titlebar()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _quit(self):
        self._tray.hide()
        QApplication.quit()

    # ── Temperature polling ───────────────────────────────────────────────────
    def _kick_worker(self):
        if not self._worker.isRunning():
            self._worker = TempWorker()
            self._worker.ready.connect(self._apply_temps)
            self._worker.start()

    def _apply_temps(self, temps: tuple, ram: tuple, battery, hdr: bool, fans: list, sensors: dict):
        (cpu_temp, cpu_load, cpu_power,
         gpu_temp, gpu_load, gpu_power,
         gpu_mem_used, gpu_mem_total) = temps
        ram_used, ram_total = ram

        cpu_text = f"{cpu_temp:.0f} °C" if cpu_temp is not None else "N/A"
        if cpu_load is not None:
            cpu_text += f"  ·  {cpu_load:.0f}%"
        self._chip_cpu.set_value(cpu_text)

        gpu_text = f"{gpu_temp:.0f} °C" if gpu_temp is not None else "N/A"
        if gpu_load is not None:
            gpu_text += f"  ·  {gpu_load:.0f}%"
        if gpu_mem_used is not None and gpu_mem_total is not None:
            gpu_text += f"  ·  {gpu_mem_used/1024:.1f}/{round(gpu_mem_total/1024)} GB"
        self._chip_gpu.set_value(gpu_text)

        pwr_parts = [p for p in (cpu_power, gpu_power) if p is not None]
        pwr_text  = f"{sum(pwr_parts):.0f} W" if pwr_parts else "N/A"
        pwr_text += f"  ·  {ram_used:.1f}/{ram_total} GB"
        self._chip_sys.set_value(pwr_text)

        self._chip_ctrl.set_value(battery if battery else "—")
        self._apply_hdr_color(hdr)
        self._update_fans(fans)
        self._update_sensors(temps, ram, sensors)

    def _update_fans(self, fans: list):
        current = set(self._fan_rows.keys())
        incoming = {f["name"] for f in fans}
        if current != incoming:
            # Rebuild fan grid
            while self._fans_layout.count():
                item = self._fans_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._fan_rows.clear()
            for idx, f in enumerate(fans):
                sname = f["name"]
                display = self._fan_names.get(sname, sname)
                tile = FanTile(sname, f["rpm"], display, self._fans_grid_host)
                tile.renamed.connect(self._on_fan_renamed)
                row, col = divmod(idx, 2)
                self._fans_layout.addWidget(tile, row, col)
                self._fan_rows[sname] = tile
        else:
            for f in fans:
                self._fan_rows[f["name"]].update_rpm(f["rpm"])

    def _on_fan_renamed(self, sensor_name: str, new_name: str):
        self._fan_names[sensor_name] = new_name
        save_fan_names(self._fan_names)

    def _update_sensors(self, temps: tuple, ram: tuple, sensors: dict):
        (cpu_temp, cpu_load, _cpu_power,
         gpu_temp, gpu_load, gpu_power,
         gpu_mem_used, gpu_mem_total) = temps
        ram_used, ram_total = ram

        cpu_summary = f"{cpu_temp:.0f}°C" if cpu_temp is not None else "N/A"
        if cpu_load is not None:
            cpu_summary += f"  ·  {cpu_load:.0f}%"
        self._sensor_cpu.set_summary(cpu_summary)
        self._sensor_cpu.set_value("Package", f"{cpu_temp:.0f}°C" if cpu_temp is not None else "—")
        self._sensor_cpu.set_value(
            "Voltage",
            f"{sensors.get('cpu_voltage'):.3f} V" if sensors.get("cpu_voltage") is not None else "—",
        )
        for core in sensors.get("cpu_cores", []):
            clock = core.get("clock")
            load  = core.get("load")
            parts = []
            if clock is not None:
                parts.append(f"{clock/1000:.1f}GHz" if clock > 100 else f"{clock:.1f}GHz")
            if load is not None:
                parts.append(f"{load:.0f}%")
            self._sensor_cpu.set_value(f"Core {core.get('index')}", "  ·  ".join(parts) or "—")

        gpu_summary_parts = []
        if gpu_temp is not None:
            gpu_summary_parts.append(f"{gpu_temp:.0f}°C")
        if gpu_load is not None:
            gpu_summary_parts.append(f"{gpu_load:.0f}%")
        if gpu_mem_used is not None and gpu_mem_total is not None:
            gpu_summary_parts.append(f"{gpu_mem_used/1024:.1f}/{round(gpu_mem_total/1024)}GB")
        self._sensor_gpu.set_summary("  ·  ".join(gpu_summary_parts) or "N/A")
        self._sensor_gpu.set_value("Core", f"{gpu_temp:.0f}°C" if gpu_temp is not None else "—")
        self._sensor_gpu.set_value("Hotspot", self._fmt(sensors.get("gpu_hotspot"), "°C"))
        self._sensor_gpu.set_value("Mem Junction", self._fmt(sensors.get("gpu_mem_junction"), "°C"))
        self._sensor_gpu.set_value("Core Clock", self._fmt(sensors.get("gpu_core_clock"), " MHz", 0))
        self._sensor_gpu.set_value("Mem Clock", self._fmt(sensors.get("gpu_mem_clock"), " MHz", 0))
        self._sensor_gpu.set_value("Power", f"{gpu_power:.0f} W" if gpu_power is not None else "—")
        self._sensor_gpu.set_value("Fan", self._fmt(sensors.get("gpu_fan_pct"), "%", 0))
        if gpu_mem_used is not None and gpu_mem_total is not None:
            self._sensor_gpu.set_value("VRAM", f"{gpu_mem_used/1024:.1f}/{round(gpu_mem_total/1024)} GB")
        self._sensor_gpu.set_value("PCIe Load", self._fmt(sensors.get("gpu_pcie_load"), "%", 0))

        self._sensor_ram.set_summary(f"{ram_used:.1f}/{ram_total} GB")
        self._sensor_ram.set_value("Used", f"{ram_used:.1f} GB")
        self._sensor_ram.set_value("Available", f"{ram_total - ram_used:.1f} GB")

        mb_chipset = sensors.get("mb_chipset_temp")
        self._sensor_mb.set_summary(f"{mb_chipset:.0f}°C" if mb_chipset is not None else "—")
        self._sensor_mb.set_value("Chipset", self._fmt(mb_chipset, "°C"))
        self._sensor_mb.set_value("VRM", self._fmt(sensors.get("mb_vrm_temp"), "°C"))
        for rail, value in sensors.get("mb_voltages", {}).items():
            self._sensor_mb.set_value(rail, self._fmt(value, " V", 2))

    @staticmethod
    def _fmt(value, unit: str, digits: int = 1) -> str:
        return f"{value:.{digits}f}{unit}" if value is not None else "—"

    def _refresh_hdr_btn(self):
        hdr = get_hdr_state()
        self._apply_hdr_color(hdr)

    def _apply_hdr_color(self, hdr_on: bool):
        name = "btnGreen" if hdr_on else "btnRed"
        if self._hdr_btn.objectName() != name:
            self._hdr_btn.setObjectName(name)
            self._hdr_btn.style().unpolish(self._hdr_btn)
            self._hdr_btn.style().polish(self._hdr_btn)

    # ── Monitor cards ─────────────────────────────────────────────────────────
    def refresh_monitors(self):
        # Remove all widgets except the bottom stretch
        while self._monitor_layout.count() > 1:
            item = self._monitor_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        active   = get_active_monitors()
        disabled = get_disabled_devices({m["device"] for m in active})

        if not active and not disabled:
            lbl = QLabel("No monitors detected.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color:{SUBTEXT}; padding:32px;")
            self._monitor_layout.insertWidget(0, lbl)
            return

        idx = 0
        for mon in active:
            card = MonitorCard(mon)
            card.sig_disable.connect(self._on_disable)
            card.sig_make_primary.connect(self._on_make_primary)
            self._monitor_layout.insertWidget(idx, card)
            idx += 1

        for dev in disabled:
            card = DisabledCard(dev, active)
            card.sig_enable.connect(self._on_enable)
            self._monitor_layout.insertWidget(idx, card)
            idx += 1

    # ── Actions ───────────────────────────────────────────────────────────────
    def _on_turn_off(self):
        turn_off_all()

    def _on_screensaver(self):
        err = start_screensaver()
        if err:
            QMessageBox.information(self, "System Manager", err)

    def _on_toggle_hdr(self):
        toggle_hdr()
        QTimer.singleShot(600, self._refresh_hdr_btn)

    def _on_disable(self, device: str, primary: bool):
        ok, msg = disable_monitor(device, primary)
        if ok:
            self.refresh_monitors()
        else:
            QMessageBox.warning(self, "System Manager", msg or f"Could not disable {device}.")

    def _on_enable(self, device: str, active_monitors: list):
        if enable_monitor(device, active_monitors):
            self.refresh_monitors()
        else:
            QMessageBox.critical(self, "System Manager",
                                 f"Could not enable {device}.")

    def _on_make_primary(self, device: str):
        monitors = get_active_monitors()
        if make_primary(device, monitors):
            self.refresh_monitors()
        else:
            QMessageBox.critical(self, "System Manager",
                                 f"Could not set {device} as primary.")

    def _apply_rate(self, device: str, hz: int):
        if not set_refresh_rate(device, hz):
            QMessageBox.critical(self, "System Manager",
                                 f"Could not set {hz} Hz on {device}.")

    def _custom_rate(self, device: str):
        hz, ok = QInputDialog.getInt(self, "Refresh Rate",
                                      "Enter refresh rate (Hz):", 60, 1, 500)
        if ok:
            self._apply_rate(device, hz)

    def _on_rtss_cap(self):
        if not _find_rtss_path():
            QMessageBox.critical(self, "System Manager",
                "RTSS not found.\nMake sure RivaTuner Statistics Server is installed.")
            return
        RTSSCapDialog(self).exec()

    def _set_audio_output(self, device_id: str):
        threading.Thread(target=self._do_set_audio,
                         args=(device_id,), daemon=True).start()

    def _do_set_audio(self, device_id: str):
        ok, err = set_default_audio_output(device_id)
        if not ok:
            msg = f"Could not switch audio output.\n\n{err}" if err \
                  else "Could not switch audio output."
            QTimer.singleShot(0, lambda: QMessageBox.critical(
                self, "Audio Switch Failed", msg
            ))

    def _on_toggle_autostart(self, checked: bool):
        ok, err = set_autostart(checked)
        if not ok:
            self._autostart_action.setChecked(not checked)
            QMessageBox.warning(self, "Start with Windows",
                err or "Failed to update scheduled task.")

    def _on_check_update(self):
        self.setWindowTitle("System Manager  —  Downloading update…")
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        def on_progress(text):
            QTimer.singleShot(0, lambda: self.setWindowTitle(
                f"System Manager  —  Downloading update… {text}"
            ))
        ok, result = download_update(progress_cb=on_progress)
        if ok:
            QTimer.singleShot(0, lambda: self._finish_update(result))
        else:
            QTimer.singleShot(0, lambda: (
                self.setWindowTitle("System Manager"),
                QMessageBox.critical(self, "Update Failed",
                                     result or "Could not download update."),
            ))

    def _finish_update(self, tmp_exe: str):
        self.setWindowTitle("System Manager")
        QMessageBox.information(self, "Update",
                                "Update downloaded!\nThe app will now restart.")
        apply_update(tmp_exe)
        self._quit()


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    app.setQuitOnLastWindowClosed(False)

    win = MainWindow()
    if "--minimized" not in sys.argv:
        win.show()

    sys.exit(app.exec())
