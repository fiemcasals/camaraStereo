#!/usr/bin/env python3
"""Se interpone entre move_base y auto_driver.py: baja la velocidad cuando hay
personas/animales cerca y adelante, usando la deteccion de objetos nativa de
la ZED (sin correr un YOLO aparte). move_base publica en /cmd_vel_nav (ver
remap en navigation.launch), este nodo republica en /cmd_vel ya escalado, que
es lo que auto_driver.py escucha sin ningun cambio de interfaz."""
import math

import rospy
from geometry_msgs.msg import Twist
from zed_interfaces.msg import ObjectsStamped

# Clases del modelo de deteccion de la ZED (MULTI_CLASS_BOX_ACCURATE) que
# consideramos "sensibles": bajar la velocidad cerca de ellas.
SENSITIVE_LABELS = {'person', 'animal'}

# Distancia (m) a partir de la cual ya no se reduce velocidad, y distancia a
# partir de la cual se frena del todo. Lineal entre las dos.
SAFE_DIST = 3.0
STOP_DIST = 0.8

# Solo se consideran objetos dentro de este cono adelante del robot (medio
# ancho, en metros, a la distancia del objeto) - no frenar por alguien pasando
# lejos al costado.
LATERAL_HALF_WIDTH = 1.0

state = {'scale': 1.0, 'last_objects_stamp': None}


def objects_cb(msg):
    state['last_objects_stamp'] = rospy.Time.now()
    min_scale = 1.0

    for obj in msg.objects:
        label = (obj.label or '').lower()
        if not any(s in label for s in SENSITIVE_LABELS):
            continue
        if not obj.tracking_available:
            continue

        x, y = obj.position[0], obj.position[1]  # x=adelante, y=izquierda (frame de la camara)
        if x <= 0:
            continue  # esta atras, no importa para frenar
        if abs(y) > LATERAL_HALF_WIDTH:
            continue  # esta muy al costado, no esta en el camino

        dist = math.hypot(x, y)
        if dist >= SAFE_DIST:
            scale = 1.0
        elif dist <= STOP_DIST:
            scale = 0.0
        else:
            scale = (dist - STOP_DIST) / (SAFE_DIST - STOP_DIST)

        min_scale = min(min_scale, scale)

    state['scale'] = min_scale


def cmd_vel_cb(msg, pub):
    scale = state['scale']
    out = Twist()
    out.linear.x = msg.linear.x * scale
    out.linear.y = msg.linear.y * scale
    out.linear.z = msg.linear.z
    out.angular.x = msg.angular.x
    out.angular.y = msg.angular.y
    out.angular.z = msg.angular.z  # el giro no se recorta, solo el avance
    pub.publish(out)


if __name__ == '__main__':
    rospy.init_node('speed_moderator')
    pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
    rospy.Subscriber('/zed/zed_node/obj_det/objects', ObjectsStamped, objects_cb, queue_size=1)
    rospy.Subscriber('/cmd_vel_nav', Twist, cmd_vel_cb, callback_args=pub, queue_size=1)
    rospy.loginfo("speed_moderator: activo, escuchando /cmd_vel_nav y /zed/zed_node/obj_det/objects")
    rospy.spin()
