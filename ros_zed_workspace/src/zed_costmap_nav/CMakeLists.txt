cmake_minimum_required(VERSION 3.0.2)
project(zed_costmap_nav)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  geometry_msgs
  sensor_msgs
  nav_msgs
  zed_interfaces
)

catkin_package(
#  INCLUDE_DIRS include
#  LIBRARIES zed_costmap_nav
#  CATKIN_DEPENDS rospy std_msgs geometry_msgs sensor_msgs
#  DEPENDS system_lib
)

include_directories(
# include
  ${catkin_INCLUDE_DIRS}
)

catkin_install_python(PROGRAMS
  scripts/auto_driver.py
  scripts/depth_to_heatmap.py
  scripts/render_plan.py
  scripts/scan_to_costmap.py
  scripts/sensor_tf_broadcaster.py
  scripts/speed_moderator.py
  scripts/position_uploader.py
  scripts/waypoint_router.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
