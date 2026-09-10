"""D1 (PLAN-DEUDA-TECNICA.md): decodificación restringida dinámica por reason_note.

Verifica que `_schema_for_reason` poda correctamente el enum de macro_action
según el motivo de consulta, sin afectar los casos no listados.
"""
from __future__ import annotations

import src.agents.deliberative as deliberative

FULL_ACTIONS = deliberative.PROMPT_ACTIONS


def _enum_for(reason_key: str) -> set:
    schema = deliberative._schema_for_reason(reason_key)
    return set(schema["json_schema"]["schema"]["properties"]["macro_action"]["enum"])


class TestSchemaForReason:
    def test_ttc_critico_excluye_mantener_rumbo(self):
        enum = _enum_for("TTC_CRITICO")
        assert "MANTENER_RUMBO" not in enum, "TTC_CRITICO no debe permitir MANTENER_RUMBO"

    def test_ttc_critico_incluye_acciones_de_evasion(self):
        enum = _enum_for("TTC_CRITICO")
        for action in ("EVADIR_IZQUIERDA", "EVADIR_DERECHA", "GANAR_ALTURA", "PERDER_ALTURA", "FRENAR"):
            assert action in enum, f"TTC_CRITICO debe incluir {action}"

    def test_deadlock_escape_excluye_mantener_rumbo_y_frenar(self):
        enum = _enum_for("DEADLOCK_ESCAPE")
        assert "MANTENER_RUMBO" not in enum
        assert "FRENAR" not in enum

    def test_deadlock_escape_incluye_acciones_de_evasion(self):
        enum = _enum_for("DEADLOCK_ESCAPE")
        for action in ("EVADIR_IZQUIERDA", "EVADIR_DERECHA", "GANAR_ALTURA", "PERDER_ALTURA"):
            assert action in enum

    def test_clave_desconocida_devuelve_enum_completo(self):
        for clave in ("", "OTRO", "NO_EVIDENCE", "LATERAL", "xyz"):
            enum = _enum_for(clave)
            assert enum == FULL_ACTIONS, f"Clave '{clave}' debe devolver el enum completo"

    def test_no_muta_schema_base(self):
        """_schema_for_reason no debe modificar RESPONSE_JSON_SCHEMA."""
        original_enum = set(
            deliberative.RESPONSE_JSON_SCHEMA["json_schema"]["schema"]["properties"]["macro_action"]["enum"]
        )
        _enum_for("TTC_CRITICO")
        after_enum = set(
            deliberative.RESPONSE_JSON_SCHEMA["json_schema"]["schema"]["properties"]["macro_action"]["enum"]
        )
        assert original_enum == after_enum, "RESPONSE_JSON_SCHEMA fue mutado por _schema_for_reason"

    def test_enum_es_lista_ordenada(self):
        """El enum debe ser una lista ordenada (requerimiento del JSON Schema)."""
        schema = deliberative._schema_for_reason("TTC_CRITICO")
        enum_list = schema["json_schema"]["schema"]["properties"]["macro_action"]["enum"]
        assert isinstance(enum_list, list)
        assert enum_list == sorted(enum_list)


class TestGetReasonKey:
    def _make_blocked_field(self):
        from src.perception.obstacle_field import ObstacleField, Cell, SECTORS, BANDS
        cells = {
            (s, b): Cell(
                sector=s, band=b,
                occupancy=1.0 if s == "centro" else 0.0,
                ttc_s=1.0 if s == "centro" else float("inf"),
                confidence=1.0 if s == "centro" else 0.0,
            )
            for s in SECTORS for b in BANDS
        }
        return ObstacleField(cells=cells, source="flow", foe_confidence=1.0)

    def _make_clear_field(self):
        from src.perception.obstacle_field import empty_field
        return empty_field()

    def test_campo_bloqueado_devuelve_ttc_critico(self):
        field = self._make_blocked_field()
        assert deliberative._get_reason_key(field) == "TTC_CRITICO"

    def test_campo_libre_devuelve_clave_vacia(self):
        field = self._make_clear_field()
        assert deliberative._get_reason_key(field) == ""
