import os
import subprocess
import json

# ============================================================
#  Elimina todos los .mp4 de la carpeta que NO sean 568x320.
#  Requiere ffprobe (FFmpeg) instalado y en el PATH.
# ============================================================

CARPETA = r"videos_val"
RESOLUCION_OK = (568, 320)
MODO_PRUEBA = False  # Cambia a False para borrar de verdad


def get_resolucion(ruta):
    "Devuelve el ancho, alto del vídeo usando ffprobe, o None si falla."
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        ruta
    ]
    try:
        resultado = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        datos = json.loads(resultado.stdout)
        stream = datos["streams"][0]
        return stream["width"], stream["height"]
    except Exception:
        return None


def main():
    print("=" * 60)
    print(f"  Carpeta      : {CARPETA}")
    print(f"  Resolución   : {RESOLUCION_OK[0]}x{RESOLUCION_OK[1]}")
    print(f"  Modo prueba  : {'SÍ' if MODO_PRUEBA else 'NO (borra archivos)'}")
    print("=" * 60)

    archivos = [
        f for f in os.listdir(CARPETA)
        if f.lower().endswith(".mp4")
    ]

    if not archivos:
        print("\nNo se encontraron archivos .mp4 en la carpeta.")
        return

    total = len(archivos)
    conservados, borrados, errores = [], [], []

    for nombre in sorted(archivos):
        ruta = os.path.join(CARPETA, nombre)
        res = get_resolucion(ruta)

        if res is None:
            print(f"  [SKIP]  {nombre}  <-- no se pudo leer la resolución")
            errores.append(nombre)
            continue

        ancho, alto = res
        etiqueta = f"{ancho}x{alto}"

        if (ancho, alto) == RESOLUCION_OK:
            print(f"  [OK]   {etiqueta}  ->  {nombre}")
            conservados.append(nombre)
        else:
            print(f"  [DEL]  {etiqueta}  ->  {nombre}")
            borrados.append(nombre)
            if not MODO_PRUEBA:
                try:
                    os.remove(ruta)
                except OSError as e:
                    print(f"           ERROR al borrar: {e}")
                    errores.append(nombre)
                    borrados.pop()

    print("\n" + "=" * 60)
    print("  RESUMEN")
    print(f"  Total analizados : {total}")
    print(f"  Conservados      : {len(conservados)}")
    print(f"  Eliminados       : {len(borrados)}")
    print(f"  Errores / Skips  : {len(errores)}")
    if MODO_PRUEBA:
        print()
        print("MODO PRUEBA: ningún archivo fue borrado")
        print("Cambia MODO_PRUEBA = False para borrar")
    print("=" * 60)


if __name__ == "__main__":
    main()
