import cv2
import numpy as np

def nada(x):
    pass

def main():
    print("Iniciando Mapa de Profundidad Denso...")
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

    # Forzar la resolución nativa panorámica
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1344)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 376)
    
    # Creamos la ventana PRINCIPAL limpia (GUI_NORMAL oculta los botones de zoom/guardar que veías arriba)
    nombre_ventana = "Navegacion Autonoma - Mapa de Profundidad"
    cv2.namedWindow(nombre_ventana, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
    
    # Rango de -20 a +20 píxeles de corrección vertical. El centro es 20 (0 corrección)
    # Pegamos el deslizador directamente en la ventana principal
    cv2.createTrackbar("Alineacion Vertical (Y)", nombre_ventana, 20, 40, nada)

    # Parámetros SGBM Clásicos (Con Filtro de Alta Calidad)
    window_size = 7
    min_disp = 0
    num_disp = 16 * 4
    
    stereo = cv2.StereoSGBM_create(
        minDisparity=min_disp,
        numDisparities=num_disp,
        blockSize=window_size,
        P1=8 * 3 * window_size ** 2,
        P2=32 * 3 * window_size ** 2,
        disp12MaxDiff=1,
        uniquenessRatio=15, # MUY ESTRICTO: Para evitar alucinaciones rojas
        speckleWindowSize=200,
        speckleRange=2,
        preFilterCap=63,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY
    )

    right_matcher = cv2.ximgproc.createRightMatcher(stereo)
    wls_filter = cv2.ximgproc.createDisparityWLSFilter(matcher_left=stereo)
    wls_filter.setLambda(80000) # Restauramos la fuerza del WLS
    wls_filter.setSigmaColor(1.5)

    print("Presiona 'q' para salir.")

    while True:
        ret, frame = cap.read()
        if not ret: 
            break
            
        mitad = frame.shape[1] // 2
        img_izq = frame[:, :mitad]
        img_der = frame[:, mitad:]
        
        gray_izq = cv2.cvtColor(img_izq, cv2.COLOR_BGR2GRAY)
        gray_der = cv2.cvtColor(img_der, cv2.COLOR_BGR2GRAY)
        
        # SGBM necesita textura. Forzamos contraste con CLAHE.
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray_izq = clahe.apply(gray_izq)
        gray_der = clahe.apply(gray_der)
        
        # 1. LEER DESLIZADOR INTERACTIVO
        desfase_y = cv2.getTrackbarPos("Alineacion Vertical (Y)", nombre_ventana) - 20
        max_visual = 30 # Valor fijo y estable para el color

        # 2. ALINEACIÓN MECÁNICA MANUAL
        if desfase_y != 0:
            M = np.float32([[1, 0, 0], [0, 1, desfase_y]])
            gray_der = cv2.warpAffine(gray_der, M, (gray_der.shape[1], gray_der.shape[0]))
            
        escala = 0.5
        gray_izq_peq = cv2.resize(gray_izq, (0,0), fx=escala, fy=escala)
        gray_der_peq = cv2.resize(gray_der, (0,0), fx=escala, fy=escala)
        
        # 3. CÁLCULO SGBM
        disp_izq_peq = stereo.compute(gray_izq_peq, gray_der_peq)
        disp_der_peq = right_matcher.compute(gray_der_peq, gray_izq_peq)
        
        # Restaurar tamaño
        disp_izq = cv2.resize(disp_izq_peq, (img_izq.shape[1], img_izq.shape[0]), interpolation=cv2.INTER_NEAREST)
        disp_der = cv2.resize(disp_der_peq, (img_der.shape[1], img_der.shape[0]), interpolation=cv2.INTER_NEAREST)
        
        disp_izq = np.int16(disp_izq / escala)
        disp_der = np.int16(disp_der / escala)
        
        # 4. APLICAR WLS FILTER (IA de rellenado)
        disp_filtrada = wls_filter.filter(disp_izq, img_izq, None, disp_der)
        
        # Ajustar por la escala y dividir por 16 (formato de OpenCV)
        disparidad_float = disp_filtrada.astype(np.float32) / 16.0
        
        # Eliminar valores negativos (puntos ciegos por oclusión o falta de textura)
        disparidad_float[disparidad_float < 0] = 0
        
        # 5. NORMALIZACIÓN Y COLOR
        disp_fija = np.clip(disparidad_float, 0, max_visual)
        disp_visual = np.uint8(disp_fija * (255.0 / max_visual))
        
        mapa_color = cv2.applyColorMap(disp_visual, cv2.COLORMAP_JET)
        
        # Imponer el NEGRO absoluto en los puntos ciegos (zonas no resueltas)
        mapa_color[disparidad_float <= 0] = [0, 0, 0]
        
        cv2.putText(img_izq, f"Desfase en Y (Alineacion): {desfase_y}px", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(img_izq, "MODO ALTA RESOLUCION (SGBM + WLS + CLAHE)", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
        
        pantalla_dividida = np.hstack((img_izq, mapa_color))
        cv2.imshow("Navegacion Autonoma - Mapa de Profundidad", pantalla_dividida)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
