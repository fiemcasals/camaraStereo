# Entorno Oficial ZED SDK (NVIDIA CUDA)

Esta carpeta contiene todo lo necesario para levantar el software oficial de Stereolabs (ZED SDK) sin ensuciar la computadora con instalaciones pesadas, utilizando Docker.

## Requisitos en la PC Destino

La computadora donde vayas a correr esto **DEBE** cumplir lo siguiente:
1. Tener una tarjeta gráfica **NVIDIA** física (GTX, RTX, Quadro, etc).
2. Tener instalados los drivers de NVIDIA de Linux (`nvidia-driver`).
3. Tener instalado Docker y el **NVIDIA Container Toolkit** (para que Docker pueda usar la GPU).
4. Conectar la cámara ZED al puerto **USB 3.0** (el puerto azul).

## Instrucciones de Uso

1. **Permitir entorno gráfico:**
   Para que las ventanas de OpenCV del Docker se vean en el monitor host, ejecuta en tu terminal física:
   ```bash
   xhost +local:root
   ```

2. **Construir y levantar el contenedor:**
   Ubicado en esta misma carpeta, ejecuta:
   ```bash
   docker-compose up -d --build
   ```

3. **Entrar al entorno de trabajo:**
   Una vez levantado, puedes meterte a la consola del contenedor corriendo:
   ```bash
   docker exec -it zed_cuda_env bash
   ```

4. **Verificar que la magia funciona:**
   Dentro del contenedor, corre:
   - `nvidia-smi` (Para confirmar que el contenedor ve la placa de video).
   - `ZED_Explorer` (Esta es la herramienta oficial de diagnóstico de Stereolabs. Debería abrirse una ventana mostrándote la cámara en máxima resolución y sin distorsiones).

## Importante

Una vez dentro de este contenedor, ya NO necesitas hacer el "Hack" del modo USB 2.0.
Puedes importar `import pyzed.sl as sl` en tus scripts de Python para usar la IA nativa de la cámara y obtener mapas 3D perfectos de grado industrial.
