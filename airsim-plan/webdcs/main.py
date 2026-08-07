from __future__ import annotations

import sys
from pathlib import Path

# Agregar el directorio 'src' al path para poder importar airsim_plan
src_path = Path(__file__).resolve().parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, BackgroundTasks
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airsim_plan.missions import MissionPlanner, PlannerError, load_manifest
from airsim_plan.missions.manifest import MissionManifest, save_manifest
from airsim_plan.config import get_settings
from airsim_plan.bridge import LoopRunner, BridgeError

# Guardar los runners activos para poder detenerlos
active_runners: dict[str, LoopRunner] = {}

app = FastAPI(
    title="WebDCS - Ground Control Station Planner",
    description="Interfaz web para compilación y visualización de manifiestos de vuelo",
    version="1.0.0",
)

# Permitir CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CompileRequest(BaseModel):
    instruction: str

class SaveRequest(BaseModel):
    manifest: dict
    watch: bool | None = None

@app.post("/api/compile")
async def compile_instruction(req: CompileRequest):
    if not req.instruction.strip():
        raise HTTPException(status_code=400, detail="La instrucción no puede estar vacía")
    
    planner = MissionPlanner()
    try:
        manifest = planner.compile(req.instruction)
        return manifest.model_dump()
    except PlannerError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error inesperado del planificador: {exc}")

@app.post("/api/save")
async def save_manifest_endpoint(req: SaveRequest):
    planner = MissionPlanner()
    try:
        manifest = MissionManifest.from_dict(req.manifest)
        # Re-generar el prompt táctico por si cambiaron cosas en el JSON en la UI
        manifest.tactical_system_prompt = planner.build_tactical_prompt(manifest)
        
        target_dir = planner.settings.mission_dir / "flightplans"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{manifest.mission_id.lower()}.json"
        path = target_dir / filename
        
        save_manifest(manifest, path)
        return {
            "status": "success",
            "filename": filename,
            "path": str(path),
            "manifest": manifest.model_dump()
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Error de validación: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al guardar el manifiesto: {exc}")

@app.post("/api/launch")
async def launch_mission(req: SaveRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    planner = MissionPlanner()
    try:
        manifest = MissionManifest.from_dict(req.manifest)
        # Re-generar el prompt táctico
        manifest.tactical_system_prompt = planner.build_tactical_prompt(manifest)
        
        # Guardar manifiesto antes de lanzar para persistencia
        target_dir = planner.settings.mission_dir / "flightplans"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{manifest.mission_id.lower()}.json"
        path = target_dir / filename
        save_manifest(manifest, path)
        loop_path = Path(__file__).resolve().parent.parent.parent / "airsim-loop" / "main.py"
        if not loop_path.exists():
            loop_path = None
        runner = LoopRunner(manifest, loop_path=loop_path, watch=req.watch)
        active_runners[manifest.mission_id] = runner

        # Lanzar la misión en segundo plano
        def run_loop():
            try:
                runner.run()
            except Exception as e:
                print(f"Error ejecutando LoopRunner: {e}")

        import threading
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()

        return {
            "status": "success",
            "message": f"Misión {manifest.mission_id} lanzada con éxito.",
            "manifest": manifest.model_dump()
        }
    except BridgeError as exc:
        detail=(
            f"Error de conexión con AirSim: {exc}. "
            f"(Configuración: host={settings.airsim_host}, "
            f"port={settings.airsim_port}, "
            f"vehicle={settings.airsim_vehicle_name})"
        )
        print("Detail: ", detail)
        raise HTTPException(
            status_code=400,
            detail=detail
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Error de validación: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error al lanzar la misión: {exc}")


@app.post("/api/stop")
async def stop_mission():
    global active_runners
    stopped_count = 0
    # Detener todos los runners activos
    for mission_id, runner in list(active_runners.items()):
        try:
            runner.stop()
            stopped_count += 1
            active_runners.pop(mission_id, None)
        except Exception as e:
            print(f"Error al detener runner {mission_id}: {e}")
    
    # También forzar parada en variables de entorno por si acaso
    import os
    for key in list(os.environ.keys()):
        if key.startswith("STOP_MISSION_"):
            os.environ[key] = "1"
            
    return {"status": "success", "message": f"{stopped_count} misión(es) detenida(s)."}

@app.post("/api/reset")
async def reset_simulation():
    settings = get_settings()
    try:
        import cosysairsim as airsim
        client = airsim.MultirotorClient(ip=settings.airsim_host, port=settings.airsim_port)
        client.confirmConnection()
        client.reset()
        client.enableApiControl(False, settings.airsim_vehicle_name)
        return {"status": "success", "message": "Simulación reseteada con éxito."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al resetear simulación: {e}")

@app.get("/api/manifests")
async def list_manifests():
    settings = get_settings()
    mission_dir = settings.mission_dir / "flightplans"
    if not mission_dir.exists():
        return []
    
    manifests = []
    for path in mission_dir.glob("*.json"):
        # Ignorar archivos temporales
        if ".preloop" in path.name:
            continue
        try:
            manifest = load_manifest(path)
            manifests.append({
                "filename": path.name,
                "manifest": manifest.model_dump()
            })
        except Exception:
            # Si el JSON es corrupto o antiguo, ignorar o cargar lo básico
            pass
    return manifests

@app.delete("/api/manifests/{filename}")
async def delete_manifest_endpoint(filename: str):
    settings = get_settings()
    mission_dir = settings.mission_dir / "flightplans"
    path = mission_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="El archivo no existe")
    try:
        path.unlink()
        return {"status": "success", "message": f"Archivo {filename} eliminado"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo eliminar el archivo: {exc}")

@app.get("/api/maps")
async def list_maps():
    maps_dir = Path(__file__).resolve().parent.parent / "missions" / "maps"
    if not maps_dir.exists():
        return []
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    maps = []
    for p in maps_dir.glob("*"):
        if p.suffix.lower() in allowed_extensions:
            maps.append(p.name)
    return sorted(maps)

@app.get("/api/planner/status")
async def planner_status():
    planner = MissionPlanner()
    is_online = planner._client.check_connection()
    return {"status": "online" if is_online else "offline"}

# Servir mapas desde missions/maps
missions_maps_dir = Path(__file__).resolve().parent.parent / "missions" / "maps"
app.mount("/maps", StaticFiles(directory=str(missions_maps_dir)), name="maps")

# Servir archivos estáticos del frontend
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
