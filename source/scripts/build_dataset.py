"""
build_dataset.py
----------------
Lee manifest.csv y construye el dataset.
Reanudable: salta entradas cuyo destino ya existe.

ejecutar como Administrador (WinDivert necesita permisos).
"""

import csv
import ctypes
import ctypes.wintypes
import json
import shutil
import subprocess
import sys
import time
import threading
import random
from pathlib import Path

# ─── Rutas ───────────────────────────────────────────────────────────────────
MANIFEST   = Path(r"\source\scripts\manifest.csv")
WINDIVERT_DLL = Path(r"\WinDivert\WinDivert.dll")
OUTPUT_DIR = Path(r"\source\data")
VIDEOS_DIR = Path(r"\videos")

# ─── Parámetros ──────────────────────────────────────────────────────────────
UDP_PORT = 5004

# ─── Niveles de corrupción ────────────────────────────────────────────────────
# (drop_chance%)
LEVELS = {
    "level1":  0.6,
    "level2":  2.0,
    "level3": 15.0,
}

# ─── WinDivert constants ──────────────────────────────────────────────────────
WINDIVERT_LAYER_NETWORK = 0
WINDIVERT_FLAG_DROP     = 4
INVALID_HANDLE_VALUE    = ctypes.wintypes.HANDLE(-1).value


# ─── WinDivert wrapper ────────────────────────────────────────────────────────

class WinDivertDropper:
    """
    Drops a configurable percentage of outbound UDP packets on a given port.
    - drop_percent == 100  →  opens handle with WINDIVERT_FLAG_DROP (zero-copy fast path)
    - drop_percent <  100  →  recv loop that re-injects packets probabilistically
    """

    def __init__(self, port: int, drop_percent: float):
        self.port         = port
        self.drop_percent = drop_percent
        self._handle      = None
        self._thread      = None
        self._stop_event  = threading.Event()
        self._lib         = ctypes.WinDLL(str(WINDIVERT_DLL))
        self._configure_api()

    def _configure_api(self):
        lib = self._lib

        # WinDivertOpen
        lib.WinDivertOpen.restype  = ctypes.wintypes.HANDLE
        lib.WinDivertOpen.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int16,
            ctypes.c_uint64,
        ]

        # WinDivertRecv
        lib.WinDivertRecv.restype  = ctypes.wintypes.BOOL
        lib.WinDivertRecv.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]

        # WinDivertSend
        lib.WinDivertSend.restype  = ctypes.wintypes.BOOL
        lib.WinDivertSend.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.c_void_p,
        ]

        # WinDivertClose
        lib.WinDivertClose.restype  = ctypes.wintypes.BOOL
        lib.WinDivertClose.argtypes = [ctypes.wintypes.HANDLE]

    def start(self):
        filter_str = (
            f"loopback and udp and outbound and udp.DstPort == {self.port}"
        ).encode()

        if self.drop_percent >= 100:
            # Fast path — kernel drops everything, no userspace loop needed
            self._handle = self._lib.WinDivertOpen(
                filter_str, WINDIVERT_LAYER_NETWORK, 0, WINDIVERT_FLAG_DROP
            )
            if self._handle == INVALID_HANDLE_VALUE:
                raise OSError(f"WinDivertOpen failed (FLAG_DROP): {ctypes.GetLastError()}")
            # No thread needed
        else:
            self._handle = self._lib.WinDivertOpen(
                filter_str, WINDIVERT_LAYER_NETWORK, 0, 0
            )
            if self._handle == INVALID_HANDLE_VALUE:
                raise OSError(f"WinDivertOpen failed: {ctypes.GetLastError()}")
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._thread.start()

    def _recv_loop(self):
        BUFSIZE    = 65535
        buf        = (ctypes.c_uint8 * BUFSIZE)()
        addr_buf   = (ctypes.c_uint8 * 512)()       # WINDIVERT_ADDRESS is ~80 bytes
        pkt_len    = ctypes.c_uint(0)

        while not self._stop_event.is_set():
            ok = self._lib.WinDivertRecv(
                self._handle,
                buf, BUFSIZE,
                ctypes.byref(pkt_len),
                addr_buf,
            )
            if not ok:
                break

            # Probabilistic drop
            if random.random() * 100 < self.drop_percent:
                continue   # drop — don't re-inject

            self._lib.WinDivertSend(
                self._handle,
                buf, pkt_len,
                None,
                addr_buf,
            )

    def stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._handle and self._handle != INVALID_HANDLE_VALUE:
            self._lib.WinDivertClose(self._handle)
            self._handle = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None


