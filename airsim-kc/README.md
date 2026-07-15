# Control Manual de Dron con Teclado (airsim-kc)
---
Este directorio contiene los scripts de control manual directo para el dron de AirSim utilizando el teclado, actualizados para interactuar mediante la librería `cosysairsim` (del fork mantenido por Cosys-Lab).

## Scripts Disponibles

El controlador principal unificado es **[`kc_control.py`](file:///d:/TesisMCD/dronelm/airsim-kc/kc_control.py)**. 

Este script provee:
- **Control en tiempo real**: Vuelo manual fluido utilizando múltiples pulsaciones de teclas simultáneas vía la librería `pynput`.
- **Telemetría en tiempo real**: Tabla estructurada con posición, altitud (Z y GPS), velocidad lineal y orientación (Roll, Pitch, Yaw).
- **Asignación de segmentación**: Configura y asigna IDs de segmentación a los elementos del fondo de forma automática al iniciar la conexión.

### Cómo Iniciar:
```bash
python kc_control.py
```

---

## Controles del Teclado

Una vez iniciado el script, los comandos de teclado activos son los siguientes:

| Tecla | Acción |
|---|---|
| **W** | Mover hacia adelante (+X eje corporal) |
| **S** | Mover hacia atrás (-X eje corporal) |
| **A** | Mover hacia la izquierda (-Y eje corporal) |
| **D** | Mover hacia la derecha (+Y eje corporal) |
| **X** | Elevar altitud (-Z eje corporal / Ascender) |
| **Z** | Descender altitud (+Z eje corporal / Descender) |
| **Q** | Rotar a la izquierda (Yaw negativo) |
| **E** | Rotar a la derecha (Yaw positivo) |
| **H** | Mantener rumbo / Hover |
| **T** | Despegar (Takeoff) |
| **L** | Aterrizar en el lugar (Land) |
| **R** | Resetear la simulación |
| **Space** | Limpiar la terminal y mostrar la ayuda |
| **?** | Imprimir tabla de telemetría completa del dron |
| **ESC** | Terminar la ejecución del script y liberar el control del API |

---

## Instalación y Requisitos

1. Asegúrate de tener instalado el entorno con las dependencias necesarias:
   ```bash
   pip install cosys-airsim numpy pynput python-dotenv
   ```
2. El simulador (Unreal Engine + Cosys-AirSim) debe estar corriendo en modo **Multirotor**.
3. Las variables del entorno (como `AIRSIM_IP` para conexiones remotas) se cargarán desde el archivo `.env` local.
