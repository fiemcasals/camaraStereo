# Clase 12: Visión Estéreo (Bifoco) y Percepción de Profundidad

Este directorio contiene un ejemplo pedagógico para introducir el concepto de visión estéreo (cálculo de disparidad y profundidad usando dos "cámaras" o perspectivas).

## Contenido del Directorio

- `stereo_vision_tutorial.py`: Script de Python que genera imágenes sintéticas y aplica el algoritmo `StereoSGBM` (Semi-Global Block Matching) de OpenCV para calcular el mapa de disparidad y profundidad.
- `resultado_bifoco.png`: Imagen de salida que muestra las cámaras originales, la disparidad y el mapa de profundidad convertido a metros. (Se genera al correr el script).
- `presentacion/`: Una presentación web interactiva (HTML/CSS/JS) diseñada para proyectar en clase, explicando visualmente la fórmula de la profundidad y el concepto de disparidad de forma dinámica.

---

## 🛠️ Instrucciones para correr el código Python

Para ejecutar este script, es altamente recomendable usar un Entorno Virtual (Virtual Environment o `venv`) para no ensuciar tu instalación global de Python.

### Paso 1: Crear el Entorno Virtual

Abre tu terminal en la carpeta actual (`clase 12 bifoco`) y ejecuta:

```bash
# Crea un entorno virtual llamado 'venv'
python3 -m venv venv
```

### Paso 2: Activar el Entorno Virtual

Debes activar el entorno virtual cada vez que quieras ejecutar o instalar algo para este proyecto:

```bash
# En Linux o macOS:
source venv/bin/activate
```
*(Sabrás que está activo porque tu terminal dirá `(venv)` al principio de la línea).*

### Paso 3: Instalar las Dependencias

El script requiere de `OpenCV` para el procesamiento de imágenes, `NumPy` para las matemáticas con matrices, y `Matplotlib` para dibujar los resultados. Instálalos ejecutando:

```bash
pip install opencv-python numpy matplotlib
```

### Paso 4: Ejecutar el Script

Con las dependencias instaladas, simplemente corre el programa:

```bash
python3 stereo_vision_tutorial.py
```

### Resultado Esperado

Verás en la consola la impresión de los pasos que va realizando el algoritmo y el cálculo teórico de la profundidad en metros. Al finalizar, el script creará (o sobrescribirá) el archivo **`resultado_bifoco.png`** en esta misma carpeta, el cual puedes abrir para ver los mapas de calor generados.

---

## 🎓 Instrucciones para la Presentación Interactiva

1. Entra a la carpeta `presentacion/`.
2. Haz doble clic en el archivo `index.html`. 
3. Se abrirá en tu navegador web por defecto (Chrome, Firefox, etc.).
4. Utiliza las flechas direccionales de tu teclado `<-` y `->` o la barra espaciadora para avanzar por las diapositivas.
5. En la Diapositiva 3, invita a los alumnos a interactuar con el control deslizante (slider) para observar cómo cambia matemáticamente la disparidad a medida que varía la profundidad (distancia en Z).

---

## 📸 Práctica en Vivo: Medidor de Profundidad con Cámara ZED

Este proyecto también incluye un script de práctica en tiempo real (`practica/medidor_profundidad.py`) que combina una cámara estéreo física (ZED), Inteligencia Artificial (YOLOv8) y correlación matemática (Template Matching) para medir la distancia de objetos en tu aula en tiempo real.

### ⚠️ Requisito Crítico de Hardware (El "Hack" de la Cámara ZED)

Para ejecutar este script **sin instalar el pesado SDK de Stereolabs**, debes engañar al driver de Linux conectando la cámara de una forma específica:
- Conecta la cámara ZED **ESTRICTAMENTE a un puerto USB 2.0** de tu computadora (generalmente los puertos de color negro, NO los azules). 
- *¿Por qué?* Si la conectas a un puerto USB 3.0, el núcleo de Linux se bloqueará esperando la inicialización del software propietario (`not a v4l2 node` / `Inappropriate ioctl`). Al usar un puerto USB 2.0, el cable estrangula el ancho de banda y obliga a la cámara a caer en un modo de "compatibilidad básica UVC", lo que permite que OpenCV lea el video directamente en crudo.

*Nota de Calibración:* Al forzar el USB 2.0, la imagen panorámica original se comprime internamente, reduciendo la distancia focal óptica a ~183 píxeles. El script ya está parcheado matemáticamente (con precisión de parábola sub-píxel) para contemplar esto.

### Instrucciones de Ejecución

1. **Instalar Dependencias Extra:** Si aún no tienes YOLO, instálalo en tu entorno virtual:
   ```bash
   source venv/bin/activate
   pip install ultralytics torch
   ```

2. **Iniciar la Práctica:** 
   (Asegúrate de haber conectado la cámara al USB 2.0 como se indicó arriba).
   ```bash
   python3 practica/medidor_profundidad.py
   ```

3. **Solución de Problemas Frecuentes:**
   - Si la terminal arroja el error `Inappropriate ioctl for device` o `Camera index out of range`: significa que el driver USB de la cámara se quedó trabado por una mala suspensión. **Solución:** Desenchufa la cámara físicamente, cuenta hasta 3, enchúfala en otro puerto USB 2.0 y vuelve a lanzar el script.
   - Si no puedes cerrar la ventana de OpenCV, abre otra terminal y ejecuta `killall python` para liberar el bloqueo.

### ¿Qué sucede durante la ejecución?
1. **Detección (Ojo Izq):** YOLOv8 escanea la mitad izquierda de la imagen y dibuja cajas verdes sobre objetos conocidos (sillas, personas).
2. **Correlación (Ojo Der):** El script extrae esos píxeles y realiza un barrido por la *franja epipolar* en la imagen derecha para encontrar el mismo objeto (Cajas azules).
3. **Calibración Sub-Píxel:** Para evitar saltos violentos de distancia por baja resolución, el script calcula el "pico de la parábola" de coincidencia con precisión decimal y compensa empíricamente las distorsiones de la lente no rectificada.
4. Las distancias finales se imprimen en vivo en pantalla.
