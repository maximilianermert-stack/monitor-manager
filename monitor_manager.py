"""
Monitor Manager
Run on Windows with Python 3.x — no extra dependencies needed.
Requires administrator privileges for full hardware access.
"""

import tkinter as tk
from tkinter import messagebox, simpledialog
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

try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_AVAILABLE = True
except ImportError:
    _TRAY_AVAILABLE = False

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

def get_ram_usage():
    """Returns (used_gb, total_gb) for system RAM."""
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    total = mem.ullTotalPhys / (1024 ** 3)
    used  = (mem.ullTotalPhys - mem.ullAvailPhys) / (1024 ** 3)
    return round(used, 1), round(total)

# ── Temperature reading via bundled TempReader.exe (LHM / C#) ─────────────────

def _tempreader_path():
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "tempreader", "TempReader.exe")


def get_temperatures():
    """
    Returns (cpu_temp, cpu_load, cpu_power, gpu_temp, gpu_load, gpu_power, gpu_mem_used_mb, gpu_mem_total_mb).
    Values are float or None. Calls the bundled TempReader.exe (LibreHardwareMonitor).
    """
    try:
        exe = _tempreader_path()
        result = subprocess.run(
            [exe], capture_output=True, text=True,
            timeout=10, creationflags=CREATE_NO_WINDOW
        )
        data      = json.loads(result.stdout.strip())
        cpu       = data.get("cpu")
        cpu_load      = data.get("cpu_load")
        cpu_power     = data.get("cpu_power")
        gpu           = data.get("gpu")
        gpu_load      = data.get("gpu_load")
        gpu_power     = data.get("gpu_power")
        gpu_mem_used  = data.get("gpu_mem_used")
        gpu_mem_total = data.get("gpu_mem_total")
        return (
            round(float(cpu),           1) if cpu           is not None else None,
            round(float(cpu_load),      1) if cpu_load      is not None else None,
            round(float(cpu_power),     1) if cpu_power     is not None else None,
            round(float(gpu),           1) if gpu           is not None else None,
            round(float(gpu_load),      1) if gpu_load      is not None else None,
            round(float(gpu_power),     1) if gpu_power     is not None else None,
            round(float(gpu_mem_used),  0) if gpu_mem_used  is not None else None,
            round(float(gpu_mem_total), 0) if gpu_mem_total is not None else None,
        )
    except Exception:
        return None, None, None, None, None, None, None, None

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


def disable_monitor(device: str, primary: bool) -> bool:
    if primary:
        messagebox.showwarning(
            "Monitor Manager",
            "The primary monitor cannot be disabled.\n"
            "Set another monitor as primary first."
        )
        return False

    dm = DEVMODE()
    dm.dmSize       = ctypes.sizeof(DEVMODE)
    dm.dmFields     = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth  = 0
    dm.dmPelsHeight = 0

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


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


def start_screensaver():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            path, _ = winreg.QueryValueEx(key, "SCRNSAVE.EXE")
        if path:
            subprocess.Popen([path, "/s"])
        else:
            messagebox.showinfo("Monitor Manager", "No screensaver is configured in Windows Settings.")
    except (FileNotFoundError, OSError):
        messagebox.showinfo("Monitor Manager", "No screensaver is configured in Windows Settings.")

# ── Autostart (Start with Windows) ────────────────────────────────────────────
# Uses Task Scheduler with "run with highest privileges" so the app
# starts elevated at login — the HKCU\Run key doesn't support elevation.
_TASK_NAME = "MonitorManager"


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


def set_autostart(enable: bool):
    if enable:
        subprocess.run(
            [
                "schtasks", "/create",
                "/tn", _TASK_NAME,
                "/tr", f"{_app_launch_cmd()} --minimized",
                "/sc", "onlogon",
                "/rl", "highest",
                "/f",
            ],
            capture_output=True, creationflags=CREATE_NO_WINDOW,
        )
    else:
        subprocess.run(
            ["schtasks", "/delete", "/tn", _TASK_NAME, "/f"],
            capture_output=True, creationflags=CREATE_NO_WINDOW,
        )

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
    "https://api.github.com/repos/maximilianermert-stack/monitor-manager"
    "/releases/tags/latest"
)
_DETACHED_PROCESS = 0x00000008


