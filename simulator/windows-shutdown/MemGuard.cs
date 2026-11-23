// mem_guard.exe - the protective WATCHDOG of scenario 4 (it presses the button, it is not the cause).
//
// Many industrial PCs run a supervisor that powers the machine off cleanly when it is about to
// run out of memory, rather than letting the HMI/PLC software freeze. mem_guard does that:
// every --poll seconds it reads the physical memory load AND the commit charge (committed memory
// as a percent of the commit limit = RAM + page file). When either stays at or above its threshold
// (--threshold / --commit-threshold) for --sustain seconds, it
//   1. writes a Warning to the Application event log (source "DeviceOnSim", event id 3001)
//      with the top processes by private memory at that moment,
//   2. if --arm is given, calls InitiateSystemShutdownEx (power off, apps force-closed,
//      --grace seconds of warning, reason "Application: Unstable"). Event 1074 then names
//      mem_guard.exe as the process that initiated the shutdown.
// Without --arm it only logs "DRY RUN" and keeps watching (the default, for safe testing).
//
// A full power-off (S5) is what Wake-on-LAN can recover from; a crash or power cut is not.
//
// Why commit too: on the first real run (DS054, 2026-11-19) the leak's pages were paged out, so the
// physical load stayed below 80 % while commit ran out and the machine froze; a physical-only
// watchdog never tripped. Running out of commit is what "out of memory" means on Windows.
// A heartbeat line is logged every 5 minutes so the log shows what the guard saw.
//
// Usage: mem_guard.exe [--threshold 90] [--commit-threshold 90] [--sustain 60] [--poll 5] [--grace 30]
//                      [--arm] [--log <path>]
// C# 5 (csc.exe from .NET Framework 4.x).

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

static class MemGuard
{
    [StructLayout(LayoutKind.Sequential)]
    class MemoryStatusEx
    {
        public uint dwLength = (uint)Marshal.SizeOf(typeof(MemoryStatusEx));
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;

        public int CommitPercent
        {
            get { return ullTotalPageFile == 0 ? 0 : (int)(100 - ullAvailPageFile * 100 / ullTotalPageFile); }
        }
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct TokenPrivileges
    {
        public uint PrivilegeCount;
        public long Luid;
        public uint Attributes;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GlobalMemoryStatusEx([In, Out] MemoryStatusEx status);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool LookupPrivilegeValue(string system, string name, out long luid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool AdjustTokenPrivileges(IntPtr token, bool disableAll, ref TokenPrivileges newState,
                                             uint len, IntPtr prev, IntPtr prevLen);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool InitiateSystemShutdownEx(string machine, string message, uint timeout,
                                                bool forceAppsClosed, bool reboot, uint reason);

    [DllImport("kernel32.dll")]
    static extern bool CloseHandle(IntPtr handle);

    const uint TOKEN_ADJUST_PRIVILEGES = 0x20, TOKEN_QUERY = 0x8, SE_PRIVILEGE_ENABLED = 0x2;
    // SHTDN_REASON_MAJOR_APPLICATION | SHTDN_REASON_MINOR_UNSTABLE (unplanned): "Application: Unstable"
    const uint ShutdownReason = 0x00040000 | 0x00000006;
    const string EventSource = "DeviceOnSim";
    const int EventId = 3001;

    static string logPath;
    static int pid;

    static int Main(string[] args)
    {
        int threshold = 90, commitThreshold = 90, sustain = 60, poll = 5, grace = 30;
        bool arm = false;
        logPath = Path.Combine(Path.Combine(Path.GetTempPath(), "deviceon-sim"), "mem_guard.log");
        pid = Process.GetCurrentProcess().Id;
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "--threshold") threshold = Int(args, ++i, 50, 99);
                else if (a == "--commit-threshold") commitThreshold = Int(args, ++i, 50, 99);
                else if (a == "--sustain") sustain = Int(args, ++i, 5, 3600);
                else if (a == "--poll") poll = Int(args, ++i, 1, 60);
                else if (a == "--grace") grace = Int(args, ++i, 0, 600);
                else if (a == "--arm") arm = true;
                else if (a == "--log") logPath = args[++i];
                else throw new ArgumentException("unknown option " + a);
            }
        }
        catch (Exception ex)
        {
            Log("bad arguments: " + ex.Message);
            return 1;
        }

        bool created;
        using (var mutex = new Mutex(true, @"Global\DeviceOnSim.MemGuard", out created))
        {
            if (!created)
            {
                Log("another mem_guard instance is running; exiting");
                return 2;
            }
            MemoryStatusEx ms0 = Status();
            Log(string.Format("start: load >= {0}% or commit >= {1}% for {2} s (poll {3} s), grace {4} s, {5}; " +
                "now load {6}%, commit {7}% of {8} MB",
                threshold, commitThreshold, sustain, poll, grace, arm ? "ARMED (will power off)" : "DRY RUN (logs only)",
                ms0.dwMemoryLoad, ms0.CommitPercent, ms0.ullTotalPageFile >> 20));
            Watch(threshold, commitThreshold, sustain, poll, grace, arm);
            return 0;
        }
    }

    static string Reading(MemoryStatusEx ms)
    {
        return string.Format(CultureInfo.InvariantCulture, "load {0}% (avail {1} MB of {2} MB), commit {3}% of {4} MB",
            ms.dwMemoryLoad, ms.ullAvailPhys >> 20, ms.ullTotalPhys >> 20, ms.CommitPercent, ms.ullTotalPageFile >> 20);
    }

