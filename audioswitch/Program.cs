using System;
using System.Runtime.InteropServices;

[Guid("568b9108-44bf-40b4-9006-86afe520171f")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPolicyConfig
{
    [PreserveSig] int GetMixFormat(string d, IntPtr p);
    [PreserveSig] int GetDeviceFormat(string d, bool b, IntPtr p);
    [PreserveSig] int ResetDeviceFormat(string d);
    [PreserveSig] int SetDeviceFormat(string d, IntPtr p, IntPtr m);
    [PreserveSig] int GetProcessingPeriod(string d, bool b, IntPtr p1, IntPtr p2);
    [PreserveSig] int SetProcessingPeriod(string d, IntPtr p);
    [PreserveSig] int GetShareMode(string d, IntPtr p);
    [PreserveSig] int SetShareMode(string d, IntPtr p);
    [PreserveSig] int GetPropertyValue(string d, bool b, IntPtr k, IntPtr v);
    [PreserveSig] int SetPropertyValue(string d, bool b, IntPtr k, IntPtr v);
    [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string deviceId, uint role);
    [PreserveSig] int SetEndpointVisibility(string d, bool b);
}

[ComImport]
[Guid("294935CE-F637-4E7C-A41B-AB255460B862")]
[ClassInterface(ClassInterfaceType.None)]
class PolicyConfigClient { }

class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length < 1) return 1;
        try
        {
            var ipc = (IPolicyConfig)(new PolicyConfigClient());
            for (uint role = 0; role < 3; role++)
                ipc.SetDefaultEndpoint(args[0], role);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }
}
