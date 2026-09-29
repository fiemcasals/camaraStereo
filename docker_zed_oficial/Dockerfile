# Usa la imagen oficial de Stereolabs específica para la Jetson (Arquitectura L4T / ARM64):
# - Ubuntu 20.04
# - NVIDIA CUDA 11.4
# - ZED SDK 4.1
# - OpenCV
FROM stereolabs/zed:4.1-devel-l4t-r35.2

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
