using System;
using System.Diagnostics;
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
float? cpuLoad     = null;
float? cpuPower    = null;
float? gpuTemp     = null;
float? gpuLoad     = null;
float? gpuPower    = null;
float? gpuMemUsed  = null;  // MB
float? gpuMemTotal = null;  // MB
string gpuName     = "";

var fans = new System.Collections.Generic.List<object>();

foreach (var hw in computer.Hardware)
{
    hw.Update();

    bool isCpu = hw.HardwareType == HardwareType.Cpu;
    bool isGpu = hw.HardwareType is HardwareType.GpuNvidia
                                 or HardwareType.GpuAmd
                                 or HardwareType.GpuIntel;
    bool isMb  = hw.HardwareType == HardwareType.Motherboard;

    if (!isCpu && !isGpu && !isMb) continue;

    foreach (var sensor in hw.Sensors)
    {
        if (sensor.Value == null) continue;

        if (isCpu)
        {
            if (sensor.SensorType == SensorType.Temperature)
            {
                if (sensor.Name.Contains("Package") || sensor.Name.Contains("Average"))
                    cpuTemp = sensor.Value;
                else if (cpuTemp == null)
                    cpuTemp = sensor.Value;
            }
            else if (sensor.SensorType == SensorType.Load && sensor.Name == "CPU Total")
                cpuLoad = sensor.Value;
            else if (sensor.SensorType == SensorType.Power && cpuPower == null
                     && (sensor.Name.Contains("Package") || sensor.Name.Contains("CPU")))
                cpuPower = sensor.Value;
        }
        else if (isGpu)
        {
            if (sensor.SensorType == SensorType.Temperature && gpuTemp == null)
            {
                gpuTemp = sensor.Value;
                gpuName = hw.Name;
            }
            else if (sensor.SensorType == SensorType.Load && gpuLoad == null
                     && sensor.Name.Contains("Core"))
                gpuLoad = sensor.Value;
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
        else if (isMb)
        {
            if (sensor.SensorType == SensorType.Fan && sensor.Value > 0)
                fans.Add(new { name = sensor.Name, rpm = (int)sensor.Value });
        }
    }
}

computer.Close();

// nvidia-smi fallback for GPU load and VRAM (LHM 0.9.4 lacks Blackwell support)
if (gpuLoad == null || gpuLoad == 0 || gpuMemTotal == null || gpuMemTotal == 0)
{
    try
    {
        var psi = new ProcessStartInfo
        {
            FileName               = "nvidia-smi",
            Arguments              = "--query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits",
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
            if (parts.Length >= 3
                && float.TryParse(parts[0].Trim(), out float smiLoad)
                && float.TryParse(parts[1].Trim(), out float smiMemUsed)
                && float.TryParse(parts[2].Trim(), out float smiMemTotal))
            {
                gpuLoad     = smiLoad;
                gpuMemUsed  = smiMemUsed;
                gpuMemTotal = smiMemTotal;
            }
        }
    }
    catch { }
}

Console.WriteLine(JsonConvert.SerializeObject(new
{
    cpu           = cpuTemp,
    cpu_load      = cpuLoad,
    cpu_power     = cpuPower,
    gpu           = gpuTemp,
    gpu_load      = gpuLoad,
    gpu_power     = gpuPower,
    gpu_mem_used  = gpuMemUsed,
    gpu_mem_total = gpuMemTotal,
    gpu_name      = gpuName,
    fans          = fans,
}));
