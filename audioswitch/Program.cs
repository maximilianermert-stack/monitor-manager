using System;
using System.Runtime.InteropServices;

// PolicyConfigClient COM class — CLSID is stable across Windows versions.
// We do NOT cast to IPolicyConfig (that IID changed on newer Windows).
// Instead we get IUnknown (always works) and call vtable[13] directly.
[ComImport]
[Guid("294935CE-F637-4E7C-A41B-AB255460B862")]
[ClassInterface(ClassInterfaceType.None)]
class PolicyConfigClient { }

// vtable: IUnknown(0-2) + GetMixFormat(3) GetDeviceFormat(4) ResetDeviceFormat(5)
//         SetDeviceFormat(6) GetProcessingPeriod(7) SetProcessingPeriod(8)
//         GetShareMode(9) SetShareMode(10) GetPropertyValue(11) SetPropertyValue(12)
//         SetDefaultEndpoint(13)
[UnmanagedFunctionPointer(CallingConvention.StdCall)]
delegate int SetDefaultEndpointFn(
    IntPtr self,
    [MarshalAs(UnmanagedType.LPWStr)] string deviceId,
    uint role);

class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length < 1)
        {
            Console.Error.WriteLine("Usage: AudioSwitch.exe <deviceId>");
            return 1;
        }

        try
        {
            var obj  = new PolicyConfigClient();
            IntPtr punk = Marshal.GetIUnknownForObject(obj);
            try
            {
                IntPtr vtable = Marshal.ReadIntPtr(punk);
                IntPtr fnPtr  = Marshal.ReadIntPtr(vtable, 13 * IntPtr.Size);
                var fn = Marshal.GetDelegateForFunctionPointer<SetDefaultEndpointFn>(fnPtr);

                for (uint role = 0; role < 3; role++)
                {
                    int hr = fn(punk, args[0], role);
                    // HRESULT: negative = failure (bit 31 set), positive = success
                    if (hr < 0)
                    {
                        Console.Error.WriteLine($"HRESULT 0x{(uint)hr:X8} role={role}");
                        return 1;
                    }
                }
                return 0;
            }
            finally
            {
                Marshal.Release(punk);
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"{ex.GetType().Name}: {ex.Message}");
            return 1;
        }
    }
}
