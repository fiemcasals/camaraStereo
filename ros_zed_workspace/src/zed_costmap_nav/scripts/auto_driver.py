#!/usr/bin/env python3
import rospy
from geometry_msgs.msg import Twist

def velocity_callback(msg):
    # msg.linear.x es la velocidad hacia adelante (m/s)
    # msg.angular.z es la velocidad de giro (rad/s)
    
    linear_velocity = msg.linear.x
    angular_velocity = msg.angular.z
    
    # ACÁ VA TU CÓDIGO DE HARDWARE
    # Ejemplo: Si tenés un Arduino o un puente H (L298N) conectado a la Jetson,
    # le mandás las señales PWM proporcionales a las velocidades deseadas.
    
    rospy.loginfo(f"Moviendo auto: Acelerador={linear_velocity:.2f}, Volante={angular_velocity:.2f}")

def listener():
    rospy.init_node('auto_driver', anonymous=True)
    
    # Nos suscribimos al tópico /cmd_vel que genera el navegador al ver el Mapa de Calor
    rospy.Subscriber("/cmd_vel", Twist, velocity_callback)
    
    rospy.loginfo("Driver del Auto listo y esperando órdenes del Navegador ROS...")
    
    # Mantener el script corriendo
    rospy.spin()

if __name__ == '__main__':
    try:
        listener()
    except rospy.ROSInterruptException:
        pass
