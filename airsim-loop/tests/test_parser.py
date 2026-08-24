from src.agents.deliberative import PROMPT_ACTIONS, _fallback_decision, _parse_decision
from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


def test_parse_clean_json():
    raw = '{"macro_action": "EVADIR_IZQUIERDA", "rationale": "calle libre"}'
    result = _parse_decision(raw)
    assert result["macro_action"] == "EVADIR_IZQUIERDA"
    assert result["rationale"] == "calle libre"


def test_parse_markdown_fenced_json():
    raw = '```json\n{"macro_action": "GANAR_ALTURA", "rationale": "callejon sin salida"}\n```'
    result = _parse_decision(raw)
    assert result["macro_action"] == "GANAR_ALTURA"


def test_parse_conversational_text_with_embedded_json():
    raw = 'Claro, aca esta mi decision: {"macro_action": "FRENAR", "rationale": "peligro"} espero que ayude.'
    result = _parse_decision(raw)
    assert result["macro_action"] == "FRENAR"


def test_parse_single_quoted_json():
    raw = "{'macro_action': 'MANTENER_RUMBO', 'rationale': 'todo despejado'}"
    result = _parse_decision(raw)
    assert result["macro_action"] == "MANTENER_RUMBO"


def test_parse_invalid_action_returns_none():
    raw = '{"macro_action": "VOLAR_A_LA_LUNA", "rationale": "no"}'
    assert _parse_decision(raw) is None


def test_parse_truncated_json_falls_back_to_regex():
    raw = '{"macro_action": "EVADIR_DERECHA", "rationale": "se corto aca'
    result = _parse_decision(raw)
    assert result["macro_action"] == "EVADIR_DERECHA"


def test_parse_empty_response_returns_none():
    assert _parse_decision("") is None
    assert _parse_decision(None) is None


def test_parse_bare_action_word_in_prose():
    raw = "Creo que lo mejor es PERDER_ALTURA porque hay un dron encima."
    result = _parse_decision(raw)
    assert result["macro_action"] == "PERDER_ALTURA"


def test_fallback_without_evidence_brakes_instead_of_advancing():
    """Regresion: la version original devolvia MANTENER_RUMBO con lista vacia

    de obstaculos (empujando al dron contra lo que sea que causo el freno).
    Sin evidencia de percepcion, el fallback debe frenar, no avanzar.
    """
    decision = _fallback_decision(empty_field(), guidance={})
    assert decision["macro_action"] == "FRENAR"


def test_fallback_with_clear_center_keeps_going():
    field = empty_field()
    cells = dict(field.cells)
    cells[("centro", "medio")] = Cell(sector="centro", band="medio", occupancy=0.0, ttc_s=float("inf"), confidence=0.9)
    field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)
    decision = _fallback_decision(field, guidance={})
    assert decision["macro_action"] == "MANTENER_RUMBO"


def test_fallback_boxed_in_climbs():
    cells = {
        (s, b): Cell(sector=s, band=b, occupancy=0.9, ttc_s=1.0, confidence=0.9)
        for s in SECTORS for b in BANDS
    }
    field = ObstacleField(cells=cells, source="flow", foe=(0.0, 0.0), foe_confidence=1.0)
    decision = _fallback_decision(field, guidance={})
    assert decision["macro_action"] == "GANAR_ALTURA"
