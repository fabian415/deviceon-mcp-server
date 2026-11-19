// hang_app.exe - "Not Responding" window simulator for the DeviceOn MCP PoC (Windows).
//
// Shows a small window with a counter that ticks every second. After --after seconds (or when
// the button is clicked) the UI thread deadlocks with a worker thread:
//
//   worker thread : takes the gate, then Control.Invoke(...) -> waits for the UI thread to run it
//   UI thread     : waits for the gate                      -> held by the worker, forever
//
// Both threads sit in kernel waits, so CPU stays ~0% and memory stays flat. Because the UI thread
// no longer pumps messages, Windows marks the window "Not Responding" after ~5 s (IsHungAppWindow,
// Process.Responding == false). The waits are ordinary user-mode waits, so taskkill /f or
// TerminateProcess ends the process normally.
//
// Why the gate is a kernel semaphore waited via P/Invoke instead of lock(): CLR waits on an STA
// thread (Monitor.Enter, WaitOne) may pump some messages, which can make the hang flaky. A raw
// WaitForSingleObject never pumps, so the deadlock is deterministic.
//
// Must run in the logged-on user's desktop session (not Session 0 / as a service), otherwise
// nobody sees the window and Windows has no visible window to mark as hung.
//
// Build: build.bat   (csc.exe bundled with .NET Framework 4.x; C# 5 syntax only)
// Run:   hang_app.exe                       -> deadlock 30 s after start
//        hang_app.exe --after 60            -> deadlock after 60 s
//        hang_app.exe --after 0             -> only when the button is clicked
// Stop:  taskkill /im hang_app.exe /f
// Log:   %TEMP%\deviceon-sim\hang_app.log (PID, start time, deadlock time) - override with --log

using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

internal static class HangApp
{
    [STAThread]
    private static int Main(string[] args)
    {
        string mode = "deadlock";
        int after = 30;
        string log = Path.Combine(Path.Combine(Path.GetTempPath(), "deviceon-sim"), "hang_app.log");
        try
        {
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant();
                if (a == "-h" || a == "--help" || a == "/?") { ShowUsage(null); return 0; }
                if (i + 1 >= args.Length) throw new ArgumentException("missing value for " + args[i]);
                string v = args[++i];
                if (a == "--mode") mode = v.ToLowerInvariant();
                else if (a == "--after") after = int.Parse(v, CultureInfo.InvariantCulture);
                else if (a == "--log") log = v;
                else throw new ArgumentException("unknown option " + args[i - 1]);
            }
            if (mode != "deadlock") throw new ArgumentException("unsupported --mode " + mode + " (only 'deadlock' for now)");
            if (after < 0) throw new ArgumentException("--after must be >= 0");
        }
        catch (Exception ex)
        {
            ShowUsage("error: " + ex.Message);
            return 2;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new HangForm(after, new Logger(log)));
        return 0;
    }

    private static void ShowUsage(string error)
    {
        string text =
            (error != null ? error + "\r\n\r\n" : "") +
            "hang_app.exe [--mode deadlock] [--after 30] [--log <path>]\r\n\r\n" +
            "--mode   deadlock: UI thread and a worker thread wait on each other forever\r\n" +
            "--after  seconds before the hang starts (0 = only via the button)\r\n" +
            "--log    log file (default %TEMP%\\deviceon-sim\\hang_app.log)";
        MessageBox.Show(text, "hang_app", MessageBoxButtons.OK, error != null ? MessageBoxIcon.Error : MessageBoxIcon.Information);
    }
}

internal sealed class Logger
{
    private readonly string _path;

    public Logger(string path)
    {
        _path = path;
        try { Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))); }
        catch (Exception) { /* logging is best effort */ }
    }

    public void Write(string message)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) +
                      " pid=" + Process.GetCurrentProcess().Id + " " + message + Environment.NewLine;
        try { File.AppendAllText(_path, line); }
        catch (Exception) { /* logging is best effort */ }
    }
}

