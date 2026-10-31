# Respuesta original de DeepSeek — Señal de Tiempo 5 (primer intento, sin pedir búsqueda web)

- Fecha: 31 de octubre de 2026
- Modelo: deepseek-v4-pro a través de OpenCode Go (Claude Code en modo no interactivo como cliente, carpeta vacía, sin contexto previo; la búsqueda web no tenía permiso y respondió con su conocimiento)

## Prompt

```text
Actúa como Arquitecto de Software especializado en sistemas con LLM. Diseño la capa de IA de un MVP académico (Sistemas de Información de Gestión y Business Intelligence) que optimiza la cesta de la compra en León (España): dada una lista, recomienda qué productos comprar y en qué supermercados (máximo 3 tiendas, a pie o en coche), minimizando coste + lambda * minutos de desplazamiento. Es de uso personal, no se publica, sin cuentas y en español.

Decisiones ya tomadas:
- El "agente recomendador" exigido es un orquestador basado en LLM: interpreta la lista escrita en texto libre ("leche sin lactosa, 2 kg de naranjas, algo para la cena"), aplica preferencias blandas, llama a herramientas deterministas (búsqueda de equivalencias, matriz de tiempos de viaje de OSRM/Valhalla, optimizador de cesta) y explica el resultado. Precios, tiempos y la cesta óptima nunca los calcula el LLM.
- PostgreSQL único con pgvector y PostGIS. Cada producto obtenido por scraping (30.000-100.000 en total, 4-8 cadenas) se asigna a un producto canónico, por vecinos más cercanos sobre embeddings con un umbral de confianza, más reglas.
- El proveedor de LLM queda detrás de una interfaz para poder cambiar entre local y nube.

Restricciones:
- Sin costes recurrentes: modelos locales ligeros o capas gratuitas de API (por ejemplo, Gemini Flash en la capa gratuita).
- Todo el sistema se despliega con Docker Compose en un único servidor modesto, previsiblemente sin GPU dedicada. El portátil de desarrollo tiene un Intel Core Ultra 7 258V, 32 GB de RAM compartida, GPU integrada Intel Arc 140V y NPU.
- Privacidad: a un LLM en la nube solo se le envía el texto de la lista, nunca la ubicación.
- Objetivo de latencia: recomendación completa para una lista de 30 artículos en menos de 5 s (p95).
- Volumen esperado: pocas decenas de recomendaciones al día. Los embeddings del catálogo se recalculan solo para productos nuevos o cambiados (ingesta diaria).

Preguntas:
1. Embeddings de productos (nombres cortos en español, con marca y formato, por ejemplo "Leche semidesnatada Hacendado 1 L"): ¿modelo local o API? Propón 2-3 modelos concretos y abiertos, con dimensión, tamaño y si se ejecutan bien en CPU, y cómo evaluar cuál distingue mejor formatos y variantes (800 g frente a 200 g, entera frente a desnatada).
2. LLM del orquestador: ¿un modelo local ligero (3-8B, cuantizado, con Ollama o llama.cpp) es suficiente para interpretar la lista, llamar a herramientas con argumentos JSON válidos y explicar en español, cumpliendo la latencia sin GPU? Compáralo con un LLM en la nube de capa gratuita: calidad del uso de herramientas, latencia, límites de la capa gratuita, privacidad, dependencia del proveedor y reproducibilidad.
3. ¿Uno o varios agentes? Valora un único agente con herramientas frente a un sistema multiagente (por ejemplo, intérprete de lista, resolutor de equivalencias y explicador), para este alcance y para lo que se puede defender en una memoria académica.
4. ¿Hay tareas que convenga resolver sin LLM o con un modelo más pequeño (clasificación de categorías, extracción de formato y cantidad con reglas o expresiones regulares)?

Da una recomendación concreta para el MVP (qué local, qué en la nube y por qué), un plan de reserva si la opción elegida falla y umbrales medibles que harían cambiar la decisión. Indica qué afirmaciones no puedes verificar o dependen de versiones o de límites de capa gratuita que pueden haber cambiado.
```

