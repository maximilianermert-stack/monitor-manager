# System Manager

[![Build Windows EXE](https://github.com/maximilianermert-stack/monitor-manager/actions/workflows/build.yml/badge.svg)](https://github.com/maximilianermert-stack/monitor-manager/actions/workflows/build.yml)

A lightweight **Windows tray app** that shows what your PC is doing and lets you control your displays — in one dark, resizable dashboard.

CPU, GPU, RAM, SSD and motherboard sensors with trend sparklines and colour-coded alerts · the **real RTX 50 hotspot** (which NVIDIA hides) via MSI Afterburner · energy statistics in kWh and € · fan gauges · multi-monitor on/off, refresh rate, HDR, RTSS FPS cap, audio output switching. Built with PyQt6 and LibreHardwareMonitor. UI in **English, Deutsch, Español, Français**.

> Status: actively developed hobby project, tested on one machine (Ryzen 7 9800X3D · RTX 5080 · ASUS B850). Other hardware will mostly work (LibreHardwareMonitor does the heavy lifting), but expect rough edges.

---

## Features

**Overview**
- Four hero tiles — **CPU · GPU · System · Controller** — with big colour-coded values, usage · watts, a **60-second sparkline** each, and the GPU hotspot highlighted in magenta.
- Values turn **amber / red** past configurable thresholds; a health dot in the header and the **tray icon** change colour; an optional Windows notification fires once when something goes critical.
- **Cooling** tiles for every board fan (PWM %), **Displays** summary, and a **lock/unlock** button to resize the sections with drag dividers (layout is saved).

**System tab** — collapsible cards with detailed readouts
- **CPU**: package temp, power, voltage, per-core clock & load.
- **GPU**: core, hotspot, memory junction, clocks, power, fan, VRAM, PCIe load.
- **RAM**, **Motherboard** (chipset/VRM temps, voltages, BIOS info).
- **SSD · Storage**: per drive temperature, used space, health and total data written (NVMe & SATA).
- **PWR · Power Consumption (CPU + GPU)**: now / average / peak (with time) / spikes, kWh and cost for today, this month and this year, peak CPU & GPU, yesterday — with your own electricity price.

**Fans tab** — animated ring gauges (RPM + PWM %) for every fan, rename by double-click. *Read-only by design:* System Manager never writes fan speeds, so it runs happily next to FanControl, Armoury Crate & co.

**Monitors tab** — see every attached display, make one primary, **enable/disable** individual monitors, pick refresh rates.

**Bottom bar & Misc menu** — Turn Off All displays · Screensaver · HDR toggle · extend/duplicate/PC-only/second-only · refresh rate · **RTSS FPS cap** · sound output device · Snipping Tool · display settings · GPU hotspot setup · design themes (8 presets + custom colours) · alert toggles & thresholds · electricity price · **Language** · start with Windows · debug info · **check for updates** (self-updating).

## The RTX 50 hotspot

NVIDIA removed the hotspot sensor from its public API on Blackwell cards. System Manager reads it anyway — safely — by **reading MSI Afterburner's shared memory**, where the community *BlackwellHotspot* plugin publishes the real die temperature. System Manager itself never touches the GPU registers.

**Misc → GPU Hotspot (Afterburner)…** walks you through it in three steps (plugin install with one click, the one-time RTCore unlock with ready-to-paste lines for your detected GPU, enabling the readout). Note that the unlock edits two MSI Afterburner config files; the dialog tells you exactly which lines, and you make the edits yourself.

## Requirements

- Windows 10 / 11, 64-bit.
- **Administrator rights** — sensor reading uses LibreHardwareMonitor's kernel driver (WinRing0). The app requests elevation on start.
- .NET Framework 4.7.2+ (already on every modern Windows) for the bundled sensor helper.
- Optional: **MSI Afterburner** (for the RTX 50 hotspot) and **RivaTuner Statistics Server** (for the FPS cap).

## Install

1. Download `SystemManager.zip` from the [latest build](https://github.com/maximilianermert-stack/monitor-manager/releases/tag/latest) (every push to `main` publishes a fresh one).
2. Extract the folder anywhere (e.g. `C:\Tools\SystemManager`) and run `SystemManager.exe`. It lives in the tray; double-click the icon to open the window.
3. Later updates: **Misc → Check for Updates** downloads and swaps the build in place.

**Antivirus note:** the build is **not code-signed** and ships a kernel driver (WinRing0 via LibreHardwareMonitor), so Bitdefender and friends may quarantine `TempReader.exe`. If sensors show "—", add the extracted folder to your AV exclusions — that is also why the app is distributed as a folder rather than a single exe.

## Good to know

- **Power figures are CPU + GPU only.** Board, RAM, fans and PSU losses are not measured — real wall power is roughly 60–100 W higher.
- **Energy history** is stored in `%APPDATA%\SystemManager\energy.json` (~400 days); settings, theme and fan names live next to it.
- **Thresholds** default to CPU 80/90 °C, GPU 80/88 °C, hotspot 90/100 °C (warning/critical) and can be changed under Misc.
- Switching the **language** restarts the app so every label is rebuilt.

## Build from source

The GitHub Actions workflow in `.github/workflows/build.yml` is the reference build. Locally on Windows:

```bash
pip install pyinstaller PyQt6 Pillow
cd tempreader  && dotnet publish -c Release --framework net472 -o ../tempreader_out  && cd ..
cd audioswitch && dotnet publish -c Release --framework net472 -o ../audioswitch_out && cd ..
python create_icon.py
pyinstaller --onedir --noupx --windowed --name SystemManager --uac-admin --icon icon.ico ^
  --version-file version_info.txt --collect-all PyQt6 ^
  --add-data "tempreader_out;tempreader" --add-data "audioswitch_out;audioswitch" ^
  --add-data "plugin;plugin" system_manager.py
```

Running from source for development: `python system_manager.py` (sensors still need the compiled `TempReader.exe` next to the script in `tempreader/`).

## Project layout

```
system_manager.py   PyQt6 app: UI, polling, alerts, energy stats, updater, i18n
tempreader/         C# helper (LibreHardwareMonitorLib 0.9.5-pre453) → sensor JSON + Afterburner shared memory
audioswitch/        C# helper to switch the default audio device (IPolicyConfig)
plugin/             BlackwellHotspot Afterburner plugin (Hotspot.dll + its README) bundled for one-click install
create_icon.py      Generates the app icon at build time
.github/workflows/  CI: builds both helpers + the PyInstaller bundle, publishes SystemManager.zip
```

## Credits

- [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) — sensor access (CPU, GPU, motherboard, storage, fans).
- The community **BlackwellHotspot** Afterburner plugin — RTX 50 hotspot and per-module GDDR7 temperatures. Bundled as provided, with its original README; all credit to its author.
- [MSI Afterburner / RivaTuner Statistics Server](https://www.guru3d.com/) by Unwinder — shared-memory sensors and the FPS limiter this app talks to.

## Disclaimer

This software reads hardware through a kernel driver and, for the hotspot feature, guides you through editing another application's configuration. It is provided as-is, without warranty. Use at your own risk.
