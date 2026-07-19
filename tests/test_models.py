"""
Tests de validación de modelos Pydantic y excepciones.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from unifi_agent.core.models import (
    MetricaDispositivo, ConfigWlan, ConfigNetwork,
    AccionRecomendada, AnalisisMejoresPracticas, DiagnosticoRed,
    UniFiError, UniFiConnectionError, UniFiAuthError, UniFiAPIError,
)


class TestMetricaDispositivo:
    def test_modelo_valido(self):
        m = MetricaDispositivo(
            nombre="AP-Sala", mac="aa:bb:cc:dd:ee:ff", modelo="U6-Pro",
            tipo="Access Point", estado="conectado", ip="192.168.1.10",
            uptime="3d 14h 22m", uptime_segundos=300000,
            version_firmware="6.6.55", satisfaccion=95,
            num_usuarios=12, carga_cpu="5.2%", uso_memoria="42.1%",
            tx_bytes=1000000, rx_bytes=2000000, ultimo_contacto="2026-07-19 10:00:00"
        )
        assert m.nombre == "AP-Sala"
        assert m.tipo == "Access Point"
        assert m.num_usuarios == 12

    def test_modelo_defaults(self):
        m = MetricaDispositivo(tipo="Switch")
        assert m.nombre == "Sin nombre"
        assert m.mac == "N/A"
        assert m.estado == "desconocido"
        assert m.num_usuarios == 0


class TestConfigWlan:
    def test_alias_mapping(self):
        w = ConfigWlan(**{
            "name": "Corporativo",
            "security": "wpa2",
            "wpa3_support": True,
            "pmf_mode": "required",
            "fast_roaming_enabled": True,
            "uapsd_enabled": False,
            "multicast_enhance": True,
            "hide_ssid": False,
        })
        assert w.ssid == "Corporativo"
        assert w.seguridad == "wpa2"
        assert w.wpa3 is True
        assert w.pmf == "required"
        assert w.fast_roaming is True

    def test_defaults(self):
        w = ConfigWlan()
        assert w.ssid == "Sin SSID"
        assert w.seguridad == "open"
        assert w.wpa3 is False


class TestConfigNetwork:
    def test_alias_mapping(self):
        n = ConfigNetwork(**{
            "name": "IoT",
            "vlan": 30,
            "purpose": "corporate",
            "ip_subnet": "192.168.30.1/24",
            "dhcpd_enabled": True,
            "igmp_snooping": True,
            "upnp_enabled": False,
        })
        assert n.nombre == "IoT"
        assert n.vlan_id == 30
        assert n.subred == "192.168.30.1/24"
        assert n.igmp_snooping is True

    def test_defaults(self):
        n = ConfigNetwork()
        assert n.nombre == "Sin nombre"
        assert n.vlan_id is None
        assert n.upnp is False


class TestDiagnosticoRed:
    def test_estructura_completa(self):
        d = DiagnosticoRed(
            resumen_general="Red estable.",
            problemas_detectados=["AP-Sala con CPU alta"],
            mejores_practicas=[
                AnalisisMejoresPracticas(
                    regla="WPA3", estado_actual="WPA2", cumple=False,
                    recomendacion="Activar WPA3", prioridad="alta"
                )
            ],
            acciones_recomendadas=[
                AccionRecomendada(
                    dispositivo="AP-Sala", mac="aa:bb:cc:dd:ee:ff",
                    accion="monitorear", motivo="CPU alta", prioridad="media"
                )
            ],
            observaciones_adicionales=["Considerar añadir más APs"],
        )
        assert d.resumen_general == "Red estable."
        assert len(d.problemas_detectados) == 1
        assert len(d.mejores_practicas) == 1
        assert d.mejores_practicas[0].cumple is False


class TestExcepciones:
    def test_herencia_unifi(self):
        assert issubclass(UniFiConnectionError, UniFiError)
        assert issubclass(UniFiAuthError, UniFiError)
        assert issubclass(UniFiAPIError, UniFiError)
        assert issubclass(UniFiError, Exception)
