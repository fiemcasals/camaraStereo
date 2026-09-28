#!/bin/bash
# RNF-05: mide si la Jetson Xavier NX soporta todas las funciones de la ZED 2i.
# Correr EN LA JETSON (no dentro del contenedor), con el stack levantado
# (docker-compose up -d). Mide tres configuraciones seguidas:
#   1. solo profundidad (deteccion de objetos apagada por servicio)
#   2. profundidad + deteccion de objetos
#   3. stack completo (lo anterior + un goal de move_base activo, si se pasa --con-goal)
#   (model 1 = MULTI_CLASS_BOX_MEDIUM, el mismo que navigation.launch)
# y deja un CSV + un resumen en ~/medicion_capacidad_<fecha>/.
#
# Uso: ./medir_capacidad.sh [segundos_por_configuracion]   (default 300 = 5 min)
set -u
DUR=${1:-300}
C=ros_zed_navigation
OUT=~/medicion_capacidad_$(date +%Y%m%d_%H%M)
mkdir -p "$OUT"
ROS="source /opt/ros/noetic/setup.bash; source /root/catkin_ws/devel/setup.bash"
TOPICS="/zed/zed_node/depth/depth_registered /zed/zed_node/obj_det/objects /zed/zed_node/imu/data /scan /move_base/local_costmap/costmap /odometry/filtered"

dexec() { sudo docker exec "$C" bash -c "$ROS; $1"; }

medir() {  # $1 = nombre de la configuracion
    local name=$1
    echo "== $name ($DUR s) =="
    tegrastats --interval 1000 --logfile "$OUT/tegra_$name.log" &
    local tpid=$!
    for t in $TOPICS; do
        dexec "timeout $DUR rostopic hz -w 50 $t" > "$OUT/hz_${name}_$(echo $t | tr / _).log" 2>&1 &
    done
    sleep "$DUR"; sleep 3
    kill $tpid 2>/dev/null; tegrastats --stop 2>/dev/null
    wait 2>/dev/null
}

resumir() {  # $1 = nombre -> una fila del CSV
    local name=$1 row="$name,$(sudo nvpmodel -q 2>/dev/null | head -1 | awk -F': ' '{print $2}')"
    for t in $TOPICS; do
        hz=$(grep "average rate" "$OUT/hz_${name}_$(echo $t | tr / _).log" | tail -20 | awk '{s+=$3; n++} END {if (n) printf "%.1f", s/n; else print "0"}')
        row="$row,$hz"
    done
    row="$row,$(awk '{
        match($0, /CPU \[[^]]*\]/); c=substr($0, RSTART+5, RLENGTH-6); n=split(c, a, ","); s=0; k=0
        for (i=1; i<=n; i++) if (a[i] != "off") { split(a[i], b, "%"); s+=b[1]; k++ }
        cpu+=s/k
        match($0, /GR3D_FREQ [0-9]+%/); gpu+=substr($0, RSTART+10, RLENGTH-11)
        match($0, /RAM [0-9]+/); ram+=substr($0, RSTART+4, RLENGTH-4)
        match($0, /GPU@[0-9.]+C/); t=substr($0, RSTART+4, RLENGTH-5); if (t > tmax) tmax=t
        lines++
    } END { printf "%.0f,%.0f,%.0f,%.1f", cpu/lines, gpu/lines, ram/lines, tmax }' "$OUT/tegra_$name.log")"
    echo "$row" >> "$OUT/resumen.csv"
}

echo "configuracion,modo_energia,$(echo $TOPICS | tr ' ' ','),cpu_prom_%,gpu_prom_%,ram_prom_MB,temp_gpu_max_C" > "$OUT/resumen.csv"

dexec "rosservice call /zed/zed_node/stop_object_detection" > /dev/null
medir solo_profundidad; resumir solo_profundidad

dexec "rosservice call /zed/zed_node/start_object_detection '{model: 1, confidence: 50.0, max_range: 15.0, tracking: true, sk_body_fitting: false, mc_people: true, mc_vehicles: true, mc_bag: true, mc_animal: true, mc_electronics: false, mc_fruit_vegetable: false, mc_sport: false}'" > /dev/null
medir profundidad_y_deteccion; resumir profundidad_y_deteccion

if [ "${2:-}" = "--con-goal" ]; then
    dexec "rostopic pub -1 /move_base_simple/goal geometry_msgs/PoseStamped '{header: {frame_id: odom}, pose: {position: {x: 3.0}, orientation: {w: 1.0}}}'" > /dev/null
    medir stack_completo; resumir stack_completo
fi

echo; column -s, -t "$OUT/resumen.csv"
echo; echo "Resultados en $OUT"
echo "Criterio RNF-05: alcanza si obj_det >= 10 Hz y local_costmap >= 5 Hz con el stack completo."
