// mem_leak.exe - memory-growth simulator meant to be launched by Windows Task Scheduler.
//
// One run: grow the working set step by step up to a target, hold it, then exit (which
// releases everything). install.ps1 schedules it every N minutes, so DeviceOn sees a
// saw-tooth on "System Monitor Info / usagePhysMem" and every run is a NEW PID.
//
// Safety: the target is capped by --max-mb AND --max-pct of physical RAM, and growth stops
// early when available RAM drops below --floor-pct. Task Scheduler also kills the run after
// its ExecutionTimeLimit.
//
// Built as a windowless exe (/target:winexe); progress goes to a log file
// (default %TEMP%\deviceon-sim\mem_leak.log).
//
// Usage: mem_leak.exe [--grow 120] [--hold 30] [--max-mb 2048] [--max-pct 40]
//                     [--floor-pct 15] [--chunk-mb 16] [--log <path>]
// C# 5 (compiles with the csc.exe bundled in .NET Framework 4.x).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

static class MemLeak
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
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GlobalMemoryStatusEx([In, Out] MemoryStatusEx status);

    const int PageSize = 4096;
    static string logPath;
    static int pid;

    static int Main(string[] args)
    {
        int growSec = 120, holdSec = 30, maxMb = 2048, maxPct = 40, floorPct = 15, chunkMb = 16;
        logPath = Path.Combine(Path.Combine(Path.GetTempPath(), "deviceon-sim"), "mem_leak.log");
        pid = Process.GetCurrentProcess().Id;

        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "--grow") growSec = Int(args, ++i, 1);
                else if (a == "--hold") holdSec = Int(args, ++i, 0);
                else if (a == "--max-mb") maxMb = Int(args, ++i, 16);
                else if (a == "--max-pct") maxPct = Math.Min(Int(args, ++i, 1), 80);
                else if (a == "--floor-pct") floorPct = Math.Min(Int(args, ++i, 5), 90);
                else if (a == "--chunk-mb") chunkMb = Math.Min(Int(args, ++i, 1), 256);
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
        using (var mutex = new Mutex(true, @"Local\DeviceOnSim.MemLeak", out created))
        {
            if (!created)
            {
                Log("another mem_leak instance is running; exiting");
                return 2;
            }
            return Run(growSec, holdSec, maxMb, maxPct, floorPct, chunkMb);
        }
    }

    static int Run(int growSec, int holdSec, int maxMb, int maxPct, int floorPct, int chunkMb)
    {
        MemoryStatusEx ms = Status();
        long totalMb = (long)(ms.ullTotalPhys / (1024 * 1024));
        long targetMb = Math.Min(maxMb, totalMb * maxPct / 100);
        long floorMb = totalMb * floorPct / 100;
        int chunks = (int)Math.Max(1, targetMb / chunkMb);
        int delayMs = growSec * 1000 / chunks;

        Log(string.Format(CultureInfo.InvariantCulture,
            "start: target={0} MB in {1} s ({2} x {3} MB), hold={4} s, total RAM={5} MB, load={6}%",
            (long)chunks * chunkMb, growSec, chunks, chunkMb, holdSec, totalMb, ms.dwMemoryLoad));

        var held = new List<byte[]>(chunks);
        var sw = Stopwatch.StartNew();
        int lastDecile = 0;
        string stopReason = "target reached";
        for (int c = 0; c < chunks; c++)
        {
            long availMb = (long)(Status().ullAvailPhys / (1024 * 1024));
            if (availMb < floorMb)
            {
                stopReason = string.Format("available RAM {0} MB below floor {1} MB", availMb, floorMb);
                break;
            }
            try
            {
                byte[] block = new byte[chunkMb * 1024 * 1024];
                for (int i = 0; i < block.Length; i += PageSize) block[i] = 1; // commit every page
                held.Add(block);
            }
            catch (OutOfMemoryException)
            {
                stopReason = "OutOfMemoryException";
                break;
            }

            int decile = (c + 1) * 10 / chunks;
            if (decile > lastDecile)
            {
                lastDecile = decile;
                Log(string.Format("grow: {0} MB held ({1}%), system load {2}%",
                    (long)held.Count * chunkMb, decile * 10, Status().dwMemoryLoad));
            }

            long wait = (long)(c + 1) * delayMs - sw.ElapsedMilliseconds;
            if (wait > 0) Thread.Sleep((int)wait);
        }

        Log(string.Format("peak: {0} MB held ({1}), system load {2}%; holding {3} s",
            (long)held.Count * chunkMb, stopReason, Status().dwMemoryLoad, holdSec));
        Thread.Sleep(holdSec * 1000);
        GC.KeepAlive(held);
        Log("exit: memory released");
        return 0;
    }

    static MemoryStatusEx Status()
    {
        var ms = new MemoryStatusEx();
        if (!GlobalMemoryStatusEx(ms)) throw new InvalidOperationException("GlobalMemoryStatusEx failed");
        return ms;
    }

    static int Int(string[] args, int i, int min)
    {
        return Math.Max(min, int.Parse(args[i], CultureInfo.InvariantCulture));
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
            // logging must never kill the simulator
        }
    }
}
