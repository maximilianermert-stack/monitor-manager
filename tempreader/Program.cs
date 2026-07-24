using System;
using System.Diagnostics;
using System.Text.RegularExpressions;
using LibreHardwareMonitor.Hardware;
using Newtonsoft.Json;

var computer = new Computer
{
    IsCpuEnabled         = true,
    IsGpuEnabled         = true,
    IsMotherboardEnabled = true,
};
computer.Open();

float? cpuTemp     = null;
bool   cpuTempLocked = false;   // set once a definitive die/package sensor is found
float? cpuLoad     = null;
float? cpuPower    = null;
float? cpuVoltage  = null;
float? gpuTemp     = null;
float? gpuLoad     = null;
float? gpuPower    = null;
float? gpuMemUsed  = null;  // MB
float? gpuMemTotal = null;  // MB
string gpuName     = "";

float? gpuHotspot     = null;
float? gpuMemJunction = null;
float? gpuCoreClock   = null;
float? gpuMemClock    = null;
float? gpuFanPct      = null;
float? gpuPcieLoad    = null;

float? mbChipsetTemp = null;
float? mbVrmTemp     = null;
var mbVoltages = new System.Collections.Generic.Dictionary<string, float>();

// index -> (clock, load), merged into a list once both sensor types are seen
var cpuCoreData = new System.Collections.Generic.Dictionary<int, (float? clock, float? load)>();

var fans    = new System.Collections.Generic.List<object>();
var debugHw = new System.Collections.Generic.List<string>();

// Systems with an AMD/Intel CPU often expose an integrated GPU alongside the
// discrete card. The iGPU sits on the CPU die, so its "GPU" temperature is
// really the CPU temperature — picking it makes GPU temp track CPU temp. When
// a discrete NVIDIA GPU is present, treat only it as "the GPU".
bool hasNvidia = System.Linq.Enumerable.Any(
    computer.Hardware, h => h.HardwareType == HardwareType.GpuNvidia);

