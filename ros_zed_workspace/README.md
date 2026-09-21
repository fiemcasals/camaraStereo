# VAD — Navegación autónoma con ZED + Jetson (ROS Noetic)

> **Si sos una sesión de Claude Code retomando este proyecto:** además de este README, pedí que se lea el documento completo del plan en `~/.claude/plans/structured-whistling-heron.md` (memoria del asistente en esta máquina) — ahí está el detalle de cada decisión de arquitectura, cada bug encontrado y cómo se resolvió, y las tareas pendientes por fase. Este README es solo un resumen rápido de arranque.

## Qué es esto

Vehículo autónomo de reparto (proyecto "VAD"): navega de un punto a otro esquivando obstáculos con una cámara estéreo ZED sobre una Jetson, corriendo ROS Noetic dentro de Docker. Hoy es un prototipo de escritorio (solo la cámara, sin chasis/motores todavía); el resto del hardware (Jetson Orin NX, ZED 2i, LiDAR, GNSS, motores ODrive) está en camino.

## Estado actual: Fase 0 completa ✅

1. Costmap real reaccionando a obstáculos + `move_base` planificando y esquivando.
2. `speed_moderator.py`: baja la velocidad cerca de personas/animales (probado con datos simulados, esta ZED no soporta detección de objetos real).
3. `robot_localization` (EKF) fusionando la odometría de la cámara, listo para sumar encoders/LiDAR.
4. `map_editor.html`: cargar waypoints, dibujar conexiones entre ellos y marcar destino sobre un mapa real (OpenStreetMap).
5. `waypoint_router.py`: calcula el camino más corto (Dijkstra bidireccional) sobre ese grafo — no importa el orden en que se cargaron los puntos.
6. Bridge de motores decidido (`belovictor/odrive_can_ros_driver`) para cuando llegue el hardware.
7. Prototipo de "carril prohibido" (`costmap_prohibition_layer`) para bloquear zonas como el carril contrario.

**Para seguir hace falta el hardware nuevo.** Sin eso, lo próximo (Fase 1) no se puede avanzar mucho más.

## Cómo conectarse a la Jetson

- Cable USB entre la laptop y la Jetson (también la alimenta — si se desconecta, se reinicia sola).
- IP `192.168.55.1`, usuario/contraseña en `../credenciales_jetson.txt` (un nivel arriba de esta carpeta).
- `ssh jetson@192.168.55.1`

## Arranque

Todo arranca solo con el contenedor (no hace falta lanzar nada a mano):

```bash
cd ~/ros_zed_workspace   # en la Jetson
sudo docker-compose restart   # reinicio normal, recompila con catkin_make (~5 min)
```

Solo usar `sudo docker-compose up -d` (sin `--build`) si cambió `docker-compose.yml` (montajes/variables de entorno) — ese comando recrea el contenedor y **pierde cualquier paquete `apt install`ado en caliente que no esté en el `Dockerfile`**.

## Dashboard

- `http://192.168.55.1:8080/` — mapa de calor de profundidad + mapa 2D con la ruta planificada, en vivo.
- `http://192.168.55.1:8080/map_editor.html` — cargar/editar waypoints y conexiones sobre un mapa real.

## Debug visual (rviz / rqt_reconfigure)

Se puede conectar un monitor+mouse físico a la Jetson y correr herramientas gráficas reales en vez de ir a ciegas por SSH:

1. Iniciar sesión en el escritorio de la Jetson (usuario `jetson`; si no hay teclado, la pantalla de login tiene teclado en pantalla en el ícono de accesibilidad).
2. `DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority xhost +SI:localuser:root`
3. `sudo docker exec -d ros_zed_navigation bash -c "export DISPLAY=:1; export XAUTHORITY=/root/.Xauthority; rviz -d /app/web_dashboard/debug.rviz"`

`debug.rviz` ya trae armado: TF, `/scan`, ambos costmaps, el plan y la nube de puntos.

## Estructura del código (`src/zed_costmap_nav/`)

- `launch/navigation.launch`: arma todo el stack.
- `config/`: parámetros de costmap, `move_base`, EKF, extrínsecos de sensores — cada archivo tiene comentarios explicando el porqué de cada valor no obvio.
- `scripts/`: `scan_to_costmap.py`, `speed_moderator.py`, `waypoint_router.py`, `sensor_tf_broadcaster.py`, `depth_to_heatmap.py`, `render_plan.py`, `auto_driver.py` (pendiente de completar con hardware real).

**Dependencias externas** (clonadas directo en `src/` de la Jetson, no versionadas en este repo — hay que re-clonarlas en una instalación nueva): `zed-ros-wrapper`, `zed-ros-interfaces` (Stereolabs), `costmap_prohibition_layer` (`rst-tu-dortmund`, rama `kinetic-devel`).

## Cosas raras a tener en cuenta

- `costmap_2d::ObstacleLayer` no funciona en esta build (bug de la imagen de Stereolabs, no de esta config) — se reemplazó por un `StaticLayer` alimentado a mano (`scan_to_costmap.py`). Ver detalle completo en el plan.
- `footprint` y el offset de `base_link` son provisorios (aproximados, sin chasis real todavía).
- Esta ZED (la original, sin IMU) no soporta detección de objetos por IA — la ZED 2i que ya se compró sí.
