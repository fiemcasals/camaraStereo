#!/usr/bin/env python3
"""Nucleo del modo seguimiento (RF-10), sin ROS a proposito (mismo criterio
que traversability_label.py): se puede probar en cualquier maquina con
python3 -m unittest test_follow_logic.

Convencion de ejes: la del frame de la camara ZED en ROS (REP-103),
x = adelante, y = izquierda, en metros. Es como vienen las posiciones en
zed_interfaces/Object.position."""
import math

# Distancia a la que el vehiculo se queda detras de la persona (m).
DEFAULT_FOLLOW_DIST = 1.5
# Por debajo de esta distancia no avanza nunca, aunque la persona retroceda:
# el vehiculo no retrocede solo para "mantener" la distancia.
MIN_DIST = 0.8
MAX_LINEAR = 0.8   # m/s
MAX_ANGULAR = 1.0  # rad/s
K_LINEAR = 0.6     # (m/s) por metro de error de distancia
K_ANGULAR = 1.5    # (rad/s) por radian de error de rumbo
# Si la persona esta muy de costado, primero girar y despues avanzar: evita
# arcos largos que la sacan del campo de vision de la camara (110 grados).
TURN_IN_PLACE_BEARING = math.radians(35)
# Tiempo sin ver al objetivo antes de declararlo perdido y frenar (s).
LOST_TIMEOUT = 2.0
# Reenganche: la ZED reinicia el ID de tracking de una persona cuando la pierde
# un instante (oclusion, muy cerca). Si mientras se espera aparece un ID NUEVO a
# menos de esta distancia de donde se vio al objetivo por ultima vez, se asume
# que es la misma persona (m).
REACQUIRE_RADIUS = 0.8


def is_person(label):
    return 'person' in (label or '').lower()


def has_position(person):
    """La ZED manda NaN en la posicion cuando la persona esta mas cerca que la
    profundidad minima (0,3 m) o la profundidad no es valida."""
    x, y = person.get('x'), person.get('y')
    return x is not None and y is not None and math.isfinite(x) and math.isfinite(y)


def normalize_bbox(corners, img_w, img_h):
    """corners: 4 puntos (x, y) en pixeles de la imagen de captura, en el
    orden del SDK (arriba-izq, arriba-der, abajo-der, abajo-izq). Devuelve
    (x0, y0, x1, y1) normalizados a [0, 1] para que la interfaz los dibuje
    sobre la imagen sin importar la resolucion con que se publique."""
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    clamp = lambda v: max(0.0, min(1.0, v))
    return (clamp(min(xs) / img_w), clamp(min(ys) / img_h),
            clamp(max(xs) / img_w), clamp(max(ys) / img_h))


def find_target(persons, target_id):
    """persons: lista de dicts con 'id' y 'x', 'y'. Devuelve el del ID
    elegido o None. Nunca cambia a otra persona: si el objetivo no esta, es
    None aunque haya otras personas a la vista (condicion 3 de RF-10)."""
    for p in persons:
        if p['id'] == target_id:
            return p
    return None


def follow_cmd(x, y, follow_dist=DEFAULT_FOLLOW_DIST):
    """Velocidad (lineal, angular) para quedar a follow_dist de una persona
    en (x, y). Solo avanza, nunca retrocede."""
    dist = math.hypot(x, y)
    bearing = math.atan2(y, x)

    angular = max(-MAX_ANGULAR, min(MAX_ANGULAR, K_ANGULAR * bearing))

    if dist <= MIN_DIST or abs(bearing) > TURN_IN_PLACE_BEARING:
        linear = 0.0
    else:
        linear = max(0.0, min(MAX_LINEAR, K_LINEAR * (dist - follow_dist)))
    return linear, angular


class FollowState:
    """Estado del seguimiento: a quien se sigue y cuando se lo vio por
    ultima vez. Los tiempos se pasan de afuera (segundos) para poder
    probarlo sin reloj real."""

    IDLE = 'inactivo'
    FOLLOWING = 'siguiendo'
    LOST = 'objetivo perdido'

    def __init__(self, lost_timeout=LOST_TIMEOUT, reacquire_radius=REACQUIRE_RADIUS):
        self.lost_timeout = lost_timeout
        self.reacquire_radius = reacquire_radius
        self.target_id = None
        self.last_seen = None
        self.last_pos = None     # (x, y) donde se vio al objetivo por ultima vez
        self.seen_ids = set()    # IDs ya vistos desde que se eligio el objetivo

    def set_target(self, target_id, now):
        """target_id < 0 cancela el seguimiento (boton 'Dejar de seguir')."""
        self.last_pos = None
        self.seen_ids = set()
        if target_id is None or target_id < 0:
            self.target_id = None
            self.last_seen = None
        else:
            self.target_id = target_id
            self.last_seen = now

    def _reacquire(self, persons):
        """Un ID que nunca se habia visto, cerca de la ultima posicion del
        objetivo. Nunca uno ya conocido: esa es otra persona que se cruza."""
        if self.last_pos is None:
            return None
        best, best_d = None, self.reacquire_radius
        for p in persons:
            if p['id'] in self.seen_ids or not has_position(p):
                continue
            d = math.hypot(p['x'] - self.last_pos[0], p['y'] - self.last_pos[1])
            if d <= best_d:
                best, best_d = p, d
        return best

    def update(self, persons, now, follow_dist=DEFAULT_FOLLOW_DIST):
        """Devuelve (estado, (lineal, angular) o None). None = no publicar
        nada (modo normal, manda move_base); (0, 0) = frenar."""
        if self.target_id is None:
            return self.IDLE, None

        target = find_target(persons, self.target_id)
        if target is None and now - self.last_seen <= self.lost_timeout:
            target = self._reacquire(persons)
            if target is not None:
                self.target_id = target['id']
        self.seen_ids.update(p['id'] for p in persons)

        if target is not None:
            self.last_seen = now
            if not has_position(target):
                # Se lo ve pero sin distancia valida (mas cerca que el minimo de
                # la camara, 0,3 m): frenar, sin declararlo perdido.
                return self.FOLLOWING, (0.0, 0.0)
            self.last_pos = (target['x'], target['y'])
            return self.FOLLOWING, follow_cmd(target['x'], target['y'], follow_dist)

        if now - self.last_seen > self.lost_timeout:
            return self.LOST, (0.0, 0.0)
        # Perdido hace poco (oclusion breve): frenar pero seguir esperando.
        return self.FOLLOWING, (0.0, 0.0)
