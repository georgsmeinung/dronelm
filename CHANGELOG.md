**2026-0413**
---
* Reunión avance de Tesis
TODO
* Revisar telemetría real de drones cuadricópteros en https://zenodo.org/records/15912415
* Generar telemetría automatizada de al menos 100 vuelos simulados
* Generar métricas sugeridas inicialmente
* Considerar simular el vuelo de 5 waypoints recogidos de drones reales

**2026-0409**
---
* Generado script de vuelo de calibración y archivo de comandos
* Ejecutados los 10 primeros vuelos de calibración. Cada vuelo individual tiene la telmetría registrada en un .CSV separado

**2026-0402**
---
* En preparación para vuelos de calibración, agregada la condicion de reset para detener el `airsim_logger.py` (escritura de telemetría a archivos)

**2026-0331**
---
* Los modelos Qwen no están interpretando bien los comandos y el Phi 4 no es eficiente. Probando con modelo: (**nvidia/nemotron-3-nano-4b
**)[https://lmstudio.ai/models/nvidia/nemotron-3-nano-4b]
* Determinada plataforma para calibración: Drone con nvidia/nemotron-3-nano-4b. Funciona mejor sin el modo thinking, para no llenar la ventana de contexto muy rápidamente.

**2026-0313**
---
* Probando una versión destilada de Claude 4.6 Opus para evitar consumir muchas VRAM: (**Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF**)[https://huggingface.co/Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF] funciona ocupando sólo 1.69 GB con cuantización de 4 bits  y venta de contexto de 8192 tokens.
* Conectado Claude Code con modelo local `Jackrong/Qwen3.5-2B-Claude-4.6-Opus-Reasoning-Distilled-GGUF` corriendo en LMStudio, pero tuve que subir la ventana de contexto a 32768 por la cantidad de system promps que envia Claude.

**2026-0312**
---
Buscando opciones para mejorar la capacidad agéntica del despliegue sin consumir muchas VRAM. Dado que se está usando una RTX 5060 (8 GB) y se necesita mantener a Unreal Engine funcionando sin problemas, cada megabyte de VRAM cuenta. 
[**Qwen2.5‑Coder‑1.5B‑Instruct**](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF) es una buena opción en este escenario. Con cuantización **Q4\_K\_M**, tiene una huella de aproximadamente **\~1.1 GB**.

**Cómo ajustarlo para que entre en 2 GB (dejando 6 GB para Unreal)**
Para asegurar que el LLM se mantenga estrictamente dentro de 2 GB y no interfiera con la simulación, se usarán estos ajustes específicos en **LM Studio 0.4.1**:

**1. Ventana de contexto** configurada en **8.192 (8k)**. Es crucial habilitar **4‑bit KV Cache (Flash Attention)** en la configuración de LM Studio.  Esto reduce el costo de VRAM de la “memoria” en un **50 %**. Un contexto de 8k en 4‑bit ocupará solo unos **\~150 MB**, mientras que 32k se comería casi **1 GB**.

**2. Offload a GPU** en **Max (todas las capas)**. Si las capas se desbordan a la RAM del sistema (CPU), la velocidad de generación de tokens caerá significativamente, lo que puede hacer que agentes como **Claude Code** haga *timeout* durante tareas complejas.

**3. Estabilidad entre aplicaciones**. En el **Panel de Control de NVIDIA**, setear **“Background Application Max Frame Rate”** para que esté limitado para LM Studio a **20–30 FPS**. Esto evita que la interfaz del LLM compita con Unreal por los recursos de la GPU. 

**Consideraciones adionales: ¿Por qué no usar BitNet aquí?**
Aunque **BitNet (1.58‑bit)** usa aún menos VRAM (**\~0.4 GB**), requiere **bitnet.cpp** o *kernels* especializados. Dado que **LM Studio 0.4.1** todavía no soporta de forma nativa la arquitectura BitNet, se perdería la conveniencia del nuevo endpoint “compatible con Anthropic”. **Qwen 1.5B** es un buen equilibrio entre compatibilidad nativa con LM Studio y bajo consumo de recursos.

**Configuración (PowerShell)**
Una vez que el servidor esté corriendo en el puerto **1234** en LM Studio:
```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL="http://localhost:1234/v1"
$env:ANTHROPIC_API_KEY="lm-studio"
claude
```
Si Unreal Engine empieza a dar lags en el render, revisar el uso de VRAM en la barra inferior de LM Studio. Si supera **1.8 GB**, bajar la ventana de contexto a **4.096**.

* Modelo Qwen2.5‑Coder‑1.5B‑Instruct funcionando correctamente con MCP server de AirSim

**2026-0310**
---
* Generada una versión funcional del Airsim Drone MCP server
* Pruebas de conexión y funcionamiento del loop de eventos de Airsim y el MCP


**2026-0304**
---
* Instalado https://huggingface.co/DevQuasar/HuggingFaceTB.SmolLM2-135M-Instruct-GGUF en lmstudio. 
* `HuggingFaceTB/SmolLM2-135M` no es muy bueno interpretando comandos.
* Probando con:
```
Model: Qwen/Qwen2.5-Coder-0.5B-Instruct
Provider: Alibaba
Parameters: 494M
Best Quant: Q8_0 (for this hardware) 
Context: 32768 tokens
Use Case: Code generation and completion
```
* `Qwen/Qwen2.5-Coder-0.5B-Instruct` funciona bien para procesar comandos simples

**2026-0303**
---
* Determinando mejor llm local con `llmfit`. 
Seleccionado:
```
Model: HuggingFaceTB/SmolLM2-135M
Provider: huggingfacetb
Parameters: 135M
Quantization: Q4_K_M
Best Quant: Q8_0 (for this hardware)
Context: 8192 tokens
Use Case: General purpose text generation
Category: General
Released: 2024-10-31
Runtime: llama.cpp (baseline est. ~1046.7 tok/s)
Installed: No provider running
```

**2026-0212**
---
* Buscando variaciones de LLM local que requiera poco poder de cómputo de la GPU. Analizando los siguiente modelos con capacidad agéntica con formato GGUF-quantized para llama.cpp o LM Studio:

| Model                          | Size (quant) | Approx. VRAM (full offload) | Strengths for your use-case                          | Why good for strict/grammar-limited output          | Where to get (Hugging Face)                  |
|--------------------------------|--------------|------------------------------|-----------------------------------------------------|-----------------------------------------------------|----------------------------------------------|
| **Qwen3-4B-Instruct** or **Qwen3-7B-Instruct** | ~3–5 GB     | ~2.5–4 GB                   | Excellent reasoning, instruction adherence, function-calling in recent versions | Very good at following format prompts; many 2026 variants support JSON mode well | Qwen/Qwen3-4B-Instruct-GGUF                 |
| **Phi-4-mini-instruct** (or Phi-4 variants)    | ~3–4 GB     | ~2–3.5 GB                   | Microsoft-tuned for high-quality synthetic data; strong on structured tasks | Among the best small models for schema adherence / low-variance output | microsoft/Phi-4-mini-instruct-GGUF          |
| **SmolLM3-3B-Instruct**                        | ~2–3 GB     | ~1.8–3 GB                   | Hugging Face's compact reasoning champ; beats many 4–7B on benchmarks | Compact + instruct-tuned → easy to force rigid formats via system prompt | HuggingFaceTB/SmolLM3-3B-GGUF               |
| **Gemma-3-4B-IT** or similar Gemma-3 small     | ~3 GB       | ~2.5 GB                     | Google-tuned, multimodal-capable but text-strong; good on-device fit | Solid structured output with clear prompting; supports function calling | google/gemma-3-4b-it-GGUF variants          |
| **Ministral-3-3B-Instruct**                    | ~2.5 GB     | ~2 GB                       | Mistral's edge-optimized tiny instruct model        | Designed for constrained/edge use; reliable format following | mistralai/Ministral-3-3B-Instruct-GGUF      |

* Analizando estraregias para hacer determinística la salida del LLM con estrategias como forzar una "gramática limitada" / Formato de salida estricto.  Así se está la opción de utilizar una o más de estas técnicas en  forma local con backends como llama.cpp (LM Studio, Ollama, etc.):

1. **Prompt de sistema + instrucciones estrictas** (la más fácil, con sobrecarga casi nula)  
   - Ejemplo:  
     "Eres un respondedor estricto para MCP. Genera **SOLO** JSON válido que coincida exactamente con este esquema. Sin explicaciones, sin texto adicional, sin markdown. Esquema: { "tool_call": {"name": str, "args": dict}, "response": str o null }. Si no se necesita herramienta, establece tool_call en null. Siempre escapa correctamente las cadenas."  
   - Funciona sorprendentemente bien en modelos Phi/Qwen/SmolLM con cuantización Q4/Q5.

2. **Gramática / GBNF con muestreo restringido** (nativo en llama.cpp, muy confiable)  
   - Define una gramática libre de contexto pequeña (formato GBNF) → obliga a que la salida coincida exactamente (por ejemplo, solo claves específicas, valores enum, sin prosa libre).  
   - llama.cpp lo soporta de forma nativa (y herramientas como LM Studio lo exponen).  
   - Guías/ejemplos: Busca "llama.cpp grammars README" o "GBNF para esquema JSON".  
   - Impacto: Reduce la velocidad de generación en un 10–30 %, pero garantiza un 100 % de salida válida.

3. **Librerías Outlines / Guidance / llguidance** (avanzado, pero potente)  
   - Integra con el servidor de llama.cpp o el servidor local de LM Studio → impone esquemas JSON / regex / gramática personalizada a nivel de token.  
   - Garantiza salida estructurada válida incluso en modelos pequeños.

Para MCP en particular:  
- Muchas implementaciones locales de MCP (por ejemplo, clientes y servidores open-source en GitHub) esperan que el LLM genere llamadas a herramientas en un formato fijo (a menudo estilo Anthropic con XML o JSON).  
- Usa los métodos de restricción anteriores → tu SLM se convierte en un "cerebro MCP" confiable sin divagaciones.

Estas técnicas te permiten mantener la salida del modelo extremadamente controlada y parseable, ideal para integraciones estructuradas como MCP mientras consumes pocos recursos en tu RTX 5060. Si necesitas ejemplos más específicos (como un archivo GBNF listo para usar), avísame. 😊

**2026-0205**
---
* Restaurado configuración para sólo API Python, no se va a implementar STIL por MAVLink hasta calibrar el escenario:
```json
{
  "SeeDocsAt": "https://github.com/Cosys-Lab/Cosys-AirSim/blob/main/docs/settings_example.json",
  "SettingsVersion": 2.0,
  "SimMode": "Multirotor",
  "LocalHostIp": "127.0.0.1",
  "ApiServerPort": 41451,
  "RecordUIVisible": false
}
```
* Prueba de captura de logs de telemetría (en pantalla) en simultaneo con navegación controlada por API

**2026-0204**
---
* Instalado Docker Desktop para ejecutar PX4 Autopilot
* Instalado container con Autopilot cloando repositorio:
```bash
git clone https://github.com/PX4/PX4-Autopilot.git --recursive
```
* Generado `docker-compose.yml`:
```yaml
services:
  px4_sitl:
      image: px4io/px4-dev-simulation-focal:latest
      container_name: px4_sitl
      privileged: true
      volumes:
        - ./PX4-Autopilot:/src/PX4-Autopilot
      ports:
        - "4560:4560"
        - "14550:14550/udp"
      stdin_open: true # Equivalent to -i
      tty: true        # Equivalent to -t
      working_dir: /src/PX4-Autopilot
      command: bash -c "make px4_sitl_default none_iris"
```
Iniciando contenedor con volumen referenciado al repositorio clonado:

```bash
docker-compose up
```
* Configurado Airsim para hacer de bridge en entre PX4 y QGroundControl
```json
{
  "SeeDocsAt": "https://cosys-lab.github.io/settings/",
  "SettingsVersion": 2.0,
  "LocalHostIp": "127.0.0.1",
  "ApiServerPort": 41451,
  "SimMode": "Multirotor",
  "Vehicles": {
    "PX4": {
      "VehicleType": "PX4Multirotor",
      "UseSerial": false,
      "LockStep": true,
      "UseTcp": true,
      "TcpPort": 4560,
      "QgcHostIp": "127.0.0.1",
      "QgcPort": 14550,
      "Parameters": {
        "NAV_RCL_ACT": 0,
        "NAV_DLL_ACT": 0,
        "COM_OBL_ACT": 1
      }
    }
  },
  "RecordUIVisible": false
}
```
* Secuencia de inicio: 
1. PX4
2. Unreal Engine + Airsim
3. QGroundControl

**2026-0131**
---
* Instalado QGroudControl para control de misión. 

**2026-0130**
---
* Optimizado proyecto Unreal Engine para reducir el footprint de VRAM que va a compartir con LLM local: reducción de hasta 40% de uso de VRAM dedicada para dejar lugar a capas críticas para la inferencia rápida: próximo paso prueba de eficiencia con arquitectura MCP completa en local.
Configuración optimizada en [./CityParkSim/Config/DefaultEngine.ini](./CityParkSim/Config/DefaultEngine.ini).

**2026-0115**
---
* Generado proyecto auxiliar, a partir de un fork, para control de drone desde el teclado https://github.com/georgsmeinung/airsim-drone-kc utilizando la nueva librería `cosysairsim`

**2026-0109**
---
* Reunión seguimiento con Ezequiel. Acordado calibrar la simulación con un script de vuelo repetido para determinar la varianza usando datos de [telemetría de AirSim en formato PX4/MavLink Logging](https://microsoft.github.io/AirSim/px4_logging/).

**2026-0108**
---
* Creado servidor MCP para control del drone via prompts
* Creado este repositorio de proyecto: https://github.com/georgsmeinung/lm-drone 
* Instalado LM Studio con el modelo `qwen/qwen3-vl-4b one` para correr modelos de lenguaje localmente y disponibilizarlos con una [API compatible con OpenAI](https://lmstudio.ai/docs/developer/openai-compat)
* Subido video ["Airsim Plugin on UE 5.5 controlled through MCP Server PoC" video"](https://youtu.be/lNdmPKZekkk) a YouTube  mostrando el control del drone a través de un server MCP muy básico disponible en `./python_poc/drone_mcp_server.py` con comunicación STDIO

**2025-1202**
---
* Instalación de [text-gen-webui-3.19](https://github.com/oobabooga/text-generation-webui/releases/tag/v3.19) para ejecutar modelos de lenguaje localmente.

**2025-1203**
--
* Compilación del [Plugin Airsim](https://github.com/Cosys-Lab/Cosys-AirSim). Abandonado el proyecto original [AirSim por Microsoft](https://github.com/microsoft/AirSim), se utiliza la actual versión a partir de un fork mantenido por el [Cosys-Lab](https://www.uantwerpen.be/en/research-groups/cosys-lab/): Laboratorio de Co-Diseño para Sistema Ciber-físicos de la Universidad de Ambéres en Bélgica
* Incorporación del Plugin al proyecto [CityParkSim](https://drive.google.com/drive/folders/1ImTngQAt0gAlrXNOfOYs5csRWQt3IhS_?usp=sharing) configurado para utilizar [Unreal Engine 5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-5-5-documentation?application_version=5.5)
* Subido video ["Airsim Plugin on UE 5.5 controlled by Python PoC video"](https://youtu.be/4ykS1tUelrY) a YouTube mostrando el control del drone desde un script de Phython.

**2025-0912**
---
* [Reunión de organización con Ezequiel](./follow_up/2025-0912-objetivo_1.md)

**2025-0829**
---
* Aprobación de [Plan de Tesis](./plan_tesis/nicolau-plan-aprobado.pdf)