foreach (var hw in computer.Hardware)
{
    hw.Update();

    bool isCpu = hw.HardwareType == HardwareType.Cpu;
    bool isGpu = hasNvidia
        ? hw.HardwareType == HardwareType.GpuNvidia
        : hw.HardwareType is HardwareType.GpuAmd
                          or HardwareType.GpuIntel
                          or HardwareType.GpuNvidia;
    bool isMb  = hw.HardwareType == HardwareType.Motherboard;

    debugHw.Add($"{hw.HardwareType}:{hw.Name}");
    foreach (var s in hw.Sensors)
        debugHw.Add($"  {s.SensorType}/{s.Name}={s.Value}");
    foreach (var sub in hw.SubHardware)
        debugHw.Add($"  sub:{sub.HardwareType}:{sub.Name}:{string.Join(",", System.Linq.Enumerable.Select(sub.Sensors, s => $"{s.SensorType}/{s.Name}={s.Value}"))}");

    if (!isCpu && !isGpu && !isMb) continue;

    foreach (var sensor in hw.Sensors)
    {
        if (sensor.Value == null) continue;

        if (isCpu)
        {
            if (sensor.SensorType == SensorType.Temperature && sensor.Value > 0)
            {
                // On AMD, "Core (Tctl/Tdie)" is the sensor to display; only it
                // carries "Tctl" (per-CCD sensors are "CCDx (Tdie)" only), so we
                // treat Tctl as definitive and let it win regardless of order.
                // Intel's "CPU Package" is the equivalent definitive sensor.
                // Everything else is a fallback, and 0-value readings (parked
                // CCDs, unused probes) are skipped so they can't mask the real temp.
                bool definitive = sensor.Name.Contains("Tctl")
                               || sensor.Name.Contains("Package");
                if (definitive)
                {
                    cpuTemp = sensor.Value;
                    cpuTempLocked = true;
                }
                else if (!cpuTempLocked)
                {
                    bool preferred = sensor.Name.Contains("Tdie")
                                  || sensor.Name.Contains("Average");
                    if (preferred || cpuTemp == null)
                        cpuTemp = sensor.Value;
                }
            }
            else if (sensor.SensorType == SensorType.Load && sensor.Name == "CPU Total")
                cpuLoad = sensor.Value;
            else if (sensor.SensorType == SensorType.Power && cpuPower == null
                     && (sensor.Name.Contains("Package") || sensor.Name.Contains("CPU")))
                cpuPower = sensor.Value;
            else if (sensor.SensorType == SensorType.Voltage && cpuVoltage == null
                     && (sensor.Name.Contains("Core") || sensor.Name.Contains("VCore") || sensor.Name.Contains("Vcore")))
                cpuVoltage = sensor.Value;
            else if (sensor.SensorType == SensorType.Load && sensor.Name.Contains("CPU Core"))
            {
                var m = Regex.Match(sensor.Name, @"#(\d+)");
                if (m.Success && int.TryParse(m.Groups[1].Value, out int idx))
                {
                    float? prevClock = cpuCoreData.TryGetValue(idx, out var v) ? v.clock : null;
                    cpuCoreData[idx] = (prevClock, sensor.Value);
                }
            }
            else if (sensor.SensorType == SensorType.Clock && sensor.Name.Contains("Core"))
            {
                var m = Regex.Match(sensor.Name, @"#(\d+)");
                if (m.Success && int.TryParse(m.Groups[1].Value, out int idx))
                {
                    float? prevLoad = cpuCoreData.TryGetValue(idx, out var v) ? v.load : null;
                    cpuCoreData[idx] = (sensor.Value, prevLoad);
                }
            }
        }
        else if (isGpu)
        {
            if (sensor.SensorType == SensorType.Temperature)
            {
                if (sensor.Name.Contains("Hot Spot"))
                    gpuHotspot = sensor.Value;
                else if (sensor.Name.Contains("Memory Junction"))
                {
                    // 255 is LHM's "sensor unavailable" sentinel on Blackwell — ignore it.
                    if (sensor.Value < 250)
                        gpuMemJunction = sensor.Value;
                }
                else if (gpuTemp == null)
                {
                    gpuTemp = sensor.Value;
                    gpuName = hw.Name;
                }
            }
            else if (sensor.SensorType == SensorType.Fan)
                // Discrete GPU fans (e.g. "GPU Fan 1"). Included even at 0 RPM
                // (zero-fan idle mode) so the Fans tab isn't empty on boards
                // whose motherboard SuperIO LHM can't read. No paired PWM % here.
                fans.Add(new { name = sensor.Name, rpm = (int)sensor.Value, pct = (float?)null });
            else if (sensor.SensorType == SensorType.Load)
            {
                if (gpuLoad == null && sensor.Name.Contains("Core"))
                    gpuLoad = sensor.Value;
                else if (gpuPcieLoad == null
                         && (sensor.Name.Contains("PCIe") || sensor.Name.Contains("Bus")))
                    gpuPcieLoad = sensor.Value;
            }
            else if (sensor.SensorType == SensorType.Clock)
            {
                if (gpuCoreClock == null && sensor.Name.Contains("Core"))
                    gpuCoreClock = sensor.Value;
                else if (gpuMemClock == null && sensor.Name.Contains("Memory"))
                    gpuMemClock = sensor.Value;
            }
            else if (sensor.SensorType == SensorType.Control && gpuFanPct == null
                     && sensor.Name.Contains("Fan"))
                gpuFanPct = sensor.Value;
            else if (sensor.SensorType == SensorType.Power)
            {
                // Always upgrade to a Package/Board/total sensor if found.
                // Fall back to whatever comes first (including memory sub-sensors)
                // so we never return null when any power reading exists.
                bool isTotal = sensor.Name.Contains("Package")
                            || sensor.Name == "GPU Power"
                            || sensor.Name.Contains("Board");
                if (isTotal || gpuPower == null)
                    gpuPower = sensor.Value;
            }
            else if (sensor.SensorType == SensorType.SmallData)
            {
                if (gpuMemUsed  == null && sensor.Name.Contains("Memory Used"))
                    gpuMemUsed  = sensor.Value;
                else if (gpuMemTotal == null && sensor.Name.Contains("Memory Total"))
                    gpuMemTotal = sensor.Value;
            }
        }
    }

    // Motherboard fan/temp/voltage sensors live on sub-hardware (SuperIO chip), not the MB itself
    if (isMb)
    {
        foreach (var sub in hw.SubHardware)
        {
            sub.Update();
            // Pair each fan (RPM) with its PWM control (%) by sensor index — the
            // SuperIO exposes Fan #N and Control #N on the same header. This is
            // the actual duty-cycle FanControl shows; read-only, we set nothing.
            var controlPct = new System.Collections.Generic.Dictionary<int, float>();
            foreach (var s in sub.Sensors)
                if (s.SensorType == SensorType.Control && s.Value != null)
                    controlPct[s.Index] = s.Value.Value;

            foreach (var sensor in sub.Sensors)
            {
                if (sensor.Value == null) continue;

                if (sensor.SensorType == SensorType.Fan && sensor.Value > 0)
                {
                    float? pct = controlPct.TryGetValue(sensor.Index, out var c) ? c : (float?)null;
                    fans.Add(new { name = sensor.Name, rpm = (int)sensor.Value, pct = pct });
                }
                else if (sensor.SensorType == SensorType.Temperature)
                {
                    if (sensor.Name.Contains("Chipset") && mbChipsetTemp == null)
                        mbChipsetTemp = sensor.Value;
                    else if ((sensor.Name.Contains("VRM") || sensor.Name.Contains("MOS")) && mbVrmTemp == null)
                        mbVrmTemp = sensor.Value;
                }
                else if (sensor.SensorType == SensorType.Voltage)
                {
                    // Board vendor naming varies a lot (+12V, +5V, VCore, DIMM, ...) —
                    // surface everything found rather than guessing specific rail names.
                    if (!mbVoltages.ContainsKey(sensor.Name))
                        mbVoltages[sensor.Name] = sensor.Value.Value;
                }
            }
        }
    }
}