## Respuesta

No me han concedido el permiso de WebSearch, así que respondo con conocimiento propio y, como pedís, marco explícitamente lo que depende de versiones o límites de capa gratuita que debéis re-verificar en el momento de implementar. La parte estructural del diseño no depende de eso.

---

# TL;DR

- **Embeddings: siempre local.** `multilingual-e5-base` (768 dim) como base; `paraphrase-multilingual-MiniLM-L12-v2` (384 dim) como opción ligera; `bge-m3` (1024 dim) si queréis calidad máxima asumiendo índice más grande. No tiene sentido una API: es batch/offline, gratuito y privado, y no hay presión de latencia. **Los embeddings no distinguen formatos numéricos (800 g vs 200 g): eso se resuelve con reglas, no con vectores.**
- **Orquestador: Gemini Flash de capa gratuita como opción por defecto**, detrás de vuestra interfaz. Motivo: es lo único que cumple el presupuesto de **5 s p95 para 30 artículos** con calidad de tool-calling y español buenos y cero infraestructura. Un 3–8B local en **CPU puro no cumple 5 s** para 30 ítems + explicación (las cuentas están abajo); es viable solo si el LLM toca pocos casos o con NPU/iGPU.
- **Un solo agente orquestador con herramientas**, no multiagente. Las "tres funciones" son: herramientas deterministas (resolutor de equivalencias = pgvector) + prompts del mismo modelo. El multiagente suma latencia y superficie de fallo sin beneficio para este alcance.
- **Sí, gran parte va sin LLM**: split de la lista, cantidades/unidades, marca (diccionario), categoría (clasificador local diminuto). El LLM solo: ítems ambiguos, preferencias blandas y explicación.

---

# 1. Embeddings de productos: local, con evaluación sobre pares difíciles

**Local, sin discusión.** Los embeddings del catálogo se calculan offline (una vez + incrementos diarios) y la consulta es un único vector por ítem. No hay restricción de latencia, no hay coste, y la privacidad queda íntegra. Una API de embeddings no es "gratuita de verdad" y añade dependencia sin aportar nada aquí.

**Modelos concretos (abiertos, multilingües, CPU-friendly):**

| Modelo | Params | Dim | Comentario CPU |
|---|---|---|---|
| `multilingual-e5-base` | ~278M | 768 | Referencia calidad/velocidad. Usa prefijos `query:` / `passage:`. |
| `paraphrase-multilingual-MiniLM-L12-v2` | ~117M | 384 | El clásico ligero; muy rápido, algo peor en matices del español. |
| `bge-m3` | ~568M | 1024 | Mejor multilingüe en general, pero más pesado y con índice más grande. |

A vuestra escala (30–100k vectores), 768 dim × 100k ≈ **300 MB** en float32: trivial para PostGIS/pgvector en un servidor modesto; el tamaño no es argumento para degradar a 384. Podéis considerar `multilingual-e5-large` (560M, 1024 dim) solo si la evaluación lo justifica, porque el coste es de ingestión, no de latencia. *(Verificad el leaderboard multilingüe de MTEB al implementar: salen modelos nuevos cada trimestre y algunos de los nombres de arriba pueden haber sido superados.)*

**Por qué el formato no lo resuelve el embedding.** "800 g" vs "200 g" es un token numérico que el pooling promedia o trata como fuera de vocabulario; ningún embedding fiable lo distingue de forma robusta. Lo que sí distingue el embedding es la variante semántica: *entera / semidesnatada / desnatada*, *sin lactosa*, *integral / normal*. La conclusión de arquitectura: **el matcher canónico combina similitud vectorial sobre el nombre normalizado (cantidad/formato enmascarado) + campos estructurados extraídos por reglas** (cantidad, unidad, formato, marca), con regla dura "no emparejes 800 g con 200 g".

