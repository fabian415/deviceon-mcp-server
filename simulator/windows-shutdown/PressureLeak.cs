// pressure_leak.exe - the CULPRIT of scenario 4: memory pressure that only ever grows.
//
// After --start-delay seconds it allocates --rate MB per minute and never frees any of it, until
// mem_guard.exe (the protective watchdog) shuts the machine down. install.ps1 starts it at every
// boot as SYSTEM, so after the device is woken up again the leak comes back unless someone
// disables its scheduled task: that is the "fix" the agent is expected to propose.
//
// Lessons from the first real run (DS054, 16 GB, 2026-11-19): memory that is written once and
// never touched again is paged out, so the physical memory load stayed at 30-77 % while the
// process held 40 GB and Windows grew the page file until commit ran out (OutOfMemoryException,
// heavy paging, a frozen machine, and a watchdog that never tripped). Therefore:
//   - every held page is re-written in a rolling sweep (about every --touch-sec seconds), so the
//     memory stays resident and the physical load (DeviceOn's usagePhysMem) really climbs;
//   - growth stops at --max-commit percent of the commit limit (RAM + page file), so the page
//     file is not pushed to grow and the commit level the watchdog watches stays high;
//   - after an OutOfMemoryException it waits 60 s before trying again.
//
// Safety: growth also stops at --max-load percent physical load or below --floor-mb available.
// It never tries to crash Windows. Windowless (/target:winexe); progress goes to a log file.
// Usage: pressure_leak.exe [--rate 256] [--start-delay 120] [--max-load 97] [--max-commit 95]
//                          [--floor-mb 300] [--touch-sec 20] [--chunk-mb 16] [--log <path>]
// C# 5 (compiles with the csc.exe bundled in .NET Framework 4.x). Build as x64: it needs > 4 GB.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

static class PressureLeak
{
    [StructLayout(LayoutKind.Sequential)]
    class MemoryStatusEx
    {
        public uint dwLength = (uint)Marshal.SizeOf(typeof(MemoryStatusEx));
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;   // commit limit
        public ulong ullAvailPageFile;   // commit still available
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;

        public int CommitPercent
        {
            get { return ullTotalPageFile == 0 ? 0 : (int)(100 - ullAvailPageFile * 100 / ullTotalPageFile); }
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GlobalMemoryStatusEx([In, Out] MemoryStatusEx status);

    const int PageSize = 4096;
    const int StepMs = 500;
    static string logPath;
    static int pid;

    static int Main(string[] args)
    {
        int rateMb = 256, startDelay = 120, maxLoad = 97, maxCommit = 95, floorMb = 300, touchSec = 20, chunkMb = 16;
        logPath = Path.Combine(Path.Combine(Path.GetTempPath(), "deviceon-sim"), "pressure_leak.log");
        pid = Process.GetCurrentProcess().Id;
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "--rate") rateMb = Int(args, ++i, 1, 4096);
                else if (a == "--start-delay") startDelay = Int(args, ++i, 0, 86400);
                else if (a == "--max-load") maxLoad = Int(args, ++i, 10, 99);
                else if (a == "--max-commit") maxCommit = Int(args, ++i, 10, 99);
                else if (a == "--floor-mb") floorMb = Int(args, ++i, 100, 1 << 20);
                else if (a == "--touch-sec") touchSec = Int(args, ++i, 2, 600);
                else if (a == "--chunk-mb") chunkMb = Int(args, ++i, 1, 256);
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
        using (var mutex = new Mutex(true, @"Global\DeviceOnSim.PressureLeak", out created))
        {
            if (!created)
            {
                Log("another pressure_leak instance is running; exiting");
                return 2;
            }
            Run(rateMb, startDelay, maxLoad, maxCommit, floorMb, touchSec, chunkMb);
            return 0;
        }
    }

