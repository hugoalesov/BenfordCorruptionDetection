"""
fix_video_column.py
--------------------
Repara la columna "video" de los CSV ya generados por run_get_csv.ipynb.

El bug: process_and_save_images nunca insertaba el nombre real del vídeo
(quedaba "0"/"1" en su lugar, mismo valor que label). Este script reconstruye
la columna "video" leyendo, en el MISMO ORDEN en que se generaron las filas
(sorted(os.listdir(folder))), los nombres de los frames en frames/<split>/<categoria>[/<level>].

Ejecutar desde la carpeta donde están csv/ (mismo sitio que run_get_csv.ipynb).
Crea una copia de seguridad .bak antes de sobreescribir cada CSV.
"""

import os
import shutil
import pandas as pd
from pathlib import Path

FRAMES_DIR = Path("../frames")
CSV_DIR    = Path("csv")
LEVELS     = ["level1", "level2", "level3"]


def frame_video_stems(folder: Path) -> list:
    """Devuelve la lista de video_stem en el mismo orden en que
    process_and_save_images recorrió los frames de esa carpeta."""
    files = sorted([f for f in os.listdir(folder) if f.endswith(('.png', '.jpg', '.jpeg'))])
    stems = []
    for f in files:
        frame_stem = os.path.splitext(f)[0]
        video_stem = "_".join(frame_stem.split("_")[:-1])
        stems.append(video_stem)
    return stems


def fix_csv(csv_path: Path, video_stems: list):
    if not csv_path.exists():
        print(f"  [SKIP] No existe: {csv_path}")
        return

    df = pd.read_csv(csv_path)

    if len(df) != len(video_stems):
        print(f"  [ERROR] {csv_path}: {len(df)} filas en CSV vs {len(video_stems)} frames en disco.")
        print(f"          No se puede reparar automáticamente por desajuste de tamaño. Revisar a mano.")
        return

    # Backup antes de tocar nada
    backup = csv_path.with_suffix(csv_path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(csv_path, backup)
        print(f"  Backup creado: {backup}")

    df["video"] = video_stems
    df.to_csv(csv_path, index=False)
    print(f"  [OK] {csv_path}: columna 'video' reparada ({df['video'].nunique()} vídeos únicos)")


def main():
    for split in ("train", "test"):
        print(f"\n=== {split} ===")

        # clean.csv
        clean_folder = FRAMES_DIR / split / "clean"
        if clean_folder.is_dir():
            stems = frame_video_stems(clean_folder)
            fix_csv(CSV_DIR / split / "clean.csv", stems)
        else:
            print(f"  [AVISO] No existe carpeta: {clean_folder}")

        # corrupted.csv -> concatenación de level1, level2, level3 en ese orden
        corrupted_stems = []
        for level in LEVELS:
            folder = FRAMES_DIR / split / "corrupted" / level
            if folder.is_dir():
                corrupted_stems.extend(frame_video_stems(folder))
            else:
                print(f"  [AVISO] No existe carpeta: {folder}")
        fix_csv(CSV_DIR / split / "corrupted.csv", corrupted_stems)

    print("\nListo. Si algún CSV dio [ERROR] por desajuste de tamaño, revisa manualmente")
    print("(puede deberse a imágenes que fallaron al cargar con cv2.imread durante el proceso original).")


if __name__ == "__main__":
    main()
