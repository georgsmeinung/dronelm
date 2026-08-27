import math

from src.navigation.waypoint_tracker import (
    ORIENT_SETTLE_CYCLES,
    WaypointTracker,
    effective_stall_threshold,
    hard_stall_threshold,
)


def test_single_waypoint_mission_completes():
    tracker = WaypointTracker([{"x": 10, "y": 0, "z": -10, "label": "WP1"}], acceptance_radius=2.0)
    assert not tracker.is_completed
    tracker.update({"x": 10, "y": 0, "z": -10})
    assert tracker.is_completed


def test_empty_waypoint_list_is_immediately_completed():
    tracker = WaypointTracker([])
    assert tracker.is_completed


def test_dist_xy_ignores_altitude_unlike_distance():
    """Regresion del bug de escape por altura descontrolado (F3.3, 2026-0824):

    subir (cambiar Z) hacia un waypoint a altitud constante no debe mover
    dist_xy, aunque si empeora distance (3D). runner.py/main.py usan dist_xy
    para decidir si hubo progreso -- si usaran distance, cada ciclo de
    ascenso durante un escape empeoraria mecanicamente la metrica y el
    escape nunca se resolveria (ver test_escape_deadlock.py).
    """
    tracker = WaypointTracker([{"x": 10, "y": 0, "z": -10, "label": "WP1"}])
    g_ground = tracker.compute_guidance({"x": 0.0, "y": 0.0, "z": -10.0}, current_yaw=0.0)
    g_climbed = tracker.compute_guidance({"x": 0.0, "y": 0.0, "z": -50.0}, current_yaw=0.0)

    assert g_ground["dist_xy"] == g_climbed["dist_xy"] == 10.0
    assert g_climbed["distance"] > g_ground["distance"]  # 3D si empeora al subir


def test_zero_length_segment_does_not_crash_guidance():
    # Waypoints duplicados: segmento de longitud 0 entre WP0 y WP1.
    wps = [
        {"x": 0, "y": 0, "z": -10, "label": "A"},
        {"x": 0, "y": 0, "z": -10, "label": "B"},
        {"x": 50, "y": 0, "z": -10, "label": "C"},
    ]
    tracker = WaypointTracker(wps, acceptance_radius=1.0)
    guidance = tracker.compute_guidance({"x": 0.0, "y": 0.0, "z": -10.0}, current_yaw=0.0)
    assert guidance is not None
    assert not (guidance["vx"] != guidance["vx"])  # no NaN


def test_inject_corner_waypoint_dedup_within_radius():
    tracker = WaypointTracker([{"x": 100, "y": 100, "z": -10, "label": "FAR"}])
    first = tracker.inject_corner_waypoint(10.0, 10.0, -10.0, label="CORNER_A")
    assert first is True
    # Segunda inyeccion muy cerca de la primera: debe ser rechazada (dedup).
    second = tracker.inject_corner_waypoint(11.0, 11.0, -10.0, label="CORNER_B")
    assert second is False


def test_record_progress_resets_on_real_progress():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(100.0)
    tracker.record_progress(99.0)
    assert tracker.progress_stall_cycles == 0


def test_record_progress_increments_when_stalled():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(50.0)
    tracker.record_progress(50.2)
    tracker.record_progress(50.1)
    assert tracker.progress_stall_cycles == 2


def test_long_correct_manhattan_detour_does_not_count_as_stuck():
    """Regresion F2.5: un desvio largo pero que sigue acercando al waypoint

    (aunque tome muchos ciclos) no debe contar como atasco.
    """
    tracker = WaypointTracker([{"x": 200, "y": 0, "z": -10, "label": "WP1"}])
    distances = [200 - i for i in range(0, 60, 2)]  # progreso monotono, de a 2m
    for d in distances:
        tracker.record_progress(float(d))
    assert tracker.progress_stall_cycles == 0


def test_reset_progress_clears_stall_counter():
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    tracker.record_progress(50.0)
    tracker.record_progress(50.0)
    assert tracker.progress_stall_cycles == 1
    tracker.reset_progress()
    assert tracker.progress_stall_cycles == 0


def test_waypoint_advance_resets_progress_tracking():
    tracker = WaypointTracker(
        [{"x": 10, "y": 0, "z": -10, "label": "A"}, {"x": 20, "y": 0, "z": -10, "label": "B"}],
        acceptance_radius=2.0,
    )
    tracker.record_progress(10.0)
    tracker.record_progress(10.0)
    assert tracker.progress_stall_cycles == 1
    tracker.update({"x": 10, "y": 0, "z": -10})  # alcanza WP A
    assert tracker.progress_stall_cycles == 0


