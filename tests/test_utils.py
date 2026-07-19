"""
Tests de utilidades: formatear_uptime, Color, funciones de display.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from unifi_agent.core.utils import formatear_uptime, Color


class TestFormatearUptime:
    def test_dias_horas_minutos(self):
        segundos = 3 * 86400 + 14 * 3600 + 22 * 60  # 3d 14h 22m
        assert formatear_uptime(segundos) == "3d 14h 22m"

    def test_solo_minutos(self):
        assert formatear_uptime(2700) == "45m"

    def test_horas_y_minutos(self):
        segundos = 2 * 3600 + 30 * 60  # 2h 30m
        assert formatear_uptime(segundos) == "2h 30m"

    def test_cero(self):
        assert formatear_uptime(0) == "N/A"

    def test_negativo(self):
        assert formatear_uptime(-100) == "N/A"

    def test_none(self):
        assert formatear_uptime(None) == "N/A"


class TestColor:
    def test_codes_exist(self):
        assert Color.RESET == "\033[0m"
        assert Color.BOLD == "\033[1m"
        assert Color.RED == "\033[91m"
        assert Color.GREEN == "\033[92m"
        assert Color.YELLOW == "\033[93m"
        assert Color.CYAN == "\033[96m"
