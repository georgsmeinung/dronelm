"""Banco de prueba offline del VLM (calibracion, cap. 11).

Mide, fuera de vuelo, que preguntas sabe responder el VLM sobre fotogramas reales de las corridas, contra
una verdad de terreno de profundidad tomada reubicando el dron en cada pose registrada. Etapas:

    dataset.py       corridas con los dos videos -> muestras (pose, meta, foto/fotograma, respuesta en vuelo)
    ground_truth.py  AirSim: reubica el dron en cada pose, captura RGB + profundidad -> etiquetas
    evaluate.py      hace cada pregunta del catalogo (questions.py) al VLM, con logprobs
    report.py        metricas por pregunta -> report.md / metrics.json

Nada de esto corre en el lazo de vuelo: la profundidad se lee solo aca, como en la calibracion del TTC.
"""