    static void Watch(int threshold, int commitThreshold, int sustain, int poll, int grace, bool arm)
    {
        DateTime? above = null;
        DateTime nextBeat = DateTime.UtcNow.AddMinutes(5);
        while (true)
        {
            MemoryStatusEx ms = Status();
            if (DateTime.UtcNow >= nextBeat)
            {
                Log("heartbeat: " + Reading(ms));
                nextBeat = DateTime.UtcNow.AddMinutes(5);
            }
            if (ms.dwMemoryLoad >= threshold || ms.CommitPercent >= commitThreshold)
            {
                if (above == null)
                {
                    above = DateTime.UtcNow;
                    Log(string.Format("over threshold: {0}; shutting down if it lasts {1} s", Reading(ms), sustain));
                }
                else if ((DateTime.UtcNow - above.Value).TotalSeconds >= sustain)
                {
                    Trip(ms, threshold, commitThreshold, sustain, grace, arm);
                    if (arm) return;          // the machine is going down
                    above = null;             // dry run: re-arm the timer and keep watching
                    Thread.Sleep(60000);
                }
            }
            else if (above != null)
            {
                Log("back below thresholds: " + Reading(ms) + "; timer reset");
                above = null;
            }
            Thread.Sleep(poll * 1000);
        }
    }

    static void Trip(MemoryStatusEx ms, int threshold, int commitThreshold, int sustain, int grace, bool arm)
    {
        string top = TopProcesses(5);
        string summary = string.Format(CultureInfo.InvariantCulture,
            "MemGuard: memory over limit (load >= {0}% or commit >= {1}%) for {2} s: {3}. Top private memory: {4}",
            threshold, commitThreshold, sustain, Reading(ms), top);
        string what = arm ? string.Format("Initiating protective power-off in {0} s.", grace)
                          : "DRY RUN: not shutting down (start with --arm to power off).";
        Log(summary + " " + what);
        WriteEvent(summary + " " + what);
        if (!arm) return;

        // InitiateSystemShutdownEx messages are limited to 512 characters.
        string message = (summary + " " + what);
        if (message.Length > 500) message = message.Substring(0, 500);
        try
        {
            EnableShutdownPrivilege();
            if (!InitiateSystemShutdownEx(null, message, (uint)grace, true, false, ShutdownReason))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            Log("InitiateSystemShutdownEx accepted");
        }
        catch (Exception ex)
        {
            Log("InitiateSystemShutdownEx failed (" + ex.Message + "); falling back to shutdown.exe");
            string comment = message.Replace("\"", "'");
            if (comment.Length > 400) comment = comment.Substring(0, 400);
            Process.Start(new ProcessStartInfo("shutdown.exe",
                string.Format("/s /f /t {0} /d u:4:6 /c \"{1}\"", grace, comment))
            { UseShellExecute = false, CreateNoWindow = true });
        }
    }

    static string TopProcesses(int n)
    {
        var rows = new List<KeyValuePair<string, long>>();
        foreach (Process p in Process.GetProcesses())
        {
            try { rows.Add(new KeyValuePair<string, long>(p.ProcessName + ".exe(" + p.Id + ")", p.PrivateMemorySize64)); }
            catch (Exception) { }
            finally { p.Dispose(); }
        }
        return string.Join(", ", rows.OrderByDescending(r => r.Value).Take(n)
            .Select(r => string.Format(CultureInfo.InvariantCulture, "{0} {1} MB", r.Key, r.Value >> 20)).ToArray());
    }

    static void WriteEvent(string message)
    {
        // install.ps1 registers the source. SourceExists() scans every log including Security,
        // which a non-admin cannot read, so write first and only register on failure.
        try
        {
            EventLog.WriteEntry(EventSource, message, EventLogEntryType.Warning, EventId);
            return;
        }
        catch (Exception)
        {
        }
        try
        {
            EventLog.CreateEventSource(EventSource, "Application");
            EventLog.WriteEntry(EventSource, message, EventLogEntryType.Warning, EventId);
        }
        catch (Exception ex)
        {
            Log("could not write the event log entry (run install.ps1 as administrator to register source '"
                + EventSource + "'): " + ex.Message);
        }
    }

    static void EnableShutdownPrivilege()
    {
        IntPtr token;
        if (!OpenProcessToken(Process.GetCurrentProcess().Handle, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, out token))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            var tp = new TokenPrivileges { PrivilegeCount = 1, Attributes = SE_PRIVILEGE_ENABLED };
            if (!LookupPrivilegeValue(null, "SeShutdownPrivilege", out tp.Luid))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            if (!AdjustTokenPrivileges(token, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        finally
        {
            CloseHandle(token);
        }
    }

    static MemoryStatusEx Status()
    {
        var ms = new MemoryStatusEx();
        if (!GlobalMemoryStatusEx(ms)) throw new InvalidOperationException("GlobalMemoryStatusEx failed");
        return ms;
    }

    static int Int(string[] args, int i, int min, int max)
    {
        return Math.Min(max, Math.Max(min, int.Parse(args[i], CultureInfo.InvariantCulture)));
    }

    static void Log(string msg)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(logPath)));
            File.AppendAllText(logPath, string.Format(CultureInfo.InvariantCulture,
                "{0:yyyy-MM-dd HH:mm:ss} pid={1} {2}{3}", DateTime.Now, pid, msg, Environment.NewLine));
        }
        catch (Exception)
        {
        }
    }
}
