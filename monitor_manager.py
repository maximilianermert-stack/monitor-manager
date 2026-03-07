"""
Monitor Manager
Run on Windows with Python 3.x — no extra dependencies needed.
"""

import tkinter as tk
from tkinter import messagebox
import ctypes
import ctypes.wintypes
import winreg
import subprocess

# ── Windows API constants ──────────────────────────────────────────────────────
MONITORINFOF_PRIMARY        = 0x00000001
WM_SYSCOMMAND               = 0x0112
SC_MONITORPOWER             = 0xF170
HWND_BROADCAST              = 0xFFFF
ENUM_CURRENT_SETTINGS       = 0xFFFFFFFF

DM_POSITION                 = 0x00000020
DM_PELSWIDTH                = 0x00080000
DM_PELSHEIGHT               = 0x00100000
CDS_UPDATEREGISTRY          = 0x00000001
CDS_NORESET                 = 0x10000000
DISP_CHANGE_SUCCESSFUL      = 0

DISPLAY_DEVICE_ACTIVE       = 0x00000001   # attached to desktop

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
        # Union (display layout)
        ("dmPositionX",          ctypes.c_long),
        ("dmPositionY",          ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        # Shared fields
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

# ── Monitor helpers ─────────────────────────────────────────────────────────────
_MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(RECT),
    ctypes.c_long,
)

def get_active_monitors():
    """Return active monitors with resolution and position info."""
    monitors = []
    counter = [0]

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
            "active":  True,
        })
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
    monitors.sort(key=lambda m: (not m["primary"], m["index"]))
    return monitors


def get_disabled_devices(active_devices: set) -> list:
    """Return display devices that exist but are not active (i.e. disabled)."""
    disabled = []
    dd = DISPLAY_DEVICE()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
    i = 0
    while ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
        is_active = bool(dd.StateFlags & DISPLAY_DEVICE_ACTIVE)
        device_name = dd.DeviceName

        if not is_active and device_name not in active_devices:
            # Only include if the device has at least one valid display mode
            # (filters out phantom adapter outputs with no monitor attached)
            dm = DEVMODE()
            dm.dmSize = ctypes.sizeof(DEVMODE)
            has_modes = ctypes.windll.user32.EnumDisplaySettingsW(device_name, 0, ctypes.byref(dm))
            if has_modes:
                disabled.append({
                    "device":      device_name,
                    "description": dd.DeviceString,
                    "active":      False,
                })
        i += 1
    return disabled


# ── Actions ─────────────────────────────────────────────────────────────────────
def turn_off_all():
    """Power-off signal to all monitors — wake on any input."""
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
        device, ctypes.byref(dm), None,
        CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


def enable_monitor(device: str, active_monitors: list) -> bool:
    """Re-enable a disabled monitor at the highest supported resolution."""
    # Find highest supported resolution for this device
    best_w, best_h, best_freq = 1920, 1080, 60  # safe fallback
    dm_query = DEVMODE()
    dm_query.dmSize = ctypes.sizeof(DEVMODE)
    i = 0
    while ctypes.windll.user32.EnumDisplaySettingsW(device, i, ctypes.byref(dm_query)):
        if dm_query.dmPelsWidth * dm_query.dmPelsHeight > best_w * best_h:
            best_w  = dm_query.dmPelsWidth
            best_h  = dm_query.dmPelsHeight
            best_freq = dm_query.dmDisplayFrequency
        i += 1

    # Place the monitor to the right of the rightmost active monitor
    rightmost_x = max((m["left"] + m["width"] for m in active_monitors), default=0)

    dm = DEVMODE()
    dm.dmSize         = ctypes.sizeof(DEVMODE)
    dm.dmFields       = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth    = best_w
    dm.dmPelsHeight   = best_h
    dm.dmPositionX    = rightmost_x
    dm.dmPositionY    = 0

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None,
        CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    ctypes.windll.user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    return result == DISP_CHANGE_SUCCESSFUL


def start_screensaver():
    """Launch the screensaver currently configured in Windows Settings."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            path, _ = winreg.QueryValueEx(key, "SCRNSAVE.EXE")
        if path:
            subprocess.Popen([path, "/s"])
        else:
            messagebox.showinfo("Monitor Manager", "No screensaver is configured in Windows Settings.")
    except (FileNotFoundError, OSError):
        messagebox.showinfo("Monitor Manager", "No screensaver is configured in Windows Settings.")


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


def make_btn(parent, label, cmd, fg=TEXT):
    return tk.Button(
        parent, text=label, command=cmd,
        bg=SURFACE, fg=fg,
        activebackground=OVERLAY, activeforeground=fg,
        font=("Segoe UI", 10), relief="flat",
        padx=12, pady=6, cursor="hand2", bd=0,
    )


# ── Application ─────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor Manager")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG, padx=16, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Monitor Manager",
                 font=("Segoe UI", 14, "bold"), bg=BG, fg=TEXT).pack(side="left")

        self.list_frame = tk.Frame(self, bg=BG, padx=16)
        self.list_frame.pack(fill="both")

        tk.Frame(self, bg=OVERLAY, height=1).pack(fill="x", padx=16, pady=(8, 0))

        bar = tk.Frame(self, bg=BG, padx=16, pady=14)
        bar.pack(fill="x")

        make_btn(bar, "Turn Off All",     turn_off_all,      RED  ).pack(side="left", padx=(0, 8))
        make_btn(bar, "Screensaver Mode", start_screensaver, BLUE ).pack(side="left")
        make_btn(bar, "↻  Refresh",       self.refresh,      GREEN).pack(side="right")

    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        active   = get_active_monitors()
        active_names = {m["device"] for m in active}
        disabled = get_disabled_devices(active_names)

        if not active and not disabled:
            tk.Label(self.list_frame, text="No monitors detected.",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 10), pady=24).pack()
            return

        for mon in active:
            self._active_card(mon)

        for dev in disabled:
            self._disabled_card(dev, active)

    # ── Active monitor card ──────────────────────────────────────────────────────
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
                 YELLOW).pack(side="right")

        info = (
            f"{mon['width']} × {mon['height']}    "
            f"Position  ({mon['left']}, {mon['top']})    "
            f"Device  {mon['device']}"
        )
        tk.Label(card, text=info,
                 font=("Segoe UI", 9), bg=SURFACE, fg=SUBTEXT).pack(anchor="w", pady=(5, 0))

    # ── Disabled monitor card ────────────────────────────────────────────────────
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

    # ── Handlers ────────────────────────────────────────────────────────────────
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


if __name__ == "__main__":
    app = App()
    app.mainloop()
