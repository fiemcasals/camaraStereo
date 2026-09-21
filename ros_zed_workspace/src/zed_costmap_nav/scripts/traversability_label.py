#!/usr/bin/env python3
"""Nucleo geometrico del etiquetado auto-supervisado de transitabilidad
(Fase 2.3 del plan de navegacion). Sin ROS ni numpy a proposito -- solo
matematica con listas y tuplas -- para poder probarlo con datos sinteticos
sin depender de la Jetson ni de una camara real, igual que waypoint_router.py.

Idea del etiquetado (ver "Como se entrena" en la conversacion con el
usuario): no se etiqueta nada a mano. Para cada pixel del frame de
profundidad se calcula su punto 3D respecto a base_link, y:

- Si el punto cae en el area de terreno inmediatamente delante del robot,
  dentro del ancho del chasis, y a la altura del piso (sin relieve) ->
  POSITIVO ("esto es transitable", porque el robot esta a punto de pisarlo
  y el resto del stack ya evita obstaculos ahi).
- Si el punto tiene una altura por encima del piso mayor a un umbral (un
  obstaculo real, la misma logica que ya usa el costmap por LiDAR/profundidad)
  -> NEGATIVO.
- Todo lo demas (el terreno lejano, todavia no visitado, sin evidencia de
  obstaculo) -> SIN ETIQUETAR. Es lo que el modelo tiene que aprender a
  generalizar a partir de los ejemplos cercanos (near-to-far).

Version 1 (esta): usa la ventana de profundidad del frame actual. Mejora
futura documentada: trackear el footprint en el tiempo y reproyectarlo hacia
frames pasados para confirmar con mas certeza "el robot paso por aca de
verdad" (self-supervision temporal completa).
"""
import math

POSITIVE = 1
NEGATIVE = -1
UNLABELED = 0


def quat_to_rotation_matrix(x, y, z, w):
    """Igual al helper de scan_to_costmap.py, pero con listas planas (sin
    numpy) para poder usarlo en tests sin esa dependencia."""
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def apply_transform(point, rotation, translation):
    """point: (x,y,z) en el frame origen. rotation: matriz 3x3 (tuplas de
    tuplas). translation: (tx,ty,tz). Devuelve el punto en el frame destino."""
    x, y, z = point
    r = rotation
    return (
        r[0][0] * x + r[0][1] * y + r[0][2] * z + translation[0],
        r[1][0] * x + r[1][1] * y + r[1][2] * z + translation[1],
        r[2][0] * x + r[2][1] * y + r[2][2] * z + translation[2],
    )


def pixel_to_camera_point(u, v, depth, fx, fy, cx, cy):
    """Proyeccion inversa de un pixel + profundidad a un punto 3D en el
    frame optico de la camara (convencion REP-103 para frames opticos:
    x-derecha, y-abajo, z-adelante/profundidad)."""
    x = (u - cx) * depth / fx
    y = (v - cy) * depth / fy
    z = depth
    return (x, y, z)


def classify_point_base_link(point, *, footprint_half_width=0.3,
                              near_dist=0.4, far_dist=1.2,
                              ground_tolerance=0.05, obstacle_height=0.15,
                              max_range=8.0):
    """point: (x,y,z) en base_link (REP-103: x-adelante, y-izquierda,
    z-arriba). Devuelve POSITIVE, NEGATIVE o UNLABELED."""
    forward, lateral, height = point

    if forward <= 0 or forward > max_range:
        return UNLABELED

    if abs(height) >= obstacle_height:
        return NEGATIVE

    if near_dist <= forward <= far_dist and abs(lateral) <= footprint_half_width \
            and abs(height) <= ground_tolerance:
        return POSITIVE

    return UNLABELED


def label_pixel(u, v, depth, *, fx, fy, cx, cy, rotation, translation, **kwargs):
    """Combina pixel_to_camera_point + apply_transform + classify_point_base_link
    para un solo pixel. depth en metros; depth <= 0 o no finito -> UNLABELED
    (sin medicion valida, no se puede opinar)."""
    if depth is None or depth <= 0 or not math.isfinite(depth):
        return UNLABELED
    p_cam = pixel_to_camera_point(u, v, depth, fx, fy, cx, cy)
    p_base = apply_transform(p_cam, rotation, translation)
    return classify_point_base_link(p_base, **kwargs)


def label_frame(depth_get, width, height_px, *, fx, fy, cx, cy, rotation, translation,
                 stride=4, **kwargs):
    """Etiqueta un frame completo. depth_get(u, v) -> profundidad en metros
    (indirection para poder pasar tanto una lista de listas como un array de
    numpy sin que este modulo dependa de numpy). stride: paso en pixeles
    (etiquetar 1 de cada N ahorra computo; no hace falta etiquetar cada pixel
    para entrenar). Devuelve una lista de (u, v, label) para los pixeles
    evaluados que dieron POSITIVE o NEGATIVE (los UNLABELED no se listan,
    total son la mayoria y no aportan nada al entrenamiento)."""
    out = []
    for v in range(0, height_px, stride):
        for u in range(0, width, stride):
            d = depth_get(u, v)
            label = label_pixel(u, v, d, fx=fx, fy=fy, cx=cx, cy=cy,
                                 rotation=rotation, translation=translation, **kwargs)
            if label != UNLABELED:
                out.append((u, v, label))
    return out
