"""
extract_frames.py
-----------------
Extrae todos los frames (fps nativo) de cada vídeo como JPG.
Los frames de cada vídeo se nombran {nombre_video}_{nframe:04d}.jpg

"""

import subprocess
from pathlib import Path

DATA_DIR   = Path(r"\source\data")
FRAMES_DIR = Path(r"\source\frames")


def main():
    groups: dict[Path, list[Path]] = {}
    for video in sorted(DATA_DIR.rglob("*.mp4")):
        out_dir = FRAMES_DIR / video.relative_to(DATA_DIR).parent
        groups.setdefault(out_dir, []).append(video)

    if not groups:
        print("No se encontraron vídeos")
        return

    total_videos = sum(len(v) for v in groups.values())
    print(f"Vídeos: {total_videos} en {len(groups)} categorías\n")

    for out_dir, videos in sorted(groups.items()):
        out_dir.mkdir(parents=True, exist_ok=True)
        label = "/".join(out_dir.parts[-3:])
        print(f"[{label}] {len(videos)} vídeos")

        for video in videos:
            r = subprocess.run(
                ["ffmpeg", "-i", str(video),
                 "-q:v", "2",
                 str(out_dir / f"{video.stem}_%04d.jpg")],
                capture_output=True
            )
            if r.returncode != 0:
                print(f"  ! Error: {video.name}")

        print(f"  → {len(list(out_dir.glob('*.jpg')))} frames totales")

    print("\nListo.")


if __name__ == "__main__":
    main()
