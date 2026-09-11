===============================================================================
  Hotspot.dll - RTX 50 hotspot & memory temperature plugin for MSI Afterburner
===============================================================================

Monitoring plugin that adds the sensors NVIDIA hides on RTX 50 (Blackwell)
cards:

  Sensor                            What it is                    Needs unlock?
  --------------------------------  ----------------------------  -------------
  GPU hotspot temperature           hardware-aggregated maximum   yes
                                    of the die thermal channels
  GPU hotspot delta                 hottest - coldest channel     yes
                                    (a delta that keeps growing
                                    over time = degrading paste)
  GPU average temperature           hardware-aggregated average   yes
                                    of the die channels (the
                                    "traditional" GPU temp read
                                    straight from the die)
  GPU hotspot CH0..CH3              the 4 independent channels    yes
  VRAM hottest chip                 hottest of the per-chip       yes
                                    GDDR7 DRAM sensors
  VRAM chip delta                   hottest - coldest chip        yes
  VRAM chip 0..15                   each GDDR7 chip's own         yes
                                    DRAM sensor
  GPU memory junction temperature   VRAM temperature (official    NO
                                    driver channel)

The die sensors are read from GPU MMIO registers through Afterburner's
exported ReadRegisterUlong function, exactly as published by Unwinder
(author of Afterburner/RivaTuner) in the "MSI Afterburner v4.6.7 beta 1"
thread on the Guru3D forums (posts #22-#23, register semantics from his
follow-up analysis in post #26: 4 independent channels at 0xAD0A90..0xAD0A9C
plus hardware-aggregated max at 0xAD0AA0 and average at 0xAD0AA4, 1/256 C).
The memory junction temperature uses the driver's thermal-channel interface,
as demonstrated in Unwinder's open-source RTSS OverlayEditor HAL (shipped
with the RTSS SDK). All credit for the methods goes to him.

The per-chip VRAM sensors read the raw GDDR7 DRAM sensors that the GPU's
own thermal firmware uses (NV_PFB_FBPA_DQR_STATUS_DQ, FBPA p at
0x9024C0 + p*0x4000, GDDR MR temperature code, 2 C resolution). Each FBPA
drives two chips and exposes four readout registers (+0 IC0_SUBP0,
+4 IC0_SUBP1, +8 IC1_SUBP0, +C IC1_SUBP1, validity bits 24..27 at +0x10):
the two subpartitions are the two physical chips of the pair. On
non-clamshell cards the IC1 copies mirror IC0; on clamshell cards
(memory on both PCB sides, e.g. RTX 5060 Ti 16GB) IC0/IC1 are the
front/back chip of that subpartition, shown as separate sensors - the
layout is picked automatically from the memory controller's clamshell
configuration strap. Base register map and decode
come from the open-source Linux tool olealgoritme/gddr6
(github.com/olealgoritme/gddr6), in the wake of the per-module temperature
discovery by Paulo Gomes' team; the ICx/SUBPx mapping that unlocks all 16
individual chips was provided by Mumak, author of HWiNFO. At startup the
plugin cross-checks these readings against the memory junction sensor and
keeps the whole group disabled (with the reason in Hotspot.log) if they
disagree.

The plugin is READ-ONLY (it never writes a GPU register) and automatically
disables any sensor that is not available on your system.


-------------------------------------------------------------------------------
 1. PREPARE AFTERBURNER (needed for the hotspot sensors only)
-------------------------------------------------------------------------------

With Afterburner CLOSED, edit two files in
C:\Program Files (x86)\MSI Afterburner\  (run your text editor as admin):

a) RTCore.cfg - at the end of the [GPU_10DE] section (after the G108 line)
   add:

      G1B2	= 2B85h

   2B85 is the RTX 5090 DeviceID. Different card? Use its DeviceID
   (GPU-Z -> "Device ID" field, the part after 10DE).

b) Profiles\VEN_10DE&DEV_2B85&...cfg  (your card's hardware profile) -
   under the [Settings] section add:

      LowLevelMonitoring	= 0

   !!! DO NOT SKIP THIS !!!
   Without it Afterburner shows wrong clocks or crashes once low-level
   access is unlocked.

If you only want the memory junction sensor, skip both edits.


-------------------------------------------------------------------------------
 2. INSTALL & ENABLE
-------------------------------------------------------------------------------

1. Copy Hotspot.dll and Hotspot.cfg to:
   C:\Program Files (x86)\MSI Afterburner\Plugins\Monitoring\

2. Start Afterburner -> Settings -> Monitoring tab -> click the "..." button
   next to "Active hardware monitoring graphs" -> tick Hotspot.dll -> OK.

3. Tick the new sensors in the list (and "Show in On-Screen Display" if you
   want them in the OSD).


-------------------------------------------------------------------------------
 3. OPTIONS (Hotspot.cfg)
-------------------------------------------------------------------------------

Every setting is documented inside the file itself:

  EnableHotspot     1/0  hotspot + delta              (default 1)
  EnableAverage     1/0  die average temperature      (default 1)
  EnableChannels    1/0  the 4 independent channels   (default 1)
  EnableMemory      1/0  memory junction              (default 1)
  EnableVram        1/0  VRAM hottest chip + delta    (default 1)
  VramPerModule     1/0  the individual VRAM chips    (default 1)
  VramClamshell     separate front/back sensors on clamshell cards such
                    as the RTX 5060 Ti 16GB. -1 = auto-detect from the
                    memory controller strap (default), 0/1 = force
  MemoryPollPeriod  how often the memory junction sensor is read, ms
                    (default 1000;
                    a background thread does it, Afterburner's polling is
                    never slowed down)
  GpuIndex          -1 = auto-detect (multi-GPU systems only)
  EnableLog         1 = diagnostics to Hotspot.log (troubleshooting)


-------------------------------------------------------------------------------
 BUILD FROM SOURCE
-------------------------------------------------------------------------------

One C file, no dependencies. Must be compiled as 32-BIT:

  i686-w64-mingw32-clang Hotspot.c Hotspot.def -o Hotspot.dll -shared -static -O2 -s

or with MSVC from an x86 developer prompt:

  cl /LD /O2 Hotspot.c /link /DEF:Hotspot.def


-------------------------------------------------------------------------------
 NOTES
-------------------------------------------------------------------------------

- Hotspot and per-module VRAM register addresses are Blackwell-specific
  (the per-module block is verified on GB202 / RTX 5090). The memory
  junction sensor also works on RTX 30/40 cards.
- Afterburner updates may overwrite RTCore.cfg - just re-add the line.
- Use at your own risk. The plugin only reads, but the unlock enables
  Afterburner's low-level hardware access in general: don't poke registers
  through the CLI unless you know what you are doing.