    static void Run(int rateMb, int startDelay, int maxLoad, int maxCommit, int floorMb, int touchSec, int chunkMb)
    {
        MemoryStatusEx ms = Status();
        Log(string.Format(CultureInfo.InvariantCulture,
            "start: rate={0} MB/min after {1} s delay; stop growing at load {2}%, commit {3}% or avail < {4} MB; " +
            "RAM={5} MB, commit limit={6} MB, load={7}%, commit={8}%",
            rateMb, startDelay, maxLoad, maxCommit, floorMb, ms.ullTotalPhys >> 20, ms.ullTotalPageFile >> 20,
            ms.dwMemoryLoad, ms.CommitPercent));
        Thread.Sleep(startDelay * 1000);

        var held = new List<byte[]>();
        double chunksPerStep = (double)rateMb / chunkMb * StepMs / 60000.0;   // fractional chunks per 500 ms step
        double owed = 0;
        int touchCursor = 0;
        long lastLoggedMb = 0;
        string capReason = null;
        DateTime retryAfter = DateTime.MinValue;
        var sw = Stopwatch.StartNew();

        while (true)
        {
            long stepStart = sw.ElapsedMilliseconds;
            ms = Status();
            int slack = capReason != null ? 2 : 0;   // hysteresis: resume only 2 points below the cap
            string reason = ms.dwMemoryLoad >= maxLoad - slack ? "load " + ms.dwMemoryLoad + "%"
                          : ms.CommitPercent >= maxCommit - slack ? "commit " + ms.CommitPercent + "%"
                          : (long)(ms.ullAvailPhys >> 20) < floorMb ? "avail " + (ms.ullAvailPhys >> 20) + " MB"
                          : DateTime.UtcNow < retryAfter ? "OOM back-off"
                          : null;
            if ((reason == null) != (capReason == null))
            {
                Log(reason != null
                    ? string.Format("cap reached ({0}): holding {1} MB, load {2}%, commit {3}%",
                        reason, (long)held.Count * chunkMb, ms.dwMemoryLoad, ms.CommitPercent)
                    : string.Format("growing again from {0} MB, load {1}%, commit {2}%",
                        (long)held.Count * chunkMb, ms.dwMemoryLoad, ms.CommitPercent));
            }
            capReason = reason;

            if (reason == null)
            {
                owed += chunksPerStep;
                while (owed >= 1)
                {
                    owed -= 1;
                    try
                    {
                        byte[] block = new byte[chunkMb * 1024 * 1024];
                        Touch(block);
                        held.Add(block);
                    }
                    catch (OutOfMemoryException)
                    {
                        Log("OutOfMemoryException at " + ((long)held.Count * chunkMb) + " MB; pausing growth for 60 s");
                        retryAfter = DateTime.UtcNow.AddSeconds(60);
                        owed = 0;
                        break;
                    }
                }
            }
            else
            {
                owed = 0;   // no catch-up burst after a pause
            }

            // Rolling re-write of the held memory: each block every ~touchSec seconds, so it stays resident.
            if (held.Count > 0)
            {
                int perStep = Math.Max(1, (int)Math.Ceiling(held.Count * (double)StepMs / (touchSec * 1000.0)));
                for (int k = 0; k < perStep; k++)
                {
                    Touch(held[touchCursor]);
                    touchCursor = (touchCursor + 1) % held.Count;
                }
            }

            long heldMb = (long)held.Count * chunkMb;
            if (heldMb - lastLoggedMb >= 512)
            {
                lastLoggedMb = heldMb;
                ms = Status();
                Log(string.Format("grow: {0} MB held, load {1}%, commit {2}% of {3} MB",
                    heldMb, ms.dwMemoryLoad, ms.CommitPercent, ms.ullTotalPageFile >> 20));
            }

            long wait = StepMs - (sw.ElapsedMilliseconds - stepStart);
            if (wait > 0) Thread.Sleep((int)wait);
        }
    }

    static void Touch(byte[] block)
    {
        for (int i = 0; i < block.Length; i += PageSize) block[i]++;
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
            // logging must never kill the simulator
        }
    }
}
