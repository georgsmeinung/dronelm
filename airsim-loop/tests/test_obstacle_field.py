from src.perception.obstacle_field import BANDS, SECTORS, Cell, ObstacleField, empty_field


def test_empty_field_has_no_blocked_sectors():
    field = empty_field()
    for sector in SECTORS:
        assert not field.is_blocked(sector)
        assert field.sector_ttc(sector) == float("inf")
    assert field.blocked_fraction() == 0.0
    assert field.min_ttc() == float("inf")


def test_cell_blocked_by_occupancy():
    cell = Cell(sector="centro", band="medio", occupancy=0.9, ttc_s=float("inf"), confidence=0.5)
    assert cell.is_blocked()


def test_cell_blocked_by_ttc():
    cell = Cell(sector="centro", band="medio", occupancy=0.0, ttc_s=1.0, confidence=0.5)
    assert cell.is_blocked()


def test_cell_low_confidence_never_blocked():
    cell = Cell(sector="centro", band="medio", occupancy=1.0, ttc_s=0.1, confidence=0.01)
    assert not cell.is_blocked()


def test_sector_ttc_ignores_low_confidence_cells():
    cells = {(s, b): Cell(sector=s, band=b) for s in SECTORS for b in BANDS}
    cells[("centro", "medio")] = Cell(sector="centro", band="medio", ttc_s=1.0, confidence=0.9)
    cells[("centro", "superior")] = Cell(sector="centro", band="superior", ttc_s=0.2, confidence=0.0)
    field = ObstacleField(cells=cells, source="flow")
    assert field.sector_ttc("centro") == 1.0


def test_blocked_fraction_counts_across_all_cells():
    cells = {(s, b): Cell(sector=s, band=b) for s in SECTORS for b in BANDS}
    cells[("centro", "medio")] = Cell(sector="centro", band="medio", occupancy=1.0, confidence=0.9)
    field = ObstacleField(cells=cells, source="flow")
    assert field.blocked_fraction() == 1.0 / 9.0


def test_to_dict_serializes_inf_as_none():
    field = empty_field()
    d = field.to_dict()
    assert d["min_ttc_s"] is None
    for sector in SECTORS:
        assert d["sectors"][sector]["ttc_s"] is None


def test_summary_text_reports_all_three_sectors():
    field = empty_field()
    text = field.summary_text()
    assert "IZQUIERDA" in text
    assert "CENTRO" in text
    assert "DERECHA" in text
