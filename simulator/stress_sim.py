"""Periodic CPU load generator for the PoC. Run on the edge device.

Loads all cores for --high seconds, idles for --low seconds, forever.
Everything runs in ONE process (one PID), so the agent sees a single culprit:
hashlib releases the GIL on large buffers, so threads really use multiple cores.

Usage:
    python3 stress_sim.py --high 60 --low 120
    # distinctive process name on Linux (otherwise it shows up as "python3"):
    cp "$(command -v python3)" /tmp/cpu_hog && /tmp/cpu_hog stress_sim.py
"""

from __future__ import annotations

import argparse
import hashlib
import os
import threading
import time


def burn(stop_at: float) -> None:
    buf = os.urandom(1 << 20)
    while time.time() < stop_at:
        hashlib.sha256(buf).digest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--high", type=int, default=60, help="seconds of full load per cycle")
    ap.add_argument("--low", type=int, default=120, help="seconds idle per cycle")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    print(f"pid={os.getpid()} high={args.high}s low={args.low}s threads={args.threads}", flush=True)
    while True:
        stop_at = time.time() + args.high
        workers = [threading.Thread(target=burn, args=(stop_at,), daemon=True) for _ in range(args.threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        time.sleep(args.low)


if __name__ == "__main__":
    main()
