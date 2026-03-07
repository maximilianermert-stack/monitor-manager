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
MONITORINFOF_PRIMARY = 0x00000001
WM_SYSCOMMAND        = 0x0112
SC_MONITORPOWER      = 0xF170
HWND_BROADCAST       = 0xFFFF

DM_POSITION    = 0x00000020
DM_PELSWIDTH   = 0x00080000
DM_PELSHEIGHT  = 0x00100000
CDS_UPDATEREGISTRY = 0x00000001
CDS_NORESET        = 0x10000000
DISP_CHANGE_SUCCESSFUL = 0

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
    ctypes.c_ulong,   # HMONITOR
    ctypes.c_ulong,   # HDC
    ctypes.POINTER(RECT),
    ctypes.c_long,
)

def get_monitors():
    monitors = []
    counter = [0]

    def _cb(hMonitor, hdc, lprc, _):
        info = MONITORINFOEX()
        info.cbSize = ctypes.sizeof(MONITORINFOEX)
        ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        r = info.rcMonitor
        counter[0] += 1
        monitors.append({
            "index":   counter[0],
            "device":  info.szDevice,
            "left":    r.left,
            "top":     r.top,
            "width":   r.right  - r.left,
            "height":  r.bottom - r.top,
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        })
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
    monitors.sort(key=lambda m: (not m["primary"], m["index"]))
    return monitors


# ── Actions ─────────────────────────────────────────────────────────────────────
def turn_off_all():
    """Power-off signal to all monitors — wake on any input."""
    ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


def disable_monitor(device: str, primary: bool) -> bool:
    """
    Remove a monitor from the Windows desktop layout.
    This is equivalent to setting it to 'Disconnect this display' in Display Settings.
    The monitor can be re-enabled via Refresh → it will be detected again but won't
    have a position until Windows or the user re-adds it.
    """
    if primary:
        messagebox.showwarning(
            "Monitor Manager",
            "The primary monitor cannot be disabled.\n"
            "Set another monitor as primary first."
        )
        return False

    dm = DEVMODE()
    dm.dmSize    = ctypes.sizeof(DEVMODE)
    dm.dmFields  = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT
    dm.dmPelsWidth  = 0
    dm.dmPelsHeight = 0

    result = ctypes.windll.user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None,
        CDS_UPDATEREGISTRY | CDS_NORESET, None
    )
    # Commit all pending changes
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


def make_btn(parent, label, cmd, fg=TEXT, width=None):
    kw = dict(
        text=label, command=cmd,
        bg=SURFACE, fg=fg,
        activebackground=OVERLAY, activeforeground=fg,
        font=("Segoe UI", 10), relief="flat",
        padx=12, pady=6, cursor="hand2", bd=0,
    )
    if width:
        kw["width"] = width
    return tk.Button(parent, **kw)


# ── Application ─────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor Manager")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._build_ui()
        self.refresh()

    # ── Layout ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, padx=16, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Monitor Manager",
                 font=("Segoe UI", 14, "bold"), bg=BG, fg=TEXT).pack(side="left")

        # Scrollable monitor list
        self.list_frame = tk.Frame(self, bg=BG, padx=16)
        self.list_frame.pack(fill="both")

        # Divider
        tk.Frame(self, bg=OVERLAY, height=1).pack(fill="x", padx=16, pady=(8, 0))

        # Bottom action bar
        bar = tk.Frame(self, bg=BG, padx=16, pady=14)
        bar.pack(fill="x")

        make_btn(bar, "Turn Off All",     turn_off_all,      RED  ).pack(side="left", padx=(0, 8))
        make_btn(bar, "Screensaver Mode", start_screensaver, BLUE ).pack(side="left")
        make_btn(bar, "↻  Refresh",       self.refresh,      GREEN).pack(side="right")

    # ── Monitor cards ───────────────────────────────────────────────────────────
    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        monitors = get_monitors()

        if not monitors:
            tk.Label(self.list_frame, text="No monitors detected.",
                     bg=BG, fg=SUBTEXT, font=("Segoe UI", 10), pady=24).pack()
            return

        for mon in monitors:
            self._monitor_card(mon)

    def _monitor_card(self, mon: dict):
        card = tk.Frame(self.list_frame, bg=SURFACE, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 8))

        # Top row: name + badge + disable button
        top = tk.Frame(card, bg=SURFACE)
        top.pack(fill="x")

        tk.Label(top,
                 text=f"Monitor {mon['index']}",
                 font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=TEXT
                 ).pack(side="left")

        badge_text  = "  ● Primary"   if mon["primary"] else "  ○ Secondary"
        badge_color = BLUE            if mon["primary"] else SUBTEXT
        tk.Label(top, text=badge_text,
                 font=("Segoe UI", 9), bg=SURFACE, fg=badge_color
                 ).pack(side="left")

        make_btn(
            top, "Disable",
            lambda d=mon["device"], p=mon["primary"]: self._disable(d, p),
            YELLOW
        ).pack(side="right")

        # Info row
        info = (
            f"{mon['width']} × {mon['height']}    "
            f"Position  ({mon['left']}, {mon['top']})    "
            f"Device  {mon['device']}"
        )
        tk.Label(card, text=info,
                 font=("Segoe UI", 9), bg=SURFACE, fg=SUBTEXT
                 ).pack(anchor="w", pady=(5, 0))

    def _disable(self, device: str, primary: bool):
        ok = disable_monitor(device, primary)
        if ok:
            messagebox.showinfo(
                "Monitor Manager",
                f"{device} has been disabled.\n\n"
                "Use Windows Display Settings or click Refresh + re-configure to re-enable it."
            )
            self.refresh()
        else:
            messagebox.showerror("Monitor Manager", f"Could not disable {device}.")


if __name__ == "__main__":
    app = App()
    app.mainloop()
