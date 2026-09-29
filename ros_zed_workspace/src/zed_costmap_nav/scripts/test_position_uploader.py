#!/usr/bin/env python3
"""Pruebas de position_uploader.py sin ROS ni red:
python3 -m unittest test_position_uploader"""
import math
import threading
import time
import unittest

import position_uploader as pu


class TestPayload(unittest.TestCase):
    def test_redondea_y_normaliza_el_rumbo(self):
        self.assertEqual(pu.build_payload(-34.60371234567, -58.38161234567, 370.0, 'navegando'),
                         {'lat': -34.6037123, 'lon': -58.3816123, 'status': 'navegando', 'heading': 10.0})

    def test_sin_posicion_no_hay_payload(self):
        self.assertIsNone(pu.build_payload(None, -58.0))
        self.assertIsNone(pu.build_payload(float('nan'), -58.0))

    def test_rumbo_invalido_se_omite(self):
        self.assertNotIn('heading', pu.build_payload(-34.0, -58.0, float('nan')))
        self.assertNotIn('heading', pu.build_payload(-34.0, -58.0, None))

    def test_payload_chico(self):
        import json
        size = len(json.dumps(pu.build_payload(-34.6037123, -58.3816123, 123.4, 'navegando')))
        self.assertLess(size, 200)  # x 3600 por hora = menos de 1 MB


class TestSimulado(unittest.TestCase):
    def dist_m(self, lat1, lon1, lat2, lon2):
        dn = math.radians(lat2 - lat1) * pu.EARTH_R
        de = math.radians(lon2 - lon1) * pu.EARTH_R * math.cos(math.radians(lat1))
        return math.hypot(dn, de)

    def test_circulo_de_10_m(self):
        for t in (0, 7, 33, 90):
            lat, lon, _ = pu.simulated_position(t, -34.6, -58.4)
            self.assertAlmostEqual(self.dist_m(-34.6, -58.4, lat, lon), 10.0, delta=0.05)

    def test_rumbo_tangente(self):
        _, _, h = pu.simulated_position(0, -34.6, -58.4)  # al norte del centro, yendo al este
        self.assertAlmostEqual(h, 90.0, delta=0.5)


class TestLatestSender(unittest.TestCase):
    def test_offer_no_bloquea_aunque_la_red_este_lenta(self):
        s = pu.LatestSender('x', 't', post=lambda p: time.sleep(0.5))
        threading.Thread(target=s.run, daemon=True).start()
        t0 = time.time()
        for i in range(20):
            s.offer({'i': i})
        self.assertLess(time.time() - t0, 0.05)
        s.stop()

    def test_solo_manda_el_ultimo_pendiente(self):
        got = []
        gate = threading.Event()
        def post(p):
            gate.wait(1); got.append(p['i'])
        s = pu.LatestSender('x', 't', post=post)
        threading.Thread(target=s.run, daemon=True).start()
        s.offer({'i': 0}); time.sleep(0.05)      # el 0 queda "en vuelo"
        for i in range(1, 10):
            s.offer({'i': i})                     # del 1 al 9 solo sobrevive el 9
        gate.set(); time.sleep(0.2); s.stop()
        self.assertEqual(got, [0, 9])

    def test_red_caida_cuenta_fallas_y_sigue(self):
        def post(p):
            if p['i'] < 3:
                raise OSError('sin red')
        s = pu.LatestSender('x', 't', post=post)
        threading.Thread(target=s.run, daemon=True).start()
        for i in range(5):
            s.offer({'i': i}); time.sleep(0.03)
        time.sleep(0.1); s.stop()
        self.assertEqual((s.failed, s.sent), (3, 2))
        self.assertIsNone(s.last_error)


if __name__ == '__main__':
    unittest.main()
