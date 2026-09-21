#!/usr/bin/env python3
"""Inferencia en vivo (Fase 2.3): corre DESPUES de haber entrenado un modelo
con traversability_train.py -- no entrena nada, solo lo usa. Toma la cámara
en tiempo real, corre la red (ONNX, vía onnxruntime; en la Jetson conviene
convertir a TensorRT para más velocidad, ver traversability_train.py) y
publica una capa de costmap con costo BAJO donde el modelo reconoce terreno
transitable, sin llegar a costo letal en el resto -- es una preferencia
aditiva sobre el costmap que ya existe (obstáculos + zona de exclusión), no
un reemplazo (mismo principio de "capas aditivas" del resto del stack).

Si no existe un modelo entrenado todavía (model.onnx no existe), este nodo
no arranca -- así no rompe la navegación actual, que sigue funcionando sin
esta capa hasta que haya un modelo real (ver navigation.launch,
arg use_learned_traversability).

Uso:
    roslaunch zed_costmap_nav navigation.launch use_learned_traversability:=true
"""
import os
import sys

import cv2
import numpy as np
import rospy
import tf2_ros
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import Image, CameraInfo

sys.path.insert(0, os.path.dirname(__file__))
import traversability_label as tl

IMG_SIZE = (256, 256)  # tiene que coincidir con traversability_train.py
WIDTH_M = 10.0
RESOLUTION = 0.05
SIZE = int(WIDTH_M / RESOLUTION)
STRIDE_PX = 4
MAX_SOFT_COST = 50  # preferencia, no prohibicion (nunca llega a 100/letal)


def image_msg_to_bgr(msg):
    """Mismo parseo manual que depth_to_heatmap.py -- se evita cv_bridge a
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


class TraversabilityInfer:
    def __init__(self, model_path):
        import onnxruntime as ort
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name

        self.tf_buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.tf_buffer)
        self.pub = rospy.Publisher('/learned_traversability_costmap', OccupancyGrid, queue_size=1)

        self.fx = self.fy = self.cx = self.cy = None
        self.last_depth = None
        self.last_depth_frame = None
        self.last_depth_stamp = None

        rospy.Subscriber('/zed/zed_node/rgb/camera_info', CameraInfo, self.on_camera_info, queue_size=1)
        rospy.Subscriber('/zed/zed_node/depth/depth_registered', Image, self.on_depth, queue_size=1)
        rospy.Subscriber('/zed/zed_node/rgb/image_rect_color', Image, self.on_rgb, queue_size=1)

        rospy.loginfo("traversability_infer_node: modelo cargado desde %s", model_path)

    def on_camera_info(self, msg):
        self.fx, self.fy = msg.K[0], msg.K[4]
        self.cx, self.cy = msg.K[2], msg.K[5]

    def on_depth(self, msg):
        try:
            self.last_depth = depth_msg_to_meters(msg)
        except ValueError as e:
            rospy.logwarn_throttle(5, "traversability_infer_node: %s", e)
            return
        self.last_depth_frame = msg.header.frame_id
        self.last_depth_stamp = msg.header.stamp

    def on_rgb(self, msg):
        if self.fx is None or self.last_depth is None:
            return

        try:
            rgb = image_msg_to_bgr(msg)
        except ValueError as e:
            rospy.logwarn_throttle(5, "traversability_infer_node: %s", e)
            return

        orig_h, orig_w = rgb.shape[:2]
        inp = cv2.resize(rgb, (IMG_SIZE[1], IMG_SIZE[0]))
        inp = cv2.cvtColor(inp, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[None, ...]  # 1x3xHxW

        logits = self.session.run(None, {self.input_name: inp})[0]  # 1x1xHxW
        prob = 1.0 / (1.0 + np.exp(-logits[0, 0]))  # sigmoid -> prob de transitable
        prob_full = cv2.resize(prob, (orig_w, orig_h))

        try:
            trans = self.tf_buffer.lookup_transform(
                'odom', self.last_depth_frame, self.last_depth_stamp, rospy.Duration(0.2))
            robot_tf = self.tf_buffer.lookup_transform('odom', 'base_link', rospy.Time(0), rospy.Duration(0.2))
        except Exception as e:
            rospy.logwarn_throttle(5, "traversability_infer_node: sin TF (%s)", e)
            return

        t = trans.transform.translation
        q = trans.transform.rotation
        rotation = tl.quat_to_rotation_matrix(q.x, q.y, q.z, q.w)
        translation = (t.x, t.y, t.z)
        cx_robot = robot_tf.transform.translation.x
        cy_robot = robot_tf.transform.translation.y

        ox = cx_robot - WIDTH_M / 2.0
        oy = cy_robot - WIDTH_M / 2.0
        grid = np.full((SIZE, SIZE), -1, dtype=np.int8)  # -1 = desconocido (no opina) por defecto

        depth = self.last_depth
        h, w = depth.shape[:2]
        for v in range(0, h, STRIDE_PX):
            for u in range(0, w, STRIDE_PX):
                d = float(depth[v, u])
                if not np.isfinite(d) or d <= 0:
                    continue
                p_cam = tl.pixel_to_camera_point(u, v, d, self.fx, self.fy, self.cx, self.cy)
                p_world = tl.apply_transform(p_cam, rotation, translation)
                gx = int((p_world[0] - ox) / RESOLUTION)
                gy = int((p_world[1] - oy) / RESOLUTION)
                if not (0 <= gx < SIZE and 0 <= gy < SIZE):
                    continue
                prob_ij = float(prob_full[v, u])
                cost = int(round((1.0 - prob_ij) * MAX_SOFT_COST))
                grid[gy, gx] = max(grid[gy, gx], cost)

        out = OccupancyGrid()
        out.header.stamp = rospy.Time.now()
        out.header.frame_id = 'odom'
        out.info.resolution = RESOLUTION
        out.info.width = SIZE
        out.info.height = SIZE
        out.info.origin.position.x = ox
        out.info.origin.position.y = oy
        out.info.origin.orientation.w = 1.0
        out.data = grid.flatten(order='C').tolist()
        self.pub.publish(out)


if __name__ == '__main__':
    rospy.init_node('traversability_infer_node')
    model_path = os.environ.get('TRAVERSABILITY_MODEL', os.path.expanduser('~/vad_traversability_dataset/model.onnx'))
    if not os.path.isfile(model_path):
        rospy.logwarn(
            "traversability_infer_node: no existe %s todavia -- "
            "corre traversability_data_collector.py manejando manual, despues "
            "traversability_train.py, y recien ahi esta capa va a tener un modelo "
            "para usar. El resto de la navegacion sigue funcionando sin esta capa.",
            model_path)
        sys.exit(0)
    TraversabilityInfer(model_path)
    rospy.spin()
