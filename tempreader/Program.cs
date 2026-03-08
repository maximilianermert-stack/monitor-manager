using LibreHardwareMonitor.Hardware;
using Newtonsoft.Json;

var computer = new Computer
{
    IsCpuEnabled = true,
    IsGpuEnabled = true,
};
computer.Open();

float? cpuTemp  = null;
float? gpuTemp  = null;
string gpuName  = "";

foreach (var hw in computer.Hardware)
{
    hw.Update();

    bool isCpu = hw.HardwareType == HardwareType.Cpu;
    bool isGpu = hw.HardwareType is HardwareType.GpuNvidia
                                 or HardwareType.GpuAmd
                                 or HardwareType.GpuIntel;

    foreach (var sensor in hw.Sensors)
    {
        if (sensor.SensorType != SensorType.Temperature || sensor.Value == null)
            continue;

        if (isCpu)
        {
            // Prefer package/average, fall back to first core
            if (sensor.Name.Contains("Package") || sensor.Name.Contains("Average"))
                cpuTemp = sensor.Value;
            else if (cpuTemp == null)
                cpuTemp = sensor.Value;
        }
        else if (isGpu && gpuTemp == null)
        {
            gpuTemp = sensor.Value;
            gpuName = hw.Name;
        }
    }
}

computer.Close();

Console.WriteLine(JsonConvert.SerializeObject(new
{
    cpu      = cpuTemp,
    gpu      = gpuTemp,
    gpu_name = gpuName,
}));
