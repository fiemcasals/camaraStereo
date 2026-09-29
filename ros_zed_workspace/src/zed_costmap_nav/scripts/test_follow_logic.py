#!/usr/bin/env python3
"""Pruebas del modo seguimiento (follow_logic.py). No necesitan ROS ni la
camara: python3 -m unittest test_follow_logic"""
import math
import unittest

import follow_logic as fl


class TestFollowCmd(unittest.TestCase):
    def test_a_la_distancia_justa_no_avanza(self):
        lin, ang = fl.follow_cmd(1.5, 0.0, follow_dist=1.5)
        self.assertAlmostEqual(lin, 0.0)
        self.assertAlmostEqual(ang, 0.0)

    def test_lejos_avanza_proporcional_con_tope(self):
        lin, _ = fl.follow_cmd(2.5, 0.0, follow_dist=1.5)
        self.assertAlmostEqual(lin, fl.K_LINEAR * 1.0)
        lin, _ = fl.follow_cmd(10.0, 0.0, follow_dist=1.5)
        self.assertAlmostEqual(lin, fl.MAX_LINEAR)

    def test_nunca_retrocede(self):
        lin, _ = fl.follow_cmd(1.0, 0.0, follow_dist=1.5)
        self.assertEqual(lin, 0.0)
        lin, _ = fl.follow_cmd(0.5, 0.0, follow_dist=1.5)
        self.assertEqual(lin, 0.0)

    def test_gira_hacia_la_persona(self):
        _, ang = fl.follow_cmd(3.0, 0.5)   # a la izquierda
        self.assertGreater(ang, 0)
        _, ang = fl.follow_cmd(3.0, -0.5)  # a la derecha
        self.assertLess(ang, 0)

    def test_muy_de_costado_gira_sin_avanzar(self):
        lin, ang = fl.follow_cmd(1.0, 2.0)
        self.assertEqual(lin, 0.0)
        self.assertAlmostEqual(ang, fl.MAX_ANGULAR)


class TestFollowState(unittest.TestCase):
    def persons(self, *items):
        return [{'id': i, 'x': x, 'y': y} for i, x, y in items]

    def test_sin_objetivo_no_publica(self):
        st = fl.FollowState()
        self.assertEqual(st.update(self.persons((1, 3.0, 0.0)), now=0.0), (fl.FollowState.IDLE, None))

    def test_sigue_solo_al_elegido_aunque_otro_este_mas_cerca(self):
        st = fl.FollowState()
        st.set_target(7, now=0.0)
        status, (lin, ang) = st.update(self.persons((3, 1.6, 0.0), (7, 3.0, -0.3)), now=0.1)
        self.assertEqual(status, fl.FollowState.FOLLOWING)
        self.assertGreater(lin, 0)       # va hacia el 7 (a 3 m), no se queda con el 3 (a 1,6 m)
        self.assertLess(ang, 0)          # el 7 esta a la derecha

    def test_perdido_mas_de_2s_frena_y_avisa(self):
        st = fl.FollowState(lost_timeout=2.0)
        st.set_target(7, now=0.0)
        st.update(self.persons((7, 3.0, 0.0)), now=0.5)
        self.assertEqual(st.update(self.persons((3, 2.0, 0.0)), now=1.5), (fl.FollowState.FOLLOWING, (0.0, 0.0)))
        self.assertEqual(st.update(self.persons((3, 2.0, 0.0)), now=2.6), (fl.FollowState.LOST, (0.0, 0.0)))

    def test_si_reaparece_retoma(self):
        st = fl.FollowState(lost_timeout=2.0)
        st.set_target(7, now=0.0)
        st.update([], now=3.0)
        status, (lin, _) = st.update(self.persons((7, 3.0, 0.0)), now=3.1)
        self.assertEqual(status, fl.FollowState.FOLLOWING)
        self.assertGreater(lin, 0)

    def test_sin_distancia_valida_frena_sin_perderlo(self):
        st = fl.FollowState(lost_timeout=2.0)
        st.set_target(0, now=0.0)
        nan = float('nan')
        self.assertEqual(st.update(self.persons((0, nan, nan)), now=3.0), (fl.FollowState.FOLLOWING, (0.0, 0.0)))

    def test_dejar_de_seguir(self):
        st = fl.FollowState()
        st.set_target(7, now=0.0)
        st.set_target(-1, now=1.0)
        self.assertEqual(st.update(self.persons((7, 3.0, 0.0)), now=1.1), (fl.FollowState.IDLE, None))


class TestHelpers(unittest.TestCase):
    def test_bbox_normalizado(self):
        corners = [(320, 180), (640, 180), (640, 540), (320, 540)]
        self.assertEqual(fl.normalize_bbox(corners, 1280, 720), (0.25, 0.25, 0.5, 0.75))

    def test_bbox_fuera_de_imagen_se_recorta(self):
        corners = [(-10, -5), (1300, -5), (1300, 800), (-10, 800)]
        self.assertEqual(fl.normalize_bbox(corners, 1280, 720), (0.0, 0.0, 1.0, 1.0))

    def test_is_person(self):
        self.assertTrue(fl.is_person('Person'))
        self.assertFalse(fl.is_person('Animal'))
        self.assertFalse(fl.is_person(None))


if __name__ == '__main__':
    unittest.main()