def download_update() -> tuple:
    """Download latest exe from GitHub. Returns (ok, tmp_exe_path_or_error)."""
    if not getattr(sys, "frozen", False):
        return False, "Auto-update only works when running as .exe"
    try:
        req = urllib.request.Request(
            _GITHUB_RELEASE_URL, headers={"User-Agent": "MonitorManager"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        assets = [a for a in data.get("assets", []) if a["name"].endswith(".exe")]
        if not assets:
            return False, "No .exe found in latest release."
        download_url = assets[0]["browser_download_url"]
        tmp_exe = os.path.join(tempfile.gettempdir(), "MonitorManager_new.exe")
        urllib.request.urlretrieve(download_url, tmp_exe)
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


# ── System tray icon ───────────────────────────────────────────────────────────
def _create_tray_image() -> "Image.Image":
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    # Monitor bezel
    d.rectangle([4, 10, 60, 46], fill="#89b4fa", outline="#cdd6f4", width=3)
    # Screen area
    d.rectangle([9, 15, 55, 41], fill="#1e1e2e")
    # Stand
    d.rectangle([29, 46, 35, 54], fill="#cdd6f4")
    d.rectangle([20, 54, 44, 58], fill="#cdd6f4")
    return img

# ── Theme ───────────────────────────────────────────────────────────────────────
BG      = "#1e1e2e"
SURFACE = "#313244"
OVERLAY = "#45475a"
TEXT    = "#cdd6f4"
SUBTEXT = "#6c7086"
RED     = "#f38ba8"
BLUE    = "#89b4fa"
GREEN   = "#a6e3a1"
YELLOW  = "#f9e2af"
PURPLE  = "#cba6f7"
PEACH   = "#fab387"


def make_btn(parent, label, cmd, fg=TEXT):
    return tk.Button(
        parent, text=label, command=cmd,
        bg=SURFACE, fg=fg,
        activebackground=OVERLAY, activeforeground=fg,
        font=("Segoe UI", 10), relief="flat",
        padx=12, pady=6, cursor="hand2", bd=0,
    )

# ── RTSS FPS cap dialog ────────────────────────────────────────────────────────
class RTSSCapDialog(tk.Toplevel):
    _PRESETS = [0, 30, 60, 120, 144, 165, 240]

    def __init__(self, parent):
        super().__init__(parent)
        self.title("RTSS FPS Cap")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()

        current = get_rtss_fps_limit()

        tk.Label(self, text="Global FPS Cap (RTSS)",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT,
                 padx=20, pady=14).pack()

        # Preset buttons
        btn_row = tk.Frame(self, bg=BG, padx=20)
        btn_row.pack(fill="x")
        for fps in self._PRESETS:
            label  = "Unlimited" if fps == 0 else f"{fps}"
            is_cur = fps == current
            fg     = GREEN if is_cur else TEXT
            tk.Button(
                btn_row, text=label, width=8,
                command=lambda v=fps: self._apply(v),
                bg=SURFACE, fg=fg,
                activebackground=OVERLAY, activeforeground=fg,
                font=("Segoe UI", 10), relief="flat",
                padx=8, pady=6, cursor="hand2", bd=0,
            ).pack(side="left", padx=(0, 6), pady=(0, 12))

        # Custom entry
        row = tk.Frame(self, bg=BG, padx=20, pady=4)
        row.pack(fill="x")
        tk.Label(row, text="Custom:", font=("Segoe UI", 10),
                 bg=BG, fg=SUBTEXT).pack(side="left")
        self._entry = tk.Entry(
            row, width=7,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT,
            font=("Segoe UI", 10), relief="flat", bd=4,
        )
        self._entry.pack(side="left", padx=(8, 8))
        if current not in self._PRESETS and current > 0:
            self._entry.insert(0, str(current))
        tk.Button(
            row, text="Set",
            command=self._apply_custom,
            bg=SURFACE, fg=BLUE,
            activebackground=OVERLAY, activeforeground=BLUE,
            font=("Segoe UI", 10), relief="flat",
            padx=10, pady=5, cursor="hand2", bd=0,
        ).pack(side="left")

        tk.Label(self, text=f"Current: {'Unlimited' if current == 0 else f'{current} FPS'}",
                 font=("Segoe UI", 9), bg=BG, fg=SUBTEXT, pady=10).pack()

    def _apply(self, fps: int):
        if set_rtss_fps_limit(fps):
            self.destroy()
        else:
            messagebox.showerror("Monitor Manager", "Could not write RTSS profile.", parent=self)

    def _apply_custom(self):
        try:
            fps = int(self._entry.get())
            if fps < 0:
                raise ValueError
            self._apply(fps)
        except ValueError:
            messagebox.showerror("Monitor Manager", "Enter a valid number (0 = unlimited).", parent=self)


# ── Application ─────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor Manager")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(560, 280)
        self._tray_icon    = None
        self._autostart_var = None   # set in _build_ui after tk.BooleanVar is available
        self._build_ui()
        self.refresh()
        self._schedule_temp_update()
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        if _TRAY_AVAILABLE:
            self._start_tray()
        # Start minimized to tray if launched with --minimized flag
        if "--minimized" in sys.argv:
            self.after(150, self.withdraw)

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, padx=16, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Monitor Manager",
                 font=("Segoe UI", 14, "bold"), bg=BG, fg=TEXT).pack(side="left")

        # Temperature / usage bar
        temp_bar = tk.Frame(self, bg=SURFACE, padx=16, pady=10)
        temp_bar.pack(fill="x", padx=16)

        tk.Label(temp_bar, text="CPU", font=("Segoe UI", 9, "bold"),
                 bg=SURFACE, fg=SUBTEXT).pack(side="left")
        self._cpu_lbl = tk.Label(temp_bar, text="—",
                                  font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=PEACH)
        self._cpu_lbl.pack(side="left", padx=(6, 24))

        tk.Label(temp_bar, text="GPU", font=("Segoe UI", 9, "bold"),
                 bg=SURFACE, fg=SUBTEXT).pack(side="left")
        self._gpu_lbl = tk.Label(temp_bar, text="—",
                                  font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=BLUE)
        self._gpu_lbl.pack(side="left", padx=(6, 0))

        tk.Label(temp_bar, text="System", font=("Segoe UI", 9, "bold"),
                 bg=SURFACE, fg=SUBTEXT).pack(side="left", padx=(24, 0))
        self._pwr_lbl = tk.Label(temp_bar, text="—",
                                  font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=YELLOW)
        self._pwr_lbl.pack(side="left", padx=(6, 0))

        # Monitor list
        self.list_frame = tk.Frame(self, bg=BG, padx=16)
        self.list_frame.pack(fill="both", expand=True, pady=(12, 0))

        # Divider
        tk.Frame(self, bg=OVERLAY, height=1).pack(fill="x", padx=16, pady=(8, 0))

        # Bottom bar
        bar = tk.Frame(self, bg=BG, padx=16, pady=14)
        bar.pack(fill="x")
        make_btn(bar, "Turn Off All", turn_off_all,      RED ).pack(side="left", padx=(0, 8))
        make_btn(bar, "Screensaver",  start_screensaver, BLUE).pack(side="left", padx=(0, 8))

        self._hdr_btn = make_btn(bar, "HDR", self._on_toggle_hdr, RED)
        self._hdr_btn.pack(side="left", padx=(0, 8))

        self._build_misc_menu(bar)

        make_btn(bar, "↻  Refresh", self.refresh, GREEN).pack(side="left", padx=(8, 0))
        self._refresh_hdr_btn()

    def _build_misc_menu(self, bar):
        self._autostart_var = tk.BooleanVar(value=get_autostart())

        misc_btn = tk.Menubutton(
            bar, text="Misc ▾",
            bg=SURFACE, fg=TEXT,
            activebackground=OVERLAY, activeforeground=TEXT,
            font=("Segoe UI", 10), relief="flat",
            padx=12, pady=6, cursor="hand2", bd=0,
            indicatoron=False,
        )

        menu = tk.Menu(
            misc_btn, tearoff=0,
            bg=SURFACE, fg=TEXT,
            activebackground=OVERLAY, activeforeground=TEXT,
            font=("Segoe UI", 10), bd=0,
        )

        menu.add_command(label="Extend displays",
                         command=lambda: subprocess.Popen(["DisplaySwitch.exe", "/extend"]))
        menu.add_command(label="Duplicate displays",
                         command=lambda: subprocess.Popen(["DisplaySwitch.exe", "/clone"]))
        menu.add_command(label="PC screen only",
                         command=lambda: subprocess.Popen(["DisplaySwitch.exe", "/internal"]))
        menu.add_command(label="Second screen only",
                         command=lambda: subprocess.Popen(["DisplaySwitch.exe", "/external"]))
        menu.add_separator()

        # FPS Limit (refresh rate) cascade
        self._rate_menu = tk.Menu(
            menu, tearoff=0,
            bg=SURFACE, fg=TEXT,
            activebackground=OVERLAY, activeforeground=TEXT,
            font=("Segoe UI", 10), bd=0,
        )
        menu.add_cascade(label="Refresh Rate", menu=self._rate_menu)
        menu.add_command(label="RTSS FPS Cap…", command=self._on_rtss_cap)

        # Sound output cascade
        self._sound_menu = tk.Menu(
            menu, tearoff=0,
            bg=SURFACE, fg=TEXT,
            activebackground=OVERLAY, activeforeground=TEXT,
            font=("Segoe UI", 10), bd=0,
        )
        menu.add_cascade(label="Sound Output", menu=self._sound_menu)

        menu.add_command(label="Snipping Tool",
                         command=lambda: subprocess.Popen(["SnippingTool.exe"]))

        menu.config(postcommand=self._rebuild_misc_submenus)

        menu.add_separator()
        menu.add_command(label="Open Display Settings",
                         command=lambda: subprocess.Popen(["start", "ms-settings:display"], shell=True))
        menu.add_separator()
        menu.add_checkbutton(label="Start with Windows",
                             variable=self._autostart_var,
                             command=self._on_toggle_autostart)
        menu.add_separator()
        menu.add_command(label="Check for Updates", command=self._on_check_update)

        misc_btn.config(menu=menu)
        misc_btn.pack(side="left")

    def _rebuild_misc_submenus(self):
        self._rebuild_rate_menu()
        self._rebuild_sound_menu()

    def _rebuild_sound_menu(self):
        self._sound_menu.delete(0, "end")
        devices = get_audio_outputs()
        if not devices:
            self._sound_menu.add_command(label="    No devices found", state="disabled")
            return
        current = get_default_audio_output_id().lower()
        for name, device_id in devices:
            is_cur = device_id.lower() == current
            label  = f"✓  {name}" if is_cur else f"    {name}"
            self._sound_menu.add_command(
                label=label,
                command=lambda d=device_id: self._set_audio_output(d),
            )

    def _set_audio_output(self, device_id: str):
        # Run in thread so PowerShell fallback doesn't freeze the UI
        threading.Thread(
            target=self._do_set_audio, args=(device_id,), daemon=True
        ).start()

    def _do_set_audio(self, device_id: str):
        ok, err = set_default_audio_output(device_id)
        if not ok:
            self.after(0, lambda: messagebox.showerror(
                "Audio switch failed",
                f"Could not switch audio output.\n\n{err}" if err else
                "Could not switch audio output."
            ))

    def _rebuild_rate_menu(self):
        self._rate_menu.delete(0, "end")
        monitors = get_active_monitors()
        if not monitors:
            return
        primary = next((m for m in monitors if m["primary"]), monitors[0])
        device  = primary["device"]
        current = get_current_refresh_rate(device)
        for hz in get_available_refresh_rates(device):
            label = f"✓  {hz} Hz" if hz == current else f"    {hz} Hz"
            self._rate_menu.add_command(
                label=label,
                command=lambda h=hz: self._apply_rate(device, h),
            )
        self._rate_menu.add_separator()
        self._rate_menu.add_command(label="    Custom…", command=lambda: self._custom_rate(device))

    def _apply_rate(self, device: str, hz: int):
        if not set_refresh_rate(device, hz):
            messagebox.showerror("Monitor Manager", f"Could not set {hz} Hz on {device}.")

    def _custom_rate(self, device: str):
        hz = simpledialog.askinteger(
            "Refresh Rate", "Enter refresh rate (Hz):",
            parent=self, minvalue=1, maxvalue=500,
        )
        if hz:
            self._apply_rate(device, hz)

    def _on_rtss_cap(self):
        if not _find_rtss_path():
            messagebox.showerror("Monitor Manager",
                                 "RTSS not found.\nMake sure RivaTuner Statistics Server is installed.")
            return
        RTSSCapDialog(self)

    # ── System tray ──────────────────────────────────────────────────────────
    def _start_tray(self):
        img  = _create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show Monitor Manager", self._show_from_tray, default=True),
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_autostart,
                checked=lambda item: get_autostart(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._quit_app),
        )
        self._tray_icon = pystray.Icon("MonitorManager", img, "Monitor Manager", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _hide_to_tray(self):
        self.withdraw()

    def _show_from_tray(self, icon=None, item=None):
        self.after(0, self._do_show)

    def _do_show(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_toggle_autostart(self):
        set_autostart(self._autostart_var.get())

    def _on_check_update(self):
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        self.after(0, lambda: self._set_title("Monitor Manager  —  Downloading update…"))
        ok, result = download_update()
        if ok:
            # Switch back to main thread to show dialog, THEN launch batch and quit
            self.after(0, lambda: self._finish_update(result))
        else:
            self.after(0, lambda: (
                self._set_title("Monitor Manager"),
                messagebox.showerror("Update failed", result or "Could not download update."),
            ))

    def _finish_update(self, tmp_exe: str):
        self._set_title("Monitor Manager")
        messagebox.showinfo("Update", "Update downloaded!\nThe app will now restart.")
        apply_update(tmp_exe)   # launch batch RIGHT before quitting
        self._quit_app()

    def _set_title(self, title: str):
        self.title(title)

    def _toggle_autostart(self, icon=None, item=None):
        """Called from tray menu."""
        new = not get_autostart()
        set_autostart(new)
        if self._autostart_var is not None:
            self._autostart_var.set(new)

    def _quit_app(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    # ── Temperature polling (background thread) ──────────────────────────────
    def _schedule_temp_update(self):
        threading.Thread(target=self._fetch_temps, daemon=True).start()

    def _fetch_temps(self):
        cpu_temp, cpu_load, cpu_power, gpu_temp, gpu_load, gpu_power, gpu_mem_used, gpu_mem_total = get_temperatures()
        ram_used, ram_total = get_ram_usage()
        hdr = get_hdr_state()
        self.after(0, lambda: self._apply_temps(
            cpu_temp, cpu_load, cpu_power,
            gpu_temp, gpu_load, gpu_power, gpu_mem_used, gpu_mem_total,
            ram_used, ram_total,
        ))
        self.after(0, lambda: self._apply_hdr_color(hdr))
        self.after(3000, self._schedule_temp_update)

    def _refresh_hdr_btn(self):
        self._apply_hdr_color(get_hdr_state())

    def _apply_hdr_color(self, hdr_on: bool):
        color = GREEN if hdr_on else RED
        self._hdr_btn.config(fg=color, activeforeground=color)

    def _on_toggle_hdr(self):
        toggle_hdr()
        self.after(600, self._refresh_hdr_btn)

    def _apply_temps(self, cpu_temp, cpu_load, cpu_power,
                     gpu_temp, gpu_load, gpu_power, gpu_mem_used, gpu_mem_total,
                     ram_used, ram_total):
        cpu_text = f"{cpu_temp:.0f} °C" if cpu_temp is not None else "N/A"
        if cpu_load is not None: cpu_text += f"  ·  {cpu_load:.0f}%"
        self._cpu_lbl.config(text=cpu_text)

        gpu_text = f"{gpu_temp:.0f} °C" if gpu_temp is not None else "N/A"
        if gpu_load is not None: gpu_text += f"  ·  {gpu_load:.0f}%"
        if gpu_mem_used is not None and gpu_mem_total is not None:
            gpu_text += f"  ·  {gpu_mem_used/1024:.1f}/{round(gpu_mem_total/1024)} GB"
        self._gpu_lbl.config(text=gpu_text)

        pwr_parts = [p for p in (cpu_power, gpu_power) if p is not None]
        pwr_text  = f"{sum(pwr_parts):.0f} W" if pwr_parts else "N/A"
        pwr_text += f"  ·  {ram_used:.1f}/{ram_total} GB"
        self._pwr_lbl.config(text=pwr_text)

    # ── Monitor cards ────────────────────────────────────────────────────────
    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        active   = get_active_monitors()
        disabled = get_disabled_devices({m["device"] for m in active})

        if not active and not disabled:
            tk.Label(self.list_frame, text="No monitors detected.",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 10), pady=24).pack()
            return

        for mon in active:
            self._active_card(mon)
        for dev in disabled:
            self._disabled_card(dev, active)

    def _active_card(self, mon: dict):
        card = tk.Frame(self.list_frame, bg=SURFACE, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 8))

        top = tk.Frame(card, bg=SURFACE)
        top.pack(fill="x")

        tk.Label(top, text=f"Monitor {mon['index']}",
                 font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")

        badge_text  = "  ● Primary"   if mon["primary"] else "  ○ Secondary"
        badge_color = BLUE            if mon["primary"] else SUBTEXT
        tk.Label(top, text=badge_text,
                 font=("Segoe UI", 9), bg=SURFACE, fg=badge_color).pack(side="left")

        make_btn(top, "Disable",
                 lambda d=mon["device"], p=mon["primary"]: self._on_disable(d, p),
                 YELLOW).pack(side="right", padx=(4, 0))

        if not mon["primary"]:
            make_btn(top, "★ Make Primary",
                     lambda d=mon["device"]: self._on_make_primary(d),
                     GREEN).pack(side="right")

        info = (
            f"{mon['width']} × {mon['height']}    "
            f"Position  ({mon['left']}, {mon['top']})    "
            f"Device  {mon['device']}"
        )
        tk.Label(card, text=info,
                 font=("Segoe UI", 9), bg=SURFACE, fg=SUBTEXT).pack(anchor="w", pady=(5, 0))

    def _disabled_card(self, dev: dict, active_monitors: list):
        card = tk.Frame(self.list_frame, bg=SURFACE, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 8))

        top = tk.Frame(card, bg=SURFACE)
        top.pack(fill="x")

        tk.Label(top, text=dev["device"],
                 font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=TEXT).pack(side="left")
        tk.Label(top, text="  ✕ Disabled",
                 font=("Segoe UI", 9), bg=SURFACE, fg=RED).pack(side="left")

        make_btn(top, "Enable",
                 lambda d=dev["device"], a=active_monitors: self._on_enable(d, a),
                 PURPLE).pack(side="right")

        tk.Label(card, text=dev["description"],
                 font=("Segoe UI", 9), bg=SURFACE, fg=SUBTEXT).pack(anchor="w", pady=(5, 0))

    def _on_disable(self, device: str, primary: bool):
        if disable_monitor(device, primary):
            self.refresh()
        else:
            messagebox.showerror("Monitor Manager", f"Could not disable {device}.")

    def _on_enable(self, device: str, active_monitors: list):
        if enable_monitor(device, active_monitors):
            self.refresh()
        else:
            messagebox.showerror("Monitor Manager", f"Could not enable {device}.")

    def _on_make_primary(self, device: str):
        monitors = get_active_monitors()
        if make_primary(device, monitors):
            self.refresh()
        else:
            messagebox.showerror("Monitor Manager", f"Could not set {device} as primary.")


if __name__ == "__main__":
    app = App()
    app.mainloop()
