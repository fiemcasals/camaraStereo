#!/bin/bash
# HU-02: arranca el envio de posicion a la VPS dentro del contenedor de ROS.
# Correr en la Jetson (host). Lee ~/.vad_vehicle.env (chmod 600, no va al repo):
#   VAD_SERVER_URL=https://vad.misitiowebpersonal.com.ar
#   VAD_VEHICLE_ID=vad-01
#   VAD_VEHICLE_TOKEN=<token de la VPS>
# Uso: sudo ./iniciar_posicion.sh            (con GPS, topico /gps/fix)
#      sudo ./iniciar_posicion.sh --simular  (circulo de 10 m, sin GPS)
set -eu
ENVF=$(eval echo ~${SUDO_USER:-$USER})/.vad_vehicle.env
[ -f "$ENVF" ] || { echo "Falta $ENVF"; exit 1; }
SIM=false; [ "${1:-}" = "--simular" ] && SIM=true
set -a; . "$ENVF"; set +a
docker exec ros_zed_navigation pkill -f position_uploader.py 2>/dev/null || true
docker exec -d -e VAD_SERVER_URL -e VAD_VEHICLE_ID -e VAD_VEHICLE_TOKEN ros_zed_navigation bash -c \
  "source /root/catkin_ws/devel/setup.bash; exec python3 /root/catkin_ws/src/zed_costmap_nav/scripts/position_uploader.py _simulate:=$SIM > /tmp/position_uploader.log 2>&1"
sleep 3
docker exec ros_zed_navigation tail -3 /tmp/position_uploader.log
echo "Log: docker exec ros_zed_navigation tail -f /tmp/position_uploader.log"