computer.Close();

// nvidia-smi is the authoritative source for NVIDIA temp/load/VRAM. LHM 0.9.4
// misreads Blackwell (RTX 50) — the GPU temperature in particular comes out
// wrong (e.g. ~CPU temp) — so when nvidia-smi is present we prefer its GPU
// temperature outright, and use its load/VRAM to fill any gaps LHM left.
try
{
    var psi = new ProcessStartInfo
    {
        FileName               = "nvidia-smi",
        Arguments              = "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
        RedirectStandardOutput = true,
        UseShellExecute        = false,
        CreateNoWindow         = true,
    };
    using var proc = Process.Start(psi)!;
    var line = proc.StandardOutput.ReadLine();
    proc.WaitForExit(3000);
    if (line != null)
    {
        var parts = line.Split(',');
        if (parts.Length >= 4)
        {
            if (float.TryParse(parts[0].Trim(), out float smiTemp))
                gpuTemp = smiTemp;   // authoritative on NVIDIA; overrides LHM's bad Blackwell read
            if (float.TryParse(parts[1].Trim(), out float smiLoad)
                && (gpuLoad == null || gpuLoad == 0))
                gpuLoad = smiLoad;
            if (float.TryParse(parts[2].Trim(), out float smiMemUsed)
                && float.TryParse(parts[3].Trim(), out float smiMemTotal)
                && (gpuMemTotal == null || gpuMemTotal == 0))
            {
                gpuMemUsed  = smiMemUsed;
                gpuMemTotal = smiMemTotal;
            }
        }
    }
}
catch { }

var cpuCores = System.Linq.Enumerable.Select(
    System.Linq.Enumerable.OrderBy(cpuCoreData, kv => kv.Key),
    kv => new { index = kv.Key, clock = kv.Value.clock, load = kv.Value.load }
);

Console.WriteLine(JsonConvert.SerializeObject(new
{
    cpu              = cpuTemp,
    cpu_load         = cpuLoad,
    cpu_power        = cpuPower,
    cpu_voltage      = cpuVoltage,
    cpu_cores        = cpuCores,
    gpu              = gpuTemp,
    gpu_load         = gpuLoad,
    gpu_power        = gpuPower,
    gpu_mem_used     = gpuMemUsed,
    gpu_mem_total    = gpuMemTotal,
    gpu_name         = gpuName,
    gpu_hotspot      = gpuHotspot,
    gpu_mem_junction = gpuMemJunction,
    gpu_core_clock   = gpuCoreClock,
    gpu_mem_clock    = gpuMemClock,
    gpu_fan_pct      = gpuFanPct,
    gpu_pcie_load    = gpuPcieLoad,
    mb_chipset_temp  = mbChipsetTemp,
    mb_vrm_temp      = mbVrmTemp,
    mb_voltages      = mbVoltages,
    fans             = fans,
    debug_hw         = debugHw,
}));
