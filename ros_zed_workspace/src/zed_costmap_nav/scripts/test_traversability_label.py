#!/usr/bin/env python3
"""Pruebas del nucleo de etiquetado (traversability_label.py) con escenas
sinteticas: no necesitan ROS, numpy, ni una camara real. Corren en cualquier
maquina con python3 -m unittest test_traversability_label."""
import math
import unittest

import traversability_label as tl

# Camara "de juguete" apuntando al piso: 640x480, fx=fy=500, centro en el
# medio de la imagen. Suficiente para las pruebas geometricas, no hace falta
# que coincida con la ZED real.
FX = FY = 500.0
CX, CY = 320.0, 240.0
WIDTH, HEIGHT = 640, 480

# Camara montada 0.5m sobre el piso, mirando derecho hacia adelante y hacia
# abajo 20 grados (pitch), centrada en x=0 de base_link (offset simple).
CAMERA_HEIGHT = 0.5
PITCH_DEG = 20.0


def camera_to_base_link_transform():
    """Rotacion+traslacion de 'frame optico de camara' a base_link, para una
    camara que mira hacia adelante e inclinada hacia abajo. En el frame
    optico: x-derecha, y-abajo, z-adelante. En base_link (REP-103):
    x-adelante, y-izquierda, z-arriba."""
    pitch = math.radians(PITCH_DEG)
    # Rotacion base: optico -> base_link "nivelado" (sin inclinar):
    # x_base = z_opt (adelante), y_base = -x_opt (izquierda), z_base = -y_opt (arriba)
    R_level = (
        (0, 0, 1),
        (-1, 0, 0),
        (0, -1, 0),
    )
    # Encima, la inclinacion hacia abajo de la camara: rotar alrededor del
    # eje y_base (izquierda) para que "adelante" de la camara apunte un poco
    # hacia el piso.
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)
    R_pitch = (
        (cos_p, 0, sin_p),
        (0, 1, 0),
        (-sin_p, 0, cos_p),
    )

    def matmul(a, b):
        return tuple(
            tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
            for i in range(3)
        )

    R = matmul(R_pitch, R_level)
    t = (0.0, 0.0, CAMERA_HEIGHT)
    return R, t


ROTATION, TRANSLATION = camera_to_base_link_transform()


def synthetic_flat_ground_depth(u, v):
    """Profundidad de un piso perfectamente plano, visto por esta camara.
    Se resuelve la interseccion del rayo del pixel con el plano z_base=0."""
    # Rayo en el frame optico para este pixel (direccion, no normalizado).
    dx = (u - CX) / FX
    dy = (v - CY) / FY
    dz = 1.0
    # Direccion del rayo en base_link (solo rotacion, sin trasladar).
    rx = ROTATION[0][0] * dx + ROTATION[0][1] * dy + ROTATION[0][2] * dz
    ry = ROTATION[1][0] * dx + ROTATION[1][1] * dy + ROTATION[1][2] * dz
    rz = ROTATION[2][0] * dx + ROTATION[2][1] * dy + ROTATION[2][2] * dz
    if rz >= -1e-9:
        return None  # el rayo no baja hacia el piso (apunta al horizonte o arriba)
    # origen de la camara en base_link = TRANSLATION (altura CAMERA_HEIGHT).
    # Queremos t tal que TRANSLATION[2] + t*rz == 0.
    t = -TRANSLATION[2] / rz
    return t  # t es la "profundidad" a lo largo de z_opt=1 del rayo, coincide con depth


