FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libmagic1 \
    curl \
    wget \
    git \
    build-essential \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m pip install --upgrade pip setuptools wheel

# PyTorch CPU — los motores OCR (Surya, TrOCR, MinerU) corren en CPU en el worker
RUN pip install --no-cache-dir \
    torch \
    torchvision \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .

# El resto de dependencias: pip ve torch ya instalado y no lo sobreescribe
RUN pip install --no-cache-dir -r requirements.txt

# MinerU/magic-pdf: paddle CPU (no conflicta con PyTorch CUDA)
# La inferencia pesada (layout, fórmulas) usa PyTorch/ONNX — paddle solo para init
RUN pip install --no-cache-dir paddlepaddle==3.0.0 paddleocr==2.9.1

# Parchear models_config.yml: los modelos descargados son v5 (no v3) para detección china.
# arch_config.yaml ya define ch_PP-OCRv5_det_infer (PPLCNetV3) y Multilingual (MobileNetV3).
RUN CONF=/usr/local/lib/python3.10/dist-packages/magic_pdf/model/sub_modules/ocr/paddleocr2pytorch/pytorchocr/utils/resources/models_config.yml && \
    sed -i 's/ch_PP-OCRv3_det_infer\.pth/ch_PP-OCRv5_det_infer.pth/g' $CONF && \
    sed -i 's/en_PP-OCRv3_det_infer\.pth/Multilingual_PP-OCRv3_det_infer.pth/g' $CONF

# Config de MinerU apuntando al volumen de modelos
RUN mkdir -p /root && echo '{ \
    "models-dir": "/data/models/mineru/PDF-Extract-Kit-1.0/models", \
    "device-mode": "cpu", \
    "layout-config": {"model": "doclayout_yolo"}, \
    "formula-config": {"mfd_model": "yolo_v8_mfd", "mfr_model": "unimernet_small", "enable": false}, \
    "table-config": {"model": "rapid_table", "enable": true} \
}' > /root/magic-pdf.json
ENV MINERU_TOOLS_CONFIG_JSON=/root/magic-pdf.json

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio"]
