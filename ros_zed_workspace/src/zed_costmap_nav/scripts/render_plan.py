#!/usr/bin/env python3
"""Vista cenital (top-down) real del entorno, RELATIVA A LA CAMARA (no al frame
odom): el robot/camara queda abajo del cuadro mirando "hacia arriba", como el
cono de vision real de la ZED (~90 grados hacia adelante) en vez de desperdiciar
la mitad del mapa mostrando el area de atras que la camara nunca ve.

Proyecta la nube de puntos de la ZED (con su color RGB real) vista desde arriba,
superpone el costo real del costmap con un degrade tipo JET, y dibuja el robot +
la ruta planificada por move_base. Se publica como imagen para el dashboard web
(mismo patron que depth_to_heatmap.py)."""
import os
import math
import numpy as np
import cv2
import rospy
import tf2_ros
from sensor_msgs.msg import PointCloud2
from nav_msgs.msg import OccupancyGrid, Path

state = {'costmap': None, 'plan': None, 'cloud': None}

# Ventana a dibujar (metros) y resolucion de salida
WIDTH_M = 6.0
HEIGHT_M = 6.0
PIXELS_PER_M = 100  # 1cm/pixel de salida
WIDTH_PX = int(WIDTH_M * PIXELS_PER_M)
HEIGHT_PX = int(HEIGHT_M * PIXELS_PER_M)
# El robot/camara se dibuja cerca del borde inferior, no en el centro, porque
# la ZED solo ve hacia adelante (~90 grados) - todo lo de "atras" nunca se ve.
ROBOT_ROW = int(HEIGHT_PX * 0.9)
ROBOT_COL = WIDTH_PX // 2

tf_buffer = None


def costmap_cb(msg):
    state['costmap'] = msg


def plan_cb(msg):
    state['plan'] = msg


def cloud_cb(msg):
    state['cloud'] = msg


def transform_matrix(trans):
    t = trans.transform.translation
    q = trans.transform.rotation
    x, y, z, w = q.x, q.y, q.z, q.w
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)
    T = np.array([t.x, t.y, t.z], dtype=np.float64)
    return R, T


