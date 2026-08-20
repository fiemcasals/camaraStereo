# Usa la imagen oficial de Stereolabs que ya trae preinstalado:
# - Ubuntu 22.04
# - NVIDIA CUDA 12.1
# - ZED SDK 4.1
# - OpenGL (para poder visualizar las ventanas de OpenCV)
FROM stereolabs/zed:4.1-gl-devel-cuda12.1-ubuntu22.04

# Variables de entorno para evitar interacciones durante la instalación
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias adicionales de Python y utilidades de video
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    python3-opencv \
    usbutils \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# Instalar la API de Python oficial de ZED (pyzed)
# El script 'get_python_api.py' viene incluido en el contenedor oficial de ZED
RUN python3 /usr/local/zed/get_python_api.py

# Crear un directorio de trabajo
WORKDIR /app

# Instalar otras librerías útiles para ciencia de datos y visión
RUN pip3 install --no-cache-dir numpy opencv-contrib-python

# Comando por defecto (te deja en una terminal dentro del contenedor)
CMD ["/bin/bash"]