class TestLabelPixel(unittest.TestCase):
    def test_piso_cercano_dentro_del_ancho_es_positivo(self):
        # Un punto en el piso, justo adelante del robot, centrado (lateral=0).
        u, v = CX, CY + 150  # mas abajo en la imagen = mas cerca en el piso
        d = synthetic_flat_ground_depth(u, v)
        self.assertIsNotNone(d)
        label = tl.label_pixel(u, v, d, fx=FX, fy=FY, cx=CX, cy=CY,
                                rotation=ROTATION, translation=TRANSLATION)
        p = tl.apply_transform(tl.pixel_to_camera_point(u, v, d, FX, FY, CX, CY),
                                ROTATION, TRANSLATION)
        # confirmar que el punto realmente cae donde se espera antes de juzgar la etiqueta
        self.assertAlmostEqual(p[2], 0.0, places=6)  # altura ~0 (esta sobre el piso)
        self.assertGreater(p[0], 0)  # adelante del robot
        if 0.4 <= p[0] <= 1.2 and abs(p[1]) <= 0.3:
            self.assertEqual(label, tl.POSITIVE)

    def test_piso_lejano_queda_sin_etiquetar(self):
        # Un punto de piso mucho mas lejos que la ventana "near/far" de confianza.
        u, v = CX, CY + 5  # cerca del horizonte = muy lejos en el piso
        d = synthetic_flat_ground_depth(u, v)
        if d is None or d > 8.0:
            self.skipTest("el rayo no llega a un punto de piso util en este pixel")
        label = tl.label_pixel(u, v, d, fx=FX, fy=FY, cx=CX, cy=CY,
                                rotation=ROTATION, translation=TRANSLATION)
        p = tl.apply_transform(tl.pixel_to_camera_point(u, v, d, FX, FY, CX, CY),
                                ROTATION, TRANSLATION)
        if p[0] > 1.2:
            self.assertEqual(label, tl.UNLABELED)

    def test_piso_fuera_del_ancho_del_chasis_queda_sin_etiquetar(self):
        # Un punto de piso a la misma distancia adelante pero bien a un costado.
        u, v = CX + 400, CY + 150  # corrido mucho a la derecha en la imagen
        d = synthetic_flat_ground_depth(u, v)
        self.assertIsNotNone(d)
        p = tl.apply_transform(tl.pixel_to_camera_point(u, v, d, FX, FY, CX, CY),
                                ROTATION, TRANSLATION)
        label = tl.label_pixel(u, v, d, fx=FX, fy=FY, cx=CX, cy=CY,
                                rotation=ROTATION, translation=TRANSLATION)
        if abs(p[1]) > 0.3:
            self.assertNotEqual(label, tl.POSITIVE)

    def test_pared_alta_es_negativo(self):
        # Un obstaculo real: un punto a 20cm de altura sobre el piso, adelante
        # del robot (ej. un cordon, una maceta), no a la altura del piso.
        # Se simula directamente en base_link y se pasa "hacia atras" a un
        # pixel/profundidad coherente para no depender de una escena de pared
        # completa: se verifica classify_point_base_link, que es donde vive
        # la regla real de "esto es un obstaculo".
        punto_obstaculo = (0.8, 0.0, 0.20)  # 0.8m adelante, centrado, 20cm alto
        label = tl.classify_point_base_link(punto_obstaculo)
        self.assertEqual(label, tl.NEGATIVE)

    def test_piso_perfecto_es_positivo_con_classify_directo(self):
        punto_piso = (0.6, 0.1, 0.0)  # 0.6m adelante, un poco a la izquierda, altura 0
        label = tl.classify_point_base_link(punto_piso)
        self.assertEqual(label, tl.POSITIVE)

    def test_profundidad_invalida_no_opina(self):
        for d in (0.0, -1.0, float('inf'), float('nan'), None):
            label = tl.label_pixel(100, 100, d, fx=FX, fy=FY, cx=CX, cy=CY,
                                    rotation=ROTATION, translation=TRANSLATION)
            self.assertEqual(label, tl.UNLABELED, f"deberia ser UNLABELED para depth={d}")

    def test_detras_del_robot_no_opina(self):
        # forward negativo (algo "detras" de base_link, geometricamente raro
        # para una camara delantera, pero la funcion tiene que ser robusta).
        punto = (-0.5, 0.0, 0.0)
        label = tl.classify_point_base_link(punto)
        self.assertEqual(label, tl.UNLABELED)


class TestLabelFrame(unittest.TestCase):
    def test_frame_sintetico_de_piso_da_mezcla_de_positivo_y_sin_etiquetar(self):
        def depth_get(u, v):
            d = synthetic_flat_ground_depth(u, v)
            return d if d is not None and d < 20.0 else 0.0

        muestras = tl.label_frame(depth_get, WIDTH, HEIGHT, fx=FX, fy=FY, cx=CX, cy=CY,
                                   rotation=ROTATION, translation=TRANSLATION, stride=8)
        positivos = [m for m in muestras if m[2] == tl.POSITIVE]
        negativos = [m for m in muestras if m[2] == tl.NEGATIVE]
        # Un piso perfectamente plano no deberia generar NINGUN negativo (no
        # hay obstaculos en esta escena sintetica).
        self.assertEqual(len(negativos), 0)
        # Y deberia haber al menos algunos positivos (el piso cercano y
        # centrado existe en esta escena).
        self.assertGreater(len(positivos), 0)

    def test_frame_con_pared_agrega_negativos(self):
        WALL_DIST = 1.0  # pared vertical a 1m adelante

        def depth_get(u, v):
            d_ground = synthetic_flat_ground_depth(u, v)
            # Si el rayo del piso cruzaria mas alla de la pared, en cambio se
            # "choca" contra la pared antes: profundidad menor.
            if d_ground is not None and d_ground > WALL_DIST * 1.3:
                return WALL_DIST * 1.3
            return d_ground if d_ground is not None and d_ground < 20.0 else 0.0

        muestras = tl.label_frame(depth_get, WIDTH, HEIGHT, fx=FX, fy=FY, cx=CX, cy=CY,
                                   rotation=ROTATION, translation=TRANSLATION, stride=8)
        negativos = [m for m in muestras if m[2] == tl.NEGATIVE]
        self.assertGreater(len(negativos), 0, "una pared en la escena tendria que generar negativos")


if __name__ == '__main__':
    unittest.main(verbosity=2)