def yaw_from_quat(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def world_to_px(wx, wy, cx, cy, yaw):
    """Convierte coordenadas del frame odom a pixeles relativos al robot,
    con 'adelante' del robot siempre apuntando hacia arriba de la imagen."""
    dx = wx - cx
    dy = wy - cy
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    forward = dx * cos_y + dy * sin_y
    right = dx * sin_y - dy * cos_y
    col = ROBOT_COL + right * PIXELS_PER_M
    row = ROBOT_ROW - forward * PIXELS_PER_M
    return col, row


def render(_event):
    cloud_msg = state['cloud']
    costmap_msg = state['costmap']
    if cloud_msg is None:
        return

    try:
        trans = tf_buffer.lookup_transform('odom', cloud_msg.header.frame_id,
                                            rospy.Time(0), rospy.Duration(0.2))
    except Exception as e:
        rospy.logwarn_throttle(5, "render_plan: sin TF odom<-%s (%s)", cloud_msg.header.frame_id, e)
        return
    R, T = transform_matrix(trans)

    try:
        rt = tf_buffer.lookup_transform('odom', 'base_link', rospy.Time(0), rospy.Duration(0.2))
        cx = rt.transform.translation.x
        cy = rt.transform.translation.y
        yaw = yaw_from_quat(rt.transform.rotation)
    except Exception:
        cx, cy, yaw = T[0], T[1], 0.0

    cos_y, sin_y = math.cos(yaw), math.sin(yaw)

    # Parsear PointCloud2 crudo: layout ZED = x,y,z (float32) + rgb empaquetado (float32/uint32)
    raw = np.frombuffer(cloud_msg.data, dtype=np.uint8)
    n_points = cloud_msg.width * cloud_msg.height
    raw = raw.reshape(n_points, cloud_msg.point_step)

    xyz = raw[:, 0:12].copy().view(np.float32).reshape(n_points, 3)
    rgb_u32 = raw[:, 12:16].copy().view(np.uint32).reshape(n_points)
    r = ((rgb_u32 >> 16) & 0xFF).astype(np.uint8)
    g = ((rgb_u32 >> 8) & 0xFF).astype(np.uint8)
    b = (rgb_u32 & 0xFF).astype(np.uint8)

    valid = np.isfinite(xyz).all(axis=1)
    xyz = xyz[valid]
    r, g, b = r[valid], g[valid], b[valid]
    if xyz.shape[0] == 0:
        return

    # Camara -> odom (submuestreo para que el proyecto sea rapido y no compita
    # tanto por CPU con move_base en este Jetson de pocos nucleos)
    step = 4
    xyz = xyz[::step]
    r, g, b = r[::step], g[::step], b[::step]
    world = (R @ xyz.T).T + T
    wx, wy, wz = world[:, 0], world[:, 1], world[:, 2]

    # Filtrar por altura (descartar techo/ruido muy alto) antes de rotar
    height_mask = (wz < 2.2) & (wz > -0.5)
    wx, wy, wz = wx[height_mask], wy[height_mask], wz[height_mask]
    r, g, b = r[height_mask], g[height_mask], b[height_mask]

    # Rotar a marco robot-relativo (adelante = arriba de la imagen)
    dx, dy = wx - cx, wy - cy
    forward = dx * cos_y + dy * sin_y
    right = dx * sin_y - dy * cos_y

    img = np.full((HEIGHT_PX, WIDTH_PX, 3), 30, dtype=np.uint8)  # fondo = no observado

    cols = (ROBOT_COL + right * PIXELS_PER_M).astype(np.int32)
    rows = (ROBOT_ROW - forward * PIXELS_PER_M).astype(np.int32)
    ok = (cols >= 0) & (cols < WIDTH_PX) & (rows >= 0) & (rows < HEIGHT_PX)
    if ok.any():
        colors = np.stack([b[ok], g[ok], r[ok]], axis=1)  # BGR para cv2
        img[rows[ok], cols[ok]] = colors

    # Overlay: costo real del costmap (0-100) con degrade tipo JET (igual paleta que
    # el mapa de calor de profundidad), cada celda pintada como un bloque del
    # tamano real de la celda (no 1 pixel suelto) para que no se vea "punteado".
    if costmap_msg is not None:
        cw = costmap_msg.info.width
        ch = costmap_msg.info.height
        cres = costmap_msg.info.resolution
        cox = costmap_msg.info.origin.position.x
        coy = costmap_msg.info.origin.position.y
        data = np.array(costmap_msg.data, dtype=np.int16).reshape(ch, cw)
        rows_idx, cols_idx = np.where(data > 0)
        if len(rows_idx) > 0:
            values_norm = np.clip(data[rows_idx, cols_idx].astype(np.float32) / 100.0, 0.0, 1.0)
            jet_lut = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(1, 256), cv2.COLORMAP_JET)[0]
            colors = jet_lut[(values_norm * 255).astype(np.uint8)]

            wxo = cox + cols_idx * cres
            wyo = coy + rows_idx * cres
            dxo, dyo = wxo - cx, wyo - cy
            fwdo = dxo * cos_y + dyo * sin_y
            righto = dxo * sin_y - dyo * cos_y
            pc = (ROBOT_COL + righto * PIXELS_PER_M).astype(np.int32)
            pr = (ROBOT_ROW - fwdo * PIXELS_PER_M).astype(np.int32)
            cell_px = max(1, int(round(cres * PIXELS_PER_M)))

            ok2 = (pc >= -cell_px) & (pc < WIDTH_PX) & (pr >= -cell_px) & (pr < HEIGHT_PX)
            pc, pr, colors, values_norm = pc[ok2], pr[ok2], colors[ok2], values_norm[ok2]

            overlay = img.copy()
            alpha_map = np.zeros((HEIGHT_PX, WIDTH_PX), dtype=np.float32)
            for x, y, col, v in zip(pc, pr, colors, values_norm):
                x0, y0 = max(x, 0), max(y, 0)
                x1, y1 = min(x + cell_px, WIDTH_PX), min(y + cell_px, HEIGHT_PX)
                if x1 > x0 and y1 > y0:
                    overlay[y0:y1, x0:x1] = col
                    alpha_map[y0:y1, x0:x1] = 0.25 + 0.55 * v
            alpha_3ch = alpha_map[:, :, None]
            img[:] = (img * (1 - alpha_3ch) + overlay * alpha_3ch).astype(np.uint8)

    # Cono de vision aproximado de la ZED (~90 grados) para que se entienda
    # visualmente por que el resto del cuadro queda vacio
    cone_len = max(WIDTH_PX, HEIGHT_PX)
    p1 = (int(ROBOT_COL - cone_len * math.tan(math.radians(45))), int(ROBOT_ROW - cone_len))
    p2 = (int(ROBOT_COL + cone_len * math.tan(math.radians(45))), int(ROBOT_ROW - cone_len))
    overlay_cone = img.copy()
    cv2.line(overlay_cone, (ROBOT_COL, ROBOT_ROW), p1, (80, 80, 80), 1)
    cv2.line(overlay_cone, (ROBOT_COL, ROBOT_ROW), p2, (80, 80, 80), 1)
    img[:] = cv2.addWeighted(overlay_cone, 0.6, img, 0.4, 0)

    # Robot (abajo, mirando hacia arriba) y ruta planificada
    cv2.circle(img, (ROBOT_COL, ROBOT_ROW), 8, (255, 50, 0), -1)
    tri = np.array([[ROBOT_COL, ROBOT_ROW - 16], [ROBOT_COL - 8, ROBOT_ROW + 4], [ROBOT_COL + 8, ROBOT_ROW + 4]])
    cv2.fillConvexPoly(img, tri, (255, 50, 0))
    cv2.putText(img, "ROBOT", (ROBOT_COL + 12, ROBOT_ROW), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 50, 0), 2)

    plan_msg = state['plan']
    if plan_msg is not None and len(plan_msg.poses) > 1:
        pts = [world_to_px(p.pose.position.x, p.pose.position.y, cx, cy, yaw) for p in plan_msg.poses]
        pts = [(int(x), int(y)) for x, y in pts]
        for i in range(len(pts) - 1):
            cv2.line(img, pts[i], pts[i + 1], (0, 255, 0), 3)
        gx, gy = pts[-1]
        cv2.circle(img, (gx, gy), 8, (0, 255, 0), -1)
        cv2.putText(img, "META", (gx + 10, gy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    temp_path = "/app/web_dashboard/plan_demo_temp.png"
    final_path = "/app/web_dashboard/plan_demo.png"
    cv2.imwrite(temp_path, img)
    os.rename(temp_path, final_path)


if __name__ == '__main__':
    rospy.init_node('render_plan')
    tf_buffer = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buffer)
    rospy.Subscriber('/move_base/local_costmap/costmap', OccupancyGrid, costmap_cb)
    rospy.Subscriber('/move_base/TrajectoryPlannerROS/global_plan', Path, plan_cb)
    rospy.Subscriber('/zed/zed_node/point_cloud/cloud_registered', PointCloud2, cloud_cb, queue_size=1)
    rospy.Timer(rospy.Duration(2.0), render)
    rospy.loginfo("render_plan: publicando vista relativa a la camara (robot abajo) en /app/web_dashboard/plan_demo.png")
    rospy.spin()
