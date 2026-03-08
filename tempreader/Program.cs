using System;
using LibreHardwareMonitor.Hardware;
using Newtonsoft.Json;

var computer = new Computer
{
    IsCpuEnabled = true,
    IsGpuEnabled = true,
};
computer.Open();

float? cpuTemp  = null;
float? cpuLoad  = null;
float? cpuPower = null;
float? gpuTemp  = null;
float? gpuLoad  = null;
float? gpuPower = null;
string gpuName  = "";

foreach (var hw in computer.Hardware)
{
    hw.Update();

    bool isCpu = hw.HardwareType == HardwareType.Cpu;
    bool isGpu = hw.HardwareType is HardwareType.GpuNvidia
                                 or HardwareType.GpuAmd
                                 or HardwareType.GpuIntel;

    if (!isCpu && !isGpu) continue;

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
            else if (sensor.SensorType == SensorType.Power && gpuPower == null)
                gpuPower = sensor.Value;
        }
    }
}

computer.Close();

Console.WriteLine(JsonConvert.SerializeObject(new
{
    cpu       = cpuTemp,
    cpu_load  = cpuLoad,
    cpu_power = cpuPower,
    gpu       = gpuTemp,
    gpu_load  = gpuLoad,
    gpu_power = gpuPower,
    gpu_name  = gpuName,
}));
