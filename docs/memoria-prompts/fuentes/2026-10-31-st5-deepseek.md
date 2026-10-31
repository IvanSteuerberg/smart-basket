# Respuesta original de DeepSeek — Señal de Tiempo 5

- Fecha: 31 de octubre de 2026
- Modelo: deepseek-v4.1-flash a través de OpenCode Go (Claude Code en modo no interactivo como cliente, carpeta vacía, sin contexto previo, con WebSearch y WebFetch; 25 búsquedas y lecturas, 405 s)

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

Antes de responder, busca en internet información actual (hoy es 31 de octubre de 2026): los modelos abiertos de embeddings y de LLM ligeros vigentes, y los modelos y límites actuales de la capa gratuita de la API de Gemini. Recomienda solo modelos vigentes y cita las fuentes con su URL. No ejecutes comandos ni modifiques archivos: usa solo la búsqueda web y la lectura de páginas.
```

## Respuesta

# Capa de IA del recomendador de cesta — recomendación de arquitectura

**Nota metodológica:** el buscador de esta sesión devolvió resultados degradados (eco de la propia consulta), así que verifiqué todo contra documentación primaria: `ai.google.dev`, tarjetas de Hugging Face y la librería de Ollama. Las cifras de velocidad local son estimaciones de orden de magnitud, no medidas: van marcadas como tales y hay que benchmarkearlas en el servidor real.

---

## 0. Recomendación en una tabla

| Capa | Decisión MVP | Motivo |
|---|---|---|
| Embeddings de producto | **Local: Qwen3-Embedding-0.6B**, 1024 d (MRL hasta 32), 32K contexto | 100k vectores caben de sobra, sin cuotas, reproducible, CPU suficiente |
| Parseo de la lista | **Gemini 3.5 Flash-Lite (capa gratuita)**, solo el texto de la lista | Es la única forma cómoda de cumplir 5 s p95 sin GPU |
| Explicación | **Local Qwen3.5-2B/4B en streaming** + plantilla determinista de respaldo | El plan contiene tiendas/tiempos: no puede salir a la nube |
| Resolución, precios, tiempos, óptimo | **100 % determinista** | Ya decidido; además es lo que hace defendible la memoria |
| Nº de agentes | **Uno**, con herramientas y bucle acotado | Multiagente no aporta nada a este alcance y rompe latencia y evaluación |

La clave del diseño es que **el LLM no genera la lista entera de 30 artículos**. Un preprocesador determinista resuelve la mayoría de líneas y el LLM solo recibe el texto original más ese borrador, devolviendo correcciones y ambigüedades. Así la salida del modelo baja de ~700 a ~150-250 tokens, que es lo que hace viable el presupuesto de latencia.

---

## 1. Embeddings: local, y con evaluación propia

### Candidatos vigentes

| Modelo | Paráms. | Dimensión | Contexto | Notas CPU |
|---|---:|---:|---:|---|
| **Qwen3-Embedding-0.6B** | 0,6B | 1024 (MRL 32-1024) | 32K | GGUF Q8_0 639 MB, F16 1,2 GB; 100+ idiomas; admite instrucción de tarea |
| **EmbeddingGemma-2** | 270M / 440M / 570M / 740M | 768 (MRL 512/256/128) | 8K (la ficha de Ollama dice 256K: inconsistente) | El de 270M es el más rápido; 100+ idiomas; MTEB multilingual v2 61,36 con el de 740M |
| **BGE-M3** | 568M | 1024 | 8K | Denso + disperso + ColBERT; baseline multilingüe muy sólido |

Fuentes: [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF), [EmbeddingGemma-2 en Ollama](https://ollama.com/library/embeddinggemma-2), [BGE-M3](https://huggingface.co/BAAI/bge-m3).

**Recomendación: Qwen3-Embedding-0.6B.** Es el mejor equilibrio para nombres cortos en español: multilingüe real, instrucción de tarea (mejora 1-5 % en consulta si no se omite), MRL para bajar a 256 d si el almacenamiento aprieta, y un solo binario de Ollama/llama.cpp. EmbeddingGemma-2-270M es el sustituto natural si el rendimiento manda; BGE-M3, el baseline que hay que batir.

**Descartaría la API de embeddings** (`gemini-embedding-2`, 128-3072 d, 8K tokens, multimodal) para el catálogo: 30-100k vectores en ingesta diaria, cuotas y no-reproducibilidad a cambio de nada. Los nombres de producto no son datos sensibles; el problema es operativo, no de privacidad.

### Cómo evaluar lo que de verdad importa

Los benchmarks MTEB **no miden** lo que decide aquí: distinguir "Leche semidesnatada Hacendado 1 L" de "Leche entera Hacendado 1 L" o "800 g" de "200 g". Hay que construir un gold set propio:

1. **1.500 SKUs estratificados** del catálogo raspado, con ID canónico y atributos (marca, tamaño, variante, nº de pack).
2. **Consulta = título crudo del scraping**, no el nombre normalizado. Es la entrada real.
3. **Negativos duros**: misma marca y categoría, distinto tamaño; misma familia, distinta grasa/sabor; distinto pack.
4. **Tres dificultades**: fácil (otra categoría), media (misma categoría, otra marca), difícil (misma marca, distinto formato/variante).

Métricas:

- **Recall@1 y Recall@5** contra el canónico correcto, y MRR.
- **Tasa de confusión en negativos duros**: fracción en que el top-1 es de la misma familia pero con tamaño o variante equivocados. Es *la* métrica del proyecto.
- **Precisión y cobertura en el umbral operativo** τ: la arquitectura ya usa un umbral de confianza, así que interesa la curva precisión-cobertura, no el AUC.
- **Separación de márgenes**: diferencia media de similitud entre positivo y negativo más duro.

Protocolo: mismo preprocesado de texto para todos; prefijos/instrucciones propios de cada modelo; comparar 1024 vs 512 vs 256 d en Qwen (MRL) y 768 vs 256 en EmbeddingGemma; bootstrap para intervalos de confianza y McNemar para diferencias pareadas. Añadir una variante **híbrida** (embedding + trigramas + regla de tamaño como veto) y medir el delta: en este dominio suele ganar más que cambiar de modelo.

**Criterio de aceptación:** ≥95 % de precisión en auto-link, ≥85 % de recall a esa precisión, confusión en negativos duros ≤2 %, y p95 de embedding <50 ms por artículo en el servidor. Si no se alcanza, no se cambia de modelo a ciegas: primero se añade el veto de tamaño/unidad y el re-ranking léxico.

Escala: 100k × 1024 d en float32 son ~400 MB (200 MB en `halfvec`); con HNSW en pgvector es trivial para este servidor. La reindexación completa en CPU son decenas de minutos, no horas; la incremental diaria, segundos.

---

## 2. LLM del orquestador: local vs nube

### Qué le pedimos exactamente

No es razonamiento profundo: es extracción estructurada en español, invocación de 3-4 herramientas con JSON simple y una explicación breve. Un 3-8B bien guiado **sí llega a la calidad** necesaria para eso. El problema es otro: **la latencia de generar 30 artículos en CPU**.

### La aritmética que decide

La decodificación en CPU está limitada por ancho de banda de memoria: `tok/s ≈ ancho_banda_efectivo / bytes_del_modelo`.

| Modelo | Tamaño Q4 | tok/s estimados (CPU servidor) | 700 tokens de salida |
|---|---:|---:|---:|
| Qwen3.5-4B | ~2,5-3 GB | 8-20 | **35-90 s** |
| Qwen3.5-2B | ~1,5 GB | 20-40 | **18-35 s** |
| + Arc 140V del portátil (Vulkan, RAM compartida) | — | 25-40 | 20-30 s |

A eso se suma el *prefill* de 1.000-1.500 tokens (5-10 s en CPU). **Ningún 3-8B cuantizado en CPU cumple 5 s si tiene que emitir la lista completa.** Ni siquiera la iGPU del portátil lo arregla; solo lo mejora.

Con salida corta (~150 tokens) la cosa cambia: 4B a 15 tok/s = 10 s; 2B a 30 tok/s = 5 s; y en streaming el usuario ve texto desde el primer token. Por eso el diseño separa "parsear 30 líneas" (nube) de "explicar 150 palabras" (local).

### Comparación

| Dimensión | Local 3-8B (Ollama) | Gemini 3.5 Flash-Lite (gratis) |
|---|---|---|
| Tool calling | Qwen3.5-4B: BFCL-V4 50,3, TAU2 79,9, IFEval 89,8; con JSON Schema forzado y temperatura 0 es usable | Función nativa, llamadas paralelas, `tool_choice` `any`/`validated`, salidas estructuradas; 1M de contexto |
| Latencia 30 artículos | 20-90 s en CPU | ~1-3 s con salida compacta |
| Límites | Ninguno; CPU ocupada | Capa gratuita existe, pero **sin cifras públicas estáticas**; se ven en AI Studio y cambian |
| Privacidad | Cero exposición | Solo texto de la lista; en EEE los términos de datos de pago aplican también a la cuota gratuita |
| Dependencia | Ninguna | Alta: Google rota modelos (2.5 ya solo para usuarios previos; 4 Argon sin capa gratuita) |
| Reproducibilidad | Pesos fijados = exacta | El modelo cambia sin avisar; hay que registrar versión y cachear |

Fuentes: [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen3.5 en Ollama](https://ollama.com/library/qwen3.5), [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [function calling](https://ai.google.dev/gemini-api/docs/function-calling), [límites](https://ai.google.dev/gemini-api/docs/rate-limits), [precios/capa gratuita](https://ai.google.dev/gemini-api/docs/pricing), [términos](https://ai.google.dev/gemini-api/terms), [GPUs en Ollama](https://docs.ollama.com/gpu).

**Punto de privacidad importante y poco conocido:** según los términos actuales, si el usuario está en el EEE (España), los términos de datos de los servicios de pago se aplican también a AI Studio y a la cuota gratuita: Google no usa prompts/respuestas para mejorar productos, aunque los registra por abuso y seguridad. La cláusula que impide ofrecer *clientes API* con capa gratuita a usuarios del EEE no afecta a uso personal. Es una lectura de los términos, no asesoría legal, y puede cambiar.

**Veredicto:** la nube gana para el parseo por latencia y calidad de tool calling; el local gana para la explicación por privacidad y para la evaluación reproducible. El MVP usa ambos, cada uno donde es fuerte.

---

## 3. ¿Uno o varios agentes?

**Un agente único con herramientas, bucle acotado a dos turnos como máximo.** En la práctica: preprocesador determinista → una llamada LLM de interpretación (con el borrador ya inyectado) → herramientas deterministas → una llamada de explicación (local).

Por qué no multiagente:

- **Latencia:** tres agentes son 3-6 llamadas LLM por recomendación; a 0,8-1,5 s por llamada se va a 6-10 s. Incumple el SLO por diseño.
- **Errores en cascada:** el intérprete se equivoca en "2 kg de naranjas", el resolutor busca "naranjas 2 kg" como nombre de producto y el explicador justifica una cesta mala con total seguridad. Un pipeline determinista entre medias corta la propagación.
- **Evaluación:** con un agente puedes medir F1 de parseo, precisión de link y latencia por etapa. Con tres, cada fallo es multicausal y la memoria se llena de ablaciones que no convergen.
- **No hay tarea que lo justifique:** el flujo es fijo (parsear → resolver → optimizar → explicar), no abierto. La autonomía no aporta.

**Cómo defenderlo en la memoria:** "orquestador LLM de agente único con uso de herramientas y *pipeline* determinista de apoyo". Puedes presentar los roles (intérprete, resolutor, explicador) como **nodos lógicos de un grafo con aristas fijas**, no como agentes autónomos, y añadir una ablación 1 llamada vs 2 llamadas vs 3 agentes con latencia y F1. Eso demuestra criterio de ingeniería, que es más valioso que exhibir multiagente. El multiagente queda como trabajo futuro: "si el catálogo creciera o aparecieran tareas abiertas".

---

## 4. Lo que no debe pasar por el LLM

| Tarea | Solución | Por qué |
|---|---|---|
| Cantidades y unidades | Regex + normalización (`kg/g/L/ml/ud`, `6x1,5 L`, "dos kilos", fracciones, rangos) | Determinista, testeable, gratis |
| Formato/tamaño | Extracción y normalización a unidad base; se guarda el string original | Es exactamente donde fallan los embeddings y los LLM pequeños |
| Marca | Diccionario del catálogo + fuzzy | Precisión 100 % con lista cerrada |
| Categoría | kNN sobre el catálogo canónico (que ya tiene categoría) o clasificador ligero | No hace falta generar texto |
| Restricciones dietéticas explícitas | Léxico: "sin lactosa", "sin gluten", "vegano" → tags | Reglas auditables |
| Precios, tiempos, cesta óptima | OSRM/Valhalla + ILP | Ya decidido; nunca LLM |
| Corrección ortográfica | SymSpell/Hunspell + léxico del catálogo | Más rápido y predecible |

El LLM se reserva para lo que de verdad es lenguaje: **"algo para la cena"**, **"para desayunar"**, ambigüedades ("naranjas" → ¿mesa o zumo?), preferencias blandas y la explicación final.

Un modelo de 270M como [functiongemma](https://ollama.com/library/functiongemma) (BFCL simple 61,6) no sustituye al orquestador en texto libre, pero sí podría clasificar intenciones cerradas si algún día quieres quitar la llamada a la nube. Para el MVP no compensa: la regla + embedding ya cubre eso.

---

## 5. Arquitectura concreta del MVP

```
texto libre
  │
  ├─ parser determinista (regex unidades, marcas, léxico, kNN categoría)
  │     └─ borrador estructurado + líneas no resueltas
  │
  ├─ [LLM nube: SOLO texto de la lista + borrador]  → items + preferencias
  │     (Qwen3.5-2B/4B local si la nube falla)
  │
  ├─ resolución canónica: pgvector kNN + reglas (tamaño/marca como veto) + τ
  │     └─ cola de revisión para baja confianza
  │
  ├─ precios + matriz OSRM (cacheada por origen) 
  │
  ├─ optimizador ILP: ≤3 tiendas, coste + λ·minutos, a pie/coche
  │
  └─ explicación: LLM local streaming (150-200 tokens) | plantilla
