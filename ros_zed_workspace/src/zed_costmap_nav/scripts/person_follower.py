#!/usr/bin/env python3
"""Modo seguimiento de personas (RF-10).

- Publica /person_follow/detections (std_msgs/String, JSON) con las personas
  que ve la ZED 2i: ID de seguimiento, recuadro normalizado y distancia. La
  pantalla seguir.html lo dibuja sobre la imagen de la camara.
- Escucha /person_follow/target_id (std_msgs/Int32): el ID que el operador
  eligio con un clic. -1 = dejar de seguir.
- Mientras sigue a alguien publica /cmd_vel_nav (el mismo topico que
  move_base), asi pasa igual por speed_moderator.py antes de llegar a
  /cmd_vel. Al elegir un objetivo cancela el goal de move_base para que no
  haya dos nodos mandando velocidad a la vez.
- Publica /person_follow/status (std_msgs/String): inactivo | siguiendo |
  objetivo perdido.

La logica (a quien seguir, que velocidad mandar, cuando declararlo perdido)
vive en follow_logic.py, sin ROS, y se prueba con test_follow_logic.py."""
import json
import math
import os
import sys

import rospy
from actionlib_msgs.msg import GoalID
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32, String
from zed_interfaces.msg import ObjectsStamped

# rosrun/roslaunch ejecuta este archivo a traves del wrapper de devel/lib, asi
# que la carpeta scripts/ no queda en sys.path por si sola.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import follow_logic as fl  # noqa: E402

# Resolucion de captura de la ZED segun general/grab_resolution del wrapper.
# Los recuadros 2D del SDK vienen en pixeles de esa resolucion.
GRAB_RESOLUTIONS = {
    'HD2K': (2208, 1242),
    'HD1080': (1920, 1080),
    'HD720': (1280, 720),
    'VGA': (672, 376),
}

state = {'persons': []}


def objects_cb(msg, ctx):
    persons = []
    for obj in msg.objects:
        if not fl.is_person(obj.label) or not obj.tracking_available:
            continue
        corners = [(c.kp[0], c.kp[1]) for c in obj.bounding_box_2d.corners]
        p = {'id': int(obj.label_id), 'x': float(obj.position[0]), 'y': float(obj.position[1]),
             'bbox': [round(v, 4) for v in fl.normalize_bbox(corners, *ctx['img_size'])]}
        # dist None (null en el JSON) si la ZED no dio posicion valida: NaN no es JSON
        # valido y el JSON.parse de seguir.js falla con el mensaje entero.
        p['dist'] = round(math.hypot(p['x'], p['y']), 2) if fl.has_position(p) else None
        persons.append(p)
    state['persons'] = persons
    ctx['det_pub'].publish(String(data=json.dumps({
        'stamp': msg.header.stamp.to_sec(),
        'target_id': ctx['follow'].target_id,
        'persons': [{k: p[k] for k in ('id', 'dist', 'bbox')} for p in persons],
    })))


def target_cb(msg, ctx):
    ctx['follow'].set_target(msg.data, rospy.get_time())
    if msg.data >= 0:
        ctx['cancel_pub'].publish(GoalID())  # GoalID vacio = cancelar todos
        rospy.loginfo("person_follower: siguiendo a la persona %d", msg.data)
    else:
        ctx['cmd_pub'].publish(Twist())  # frenar al dejar de seguir
        rospy.loginfo("person_follower: seguimiento cancelado")


def control_loop(_event, ctx):
    status, cmd = ctx['follow'].update(state['persons'], rospy.get_time(), ctx['follow_dist'])
    ctx['status_pub'].publish(String(data=status))
    if cmd is None:
        return  # modo normal: no pisar lo que publica move_base
    out = Twist()
    out.linear.x, out.angular.z = cmd
    ctx['cmd_pub'].publish(out)


if __name__ == '__main__':
    rospy.init_node('person_follower')
    grab = rospy.get_param('/zed/zed_node/general/grab_resolution', 'HD720')
    ctx = {
        'img_size': GRAB_RESOLUTIONS.get(grab, GRAB_RESOLUTIONS['HD720']),
        'follow_dist': rospy.get_param('~follow_distance', fl.DEFAULT_FOLLOW_DIST),
        'follow': fl.FollowState(rospy.get_param('~lost_timeout', fl.LOST_TIMEOUT)),
        'det_pub': rospy.Publisher('/person_follow/detections', String, queue_size=1),
        'status_pub': rospy.Publisher('/person_follow/status', String, queue_size=1, latch=True),
        'cmd_pub': rospy.Publisher('/cmd_vel_nav', Twist, queue_size=1),
        'cancel_pub': rospy.Publisher('/move_base/cancel', GoalID, queue_size=1),
    }
    rospy.Subscriber('/zed/zed_node/obj_det/objects', ObjectsStamped, objects_cb, callback_args=ctx, queue_size=1)
    rospy.Subscriber('/person_follow/target_id', Int32, target_cb, callback_args=ctx, queue_size=1)
    rospy.Timer(rospy.Duration(0.1), lambda e: control_loop(e, ctx))  # 10 Hz
    rospy.loginfo("person_follower: activo (captura %s, distancia %.1f m)", grab, ctx['follow_dist'])
    rospy.spin()
