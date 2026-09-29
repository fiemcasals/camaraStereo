# HU-02: servidor web del VAD en la VPS (login, mapas, rutas, posicion del
# vehiculo). Solo libreria estandar de Python: no hay requirements.
# Contexto de build: ros_zed_workspace/ (ver docker-compose.yml).
FROM python:3.12-alpine
WORKDIR /app
COPY web_dashboard/ web_dashboard/
COPY src/zed_costmap_nav/scripts/waypoint_router.py src/zed_costmap_nav/scripts/waypoint_router.py
RUN rm -f web_dashboard/app.db web_dashboard/mail_outbox.log && mkdir -p /data
EXPOSE 80
CMD ["python3", "web_dashboard/server.py"]
