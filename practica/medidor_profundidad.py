import cv2
import numpy as np
from ultralytics import YOLO

def main():
    """
    Script para medir la distancia de objetos usando una cámara estéreo (bifoco).
    El algoritmo sigue estos pasos:
    1. Capturar la imagen de la cámara y separarla en Ojo Izquierdo y Ojo Derecho.
    2. Utilizar Inteligencia Artificial (YOLOv8) para detectar objetos en la imagen izquierda.
    3. Extraer la Región de Interés (ROI) del objeto detectado (la menor cantidad de píxeles que lo engloban).
    4. Buscar esa misma ROI en la imagen derecha usando Template Matching (Correlación).
    5. Calcular la Disparidad (diferencia de posición en el eje X entre ambas cámaras).
    6. Aplicar la fórmula de visión estéreo para estimar la profundidad (Z = F * B / D).
    """

    # ---------------------------------------------------------
    # 1. CONSTANTES Y PARÁMETROS DE CALIBRACIÓN (IMPORTANTE)
    # ---------------------------------------------------------
    # FOCAL_LENGTH (F): Es la distancia focal de la cámara medida en píxeles. 
    # Este valor depende de tu cámara. Un valor común para webcams 720p suele rondar los 600-800 píxeles.
    # Para mayor precisión, deberías hacer una calibración de cámara (Camera Calibration).
    FOCAL_LENGTH_PIXELS = 183.0  # (Para la ZED comprimida a 640x480 por USB 2.0, la focal es ~183 px)
    
    # BASELINE (B): Es la distancia física real entre el centro de ambos lentes de tu cámara bifoco.
    # Está medida en centímetros (cm). Mide tu cámara con una regla y cambia este valor.
    BASELINE_CM = 12.0  #lo cambie a 12cm, que es la distancia entre camaras

    # ---------------------------------------------------------
    # 2. INICIALIZACIÓN DE LA CÁMARA Y EL DETECTOR DE OBJETOS
    # ---------------------------------------------------------
    # Inicializamos la cámara bifoco conectada por USB. 
    # Usualmente, las cámaras estéreo USB envían una sola imagen ancha (side-by-side).
    # Por ejemplo, una resolución de 1280x480 contiene dos imágenes de 640x480 pegadas.
    # Intentamos abrir la cámara en el índice 2 (ZED/Estéreo), si falla probamos otros (0, 1, 3, 4)
    cap = None
    for i in [2, 0, 1, 3, 4, 5]:
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            print(f"Cámara abierta exitosamente en el índice {i}")
            break
    
    if cap is None or not cap.isOpened():
        print("Error: No se pudo abrir ninguna cámara conectada al equipo.")
        return

    # Forzar la resolución nativa panorámica de la ZED (VGA side-by-side)
    # OpenCV por defecto la comprime a 640x480, lo que reduce la disparidad a la mitad 
    # y duplica las distancias calculadas.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1344)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 376)

    # Descargamos e inicializamos el detector de objetos YOLOv8 (versión Nano, ligera y rápida)
    print("Cargando modelo YOLOv8...")
    model = YOLO("yolov8n.pt") 
    print("Modelo cargado exitosamente.")

    # Bucle principal de procesamiento de video
    while True:
        # Leemos el frame actual de la cámara
        # 'ret' es un booleano que indica si se leyó correctamente
        # 'frame' contiene la matriz de píxeles de la imagen
        ret, frame = cap.read()
        if not ret:
            print("Error: No se puede recibir frame de la cámara. Saliendo...")
            break

        # ---------------------------------------------------------
        # 3. SEPARAR LA IMAGEN EN IZQUIERDA Y DERECHA
        # ---------------------------------------------------------
        # Obtenemos el ancho total y alto del frame
        alto, ancho, canales = frame.shape
        
        # Como asumimos que es una imagen side-by-side, partimos el ancho a la mitad
        mitad_ancho = ancho // 2
        
        # Recortamos (slicing de matrices numpy) para obtener cada ojo
        img_izquierda = frame[:, :mitad_ancho] # Desde la columna 0 hasta la mitad
        img_derecha = frame[:, mitad_ancho:]   # Desde la mitad hasta el final

        # Copias para dibujar sobre ellas sin alterar las originales
        img_izq_display = img_izquierda.copy()
        img_der_display = img_derecha.copy()

        # ---------------------------------------------------------
        # 4. DETECCIÓN DE OBJETOS EN LA IMAGEN IZQUIERDA (YOLO)
        # ---------------------------------------------------------
        # Ejecutamos el modelo sobre la imagen del lente izquierdo
        # stream=True ayuda al rendimiento al no guardar en memoria todos los resultados
        resultados = model(img_izquierda, stream=True, verbose=False)

        for resultado in resultados:
            # Extraemos las cajas delimitadoras (bounding boxes) de todos los objetos detectados
            cajas = resultado.boxes
            
            for caja in cajas:
                # Obtenemos las coordenadas de la caja en formato [x1, y1, x2, y2]
                # x1, y1 = Esquina superior izquierda
                # x2, y2 = Esquina inferior derecha
                x1, y1, x2, y2 = map(int, caja.xyxy[0])
                
                # Obtenemos la confianza de la detección y la clase del objeto
                confianza = caja.conf[0].item()
                clase_id = int(caja.cls[0].item())
                nombre_clase = model.names[clase_id]

                # Filtramos para que solo tome detecciones seguras (más de 50% de confianza)
                # y para simplificar, buscaremos enfocarnos en ciertos objetos, pero aquí dejamos pasar todos.
                if confianza > 0.5:
                    
                    # ---------------------------------------------------------
                    # 5. EXTRACCIÓN DE LA REGIÓN DE INTERÉS (ROI)
                    # ---------------------------------------------------------
                    # Recortamos el objeto detectado de la imagen izquierda.
                    # Nos quedamos con la MENOR cantidad de píxeles posibles que lo engloban.
                    # En OpenCV la imagen es [filas, columnas] por ende es [y1:y2, x1:x2]
                    roi = img_izquierda[y1:y2, x1:x2]
                    
                    # Verificamos que la ROI tenga un tamaño válido antes de procesar
                    if roi.shape[0] == 0 or roi.shape[1] == 0:
                        continue

                    # ---------------------------------------------------------
                    # 6. BÚSQUEDA DEL OBJETO EN LA IMAGEN DERECHA (TEMPLATE MATCHING)
                    # ---------------------------------------------------------
                    # En lugar de usar la IA pesada en el lado derecho de nuevo, 
                    # buscamos los píxeles idénticos de nuestra ROI en la imagen derecha.
                    # TM_CCOEFF_NORMED es un algoritmo estadístico de correlación.
                    # Restringimos la búsqueda a la franja horizontal (Línea Epipolar).
                    # Agregamos un margen de 20px arriba y abajo por si las lentes están levemente desalineadas.
                    margen_y = 20
                    y_busqueda_inicio = max(0, y1 - margen_y)
                    y_busqueda_fin = min(img_derecha.shape[0], y2 + margen_y)
                    
                    # También sabemos que en la cámara derecha, los objetos se desplazan hacia la IZQUIERDA.
                    # Por lo tanto, no necesitamos buscar más a la derecha de x2.
                    x_busqueda_fin = min(img_derecha.shape[1], x2)
                    
                    franja_derecha = img_derecha[y_busqueda_inicio:y_busqueda_fin, 0:x_busqueda_fin]
                    
                    # Verificamos que la franja sea válida
                    if franja_derecha.shape[1] <= roi.shape[1] or franja_derecha.shape[0] <= roi.shape[0]:
                        continue

                    resultado_match = cv2.matchTemplate(franja_derecha, roi, cv2.TM_CCOEFF_NORMED)
                    
                    # Obtenemos las coordenadas dentro de la franja donde la correlación fue más alta
                    _, val_maximo, _, pos_maxima = cv2.minMaxLoc(resultado_match)
                    
                    # Filtro de falsos positivos: Solo aceptamos si la similitud es alta
                    if val_maximo > 0.6:
                        x_max = pos_maxima[0]
                        y_max = pos_maxima[1]
                        
                        # Interpolación sub-píxel para mayor precisión
                        if 0 < x_max < resultado_match.shape[1] - 1:
                            val_izq = resultado_match[y_max, x_max - 1]
                            val_cen = resultado_match[y_max, x_max]
                            val_der = resultado_match[y_max, x_max + 1]
                            denominador = 2 * (val_izq + val_der - 2 * val_cen)
                            if denominador != 0:
                                offset_x = (val_izq - val_der) / denominador
                            else:
                                offset_x = 0
                        else:
                            offset_x = 0
                            
                        x_derecha_subpixel = x_max + offset_x
                        
                        # Mapeamos la coordenada local de la franja a la coordenada global de la imagen derecha
                        x_derecha = x_derecha_subpixel
                        y_derecha = y_busqueda_inicio + y_max
                        
                        # Calculamos el punto central (en X) del objeto en la imagen izquierda
                        centro_x_izq = x1 + (x2 - x1) / 2.0
                        
                        # Calculamos el punto central (en X) del objeto en la imagen derecha
                        centro_x_der = x_derecha + (x2 - x1) / 2.0
                        
                        # ---------------------------------------------------------
                        # 7. CÁLCULO DE LA DISPARIDAD Y LA PROFUNDIDAD
                        # ---------------------------------------------------------
                        disparidad_cruda = centro_x_izq - centro_x_der
                        
                        # CORRECCIÓN DE RECTIFICACIÓN (Fudge Factor)
                        centro_optico = img_izquierda.shape[1] / 2.0
                        correccion_lente = (centro_x_izq - centro_optico) * 0.02
                        disparidad = disparidad_cruda + correccion_lente
                        
                        # Evitamos división por cero en caso de objetos infinitamente lejanos (misma posición)
                        if disparidad > 0:
                            # Aplicamos la fórmula vista en la clase teórica:
                            # Z (Profundidad) = (Distancia Focal * Baseline) / Disparidad
                            profundidad_cm = (FOCAL_LENGTH_PIXELS * BASELINE_CM) / disparidad
                            
                            # Imprimimos en consola los cálculos paso a paso para depurar
                            print(f"[{nombre_clase}] Centro Izq: {centro_x_izq:.1f}px, Centro Der: {centro_x_der:.1f}px")
                            print(f"[{nombre_clase}] Disparidad (Corregida): {disparidad:.2f}px -> Profundidad: {profundidad_cm:.2f} cm")

                            # --- DIBUJAR EN LAS IMÁGENES (PASOS INTERMEDIOS) ---
                            
                            # Dibujamos en la IMAGEN IZQUIERDA: Bounding box de YOLO y etiqueta de profundidad
                            cv2.rectangle(img_izq_display, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            texto_izq = f"{nombre_clase} {profundidad_cm:.1f}cm"
                            cv2.putText(img_izq_display, texto_izq, (x1, y1 - 10), 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                            # Dibujamos en la IMAGEN DERECHA: Bounding box del Template Matching
                            cv2.rectangle(img_der_display, (int(x_derecha), int(y_derecha)), 
                                          (int(x_derecha + roi.shape[1]), int(y_derecha + roi.shape[0])), 
                                          (255, 0, 0), 2)
                            cv2.putText(img_der_display, "Match en Der", (int(x_derecha), int(y_derecha) - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                            
                            # Mostramos un pequeño cuadro (ROI) en la esquina superior para entender qué píxeles usa
                            roi_resize = cv2.resize(roi, (100, int(100 * roi.shape[0] / roi.shape[1])))
                            h_r, w_r, _ = roi_resize.shape
                            # Evitamos que el cuadro se salga de los límites de la pantalla (soluciona el ValueError)
                            if h_r < img_izq_display.shape[0] and w_r < img_izq_display.shape[1]:
                                img_izq_display[0:h_r, 0:w_r] = roi_resize
                                cv2.putText(img_izq_display, "ROI (Menos px)", (5, h_r + 15), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        
        # ---------------------------------------------------------
        # 8. MOSTRAR RESULTADOS EN PANTALLA
        # ---------------------------------------------------------
        # Volvemos a concatenar las imágenes procesadas para verlas juntas (Opcional, se pueden ver separadas)
        frame_final = np.hstack((img_izq_display, img_der_display))

        # Añadimos líneas de ayuda en la pantalla unificada para entender la Baseline (división de cámaras)
        cv2.line(frame_final, (mitad_ancho, 0), (mitad_ancho, alto), (0, 0, 255), 2)
        cv2.putText(frame_final, "LENTE IZQUIERDO (YOLO)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        cv2.putText(frame_final, "LENTE DERECHO (Template Match)", (mitad_ancho + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

        # Mostramos la ventana interactiva
        cv2.imshow("Estimacion de Profundidad - Camara Bifoco", frame_final)

        # Esperamos 1 milisegundo a ver si el usuario presiona la tecla 'q' para salir
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Saliendo de la aplicación...")
            break

    # Liberamos los recursos (Cámara) y cerramos todas las ventanas
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