**Cómo evaluar cuál distingue mejor.** Construid un conjunto de evaluación a partir del propio scraping, con etiquetas de verdad:
- **Etiquetas casi gratis**: si el scraping trae EAN/código de barras (muchas cadenas lo publican), tenéis pares "mismo producto en distintas cadenas" etiquetados automáticamente. Es vuestra gold/silver standard para recall entre cadenas.
- **Pares difíciles** (los etiquetáis a mano, 200–500 bastan):
  - mismo producto, distinto formato: *Leche Hacendado 1 L* vs *6×1 L* vs *200 ml*;
  - variantes: *entera* vs *semidesnatada* vs *desnatada*;
  - misma marca, distinto producto: *Leche* vs *Yogur*;
  - distinta marca, mismo producto: *Hacendado* vs *Pascual*.

Métricas: separación de las distribuciones de coseno (mismo canónico vs distinto), **precision@1 / recall@k** del vecino más cercano, y comprobación de orden para variantes (¿`desnatada` queda más cerca de `semidesnatada` que de `entera`?). Sobre eso calibrad el umbral de confianza: curva precisión/recall vs coseno → umbral de auto-emparejado con precisión alta, y por debajo, cola de revisión manual o reglas extra.

---

# 2. Orquestador: local 3–8B vs Gemini Flash de capa gratuita

**El presupuesto de 5 s p95 es la variable que decide.** Haced la cuenta de latencia antes de elegir.

Presupuesto de tokens para una lista de 30 ítems: entrada ~800–1.200 tokens (system prompt + esquemas de herramientas + lista) y salida ~750–1.100 tokens (interpretación estructurada de 30 ítems + explicación). En CPU puro con llama.cpp/Ollama, 7–8B Q4 va a ~5–15 t/s en un servidor modesto, 3–4B a ~15–30 t/s (cifras estimadas, hay que medirlas en vuestro servidor). **750–1.100 tokens de salida a 10 t/s ≈ 75–110 s; incluso a 30 t/s ≈ 25–35 s.** Además, el *prefill* (procesar prompt + esquemas de herramientas) también cuesta segundos en CPU. Es decir: **un 7–8B en CPU puro no cumple 5 s; ni siquiera un 3B cumple para 30 ítems completos.** La única vía local para acercarse es **recortar drásticamente la salida del LLM** (que solo toque ítems ambiguos y una explicación corta) o **descargar en la NPU/iGPU del portátil** (Arc 140V vía Vulkan/OpenVINO/IPEX-LLM), que no es el servidor de despliegue.

**Comparación honesta:**

| Dimensión | Local 3–8B cuantizado (CPU) | Gemini Flash capa gratuita |
|---|---|---|
| Tool-calling / JSON válido | Bueno en 7–8B (Qwen2.5-7B, Qwen3-8B); degrada en 3B; exige validación + reintento | Excelente; JSON estructurado nativo y llamadas paralelas |
| Latencia 30 ítems | No cumple 5 s en CPU puro (ver cuentas) | Cumple sobradamente (típicamente 2–5 s de ida y vuelta) |
| Límites capa gratuita | Ninguno (infinito, offline) | ~15 RPM / ~1.500 req/día / ~1M tokens/min (histórico; **verificar**) |
| Privacidad | Total | Solo texto de lista (aceptado); **ojo: la capa gratuita puede permitir usar tus prompts para entrenar — verificar ToS** |
| Dependencia del proveedor | Ninguna | Mitigada por la interfaz; riesgo de deprecación de versión |
| Reproducibilidad | Excelente (pesos y cuantización fijos, seed fijo) | Buena si fijáis versión de modelo + temp 0 y guardáis prompts/respuestas; el proveedor puede actualizar en silencio |

**Respuesta directa a "¿un 3–8B local es suficiente?":** en *calidad de interpretación y tool-calling*, un 7–8B sí (Qwen2.5-7B-Instruct, Qwen3-8B, Gemma 3 4B son suficientes para listas cortas y explicación en español). En *latencia con CPU puro y 30 ítems*, **no**. Para el MVP, la opción que cumple el objetivo sin ingeniería extra es la nube gratuita; el local es vuestro plan de reserva y vuestro modo "demo sin red".

---

# 3. ¿Uno o varios agentes? Un orquestador con herramientas