# ─── Utilidades ──────────────────────────────────────────────────────────────

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def ffprobe_duration(video: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "json", str(video)],
            capture_output=True, text=True, timeout=10
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def corrupt_video(src: Path, dst: Path, level_name: str) -> bool:
    dur = ffprobe_duration(src)
    if dur <= 0:
        return False

    drop_pct = LEVELS[level_name]
    dropper  = WinDivertDropper(port=UDP_PORT, drop_percent=drop_pct)
    dropper.start()

    try:
        # Receptor
        receiver = subprocess.Popen([
            "ffmpeg", "-y", "-err_detect", "ignore_err",
            "-i", f"udp://127.0.0.1:{UDP_PORT}?timeout=1000000",
            "-c:v", "libx264",
            "-t", str(int(dur) + 1),
            str(dst)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        time.sleep(0.001)

        # Emisor
        sender = subprocess.Popen([
            "ffmpeg", "-re", "-i", str(src),
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-f", "mpegts", f"udp://127.0.0.1:{UDP_PORT}?pkt_size=1316"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        sender.wait(timeout=dur + 1)
        receiver.wait(timeout=dur + 1)

    finally:
        dropper.stop()

    return dst.exists() and dst.stat().st_size > 1000


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not is_admin():
        print("ERROR: ejecuta este script como Administrador")
        sys.exit(1)

    if not WINDIVERT_DLL.exists():
        print(f"ERROR: no se encuentra WinDivert.dll en {WINDIVERT_DLL}")
        print("Descarga WinDivert desde https://reqrypt.org/windivert.html y ajusta WINDIVERT_DLL.")
        sys.exit(1)

    if not MANIFEST.exists():
        print(f"ERROR: no se encuentra {MANIFEST}.")
        print("Ejecuta primero generate_manifest.py")
        sys.exit(1)

    with MANIFEST.open(encoding="utf-8") as f:
        entries = list(csv.DictReader(f))

    total   = len(entries)
    pending = [e for e in entries if not Path(e["src"]).exists()]
    done    = total - len(pending)

    print(f"Manifest: {total} entradas — {done} ya hechas, {len(pending)} pendientes")

    for e in entries:
        Path(e["src"]).parent.mkdir(parents=True, exist_ok=True)

    # Clean
    clean_pending = [e for e in pending if e["category"] == "clean"]
    if clean_pending:
        print(f"\n[CLEAN] {len(clean_pending)} vídeos pendientes")
        for i, e in enumerate(clean_pending):
            dst    = Path(e["src"])
            origen = VIDEOS_DIR / dst.name
            shutil.copy2(origen, dst)
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(clean_pending)}")
        print("  [CLEAN] listo")

    #Corrupted
    corrupted_pending = [e for e in pending if e["category"] == "corrupted"]
    if corrupted_pending:
        print(f"\n[CORRUPTED] {len(corrupted_pending)} vídeos pendientes")
        for i, e in enumerate(corrupted_pending):
            dst    = Path(e["src"])
            origen = VIDEOS_DIR / dst.name
            lvl    = e["level"]
            ok     = corrupt_video(origen, dst, lvl)
            if not ok:
                print(f"  ! Sin output: {dst.name} → {lvl}")
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(corrupted_pending)}")
        print("  [CORRUPTED] listo")

    #Resumen
    print("\n─── Resumen del dataset ───────────────────────────────────")
    for split in ("train", "test"):
        n = len(list((OUTPUT_DIR / split / "clean").glob("*.mp4")))
        print(f"  {split}/clean: {n}")
        for lvl in LEVELS:
            n = len(list((OUTPUT_DIR / split / "corrupted" / lvl).glob("*.mp4")))
            print(f"  {split}/corrupted/{lvl}: {n}")
    print("──────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()