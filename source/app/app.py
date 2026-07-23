import os
import sys

from flask import Flask, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
import joblib
import cv2
import torch
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.join(BASE_DIR, "..", "code")
sys.path.insert(0, CODE_DIR)

import benford_torch as bt  # noqa: E402

MODEL_PATH = os.path.join(CODE_DIR, "models", "corruption_detector.pkl")

BASES = [10, 20, 40, 60]
FREQUENCIES = [1, 2, 3, 4, 5, 6, 7, 8, 9]
QUALITIES = [80, 85, 90, 95, 100]
QUANT_MATRICES = [bt.get_quantization_matrix(q) for q in QUALITIES]
DIVERGENCES = ["js", "r", "t"]

FEATURE_COLUMNS = [
    f"{d}_{b}_{f}_{q}"
    for b in BASES
    for f in FREQUENCIES
    for q in QUALITIES
    for d in DIVERGENCES
]

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Carga del modelo entrenado (Random Forest sobre las características de Benford).
model = joblib.load(MODEL_PATH)


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    image_url = None

    if request.method == "POST":
        if "image" not in request.files:
            return render_template("index.html", error="No se ha subido ninguna imagen")

        file = request.files["image"]
        if file.filename == "":
            return render_template("index.html", error="Nombre de archivo vacío")

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        result = detectar_corrupcion(filepath)
        image_url = f"/uploads/{filename}"

    return render_template("index.html", result=result, image_url=image_url)


def detectar_corrupcion(image_path):
    "Clasificacion de un fotograma como limpio o corrupto usando el método de Benford"
    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return "No se ha podido leer la imagen"

    # Preparación idéntica a process_and_save_images: recorte a múltiplo de 8
    # y conversión a tensor de PyTorch en float.
    image = bt.crop_image(image, bt.BLOCK_SIZE)
    image = torch.tensor(image, dtype=torch.float, device=bt.device)

    features = bt.get_feature_vector(image, BASES, FREQUENCIES, QUANT_MATRICES)
    flattened = features.cpu().numpy().flatten().reshape(1, -1)

    # Se construye un DataFrame con los nombres de columna del entrenamiento
    # para que scikit-learn no emita avisos por desajuste de características.
    X = pd.DataFrame(flattened, columns=FEATURE_COLUMNS)

    prediction = int(model.predict(X)[0])

    if prediction == 1:
        return "Imagen corrupta"
    return "Imagen limpia"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