**Un único agente orquestador.** Razones concretas:

- Cada agente extra es otra llamada al LLM → **segundos adicionales** sobre un presupuesto de 5 s que ya es ajustado. Con una decena de recomendaciones al día no hay throughput que paralelizar.
- Los tres roles que intuís se descomponen mejor así:
  - **Resolutor de equivalencias** → herramienta determinista (pgvector + reglas). Nunca un agente.
  - **Intérprete de lista** y **explicador** → el mismo modelo con prompts distintos, o incluso una sola llamada que interpreta y luego otra corta que explica. Son dos *prompts*, no dos *agentes*.
- Menos superficie de fallo, más fácil de evaluar y depurar. Un multiagente en un MVP es difícil de justificar en una memoria: estás pagando complejidad sin métrica que la respalde.
- Para la memoria académica, **defenderlo como "orquestador LLM con uso de herramientas (function calling) dentro del bucle"** es sólido y estándar. Podéis incluir un apartado "alternativa multiagente considerada y descartada" con los motivos medidos (latencia añadida, más modos de fallo) — eso *suma* rigor, no resta.

Si queréis un "segundo par de ojos", usad un **validador determinista** (validación de esquema JSON + reintento con el mensaje de error), no un segundo agente.

---

# 4. Qué resolver sin LLM (o con modelo diminuto)

Sí, la mayoría del pipeline. Regla de diseño: **el LLM orquesta, no parsea.**

| Tarea | Solución | ¿LLM? |
|---|---|---|
| Split de la lista en ítems | Regex sobre separadores/conjunciones (`y`, `más`, `2x`, saltos de línea) | No |
| Cantidad / formato / unidad | Regex + tabla de unidades y normalizador ("2 kg", "800 g", "1 L", "6 uds", "paquete de 6", "una docena") | No |
| Marca | Diccionario cerrado de marcas de vuestras cadenas | No |
| Categoría | Reglas/keywords primero; si no, clasificador local diminuto (embedding → centroide de categoría, o un MiniLM fine-tuneado) | No (modelo pequeño) |
| Equivalencias / producto canónico | pgvector + umbral + reglas (ya decidido) | No |
| Matriz de tiempos + optimizador | OSRM/Valhalla + optimizador determinista (ya decidido) | No |
| ítems ambiguos ("algo para la cena", "lo de siempre") | Orquestador | **Sí** |
| Preferencias blandas en lenguaje natural | Orquestador | **Sí** |
| Explicación final en español | Orquestador (último paso, streameable) | **Sí** |

Esto tiene un efecto colateral que conviene dejar escrito en la memoria: **cuanto más resolváis por reglas, menos tokens emite el LLM en el camino crítico, y más viable se vuelve la opción local.** El clasificador de categorías local además evita mandar más texto del necesario a la nube.

---

# Recomendación concreta para el MVP

**Local:**
- Embeddings `multilingual-e5-base` (768 dim) en CPU, dentro del pipeline de ingesta; `paraphrase-multilingual-MiniLM-L12-v2` como variante ligera.
- Todo el preproceso determinista (split, cantidades, unidades, marca, categoría por reglas + clasificador diminuto).
- pgvector/PostGIS + OSRM/Valhalla + optimizador (deterministas, ya decidido).
- Implementación local del orquestador vía Ollama (`qwen3-4b` o `qwen2.5-7b-instruct` Q4_K_M) **detrás de la misma interfaz**, lista para activar.

**Nube (solo si hace falta y siempre detrás de la interfaz):**
- Orquestador = **Gemini Flash de capa gratuita**, con salida JSON estructurada (`response_mime_type`/function calling), como opción por defecto del MVP.
- **Por qué**: es lo único que cumple 5 s p95 para 30 ítems con buena calidad de tool-calling y español, con cero infraestructura, y vuestro volumen (decenas al día) cabe de sobra en los límites de la capa gratuita. La privacidad ya está acotada: solo se envía texto de lista, nunca ubicación.

