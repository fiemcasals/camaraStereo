import cv2
import numpy as np
import matplotlib.pyplot as plt

def create_synthetic_stereo_images():
    """
    Crea dos imágenes sintéticas (izquierda y derecha) simulando una cámara estéreo.
    El fondo tiene una textura aleatoria (ruido) y el objeto (un cuadrado) tiene otra.
    La textura es esencial para que el algoritmo pueda encontrar similitudes.
    """
    height, width = 400, 400
    
    # 1. Creamos un fondo con textura (ruido aleatorio)
    np.random.seed(42)
    background = np.random.randint(0, 256, (height, width), dtype=np.uint8)
    
    # Suavizamos un poco el fondo para que sea más realista
    background = cv2.GaussianBlur(background, (5, 5), 0)
    
    # 2. Creamos una textura para nuestro objeto (un cuadrado)
    object_size = 100
    object_texture = np.random.randint(0, 256, (object_size, object_size), dtype=np.uint8)
    
    # Imagen Izquierda
    img_left = background.copy()
    # Colocamos el objeto en la posición x=150, y=150
    x_left = 150
    y_pos = 150
    img_left[y_pos:y_pos+object_size, x_left:x_left+object_size] = object_texture
    
    # Imagen Derecha
    img_right = background.copy()
    # Colocamos el objeto desplazado hacia la izquierda (perspectiva de la cámara derecha)
    # Por ejemplo, un desplazamiento (disparidad) de 30 píxeles
    disparity = 30
    x_right = x_left - disparity
    img_right[y_pos:y_pos+object_size, x_right:x_right+object_size] = object_texture
    
    return img_left, img_right

def main():
    print("1. Generando imágenes sintéticas...")
    img_left, img_right = create_synthetic_stereo_images()
    
    # --- FILTROS PREVIOS (Opcional, útil para imágenes reales) ---
    # En un caso real con cámaras, las imágenes pueden tener diferente iluminación o ruido.
    # Filtros comunes antes de calcular disparidad:
    # 1. Convertir a escala de grises (nuestras imágenes ya lo son).
    # 2. Ecualización de histograma para igualar contrastes.
    # img_left = cv2.equalizeHist(img_left)
    # img_right = cv2.equalizeHist(img_right)
    # 3. Desenfoque suave para eliminar ruido de alta frecuencia del sensor de la cámara.
    # img_left = cv2.GaussianBlur(img_left, (3,3), 0)
    # img_right = cv2.GaussianBlur(img_right, (3,3), 0)

    print("2. Configurando el algoritmo de Stereo Matching (StereoSGBM)...")
    # StereoSGBM (Semi-Global Block Matching) es más robusto que StereoBM
    
    block_size = 5  # Tamaño de la ventana de comparación. Impar (3, 5, 7...). Mayor = mapa más suave, menor = bordes más definidos.
    min_disp = 0    # Desplazamiento mínimo (generalmente 0)
    num_disp = 64   # Rango de búsqueda de disparidad. DEBE ser múltiplo de 16. Depende de cuán cerca estén los objetos.
    
    stereo = cv2.StereoSGBM_create(
        minDisparity=min_disp,
        numDisparities=num_disp,
        blockSize=block_size,
        P1=8 * 1 * block_size**2,    # Controla la suavidad del mapa de disparidad.
        P2=32 * 1 * block_size**2,   # Controla la suavidad. P2 debe ser > P1.
        disp12MaxDiff=1,             # Máxima diferencia permitida en el chequeo de consistencia izquierda-derecha.
        uniquenessRatio=10,          # Margen por el cual la mejor coincidencia debe "ganarle" a la segunda mejor. (Filtra ruido).
        speckleWindowSize=100,       # Tamaño máximo de regiones de ruido ("speckles") que serán eliminadas.
        speckleRange=32              # Variación máxima de disparidad dentro de un componente conectado.
    )

    print("3. Calculando el mapa de disparidad...")
    # compute devuelve la disparidad multiplicada por 16 (formato interno de OpenCV). Hay que dividir.
    disparity_map = stereo.compute(img_left, img_right).astype(np.float32) / 16.0
    
    print("4. Calculando la profundidad (Z)...")
    # FÓRMULA MAGICA: Z = (F * B) / D
    # Z = Profundidad (Distancia)
    # F = Distancia Focal de la cámara (en píxeles)
    # B = Línea Base (Baseline) - Distancia física entre las dos cámaras (en metros o cm)
    # D = Disparidad (en píxeles) - Lo que calculamos en el paso anterior
    
    focal_length = 800  # Píxeles (valor inventado para el ejemplo)
    baseline = 0.1      # 0.1 metros (10 cm entre cámaras)
    
    # Evitamos dividir por cero o números negativos
    disparity_map_safe = np.where(disparity_map <= 0, 0.1, disparity_map)
    
    # Calculamos el mapa de profundidad en metros
    depth_map = (focal_length * baseline) / disparity_map_safe
    
    # Limitamos la profundidad para una mejor visualización (ej: objetos entre 0 y 10 metros)
    depth_map = np.clip(depth_map, 0, 10)
    
    print(f" -> La disparidad del objeto central es de ~30 píxeles.")
    print(f" -> Profundidad teórica del objeto = ({focal_length} * {baseline}) / 30 = { (focal_length * baseline)/30 :.2f} metros")

    print("5. Visualizando resultados...")
    plt.figure(figsize=(12, 10))
    
    plt.subplot(2, 2, 1)
    plt.title("Cámara Izquierda")
    plt.imshow(img_left, cmap='gray')
    plt.axis('off')
    
    plt.subplot(2, 2, 2)
    plt.title("Cámara Derecha\n(Notar que el cuadrado se movió a la izquierda)")
    plt.imshow(img_right, cmap='gray')
    plt.axis('off')
    
    plt.subplot(2, 2, 3)
    plt.title("Mapa de Disparidad\n(Más amarillo = Mayor Disparidad = Más cerca)")
    plt.imshow(disparity_map, cmap='jet')
    plt.colorbar(label='Píxeles de Disparidad')
    plt.axis('off')
    
    plt.subplot(2, 2, 4)
    plt.title("Mapa de Profundidad\n(Más azul = Menos Metros = Más cerca)")
    # Usamos cmap='jet_r' (jet invertido) para que los colores cálidos sean lejos y fríos cerca.
    plt.imshow(depth_map, cmap='jet_r') 
    plt.colorbar(label='Profundidad (Metros)')
    plt.axis('off')
    
    plt.tight_layout()
    plt.savefig('resultado_bifoco.png')
    print("Imagen guardada como 'resultado_bifoco.png'. Revisa el directorio para verla.")
    
if __name__ == "__main__":
    main()
