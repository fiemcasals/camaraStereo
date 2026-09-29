#!/usr/bin/env python3
"""HU-02: manda la posicion del vehiculo a la VPS, una vez por segundo.

Es lo unico que sale del vehiculo mientras navega: latitud, longitud, rumbo y
estado (~200 bytes por mensaje, menos de 1 MB por hora). Todo el resto del
procesamiento queda en la Jetson.

La navegacion nunca espera a internet: el envio corre en un hilo aparte, con
timeout, y solo se guarda el ultimo dato (si la red esta caida no se acumula
nada; cuando vuelve, se manda la posicion actual).

Configuracion (variables de entorno, el token NO va al repo):
    VAD_SERVER_URL     https://vad.misitiowebpersonal.com.ar
    VAD_VEHICLE_ID     vad-01
    VAD_VEHICLE_TOKEN  el mismo que VAD_VEHICLE_TOKENS en la VPS
Parametros ROS:
    ~fix_topic   topico sensor_msgs/NavSatFix del GPS (default /gps/fix)
    ~rate        envios por segundo (default 1.0)
    ~simulate    true = sin GPS, recorre un circulo de 10 m alrededor de
                 ~sim_lat/~sim_lon (para probar la VPS antes de tener el GPS)
"""
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request

# Radio medio de la Tierra (m), para el recorrido simulado.
EARTH_R = 6371000.0


def build_payload(lat, lon, heading=None, status=''):
    """Cuerpo JSON del POST. None en lat/lon = no hay posicion para mandar."""
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    body = {'lat': round(lat, 7), 'lon': round(lon, 7), 'status': status}
    if heading is not None and math.isfinite(heading):
        body['heading'] = round(heading % 360.0, 1)
    return body


def simulated_position(t, lat0, lon0, radius_m=10.0, speed_mps=0.5):
    """Circulo de radius_m alrededor de (lat0, lon0) a speed_mps. Devuelve
    (lat, lon, rumbo en grados, 0 = norte, sentido horario)."""
    ang = (speed_mps * t) / radius_m
    north, east = radius_m * math.cos(ang), radius_m * math.sin(ang)
    lat = lat0 + math.degrees(north / EARTH_R)
    lon = lon0 + math.degrees(east / (EARTH_R * math.cos(math.radians(lat0))))
    # Tangente al circulo: se recorre en sentido horario visto desde arriba
    # (arranca al norte del centro yendo hacia el este, rumbo 90).
    heading = (math.degrees(math.atan2(math.cos(ang), -math.sin(ang))) + 360.0) % 360.0
    return lat, lon, heading


class LatestSender:
    """Hilo que manda el ultimo payload pendiente. offer() nunca bloquea."""

    def __init__(self, url, token, timeout=3.0, post=None):
        self.url, self.token, self.timeout = url, token, timeout
        self._post = post or self._http_post
        self._pending = None
        self._cv = threading.Condition()
        self.sent = self.failed = 0
        self.last_error = None
        self._stop = False

    def offer(self, payload):
        with self._cv:
            self._pending = payload  # reemplaza lo que no se llego a mandar
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify()

    def run(self):
        while True:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                payload, self._pending = self._pending, None
            try:
                self._post(payload)
                self.sent += 1
                self.last_error = None
            except Exception as e:  # red caida, timeout, 5xx: se reintenta con el proximo dato
                self.failed += 1
                self.last_error = str(e)

    def _http_post(self, payload):
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            resp.read()


def main():
    import rospy
    from sensor_msgs.msg import NavSatFix, NavSatStatus

    rospy.init_node('position_uploader')
    server = os.environ.get('VAD_SERVER_URL', '').rstrip('/')
    vehicle = os.environ.get('VAD_VEHICLE_ID', 'vad-01')
    token = os.environ.get('VAD_VEHICLE_TOKEN', '')
    if not server or not token:
        rospy.logwarn('position_uploader: faltan VAD_SERVER_URL o VAD_VEHICLE_TOKEN, no se manda nada')
        return
    rate = rospy.get_param('~rate', 1.0)
    simulate = rospy.get_param('~simulate', False)
    lat0, lon0 = rospy.get_param('~sim_lat', -34.6037), rospy.get_param('~sim_lon', -58.3816)

    sender = LatestSender(f'{server}/api/vehicles/{vehicle}/position', token)
    threading.Thread(target=sender.run, daemon=True).start()
    rospy.on_shutdown(sender.stop)

    fix = {'msg': None}
    if not simulate:
        rospy.Subscriber(rospy.get_param('~fix_topic', '/gps/fix'), NavSatFix,
                         lambda m: fix.__setitem__('msg', m), queue_size=1)

    t0 = time.time()
    r = rospy.Rate(rate)
    last_log = 0.0
    while not rospy.is_shutdown():
        if simulate:
            lat, lon, heading = simulated_position(time.time() - t0, lat0, lon0)
            payload = build_payload(lat, lon, heading, 'simulado')
        else:
            m = fix['msg']
            if m is None or m.status.status == NavSatStatus.STATUS_NO_FIX:
                payload = None  # sin fix no se manda nada: el mapa pasa a "sin senal"
            else:
                # El rumbo real llega con el EKF global (RF-04 GPS); hasta entonces va vacio.
                payload = build_payload(m.latitude, m.longitude, None, 'navegando')
        if payload is not None:
            sender.offer(payload)
        if time.time() - last_log > 30:
            rospy.loginfo('position_uploader: %d enviados, %d fallidos%s', sender.sent, sender.failed,
                          f' (ultimo error: {sender.last_error})' if sender.last_error else '')
            last_log = time.time()
        r.sleep()


if __name__ == '__main__':
    main()