**Estructura:** un único orquestador + herramientas deterministas + preproceso por reglas. Minimizad los *round-trips* LLM↔herramienta: la búsqueda de equivalencias de los 30 ítems se hace en **una** llamada batch (una consulta SQL con 30 vectores), no en 30 llamadas.

---

# Plan de reserva (si Gemini falla)

1. **Volcar a local por configuración** (la interfaz ya lo permite): Ollama con `qwen3-4b`/`qwen2.5-7b-instruct`. Mitigación de latencia: reglas primero (el LLM solo toca ambiguos), explicación en streaming, y mostrar la cesta optimizada antes que la explicación completa.
2. **Cambiar a otra capa gratuita** (p. ej. Flash-Lite u otro proveedor) sin tocar el orquestador — por eso la interfaz.
3. **Demo sin red / en el portátil**: descargar a la iGPU Arc 140V o NPU (OpenVINO/IPEX-LLM/Ollama-Vulkan), donde un 4–8B sí es rápido; aceptando que el servidor de despliegue no es ese.
4. **Registro de prompts/respuestas versionado** desde el día uno: si cambiáis de proveedor o de modelo, podéis reproducir y re-evaluar.

---

# Umbrales medibles que harían cambiar la decisión

Definid un benchmark fijo (30–50 listas reales con salida dorada) y medid:

- **Local pasa a ser preferido** si en el servidor de destino: p95 end-to-end < 5 s **y** tool-calls con JSON válido ≥ 95% (antes de reintento) **y** precisión de interpretación ≥ 90% sobre el benchmark. Si no, se queda la nube.
- **Nube se abandona** si: la capa gratuita no cubre el volumen diario + ráfagas, o añade > ~1 s de latencia mediana, o la ToS de la capa gratuita permite entrenar con vuestros datos de forma inaceptable para la memoria.
- **Cambio de modelo de embeddings**: el que maximice precision@1 en pares difíciles (formato/variante) manteniendo el tiempo de indexación; requisito duro: banda de auto-emparejado con precisión ≥ 0,98 y recall ≥ 0,95; si no, umbral más estricto o cola manual.
- **Fiabilidad de tool-calling**: si la validez JSON < 99% tras validación de esquema + 1 reintento → añadir validador determinista, usar salida estructurada nativa, o subir de modelo.
- **Calidad de explicación**: rúbrica manual sobre ~50 listas (fluidez, corrección, completitud, español), objetivo media ≥ 4/5; si falla con un local pequeño, o se sube de modelo local o se mantiene la nube para explicar.

---

# Lo que no puedo verificar (y debéis re-verificar)

- **Límites exactos de la capa gratuita de Gemini** (RPM/RPD/TPM) y los nombres de modelo vigentes (1.5 Flash / 2.x Flash / Flash-Lite). Consultad ai.google.dev en el momento de implementar.
- **Si la capa gratuita de Gemini puede usar vuestros prompts para entrenar** (cláusula de datos). Para un proyecto académico es un punto a declarar explícitamente; la capa de pago suele tener términos distintos.
- **Rendimiento CPU real** de cada modelo en *vuestro* servidor: mis t/s son estimaciones; hay que benchmarkearlos. Igual con el soporte de Ollama/llama.cpp/OpenVINO para la NPU/iGPU del Core Ultra 7 258V (cambia con cada versión).
- **Qué modelos locales son los mejores hoy** (Qwen3, Gemma 3.x, Llama 4, nuevos embeddings multilingües): los nombres que doy pueden estar superados; benchmarkead lo último.
- **Licencias**: Ministral/Mistral usan licencia de investigación no comercial — comprobadlo antes de usarlo en algo que se publique. Qwen y Gemma tienen licencias más permisivas.
- **Comportamiento del índice HNSW de pgvector y huella de memoria** a vuestra escala: dependiente de versión, aunque 100k × 768 dim es cómodo en hardware modesto.

¿Queréis que convierta esto en el esqueleto del capítulo de la memoria (con el diagrama de pipeline y la tabla de decisiones), o que deje listo el `docker-compose` con Ollama + pgvector/PostGIS como primer esqueleto?
