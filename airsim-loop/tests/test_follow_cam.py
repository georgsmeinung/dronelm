"""FollowCam: video externo sincronizado, solo auditoria (2026-0929)."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import src.hardware.airsim_client as ac
from src.logging import FollowCamRecorder, write_viewer_html
from src.logging.follow_cam import follow_video_path


# ---------------------------------------------------------------- grabador
def test_follow_video_path_naming():
    assert follow_video_path("/x/run.webm").replace("\\", "/") == "/x/run.follow.webm"


def _frame(v=50):
    return np.full((48, 64, 3), v, dtype=np.uint8)


def test_recorder_keeps_one_frame_per_cycle_filling_gaps(tmp_path):
    rec = FollowCamRecorder(str(tmp_path / "run" / "run.webm"), fps=5.0, scale=1.0)
    rec.write(None)            # antes del primer frame real: negro
    rec.write(None)
    rec.write(_frame(10))
    rec.write(None)            # repite el ultimo
    rec.write(_frame(20))
    n = rec.close()
    assert n == 5                                     # un frame por ciclo, ninguno saltado
    assert rec.out_path.name == "run.follow.webm" and rec.out_path.exists()


def test_recorder_without_any_frame_writes_nothing(tmp_path):
    rec = FollowCamRecorder(str(tmp_path / "r" / "r.webm"), fps=5.0)
    rec.write(None)
    assert rec.close() == 0


# ---------------------------------------------------------------- visor
def _csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("cycle,t,route,action\n1,0.2,reactive,MANTENER_RUMBO\n2,0.4,reactive,MANTENER_RUMBO\n", encoding="utf-8")
    return p


def test_viewer_references_follow_video_when_given(tmp_path):
    write_viewer_html(str(tmp_path / "v.html"), "r.webm", str(_csv(tmp_path)), follow_video_filename="r.follow.webm")
    html = (tmp_path / "v.html").read_text(encoding="utf-8")
    assert 'const FOLLOW = "r.follow.webm";' in html
    assert "syncFollow" in html


def test_viewer_without_follow_has_null(tmp_path):
    write_viewer_html(str(tmp_path / "v.html"), "r.webm", str(_csv(tmp_path)))
    assert "const FOLLOW = null;" in (tmp_path / "v.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- cliente
class _Resp:
    def __init__(self, w, h, rgb):
        self.width, self.height = w, h
        self.image_data_uint8 = rgb.tobytes()
        self.time_stamp = 1_000_000_000


class _FakeSim:
    def __init__(self, follow_ok=True, camera_info_ok=True, raise_on_follow=False):
        self.calls = []
        self.types = []
        self.follow_ok, self.camera_info_ok, self.raise_on_follow = follow_ok, camera_info_ok, raise_on_follow

    def simGetCameraInfo(self, name, vehicle_name=""):
        # En el plugin real esto tumba UE (nullptr sin comprobar) si la camara no existe.
        raise AssertionError("simGetCameraInfo no debe llamarse: puede tumbar Unreal Engine")

    def simGetImages(self, requests, vehicle_name=""):
        self.calls.append([r[0] for r in requests])
        self.types.append([r[1] for r in requests])
        known = {0, "FollowCam"} if self.camera_info_ok else {0}
        for r in requests:
            if r[0] not in known:
                raise RuntimeError(f"camera {r[0]} not found")     # std::map::at -> error RPC
        if self.raise_on_follow and len(requests) > 1:
            raise RuntimeError("bad camera")
        out = []
        for i, r in enumerate(requests):
            if r[1] == 1:                                         # DepthPlanar (tipo de imagen 1)
                out.append(SimpleNamespace(width=4, height=4, image_data_float=[2.0] * 16, time_stamp=1_000_000_000))
            elif r[0] == "FollowCam":
                fol = np.zeros((6, 8, 3), dtype=np.uint8)
                fol[..., 0] = 200                                 # rojo en RGB -> BGR canal 2
                # follow_ok=False solo afecta a la captura del ciclo (el probe de enable siempre devuelve imagen)
                out.append(_Resp(8, 6, fol) if (self.follow_ok or len(requests) == 1)
                           else SimpleNamespace(width=0, height=0, image_data_uint8=b"", time_stamp=0))
            else:
                front = np.zeros((4, 4, 3), dtype=np.uint8)
                front[..., 0] = 255                               # rojo en RGB
                out.append(_Resp(4, 4, front))
        return out

    def getMultirotorState(self, vehicle_name=""):
        return SimpleNamespace()

    def getImuData(self, vehicle_name=""):
        raise RuntimeError("sin IMU")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ac, "airsim", SimpleNamespace(
        ImageRequest=lambda cam, typ, a, b: (cam, typ),
        ImageType=SimpleNamespace(Scene=0, DepthPlanar=1),
    ))

    def _make(**kw):
        c = ac.AirSimClient()
        c._connected = True
        c._client = _FakeSim(**kw)
        c.frame_width, c.frame_height = 4, 4
        return c
    return _make


def test_follow_cam_is_off_by_default_and_costs_nothing(client):
    c = client()
    c.capture()
    assert len(c._client.calls[0]) == 1 and c.last_follow_frame is None


def test_follow_cam_requested_in_same_call_and_decoded_bgr(client):
    c = client()
    assert c.enable_follow_cam("FollowCam") is True
    assert c._client.calls[0] == ["FollowCam"]                   # probe de enable: solo esa camara
    img, telem = c.capture()
    assert c._client.calls[-1] == [0, "FollowCam"]               # ciclo: frontal + FollowCam en UNA llamada
    assert img.shape == (4, 4, 3)
    assert c.last_follow_frame.shape == (6, 8, 3)                # sin resize: tamano nativo
    assert c.last_follow_frame[0, 0, 2] == 200                   # RGB -> BGR


def test_follow_cam_not_requested_for_depth_capture(client):
    c = client()
    c.enable_follow_cam("FollowCam")
    img, depth, _ = c.capture(return_depth=True)
    assert c._client.types[-1] == [0, 1]                         # Scene + DepthPlanar en la camara frontal...
    assert "FollowCam" not in c._client.calls[-1]                # ...y sin FollowCam (no pisa el indice de profundidad)
    assert depth is not None and depth.shape == (4, 4)
    assert c._follow_cam == "FollowCam"                          # sigue activa para el resto de los ciclos


def test_unknown_camera_is_not_enabled(client):
    c = client(camera_info_ok=False)
    assert c.enable_follow_cam("FollowCam") is False            # el probe (simGetImages) falla -> no se activa
    c.capture()
    assert c._client.calls[-1] == [0]


def test_follow_cam_disables_after_repeated_empty_frames(client):
    c = client(follow_ok=False)
    c.enable_follow_cam("FollowCam")
    for _ in range(5):
        c.capture()
    assert c._follow_cam is None and c.last_follow_frame is None


def test_capture_error_with_follow_retries_without_it(client):
    c = client(raise_on_follow=True)
    c.enable_follow_cam("FollowCam")
    img, _ = c.capture()
    assert img is not None and c._follow_cam is None             # el ciclo no se degrada


# ------------------------------------------------- invariante de aislamiento
def test_follow_frame_never_reaches_the_graph():
    """La camara externa es solo de auditoria: ningun modulo de agentes/percepcion la usa."""
    root = Path(__file__).resolve().parents[1] / "src"
    pat = re.compile(r"last_follow_frame|follow_cam|FollowCam", re.IGNORECASE)
    offenders = []
    for sub in ("agents", "perception", "navigation"):
        for f in (root / sub).rglob("*.py"):
            if "legacy" in f.parts:
                continue
            if pat.search(f.read_text(encoding="utf-8")):
                offenders.append(str(f.relative_to(root)))
    assert offenders == []


# ------------------------------------------------- reparacion de corrida interrumpida
def test_finalize_repairs_follow_video_and_links_it_in_viewer(tmp_path, monkeypatch):
    from src.logging import FlightLogger, FlightVideoRecorder
    import src.logging.finalize_run as fin
    from src.logging.finalize_run import finalize_run

    # Un archivo cortado a mano aun reporta un conteo valido; se fuerza la rama de reparacion
    # (un webm realmente matado a mitad de escritura da conteo negativo).
    monkeypatch.setattr(fin, "_video_is_finalized", lambda p: False)

    out = tmp_path / "run" / "run.jsonl"
    lg = FlightLogger(str(out), scenario="S", seed=1, arm="slm")
    vr = FlightVideoRecorder(str(out.with_suffix(".webm")), (64, 48), 5.0, scale=1.0)
    fr = FollowCamRecorder(str(out.with_suffix(".webm")), fps=5.0, scale=1.0)
    for c in range(1, 21):
        st = {"telemetry": {"position": {"x": 0, "y": 0, "z": -6}, "velocity": {}, "orientation": {"yaw": 0},
                            "collision": {}}, "waypoint_guidance": {}, "obstacle_field": None,
              "route": "reactive", "next_action": "MANTENER_RUMBO", "current_wp_index": 0, "deliberations": []}
        lg.log_cycle(st, latency_ms={"graph": 1.0})
        vr.write_frame(_frame(c * 5))
        fr.write(_frame(255 - c * 5))
    vr.close()
    fr.close()
    lg._fh.close()
    lg._csv_fh.close()                                   # corte: sin close() del logger ni visor
    fp = out.with_name("run.follow.webm")
    fp.write_bytes(fp.read_bytes()[: int(fp.stat().st_size * 0.7)])   # follow sin indice

    rep = finalize_run(str(out.parent), log=lambda *_: None)
    assert rep["follow"].startswith("reparado")
    html = out.with_suffix(".viewer.html").read_text(encoding="utf-8")
    assert 'const FOLLOW = "run.follow.webm";' in html