def test_effective_stall_threshold_is_coherent_with_the_progress_epsilon(monkeypatch):
    """Regresion 2026-0824: el umbral en CICLOS y el epsilon en METROS se
    configuraban por separado, produciendo combinaciones imposibles.

    Con eps=0.5m, umbral=5 ciclos y LOOP_HZ=5 hacia falta acercarse a 0.5 m/s
    sostenidos para no acumular atasco; durante un giro cerrado el guiado da
    ~0.25 m/s reales, asi que el escape por altura se disparaba solo a los 5
    ciclos de arrancar la mision, sin ningun obstaculo.
    """
    monkeypatch.setenv("EVASION_STUCK_THRESHOLD", "5")
    monkeypatch.setenv("WAYPOINT_PROGRESS_EPS_M", "0.5")
    monkeypatch.setenv("LOOP_HZ", "5.0")
    monkeypatch.setenv("MIN_PROGRESS_SPEED_MPS", "0.25")

    threshold = effective_stall_threshold()
    assert threshold == 10  # ceil(0.5 * 5 / 0.25), no los 5 configurados

    # La velocidad de acercamiento exigida queda por debajo de la alcanzable.
    assert 0.5 * 5.0 / threshold <= 0.25
    assert hard_stall_threshold() > threshold


def test_effective_stall_threshold_never_lowers_the_configured_value(monkeypatch):
    monkeypatch.setenv("EVASION_STUCK_THRESHOLD", "40")
    monkeypatch.setenv("WAYPOINT_PROGRESS_EPS_M", "0.5")
    monkeypatch.setenv("LOOP_HZ", "5.0")
    monkeypatch.setenv("MIN_PROGRESS_SPEED_MPS", "0.25")
    assert effective_stall_threshold() == 40


def test_sharp_turn_gets_more_yaw_authority():
    """Regresion 2026-0824: con un tope unico de 15 deg/s, realinear un desvio
    de ~70 grados tardaba mas que lo que tarda el contador de atasco en
    dispararse -- el dron se declaraba atascado por no terminar un giro que el
    propio limitador le impedia terminar a tiempo.
    """
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    pos = {"x": 0.0, "y": 0.0, "z": -10.0}

    g_small = tracker.compute_guidance(pos, current_yaw=math.radians(10.0), cruise_speed=2.0)
    assert abs(g_small["yaw_rate"]) <= 15.0  # regimen normal: tope historico

    tracker_sharp = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    g_sharp = tracker_sharp.compute_guidance(pos, current_yaw=math.radians(72.0), cruise_speed=2.0)
    assert abs(g_sharp["yaw_rate"]) > 15.0  # giro brusco: mas autoridad


def test_guidance_sharp_turn_hysteresis_does_not_flip_flop():
    """Regresion: abs_err oscilando entre 45 y 61 grados (por encima y por

    debajo de los 60 grados de la condicion original de una sola cota) no
    debe alternar la formula de vx cada ciclo. 2026-0826: un giro pronunciado
    ahora gira en el lugar (vx=0) en vez de volar en curva ancha simultanea
    al giro -- eso era lo que se percibia como bandazo/"horcajada" en las
    esquinas. Al salir del giro brusco, un settle adicional (ORIENT_SETTLE_CYCLES)
    retiene vx=0 unos ciclos mas antes de retomar avance.
    """
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    pos = {"x": 0.0, "y": 0.0, "z": -10.0}

    g1 = tracker.compute_guidance(pos, current_yaw=math.radians(61), cruise_speed=5.0)
    assert g1["vx"] == 0.0  # abs_err=61 > 60: entra en giro brusco, gira en el lugar

    g2 = tracker.compute_guidance(pos, current_yaw=math.radians(55), cruise_speed=5.0)
    assert g2["vx"] == 0.0  # abs_err=55: bajo 60 pero sobre la banda de salida (50) -> sigue activo

    g3 = tracker.compute_guidance(pos, current_yaw=math.radians(45), cruise_speed=5.0)
    assert g3["vx"] == 0.0  # abs_err=45 < 50: sale del giro brusco, pero entra en settle

    for _ in range(ORIENT_SETTLE_CYCLES - 1):
        g_settle = tracker.compute_guidance(pos, current_yaw=math.radians(45), cruise_speed=5.0)
        assert g_settle["vx"] == 0.0  # settle en curso: sigue sin avanzar

    g_after_settle = tracker.compute_guidance(pos, current_yaw=math.radians(45), cruise_speed=5.0)
    assert g_after_settle["vx"] > 0.0  # settle agotado: recien aqui retoma avance


