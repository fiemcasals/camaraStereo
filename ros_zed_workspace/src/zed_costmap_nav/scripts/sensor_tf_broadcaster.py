#!/usr/bin/env python3
"""Publica transformadas estaticas base_link -> <sensor> para los sensores
listados en sensor_extrinsics.yaml (bajo additional_sensors). No incluye la
ZED porque esa transformada ya la publica zed_wrapper por su cuenta (ver
comentario en sensor_extrinsics.yaml) - este nodo es para sensores nuevos
(el LiDAR en la Fase 1.3, y lo que se sume despues)."""
import math

import rospy
import tf2_ros
from geometry_msgs.msg import TransformStamped


def quaternion_from_euler(roll, pitch, yaw):
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def build_transform(parent, child, cfg):
    t = TransformStamped()
    t.header.stamp = rospy.Time.now()
    t.header.frame_id = parent
    t.child_frame_id = child
    t.transform.translation.x = cfg.get('x', 0.0)
    t.transform.translation.y = cfg.get('y', 0.0)
    t.transform.translation.z = cfg.get('z', 0.0)
    qx, qy, qz, qw = quaternion_from_euler(
        cfg.get('roll', 0.0), cfg.get('pitch', 0.0), cfg.get('yaw', 0.0))
    t.transform.rotation.x = qx
    t.transform.rotation.y = qy
    t.transform.rotation.z = qz
    t.transform.rotation.w = qw
    return t


if __name__ == '__main__':
    rospy.init_node('sensor_tf_broadcaster')
    parent_frame = rospy.get_param('~parent_frame', 'base_link')
    sensors = rospy.get_param('~additional_sensors', {}) or {}

    if not sensors:
        rospy.loginfo("sensor_tf_broadcaster: additional_sensors vacio (normal hoy, sin LiDAR "
                       "todavia) - no hay nada que publicar.")
    else:
        broadcaster = tf2_ros.StaticTransformBroadcaster()
        transforms = [build_transform(parent_frame, child, cfg) for child, cfg in sensors.items()]
        broadcaster.sendTransform(transforms)
        rospy.loginfo("sensor_tf_broadcaster: publicando %d transformada(s) estatica(s) desde %s: %s",
                       len(transforms), parent_frame, list(sensors.keys()))

    rospy.spin()
