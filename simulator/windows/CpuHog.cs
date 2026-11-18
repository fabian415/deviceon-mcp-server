// cpu_hog.exe - periodic CPU load generator for the DeviceOn MCP PoC (Windows).
//
// Loads all cores for --high seconds, idles for --low seconds, repeat.
// Everything runs in ONE process (one PID) with a distinctive name, so the
// agent's process capture points at a single, obvious culprit.
//
// Build: build.bat   (uses the C# compiler bundled with .NET Framework 4.x; C# 5 syntax only)
// Run:   cpu_hog.exe                      -> 60 s high / 120 s low, all cores, forever
//        cpu_hog.exe --high 60 --low 120 --threads 4 --cycles 10
// Stop:  Ctrl+C, or: taskkill /im cpu_hog.exe /f

using System;
using System.Diagnostics;
using System.Threading;

internal static class CpuHog
{
    private static volatile bool _stopping;
    private static double _sink; // keeps the JIT from optimizing the busy loop away

    private static int Main(string[] args)
    {
        int high = 60, low = 120, threads = Environment.ProcessorCount, cycles = 0;
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant();
                if (a == "-h" || a == "--help" || a == "/?") { PrintUsage(); return 0; }
                if (i + 1 >= args.Length) throw new ArgumentException("missing value for " + args[i]);
                int v = int.Parse(args[++i]);
                if (a == "--high") high = v;
                else if (a == "--low") low = v;
                else if (a == "--threads") threads = v;
                else if (a == "--cycles") cycles = v;
                else throw new ArgumentException("unknown option " + a);
            }
            if (high <= 0 || low < 0 || threads <= 0 || cycles < 0) throw new ArgumentException("values must be positive");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("error: " + ex.Message);
            PrintUsage();
            return 2;
        }

        Console.CancelKeyPress += delegate(object s, ConsoleCancelEventArgs e)
        {
            e.Cancel = true; // let the loops finish cleanly
            _stopping = true;
            Log("Ctrl+C received, stopping...");
        };

        Log(string.Format("cpu_hog started  pid={0}  high={1}s  low={2}s  period={3}s  threads={4}/{5} cores  cycles={6}",
            Process.GetCurrentProcess().Id, high, low, high + low, threads, Environment.ProcessorCount,
            cycles == 0 ? "infinite" : cycles.ToString()));

        for (int c = 1; !_stopping && (cycles == 0 || c <= cycles); c++)
        {
            Log(string.Format("cycle {0}: HIGH for {1}s", c, high));
            Burn(high, threads);
            if (_stopping) break;
            Log(string.Format("cycle {0}: LOW  for {1}s", c, low));
            Idle(low);
        }
        Log("cpu_hog exited");
        return 0;
    }

    private static void Burn(int seconds, int threadCount)
    {
        DateTime until = DateTime.UtcNow.AddSeconds(seconds);
        Thread[] workers = new Thread[threadCount];
        for (int i = 0; i < threadCount; i++)
        {
            workers[i] = new Thread(delegate()
            {
                double x = 0;
                while (!_stopping && DateTime.UtcNow < until)
                {
                    for (int k = 1; k < 200000; k++) x += Math.Sqrt(k) * Math.Sin(k);
                }
                _sink += x;
            });
            workers[i].IsBackground = true;
            workers[i].Start();
        }
        foreach (Thread t in workers) t.Join();
    }

    private static void Idle(int seconds)
    {
        DateTime until = DateTime.UtcNow.AddSeconds(seconds);
        while (!_stopping && DateTime.UtcNow < until) Thread.Sleep(200);
    }

    private static void Log(string msg)
    {
        Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + msg);
    }

    private static void PrintUsage()
    {
        Console.WriteLine("usage: cpu_hog.exe [--high SEC] [--low SEC] [--threads N] [--cycles N]");
        Console.WriteLine("  --high     seconds of full load per cycle   (default 60)");
        Console.WriteLine("  --low      seconds idle per cycle           (default 120)");
        Console.WriteLine("  --threads  busy threads                     (default = logical cores)");
        Console.WriteLine("  --cycles   number of cycles, 0 = forever    (default 0)");
    }
}
