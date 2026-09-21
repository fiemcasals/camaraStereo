#!/usr/bin/env python3
import rospy
from sensor_msgs.msg import Image
import cv2
import numpy as np

# Procesar 1 de cada N frames: la ZED publica a ~13-15Hz y este nodo compite
# por CPU con move_base/costmap en un Jetson de pocos nucleos. No hace falta
# actualizar el heatmap del dashboard a full frame rate.
FRAME_SKIP = 3
_depth_counter = {'n': 0}


def depth_callback(msg):
    _depth_counter['n'] += 1
    if _depth_counter['n'] % FRAME_SKIP != 0:
        return
    try:
        if msg.encoding == '32FC1':
            depth_img = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
        elif msg.encoding == '16UC1':
            depth_img = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
            depth_img = depth_img.astype(np.float32) / 1000.0 # Convert mm to meters
        else:
            rospy.logwarn_throttle(5, "Unsupported depth encoding: %s", msg.encoding)
            return
            
        # Remove NaNs and Infs (replace with 0)
        depth_img = np.nan_to_num(depth_img, nan=0.0, posinf=0.0, neginf=0.0)
        
        # We want to match the thermal camera look. 
        # In the thermal image, close = RED/WHITE (Hot), far = BLUE/BLACK (Cold).
        # We will clip the depth between 0.3m and 3.0m for better contrast
        min_dist = 0.3
        max_dist = 3.0
        
        # Normalize to 0-1
        depth_norm = (depth_img - min_dist) / (max_dist - min_dist)
        depth_norm = np.clip(depth_norm, 0.0, 1.0)
        
        # Invert so CLOSE (0.0) becomes 1.0 (hot), FAR (1.0) becomes 0.0 (cold)
        depth_norm = 1.0 - depth_norm
        
        # Convert to 0-255 uint8
        depth_8u = (depth_norm * 255.0).astype(np.uint8)
        
        # Where it was exactly 0.0 (invalid/too close), make it black (0)
        mask = depth_img < 0.1
        
        # Apply colormap
        heatmap = cv2.applyColorMap(depth_8u, cv2.COLORMAP_JET)
        
        # Apply mask
        heatmap[mask] = [0, 0, 0]
        
        # Save to file
        cv2.imwrite('/app/web_dashboard/heatmap.jpg', heatmap)
        
    except Exception as e:
        rospy.logerr("Error converting depth image: %s", str(e))

_rgb_counter = {'n': 0}


def rgb_callback(msg):
    _rgb_counter['n'] += 1
    if _rgb_counter['n'] % FRAME_SKIP != 0:
        return
    try:
        # RGB from ZED is usually bgra8 or bgr8
        if msg.encoding == 'bgra8':
            rgb_img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 4)
            rgb_img = rgb_img[:,:,:3] # Drop alpha
        elif msg.encoding == 'bgr8':
            rgb_img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        elif msg.encoding == 'rgb8':
            rgb_img = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            rgb_img = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2BGR)
        else:
            return
            
        cv2.imwrite('/app/web_dashboard/rgb.jpg', rgb_img)
    except Exception as e:
        rospy.logerr("Error converting RGB image: %s", str(e))

if __name__ == '__main__':
    rospy.init_node('depth_to_heatmap')
    rospy.Subscriber('/zed/zed_node/depth/depth_registered', Image, depth_callback, queue_size=1)
    rospy.Subscriber('/zed/zed_node/rgb/image_rect_color', Image, rgb_callback, queue_size=1)
    rospy.loginfo("Depth to Heatmap node started.")
    rospy.spin()
