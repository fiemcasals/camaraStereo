# Usamos la última versión estable (5.2.3) para L4T r35 (JetPack 5) para evitar el bug de NvBufferMemMap
FROM stereolabs/zed:5.2.3-devel-l4t-r35.4

ENV DEBIAN_FRONTEND=noninteractive

# Instalar ROS Noetic (Ubuntu 20.04 Focal) y dependencias del sistema
RUN apt-get update && apt-get install -y curl gnupg2 lsb-release
RUN sh -c 'echo "deb http://packages.ros.org/ros/ubuntu focal main" > /etc/apt/sources.list.d/ros-latest.list'
RUN apt-key adv --keyserver 'hkp://keyserver.ubuntu.com:80' --recv-key C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654
RUN apt-get update && apt-get install -y \
    ros-noetic-ros-base \
    ros-noetic-navigation \
    ros-noetic-pointcloud-to-laserscan \
    ros-noetic-diagnostic-updater \
    ros-noetic-robot-state-publisher \
    ros-noetic-xacro \
    ros-noetic-tf2-geometry-msgs \
    ros-noetic-image-transport \
    ros-noetic-rosbridge-server \
    ros-noetic-web-video-server \
    ros-noetic-robot-localization \
    ros-noetic-rviz \
    ros-noetic-rqt-reconfigure \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Fase 2.3 (traversability_train.py / traversability_infer_node.py): hace
# falta PyTorch y onnxruntime. NO se instalan aca con un "pip install torch"
# generico a proposito -- en Jetson/L4T (ARM64 + CUDA) los wheels de PyPI no
# sirven, hacen falta los builds especificos de NVIDIA para este JetPack
# (Jetson Zoo: https://forums.developer.nvidia.com/t/pytorch-for-jetson).
# Instalar a mano una sola vez en la Jetson real, o agregar aca el RUN con la
# URL del wheel correcto para JetPack 5 / L4T r35 una vez verificado que
# funciona (no se pudo probar esto sin la Jetson fisica).


# Configurar el workspace de ROS dentro del contenedor
WORKDIR /root/catkin_ws
COPY ./src ./src

# Compilar el workspace
RUN /bin/bash -c '. /opt/ros/noetic/setup.bash; catkin_make'

# Crear un script de entrada (entrypoint) para levantar ROS y el servidor Web
RUN echo '#!/bin/bash\n\
source /opt/ros/noetic/setup.bash\n\
source /root/catkin_ws/devel/setup.bash\n\
# Iniciar el servidor web del Dashboard en background\n\
cd /app/web_dashboard && python3 -m http.server 8080 &\n\
# Levantar el Websocket de ROS para que la web se conecte\n\
roslaunch rosbridge_server rosbridge_websocket.launch &\n\
# Ejecutar el launch principal de navegacion\n\
roslaunch zed_costmap_nav navigation.launch\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

# El comando por defecto a ejecutar
CMD ["/entrypoint.sh"]
