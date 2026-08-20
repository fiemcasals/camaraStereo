import cv2
import numpy as np
import time

def main():
    print("Iniciando barrido de calibración automático...")
    cap = cv2.VideoCapture(2)
    if not cap.isOpened():
        print("Error al abrir cámara.")
        return
        
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1344)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 376)
    
    # Dejar que la cámara caliente y fije la exposición
    for _ in range(15):
        cap.read()
        time.sleep(0.1)
        
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("No se pudo capturar el frame.")
        return

    mitad = frame.shape[1] // 2
    img_izq_orig = frame[:, :mitad]
    img_der_orig = frame[:, mitad:]
    
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
        uniquenessRatio=10,
        speckleWindowSize=100,
        speckleRange=32,
        preFilterCap=63,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY
    )
    
    right_matcher = cv2.ximgproc.createRightMatcher(stereo)
    wls_filter = cv2.ximgproc.createDisparityWLSFilter(matcher_left=stereo)
    wls_filter.setLambda(8000)
    wls_filter.setSigmaColor(1.5)
    
    escala = 0.5
    gray_izq_orig = cv2.cvtColor(img_izq_orig, cv2.COLOR_BGR2GRAY)
    gray_der_orig = cv2.cvtColor(img_der_orig, cv2.COLOR_BGR2GRAY)
    
    desfases = [-9, -6, -3, 0, 3, 6, 9]
    for dy in desfases:
        gray_der = gray_der_orig.copy()
        if dy != 0:
            M = np.float32([[1, 0, 0], [0, 1, dy]])
            gray_der = cv2.warpAffine(gray_der, M, (gray_der.shape[1], gray_der.shape[0]))
            
        gray_izq_peq = cv2.resize(gray_izq_orig, (0,0), fx=escala, fy=escala)
        gray_der_peq = cv2.resize(gray_der, (0,0), fx=escala, fy=escala)
        
        disp_izq_peq = stereo.compute(gray_izq_peq, gray_der_peq)
        disp_der_peq = right_matcher.compute(gray_der_peq, gray_izq_peq)
        
        disp_izq = cv2.resize(disp_izq_peq, (img_izq_orig.shape[1], img_izq_orig.shape[0]), interpolation=cv2.INTER_NEAREST)
        disp_der = cv2.resize(disp_der_peq, (img_der_orig.shape[1], img_der_orig.shape[0]), interpolation=cv2.INTER_NEAREST)
        
        disp_izq = np.int16(disp_izq / escala)
        disp_der = np.int16(disp_der / escala)
        
        disp_filtrada = wls_filter.filter(disp_izq, img_izq_orig, None, disp_der)
        disparidad_float = disp_filtrada.astype(np.float32) / 16.0
        
        disp_fija = np.clip(disparidad_float, 0, 30)
        disp_visual = np.uint8(disp_fija * (255.0 / 30))
        
        mapa_color = cv2.applyColorMap(disp_visual, cv2.COLORMAP_JET)
        mapa_color[disparidad_float <= 0] = [0, 0, 0]
        
        cv2.putText(mapa_color, f"Y={dy}px", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
        pantalla_dividida = np.hstack((img_izq_orig, mapa_color))
        
        cv2.imwrite(f"sweep_{dy}.png", pantalla_dividida)
        print(f"Guardado sweep_{dy}.png")

if __name__ == "__main__":
    main()