def test_guidance_final_approach_hysteresis_does_not_flip_flop():
    """Regresion: dist_3d oscilando entre 3.8m y 4.6m (alrededor del umbral

    original de 4.0m) no debe alternar la formula de vx cada ciclo.
    """
    tracker = WaypointTracker([{"x": 10, "y": 0, "z": -10, "label": "WP1"}], acceptance_radius=1.0)
    final_approach_vx = 1.2  # 1.2 * cos(0)

    g1 = tracker.compute_guidance({"x": 6.2, "y": 0.0, "z": -10.0}, current_yaw=0.0, cruise_speed=5.0)
    assert g1["vx"] == final_approach_vx  # dist=3.8 < 4.0: entra en aproximacion final

    g2 = tracker.compute_guidance({"x": 5.7, "y": 0.0, "z": -10.0}, current_yaw=0.0, cruise_speed=5.0)
    assert g2["vx"] == final_approach_vx  # dist=4.3: sobre 4.0 pero bajo la banda de salida (4.5) -> sigue activo

    g3 = tracker.compute_guidance({"x": 5.4, "y": 0.0, "z": -10.0}, current_yaw=0.0, cruise_speed=5.0)
    assert g3["vx"] != final_approach_vx  # dist=4.6 > 4.5: recien aqui sale de aproximacion final


def test_guidance_yaw_deadzone_hysteresis_does_not_flip_flop():
    """Regresion: abs_err oscilando entre 1.0 y 3.0 grados (alrededor de la

    zona muerta original de 2.5 grados) no debe alternar yaw_rate entre 0 y
    un valor de correccion cada ciclo.
    """
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    pos = {"x": 0.0, "y": 0.0, "z": -10.0}

    g1 = tracker.compute_guidance(pos, current_yaw=math.radians(3.0), cruise_speed=5.0)
    assert g1["yaw_rate"] != 0.0  # abs_err=3.0 > 2.5: empieza a corregir

    g2 = tracker.compute_guidance(pos, current_yaw=math.radians(2.0), cruise_speed=5.0)
    assert g2["yaw_rate"] != 0.0  # abs_err=2.0: bajo 2.5 pero sobre la banda de salida (1.5) -> sigue corrigiendo

    g3 = tracker.compute_guidance(pos, current_yaw=math.radians(1.0), cruise_speed=5.0)
    # abs_err=1.0 < 1.5: la histeresis deja de corregir (yaw_rate crudo=0),
    # pero el EMA (ver test de suavizado abajo) lo hace decaer en rampa en
    # vez de saltar a 0.0 de golpe -- por eso no es exactamente 0 aqui.
    assert abs(g3["yaw_rate"]) < abs(g2["yaw_rate"])

    # Varios ciclos despues, sin correccion activa, el EMA converge a 0.
    for _ in range(20):
        g_settled = tracker.compute_guidance(pos, current_yaw=math.radians(1.0), cruise_speed=5.0)
    assert abs(g_settled["yaw_rate"]) < 0.01


def test_guidance_vx_smoothing_ramps_instead_of_jumping():
    """Regresion: un cambio abrupto del vx "crudo" (ej. al cruzar el umbral

    de giro brusco) no debe reflejarse de golpe en el vx devuelto -- el EMA
    (GUIDANCE_SMOOTHING_ALPHA) lo convierte en una rampa de varios ciclos.
    Esto es lo que ataca el ruido residual que la histeresis de umbrales por
    si sola no cubre (ver PLAN de la opcion 2: suavizado exponencial).
    """
    tracker = WaypointTracker([{"x": 100, "y": 0, "z": -10, "label": "WP1"}])
    pos = {"x": 0.0, "y": 0.0, "z": -10.0}

    # Vuelo recto (abs_err=0): vx crudo = cruise_speed = 5.0. El primer
    # valor no tiene historia previa, se usa tal cual (sin suavizar).
    g1 = tracker.compute_guidance(pos, current_yaw=0.0, cruise_speed=5.0)
    assert g1["vx"] == 5.0

    # Giro brusco (abs_err=90 > 60): vx crudo salta a 0.0 (gira en el lugar,
    # 2026-0826). Sin suavizado, g2["vx"] seria exactamente 0.0. Con EMA
    # (alpha=0.5), debe quedar a mitad de camino entre el valor anterior
    # (5.0) y el nuevo objetivo (0.0): ni el valor viejo ni el nuevo de golpe.
    g2 = tracker.compute_guidance(pos, current_yaw=math.radians(90), cruise_speed=5.0)
    assert 0.0 < g2["vx"] < 5.0

    # Con el regimen ya estable en giro brusco, varios ciclos despues
    # converge al valor objetivo (0.0).
    for _ in range(20):
        g_settled = tracker.compute_guidance(pos, current_yaw=math.radians(90), cruise_speed=5.0)
    assert abs(g_settled["vx"] - 0.0) < 0.01
