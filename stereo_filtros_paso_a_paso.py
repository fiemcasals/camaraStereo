import cv2
import numpy as np
import matplotlib.pyplot as plt

def create_noisy_low_contrast_image():
    """
    Crea una imagen sintética pero le agrega defectos intencionales 
    (poco contraste y ruido) para que podamos ver el efecto de los filtros.
    """
    height, width = 400, 400
    
    # 1. Fondo base (gris oscuro, poco contraste)
    np.random.seed(42)
    background = np.random.randint(50, 100, (height, width), dtype=np.uint8)
    
    # 2. Objeto (un poco más claro, pero sigue con poco contraste)
    object_size = 100
    object_texture = np.random.randint(80, 130, (object_size, object_size), dtype=np.uint8)
    
    # Imagen Izquierda
    img_left = background.copy()
    x_left, y_pos = 150, 150
    img_left[y_pos:y_pos+object_size, x_left:x_left+object_size] = object_texture
    
    # Imagen Derecha
    img_right = background.copy()
    disparity = 30
    x_right = x_left - disparity
    img_right[y_pos:y_pos+object_size, x_right:x_right+object_size] = object_texture
    
    # 3. Agregar ruido de "Sal y Pimienta" para simular un sensor de cámara barato o de noche
    noise_left = np.random.randint(0, 50, (height, width), dtype=np.uint8)
    noise_right = np.random.randint(0, 50, (height, width), dtype=np.uint8)
    
    img_left = cv2.add(img_left, noise_left)
    img_right = cv2.add(img_right, noise_right)
    
    return img_left, img_right

def main():
    print("1. Generando imágenes base (con ruido y bajo contraste)...")
    base_left, base_right = create_noisy_low_contrast_image()
    
    # --- PROCESO PASO A PASO ---
    
    # PASO 1: Imagen Base (ya la tenemos en grises, pero si fuera a color, aquí se convertiría)
    # cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    print("2. Aplicando Ecualización de Histograma (Mejora de Contraste)...")
    # PASO 2: Ecualización
    # Esto "estira" los colores para que los oscuros sean más oscuros y los claros más claros.
    # Ayuda muchísimo al algoritmo a encontrar características (bordes, texturas).
    eq_left = cv2.equalizeHist(base_left)
    eq_right = cv2.equalizeHist(base_right)
    
    print("3. Aplicando Filtro Gaussiano (Reducción de Ruido)...")
    # PASO 3: Desenfoque (Blur) Gaussiano
    # El ruido que agregamos antes confunde a la Inteligencia Artificial.
    # El blur suaviza la imagen eliminando ese ruido de grano.
    # (5, 5) es el tamaño del "pincel" de suavizado.
    blur_left = cv2.GaussianBlur(eq_left, (5, 5), 0)
    blur_right = cv2.GaussianBlur(eq_right, (5, 5), 0)
    
    print("4. Aplicando Algoritmo StereoSGBM sobre las imágenes filtradas...")
    # PASO 4: Cálculo de Disparidad (con las imágenes ya limpias)
    stereo = cv2.StereoSGBM_create(
        minDisparity=0,
        numDisparities=64,
        blockSize=5,
        P1=8 * 1 * 5**2,
        P2=32 * 1 * 5**2,
        disp12MaxDiff=1,
        uniquenessRatio=10,
        speckleWindowSize=100,
        speckleRange=32
    )
    
    # Calculamos el mapa final
    disparity_map = stereo.compute(blur_left, blur_right).astype(np.float32) / 16.0
    
    # --- VISUALIZACIÓN DEL PROCESO ---
    print("5. Generando el gráfico comparativo del proceso...")
    
    plt.figure(figsize=(15, 12))
    plt.suptitle("Proceso de Filtros para Visión Estéreo (Paso a Paso)", fontsize=18)
    
    # Fila 1: Imagen Original (Base)
    plt.subplot(3, 2, 1)
    plt.title("1. Base Izquierda (Mucho Ruido / Poco Contraste)")
    plt.imshow(base_left, cmap='gray', vmin=0, vmax=255)
    plt.axis('off')
    
    plt.subplot(3, 2, 2)
    plt.title("1. Base Derecha")
    plt.imshow(base_right, cmap='gray', vmin=0, vmax=255)
    plt.axis('off')
    
    # Fila 2: Ecualización
    plt.subplot(3, 2, 3)
    plt.title("2. Ecualización Izquierda (Mejora Contraste)")
    plt.imshow(eq_left, cmap='gray', vmin=0, vmax=255)
    plt.axis('off')
    
    plt.subplot(3, 2, 4)
    plt.title("2. Ecualización Derecha")
    plt.imshow(eq_right, cmap='gray', vmin=0, vmax=255)
    plt.axis('off')
    
    # Fila 3: Suavizado y Resultado
    plt.subplot(3, 2, 5)
    plt.title("3. Desenfoque Gaussiano Izq (Elimina Ruido)")
    plt.imshow(blur_left, cmap='gray', vmin=0, vmax=255)
    plt.axis('off')
    
    plt.subplot(3, 2, 6)
    plt.title("4. RESULTADO: Mapa de Disparidad Final")
    plt.imshow(disparity_map, cmap='jet')
    plt.colorbar(label='Píxeles de Disparidad')
    plt.axis('off')
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95]) # Ajuste para el título principal
    nombre_archivo = 'paso_a_paso_filtros.png'
    plt.savefig(nombre_archivo)
    print(f"Imagen guardada exitosamente como '{nombre_archivo}'")

if __name__ == "__main__":
    main()