```

**Interfaz de proveedor** (lo que permite cambiar local/nube):

```python
class LLMProvider(Protocol):
    def generate(self, messages, tools=None, response_schema=None,
                 temperature=0.0) -> LLMResult: ...
```

Adaptadores: `GeminiProvider`, `OllamaProvider`, `OpenAICompatProvider`. Todo pasa por el mismo contrato; se registra `provider`, `model_version`, `prompt_hash`, `latency_ms`, `schema_valid`, `fallback_reason`.

**Servicios en Docker Compose:** `postgres` (PostGIS + pgvector), `osrm` (grafo de León/España), `api` (FastAPI), `ingesta` (scraping + embeddings incrementales), `ollama` (Qwen3.5-2B/4B + Qwen3-Embedding-0.6B), `caddy`. Presupuesto de RAM: OSRM 2-4 GB, Ollama 4-6 GB, Postgres 2 GB, app 1 GB. En 16 GB cabe; en 8 GB, justo.

**SLO desglosado (p95):** parser 50 ms · LLM nube 1,5 s · resolución 150 ms · tiempos 200 ms · optimizador 300 ms · render 100 ms → **~2,3 s**. La explicación local va en streaming después de pintar la tabla: primera palabra <1,5 s, completa <8 s. Conviene definir en la memoria que "recomendación completa" = plan (artículos, tiendas, coste, minutos), no el texto explicativo.

**Caché:** hash del texto de la lista → parseo; hash del plan → explicación. Con uso personal y listas repetidas, esto reduce las llamadas LLM un 50-80 % y protege la cuota gratuita.

---

## 6. Plan de reserva (escalera de degradación)

| Nivel | Disparador | Comportamiento |
|---|---|---|
| N0 | Normal | Nube parsea, local explica, todo determinista |
| N1 | 429 / timeout >2,5 s / 5xx | 1 reintento con backoff → parser determinista + LLM local solo para residuales; explicación por plantilla; latencia relajada a 12 s |
| N2 | Nube caída o cuota agotada | Todo local: Qwen3.5-2B/4B para residuales y explicación; si no llega, plantilla |
| N3 | Ollama caído | Parser determinista + plantilla; `degraded=true` visible en la UI |
| N4 | OSRM caído | Tiempos por distancia euclídea × factor de rodeo (o última matriz cacheada); se marca |
| N5 | pgvector caído | Búsqueda léxica trigram sobre el catálogo; se marca |

Regla de oro: **el sistema siempre devuelve una cesta**. El LLM enriquece; nunca es un punto único de fallo.

---

## 7. Umbrales medibles que cambian la decisión

| Métrica | Umbral | Acción |
|---|---|---|
| p95 extremo a extremo (plan) | >5 s | Recortar llamada LLM o pasar a plantilla |
| p95 LLM nube | >2,5 s o error >2 % | Activar local como primario |
| Cobertura del parser determinista | ≥90 % de líneas | Eliminar la llamada LLM de parseo; dejar solo ambigüedades |
| F1 de parseo en gold set (300 líneas) | <0,95 | Subir a Gemini 3.8 Flash o mejorar prompt/esquema |
| Validez de esquema tras decodificación | <99,5 % | JSON Schema forzado + validación/reparación |
| Precisión auto-link | <95 % | Subir τ, veto de tamaño, re-ranking léxico |
| Confusión en negativos duros | >3 % | Híbrido léxico + reglas, o cambiar de modelo de embeddings |
| tok/s locales del 4B en el servidor | <25 | Local solo para explicación corta; nunca parseo |
| Cuota gratuita RPD | <100 | Caché agresiva + parser determinista; evaluar local |
| Deprecación del modelo sin sustituto gratuito | — | Conmutar a local (el adaptador ya existe) |
| Si el servidor pasa a tener GPU ≥8 GB | — | Reconsiderar local como primario: cambiaría latencia y privacidad |

---

## 8. Qué no puedo verificar / depende de versión

- **Límites numéricos de la capa gratuita de Gemini.** Google ya no publica una tabla estática de RPM/TPM/RPD para la capa gratuita; solo dice que se consulten en AI Studio y que varían por modelo y proyecto, con reset a medianoche del Pacífico. Cualquier cifra concreta (típicamente ~15 RPM / ~1.000 RPD en Flash-Lite en generaciones anteriores) es histórica y **no verificable para 3.5 Flash-Lite hoy**.
- **Nombres y disponibilidad de modelos.** Hoy existen Gemini 4 Argon, 3.8 Flash, 3.6 Flash, 3.5 Flash-Lite, 3.1 Flash-Lite; los 2.5 están restringidos a usuarios previos. Google rota rápido: la recomendación caduca.
- **Comparabilidad de benchmarks de embeddings.** Qwen3 reporta MTEB multilingual media 64,33; EmbeddingGemma-2 reporta MTEB multilingual v2 61,36 (y con el modelo de 740M, no con el de 270M); BGE-M3 no da una cifra única comparable. **No son la misma métrica**: no se pueden ordenar directamente.
- **Contexto de EmbeddingGemma-2.** La ficha de Ollama dice 256K en las tarjetas y 8.192 en la descripción técnica. Inconsistente; asumir 8K.
- **Velocidad local.** Ninguna ficha publica tok/s en CPU. Las cifras de las tablas son estimaciones por ancho de banda; hay que medirlas con el servidor real y con la cuantización elegida.
- **Soporte de Intel Arc/NPU en Ollama.** Ollama soporta CUDA, ROCm, Metal y Vulkan; Intel va por Vulkan, no hay backend dedicado, y **no hay soporte de NPU**. La NPU del portátil queda sin usar con este stack; usar OpenVINO sería otro proyecto.
- **Lectura legal de los términos de Gemini para el EEE.** La conclusión "en España la cuota gratuita no entrena con tus prompts" se deriva de los términos actuales; no es asesoría legal y Google puede cambiarla.
- **Latencia de Gemini.** No hay cifras oficiales de TTFT/tok/s; las estimaciones son órdenes de magnitud.

---

## 9. Fuentes

- Gemini API — límites: <https://ai.google.dev/gemini-api/docs/rate-limits>
- Gemini API — precios y capa gratuita: <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini API — términos (EEE y datos): <https://ai.google.dev/gemini-api/terms>
- Gemini API — modelos: <https://ai.google.dev/gemini-api/docs/models>
- Gemini 3.5 Flash-Lite: <https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite>
- Gemini API — function calling: <https://ai.google.dev/gemini-api/docs/function-calling>
- Gemini API — embeddings: <https://ai.google.dev/gemini-api/docs/embeddings>
- Qwen3-Embedding-0.6B: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- Qwen3-Embedding-0.6B GGUF: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF>
- EmbeddingGemma-2 (Ollama): <https://ollama.com/library/embeddinggemma-2>
- BGE-M3: <https://huggingface.co/BAAI/bge-m3>
- Qwen3.5 en Ollama: <https://ollama.com/library/qwen3.5>
- Qwen3.5-4B: <https://huggingface.co/Qwen/Qwen3.5-4B>
- Gemma 4 en Ollama: <https://ollama.com/library/gemma4>
- functiongemma: <https://ollama.com/library/functiongemma>
- Ollama — tool calling: <https://docs.ollama.com/capabilities/tool-calling>
- Ollama — structured outputs: <https://docs.ollama.com/capabilities/structured-outputs>
- Ollama — GPUs soportadas: <https://docs.ollama.com/gpu>
- Librería de modelos de Ollama: <https://ollama.com/library>
