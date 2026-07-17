from __future__ import annotations

import sys
from pathlib import Path

# Agregar el directorio 'src' al path para poder importar airsim_plan
src_path = Path(__file__).resolve().parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from airsim_plan.missions import MissionPlanner, PlannerError, load_manifest
from airsim_plan.missions.manifest import MissionManifest, save_manifest
from airsim_plan.config import get_settings

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

# Servir archivos estáticos del frontend
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