internal sealed class HangForm : Form
{
    private const uint INFINITE = 0xFFFFFFFF;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

    private readonly int _after;
    private readonly Logger _log;
    private readonly DateTime _startedAt = DateTime.Now;
    private readonly Label _counter = new Label();
    private readonly Label _status = new Label();
    private readonly Button _hangNow = new Button();
    private readonly System.Windows.Forms.Timer _timer = new System.Windows.Forms.Timer();
    private int _ticks;
    private bool _hanging;

    // Kernel objects so both sides can wait with WaitForSingleObject (never pumps messages).
    private readonly Semaphore _gate = new Semaphore(1, 1);
    private readonly ManualResetEvent _workerHoldsGate = new ManualResetEvent(false);

    public HangForm(int after, Logger log)
    {
        _after = after;
        _log = log;
        int pid = Process.GetCurrentProcess().Id;

        Text = "hang_app (PID " + pid + ")";
        ClientSize = new Size(380, 170);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;

        _counter.Font = new Font(FontFamily.GenericMonospace, 28f, FontStyle.Bold);
        _counter.TextAlign = ContentAlignment.MiddleCenter;
        _counter.SetBounds(10, 10, 360, 60);

        _status.TextAlign = ContentAlignment.MiddleCenter;
        _status.SetBounds(10, 75, 360, 40);

        _hangNow.Text = "Deadlock now";
        _hangNow.SetBounds(130, 122, 120, 32);
        _hangNow.Click += delegate { StartDeadlock("button"); };

        Controls.Add(_counter);
        Controls.Add(_status);
        Controls.Add(_hangNow);

        _timer.Interval = 1000;
        _timer.Tick += OnTick;
        _timer.Start();
        Render();

        _log.Write("started mode=deadlock after=" + (_after > 0 ? _after + "s" : "button-only"));
    }

    private void OnTick(object sender, EventArgs e)
    {
        _ticks++;
        Render();
        if (_after > 0 && !_hanging && (DateTime.Now - _startedAt).TotalSeconds >= _after)
            StartDeadlock("timer");
    }

    private void Render()
    {
        _counter.Text = _ticks.ToString(CultureInfo.InvariantCulture);
        if (_hanging) return;
        if (_after > 0)
        {
            int left = Math.Max(0, _after - (int)(DateTime.Now - _startedAt).TotalSeconds);
            _status.Text = "Responsive. Deadlock in " + left + " s.\r\nThe counter freezes when the UI thread hangs.";
        }
        else
        {
            _status.Text = "Responsive. Click the button to deadlock.\r\nThe counter freezes when the UI thread hangs.";
        }
    }

    // Runs on the UI thread and never returns.
    private void StartDeadlock(string trigger)
    {
        if (_hanging) return;
        _hanging = true;
        _status.Text = "DEADLOCKED (" + trigger + ") at " + DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        _status.Refresh();   // paint the final state before we stop pumping
        _log.Write("deadlock starting trigger=" + trigger);

        Thread worker = new Thread(WorkerBody);
        worker.IsBackground = true;
        worker.Name = "deadlock-worker";
        worker.Start();

        // 1) wait until the worker owns the gate
        WaitForSingleObject(_workerHoldsGate.SafeWaitHandle.DangerousGetHandle(), INFINITE);
        _log.Write("deadlock: worker holds the gate; UI thread now waits for it (forever)");
        // 2) wait for the gate the worker will only release after the UI thread runs its Invoke
        WaitForSingleObject(_gate.SafeWaitHandle.DangerousGetHandle(), INFINITE);

        _log.Write("unexpected: UI thread got the gate");   // unreachable
    }

    private void WorkerBody()
    {
        WaitForSingleObject(_gate.SafeWaitHandle.DangerousGetHandle(), INFINITE);
        try
        {
            _workerHoldsGate.Set();
            // Synchronously marshal to the UI thread, which is blocked waiting for _gate.
            Invoke((MethodInvoker)delegate { _status.Text = "unreachable"; });
        }
        finally
        {
            _gate.Release();
        }
    }
}
