graph TD
    A["capture_node<br/>(Captura AirSim)"] --> B["canny_xor_gate<br/>(Canny + XOR binario)"]
    B -->|"Sin cambios<br/>(< umbral)"| C["keep_going<br/>(Sigue Adelante)"]
    B -->|"Cambios detectados<br/>(≥ umbral)"| D["roi_yolo_detect<br/>(ROI 62° + YOLO)"]
    D --> E["ttc_estimate<br/>(TTC por BB-w)"]
    E -->|"TTC > 5.0s<br/>(Sin peligro)"| C
    E -->|"2.0s < TTC ≤ 5.0s<br/>(Evasión local)"| F["evasive_node<br/>(Maniobra reactiva)"]
    E -->|"TTC ≤ 2.0s<br/>(Peligro inminente)"| G["hover_and_slm<br/>(Hover + SLM)"]
    C --> H["motor_node"]
    F --> H
    G --> H
    H --> I["END"]