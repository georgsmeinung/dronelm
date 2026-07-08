# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🚀 Quick Start

### ✅ Prerequisites
- GPU NVIDIA with CUDA support
- Unreal Engine 5.5 with Cosys-AirSim
- Ollama/LM Studio running locally

### 📦 Environment Setup
```bash
conda env create -f environment.yml
conda activate airsimenv
```

### 🧠 LLM Configuration
Set these in `.env` files:
```env
LLM_API_URL=http://localhost:11434
AIRSIM_PORT=41451
```

## ⚙️ Key Commands

### 🧪 Lint & Test
```bash
# Full suite
airsim-loop test

# Single test
airsim-loop test --name "obstacle_avoidance"
```

### 📁 Repository Structure
```
airsim-plan       # Ground station mission planning
airsim-loop       # In-flight tactical control
airsim-mcp        # Model Context Protocol server
airsim-kc         # Manual control scripts
airsim-poc        # Proof-of-concept demos
callibration_flight # Simulation calibration
local-llm-eval    # SLM benchmarking
```

### 📈 Evaluation
```bash
# Compare SLM performance
local-llm-eval benchmark --models "llama3.2 gemma2 qwen3.5"

# Analyze telemetry
jupyter notebook telemetry_analysis.ipynb
```

## 🧠 Architecture Overview

### 🏗️ Dual-Brain System
1. **Ground Station (airsim-plan):**
   - Natural language → structured mission manifest
   - Generates `MissionManifest.json` with waypoints and constraints

2. **Flight Loop (airsim-loop):**
   - Real-time perception (YOLOv8n) → semantic scene understanding
   - Gatekeeper decides between:
     - Reactive navigation (direct control)
     - SLM-based deliberative planning

### 🧩 Core Components
- **LangGraph**: State machine for flight control
- **Pydantic**: Schema validation for mission manifests
- **Promptfoo**: JSON parsing and validation

## 📊 Simulation Calibration

### 📈 Physical Fidelity
- AirSim exhibits extreme inertial variations (±30° pitch/roll)
- Real drones have physical constraints (±30° max)
- Use `callibration_flight/telemetry_analysis.ipynb` for statistical analysis

### 🧪 Benchmarking
Compare SLMs using:
- Tokens/second throughput
- Load time latency
- Structural accuracy (JSON validation)

## 📄 Documentation

### 📖 Primary Reference
- [README.md](README.md): Project overview and installation
- [plan_tesis/plan-tesis.md](plan_tesis/plan-tesis.md): Thesis plan and objectives
- [local-llm-eval/README.md](local-llm-eval/README.md): SLM benchmarking details

### 📚 Additional Resources
- [Cosys-AirSim Documentation](https://github.com/Cosys-Lab/Cosys-AirSim)
- [YOLOv8n GitHub](https://github.com/ultralytics/yolov8)
- [LangGraph Guide](https://www.mosaicml.com/blog/langgraph)

## ⚠️ Notes
- Never commit API keys or sensitive data
- All simulations run in Unreal Engine 5.5
- SLM models run locally via Ollama/LM Studio
- Telemetry analysis uses SciPy/Matplotlib

This document reflects the state of the codebase as of 2026-07-07.