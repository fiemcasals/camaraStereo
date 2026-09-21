#!/usr/bin/env python3
"""Recoleccion de datos para el entrenamiento auto-supervisado de
transitabilidad (Fase 2.3): corre MIENTRAS SE MANEJA MANUAL, no entrena nada
en vivo -- solo guarda a disco pares (imagen RGB, mascara de etiquetas) por
frame, usando la geometria de traversability_label.py. El entrenamiento en si
es un paso aparte (traversability_train.py), corrido despues, offline.

Por que no se entrena mientras se maneja: el entrenamiento pesa mucho mas que
la inferencia y competiria por la misma Jetson que esta corriendo la
navegacion; y un tramo mal etiquetado en vivo podria arruinar el modelo sin
posibilidad de revisar antes. Coleccionar-despues-entrenar es como lo hace
cualquier sistema real de este tipo (ver charla del plan, seccion Fase 2.3).

Uso:
    roslaunch zed_costmap_nav collect_traversability.launch

Guarda en ~/vad_traversability_dataset/<timestamp>/:
    rgb.jpg     - imagen de color del frame
    labels.npy  - array Nx3 de (u, v, label) con label in {+1 positivo, -1 negativo}
"""
import os
import sys
import time

import cv2
import numpy as np
import rospy
import tf2_ros
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image, CameraInfo

sys.path.insert(0, os.path.dirname(__file__))
import traversability_label as tl

DATASET_DIR = os.path.expanduser("~/vad_traversability_dataset")
SAVE_PERIOD_S = 0.5          # como mucho 2 frames por segundo -- de sobra para entrenar despues
MIN_LINEAR_SPEED = 0.05      # m/s: si no se esta moviendo, no vale la pena guardar el frame
STRIDE_PX = 4                # etiquetar 1 de cada 4 pixeles (ver traversability_label.label_frame)


def image_msg_to_bgr(msg):
    """Igual al parseo manual de depth_to_heatmap.py -- se evita cv_bridge a
    proposito en este proyecto (ver ese archivo)."""
    if msg.encoding == 'bgra8':
        img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 4)
        return img[:, :, :3]
    if msg.encoding == 'bgr8':
        return np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
    if msg.encoding == 'rgb8':
        img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    raise ValueError(f"encoding de imagen no soportado: {msg.encoding}")


def depth_msg_to_meters(msg):
    if msg.encoding == '32FC1':
        return np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
    if msg.encoding == '16UC1':
        d = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
        return d.astype(np.float32) / 1000.0
    raise ValueError(f"encoding de profundidad no soportado: {msg.encoding}")


class TraversabilityCollector:
    def __init__(self):
        self.tf_buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.tf_buffer)

        self.fx = self.fy = self.cx = self.cy = None
        self.last_rgb_msg = None
        self.last_cmd_speed = 0.0
        self.last_save_t = 0.0
        self.saved_count = 0

        os.makedirs(DATASET_DIR, exist_ok=True)

        rospy.Subscriber('/zed/zed_node/rgb/camera_info', CameraInfo, self.on_camera_info, queue_size=1)
        rospy.Subscriber('/zed/zed_node/rgb/image_rect_color', Image, self.on_rgb, queue_size=1)
        rospy.Subscriber('/zed/zed_node/depth/depth_registered', Image, self.on_depth, queue_size=1)
        rospy.Subscriber('/cmd_vel', Twist, self.on_cmd_vel, queue_size=1)

        rospy.loginfo("traversability_data_collector: guardando en %s (maneja manual para recolectar)",
                       DATASET_DIR)

    def on_camera_info(self, msg):
        self.fx, self.fy = msg.K[0], msg.K[4]
        self.cx, self.cy = msg.K[2], msg.K[5]

    def on_cmd_vel(self, msg):
        self.last_cmd_speed = abs(msg.linear.x)

    def on_rgb(self, msg):
        self.last_rgb_msg = msg

    def on_depth(self, msg):
        if self.fx is None or self.last_rgb_msg is None:
            return
        now = time.time()
        if now - self.last_save_t < SAVE_PERIOD_S:
            return
        if self.last_cmd_speed < MIN_LINEAR_SPEED:
            return  # parado: no aporta nada nuevo, y evita sobre-representar el mismo lugar

        try:
            trans = self.tf_buffer.lookup_transform(
                'base_link', msg.header.frame_id, msg.header.stamp, rospy.Duration(0.2))
        except Exception as e:
            rospy.logwarn_throttle(5, "traversability_data_collector: sin TF camara->base_link (%s)", e)
            return

        t = trans.transform.translation
        q = trans.transform.rotation
        rotation = tl.quat_to_rotation_matrix(q.x, q.y, q.z, q.w)
        translation = (t.x, t.y, t.z)

        try:
            depth_img = depth_msg_to_meters(msg)
        except ValueError as e:
            rospy.logwarn_throttle(5, "traversability_data_collector: %s", e)
            return
        height_px, width_px = depth_img.shape[:2]

        def depth_get(u, v):
            d = float(depth_img[v, u])
            return d if np.isfinite(d) and d > 0 else 0.0

        samples = tl.label_frame(depth_get, width_px, height_px, fx=self.fx, fy=self.fy,
                                  cx=self.cx, cy=self.cy, rotation=rotation, translation=translation,
                                  stride=STRIDE_PX)
        n_pos = sum(1 for s in samples if s[2] == tl.POSITIVE)
        n_neg = sum(1 for s in samples if s[2] == tl.NEGATIVE)
        if n_pos == 0 and n_neg == 0:
            return  # frame sin ninguna etiqueta util (ej. mirando al cielo), no vale guardarlo

        try:
            rgb_img = image_msg_to_bgr(self.last_rgb_msg)
        except ValueError as e:
            rospy.logwarn_throttle(5, "traversability_data_collector: %s", e)
            return

        sample_dir = os.path.join(DATASET_DIR, f"{now:.3f}")
        os.makedirs(sample_dir, exist_ok=True)
        cv2.imwrite(os.path.join(sample_dir, "rgb.jpg"), rgb_img)
        np.save(os.path.join(sample_dir, "labels.npy"), np.array(samples, dtype=np.int32))

        self.last_save_t = now
        self.saved_count += 1
        rospy.loginfo_throttle(
            5, "traversability_data_collector: %d frames guardados (ultimo: %d positivos, %d negativos)",
            self.saved_count, n_pos, n_neg)


if __name__ == '__main__':
    rospy.init_node('traversability_data_collector')
    TraversabilityCollector()
    rospy.spin()
