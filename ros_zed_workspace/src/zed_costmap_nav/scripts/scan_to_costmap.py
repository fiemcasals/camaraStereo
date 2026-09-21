#!/usr/bin/env python3
"""Workaround para un bug no resuelto de costmap_2d::ObstacleLayer en esta build
(ROS Noetic, imagen stereolabs/zed:5.2.3-devel-l4t-r35.4): el marcado de
obstaculos vive completamente en cero pase lo que pase, a pesar de que el /scan,
el TF y la config de la capa estan todos verificados correctos (con rviz,
rqt_reconfigure, y chequeos matematicos directos).

En vez de depender de esa capa, este nodo arma un nav_msgs/OccupancyGrid
completo a mano a partir del /scan y lo publica en /scan_costmap. move_base
consume ese grid con costmap_2d::StaticLayer en vez de ObstacleLayer -
StaticLayer reemplaza el grid entero en cada mensaje nuevo en vez de
marcar/limpiar celda por celda, evitando la logica rota.

Si en el futuro se identifica y arregla el bug real de ObstacleLayer, este
nodo y el StaticLayer correspondiente se pueden retirar sin tocar nada mas
del stack (el resto de move_base no sabe ni le importa de donde sale el grid).
"""
import math

import numpy as np
import rospy
import tf2_ros
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan

WIDTH_M = 10.0
RESOLUTION = 0.05
SIZE = int(WIDTH_M / RESOLUTION)


def quat_to_rotation_matrix(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


class ScanToCostmap:
    def __init__(self):
        self.tf_buffer = tf2_ros.Buffer()
        tf2_ros.TransformListener(self.tf_buffer)
        self.pub = rospy.Publisher('/scan_costmap', OccupancyGrid, queue_size=1)
        rospy.Subscriber('/scan', LaserScan, self.on_scan, queue_size=1)

    def on_scan(self, msg):
        try:
            trans = self.tf_buffer.lookup_transform(
                'odom', msg.header.frame_id, msg.header.stamp, rospy.Duration(0.3))
        except Exception as e:
            rospy.logwarn_throttle(5, "scan_to_costmap: sin TF (%s)", e)
            return

        t = trans.transform.translation
        q = trans.transform.rotation
        R = quat_to_rotation_matrix(q.x, q.y, q.z, q.w)
        T = np.array([t.x, t.y, t.z])

        try:
            robot_tf = self.tf_buffer.lookup_transform('odom', 'base_link', rospy.Time(0), rospy.Duration(0.3))
            cx, cy = robot_tf.transform.translation.x, robot_tf.transform.translation.y
        except Exception:
            cx, cy = t.x, t.y

        ox = cx - WIDTH_M / 2.0
        oy = cy - WIDTH_M / 2.0
        grid = np.zeros((SIZE, SIZE), dtype=np.int8)

        for i, r in enumerate(msg.ranges):
            if not math.isfinite(r) or r < msg.range_min or r > msg.range_max:
                continue
            ang = msg.angle_min + i * msg.angle_increment
            p_sensor = np.array([r * math.cos(ang), r * math.sin(ang), 0.0])
            p_world = R.dot(p_sensor) + T
            gx = int((p_world[0] - ox) / RESOLUTION)
            gy = int((p_world[1] - oy) / RESOLUTION)
            if 0 <= gx < SIZE and 0 <= gy < SIZE:
                grid[gy, gx] = 100

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
    rospy.init_node('scan_to_costmap')
    ScanToCostmap()
    rospy.loginfo("scan_to_costmap: workaround activo, publicando /scan_costmap")
    rospy.spin()
