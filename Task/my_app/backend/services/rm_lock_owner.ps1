param(
    [string]$Path
)
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public class RmLock {
    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    public static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, string strSessionKey);

    [DllImport("rstrtmgr.dll")]
    public static extern int RmEndSession(uint dwSessionHandle);

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    public static extern int RmRegisterResources(uint dwSessionHandle, uint nFiles, string[] rgsFilenames, uint nApplications, IntPtr rgApplications, uint nServices, IntPtr rgServices);

    [DllImport("rstrtmgr.dll")]
    public static extern int RmGetList(uint dwSessionHandle, out uint pnProcInfoNeeded, ref uint pnProcInfo, [In, Out] RM_PROCESS_INFO[] rgAffectedApps, out uint lpdwRebootReasons);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct RM_UNIQUE_PROCESS {
        public int dwProcessId;
        public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct RM_PROCESS_INFO {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)]
        public string strServiceShortName;
        public int ApplicationType;
        public uint AppStatus;
        public int TSSessionId;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)]
        public string strAppName2;
    }

    public static List<string> GetOwners(string path) {
        List<string> result = new List<string>();
        uint session = 0;
        string key = Guid.NewGuid().ToString();
        int hr = RmStartSession(out session, 0, key);
        if (hr != 0) return result;
        try {
            string[] files = new string[] { path };
            hr = RmRegisterResources(session, 1, files, 0, IntPtr.Zero, 0, IntPtr.Zero);
            if (hr != 0) return result;
            uint needed = 0;
            uint total = 0;
            RM_PROCESS_INFO[] infos = new RM_PROCESS_INFO[0];
            uint reasons = 0;
            hr = RmGetList(session, out needed, ref total, infos, out reasons);
            if (needed == 0) return result;
            infos = new RM_PROCESS_INFO[needed];
            hr = RmGetList(session, out needed, ref total, infos, out reasons);
            if (hr != 0) return result;
            for (int i = 0; i < total; i++) {
                result.Add(infos[i].Process.dwProcessId + "|" + infos[i].strAppName);
            }
        } finally {
            RmEndSession(session);
        }
        return result;
    }
}
'@

$owners = [RmLock]::GetOwners($Path)
if ($owners.Count -eq 0) {
    Write-Output "NO_OWNER"
} else {
    foreach ($o in $owners) { Write-Output $o }
}
