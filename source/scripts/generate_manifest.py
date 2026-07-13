"""
generate_manifest.py
--------------------
Escanea videos_val, selecciona 500 con resolución 568x320 y genera
manifest.csv con el mapeo completo para cada vídeo.

build_dataset.py lee este CSV y procesa solo lo que falta.
"""

import csv
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ─── Rutas ───────────────────────────────────────────────────────────────────
VIDEOS_VAL   = Path(r"C:\Users\hugoa\Desktop\Universidad\TFG\videos")
OUTPUT_DIR   = Path(r"C:\Users\hugoa\Desktop\Universidad\TFG\benford-corruption\source\data")
MANIFEST     = Path(r"C:\Users\hugoa\Desktop\Universidad\TFG\benford-corruption\source\scripts\manifest.csv")

# ─── Parámetros ──────────────────────────────────────────────────────────────
TARGET_W     = 568
TARGET_H     = 320
TOTAL        = 500
CLEAN_N      = 250
CORRUPT_N    = 250
TRAIN_RATIO  = 0.8
SEED         = 42
SCAN_WORKERS = 16

LEVELS = [
    "level1",
    "level2",
    "level3",
]


def ffprobe_info(video: Path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "json", str(video)],
            capture_output=True, text=True, timeout=10
        )
        streams = json.loads(r.stdout).get("streams", [])
        if streams:
            w = streams[0].get("width")
            h = streams[0].get("height")
            return w, h
    except Exception:
        pass
    return None, None


def scan_videos(all_videos: list) -> list:
    print(f"Escaneando {len(all_videos)} vídeos con {SCAN_WORKERS} threads…")
    matching = []

    def check(v):
        w, h = ffprobe_info(v)
        return v if (w == TARGET_W and h == TARGET_H) else None

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
        futures = {ex.submit(check, v): v for v in all_videos}
        done = 0
        for f in as_completed(futures):
            done += 1
            result = f.result()
            if result:
                matching.append(result)
            if done % 1000 == 0:
                print(f"  {done}/{len(all_videos)} revisados — {len(matching)} coinciden…")
            if len(matching) >= TOTAL * 3:
                for pending in futures:
                    pending.cancel()
                break

    print(f"  Total con {TARGET_W}x{TARGET_H}: {len(matching)}")
    return matching  # lista de Path


def build_entries(clean_videos: list, corrupt_videos: list) -> list:
    """Genera la lista de filas del manifest."""
    entries = []

    # ── Clean ─────────────────────────────────────────────────────────────────
    n_train = int(len(clean_videos) * TRAIN_RATIO)
    for i, src in enumerate(clean_videos):
        split = "train" if i < n_train else "test"
        dst   = OUTPUT_DIR / split / "clean" / src.name
        entries.append({
            "src":      str(dst),
            "split":    split,
            "category": "clean",
            "level":    "",
        })

    # ── Corrupted ─────────────────────────────────────────────────────────────
    per_level = CORRUPT_N // len(LEVELS)
    extras    = CORRUPT_N % len(LEVELS)
    counts    = [per_level + (1 if i < extras else 0) for i in range(len(LEVELS))]

    start = 0
    for lvl_name, n in zip(LEVELS, counts):
        n_train = int(n * TRAIN_RATIO)
        for j, src in enumerate(corrupt_videos[start: start + n]):
            split = "train" if j < n_train else "test"
            dst   = OUTPUT_DIR / split / "corrupted" / lvl_name / src.name
            entries.append({
                "src":      str(dst),
                "split":    split,
                "category": "corrupted",
                "level":    lvl_name,
            })
        start += n

    return entries


def main():
    if MANIFEST.exists():
        ans = input(f"Ya existe {MANIFEST.name}. ¿Sobreescribir? [s/N] ").strip().lower()
        if ans != "s":
            print("Abortado.")
            sys.exit(0)

    all_videos = sorted(VIDEOS_VAL.glob("*.mp4"))
    matching   = scan_videos(all_videos)

    if len(matching) < TOTAL:
        print(f"AVISO: solo {len(matching)} vídeos disponibles (se pedían {TOTAL}).")

    random.seed(SEED)
    selected       = random.sample(matching, min(TOTAL, len(matching)))
    clean_videos   = selected[:CLEAN_N]
    corrupt_videos = selected[CLEAN_N: CLEAN_N + CORRUPT_N]

    entries = build_entries(clean_videos, corrupt_videos)

    # Detectar colisiones de nombre dentro de cada carpeta destino
    from collections import Counter
    src_counts = Counter(e["src"] for e in entries)
    collisions = [s for s, c in src_counts.items() if c > 1]
    if collisions:
        print(f"\nAVISO: {len(collisions)} colisiones de nombre detectadas:")
        for c in collisions[:10]:
            print(f"  {c}")

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["src", "split", "category", "level"])
        writer.writeheader()
        writer.writerows(entries)

    print(f"\nManifest guardado en {MANIFEST}")
    print(f"  Clean:     {sum(1 for e in entries if e['category'] == 'clean')} vídeos")
    print(f"  Corrupted: {sum(1 for e in entries if e['category'] == 'corrupted')} vídeos")
    for lvl in LEVELS:
        n = sum(1 for e in entries if e["level"] == lvl)
        print(f"    {lvl}: {n}")


if __name__ == "__main__":
    main()
