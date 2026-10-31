# Respuesta original de Gemini — Señal de Tiempo 5 (primer intento, sin pedir búsqueda web)

- Fecha: 31 de octubre de 2026
- Modelo: gemini-3.8-flash-high (Antigravity CLI 1.4.12, modo no interactivo, sin contexto previo)

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

Como Arquitecto de Software para este proyecto de Fin de Grado/Máster en Sistemas de Información de Gestión y Business Intelligence (SIG/BI), la prioridad es diseñar una arquitectura **robusta, defendible ante un tribunal académico, reproducible y técnicamente viable** bajo las restricciones estrictas de hardware (CPU/sin GPU dedicada) y SLA (<5 s p95).

---

### 1. Embeddings de productos: Modelo local vs. API, candidatos y evaluación

#### Decisión: Modelo Local Obligatorio
Para este caso de uso, **los embeddings deben ser 100 % locales**:
1. **Coste e ingesta**: Vectorizar un catálogo inicial de 30.000 a 100.000 referencias mediante una API gratuita satura rápidamente cuotas de peticiones por minuto (RPM/TPM).
2. **Determinismo y reproducibilidad**: Si una API en la nube cambia de versión o descataloga el modelo, los vectores de `pgvector` quedan obsoletos y obligan a reindexar la base de datos completa.
3. **Rendimiento en CPU**: Un modelo bi-encoder pequeño en ONNX Runtime procesa cadenas cortas de 5 a 15 tokens en menos de **2 a 5 ms por producto en CPU**.

#### Modelos recomendados (Abiertos y optimizados para CPU)

| Modelo | Dimensión | Parámetros / Peso (FP32 / INT8) | Rendimiento en CPU (x86 / Intel Core Ultra) | Idoneidad para catálogo español |
| :--- | :---: | :---: | :---: | :--- |
| **`intfloat/multilingual-e5-small`** *(Recomendado)* | 384 | 117M (~470 MB / ~120 MB en ONNX) | Excelente (~2-4 ms/inferencia). Muy bajo consumo de RAM. | Diseñado para búsqueda semántica multilingüe. Requiere prefijo (`"query: "` y `"passage: "`). |
| **`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** | 384 | 118M (~470 MB / ~120 MB en ONNX) | Excelente (~3-5 ms/inferencia). Estándar industrial muy probado. | Gran solidez sintáctica en español. No requiere sintaxis de prefijos. |
| **`intfloat/multilingual-e5-base`** | 768 | 278M (~1.1 GB / ~300 MB en ONNX) | Aceptable (~8-15 ms/inferencia). | Mayor capacidad representacional, pero duplica el espacio en disco e índices HNSW en `pgvector`. |

> [!IMPORTANT]
> **El talón de Aquiles de los Embeddings Semánticos:**
> Ningún modelo de embeddings densos por sí solo distingue de forma fiable "Leche entera" de "Leche desnatada", ni "800 g" de "200 g". En el espacio vectorial, "entera" y "desnatada" son casi idénticos porque comparten exactamente el mismo contexto sintáctico y de distribución.

#### Cómo evaluar y resolver la distinción de formatos y variantes

Para la memoria académica, debes proponer una evaluación cuantitativa combinada con una arquitectura híbrida:

1. **Construcción del Dataset de Evaluación (Triplet Benchmark)**:
   Crea un conjunto de prueba de ~500 tripletas representativas:
   - *Anchor*: `"Leche semidesnatada Pascual brik 1 L"`
   - *Positive*: `"Pascual leche semi 1000 ml"`
   - *Hard Negative (Atributo/Variante)*: `"Leche entera Pascual brik 1 L"`
   - *Hard Negative (Formato/Cantidad)*: `"Leche semidesnatada Pascual pack 6x1 L"`
   - *Hard Negative (Marca)*: `"Leche semidesnatada Hacendado 1 L"`

2. **Métricas a calcular**:
   - **MRR@k** y **Recall@k** en la recuperación de candidatos.
   - **Hard Negative Separation Rate (HNSR)**: Porcentaje de casos donde:
     $$\text{sim}(\vec{u}_{anchor}, \vec{u}_{pos}) - \text{sim}(\vec{u}_{anchor}, \vec{u}_{hard\_neg}) > \delta$$
     Si $\delta \le 0$, el modelo no distingue la variante.

3. **La Solución Arquitectónica (Búsqueda Híbrida en PostgreSQL)**:
   No delegues la detección de gramos, litros o tipos a los embeddings. En la ingesta:
   - Extrae con expresiones regulares estructuradas: `cantidad_num` (float), `unidad` (g, ml, ud), `grasa` (entera, semi, desnatada), `sin_lactosa` (bool).
   - En `pgvector`, filtra primero por metadatos duros (`WHERE unidad = 'l' AND grasa = 'semi'`) y utiliza el producto escalar/coseno solo para ordenar la cercanía semántica del nombre/marca.

---

### 2. LLM del Orquestador: Modelo Local vs. API en la Nube

#### ¿Es suficiente un modelo local de 3B–8B en CPU para este SLA?
**No para cumplir el SLA de <5 s p95 con 30 artículos.**
- **Cálculo de tokens**: Interpretar una lista de 30 artículos en lenguaje libre y transformarla en una llamada a herramienta con un JSON estructurado de 30 objetos requiere generar entre **400 y 700 tokens de salida**.
- **Velocidad en CPU modesta**: Un modelo de 7B/8B (como `Qwen2.5-7B` o `Llama-3.1-8B`) cuantizado a Q4_K_M genera en una CPU de servidor estándar entre **6 y 12 tokens/s**.
  - Tiempo solo de inferencia: $500 \text{ tokens} / 10 \text{ t/s} = 50 \text{ segundos}$.
  - Incluso en el portátil con Intel Core Ultra 7 (usando NPU/iGPU con OpenVINO) alcanzará ~25-35 t/s, lo que supone **15 a 20 segundos**, superando por mucho los 5 s.
- **Modelos de 3B**: Aunque alcancen 35-45 t/s en CPU (~10-12 s), su adherencia a esquemas JSON complejos de 30 elementos sin corromper la sintaxis o perder artículos en español es deficiente comparada con modelos de frontera.

#### Comparativa Técnica: Local (Ollama/llama.cpp) vs. Nube Gratuita (Gemini Flash)

| Criterio | Modelo Local (3B - 8B Q4 en CPU) | Nube Gratuita (ej. Gemini 2.0 / 1.5 Flash) |
| :--- | :--- | :--- |
| **Tool Calling / JSON Schema** | Variable (3B suele alucinar claves o truncar listas largas; 7B/8B requiere gramáticas GBNF estrictas). | **Excelente**. Soporte nativo de `response_schema` y function calling determinista. |
| **Latencia (30 ítems)** | **30 - 60 s** en CPU servidor (Inviable para SLA < 5 s). | **1.2 - 2.2 s** (Time-To-First-Token ~300 ms + streaming/buffer rápido). Cumple el SLA. |
| **Límites de Capa Gratuita** | Sin límites de red ni cuotas diarias. | **15 RPM / 1.500 RPD**. Más que suficiente para "decenas de peticiones/día". |
| **Privacidad** | **100 % local**. Cero fuga de datos. | **Cumple la restricción**: Solo viaja el texto de la lista; las coordenadas, tiendas y precios quedan en local. |
| **Dependencia / Bloqueo** | Cero dependencia externa. | Depende de la API de Google, su política de cuotas y cambios de modelo. |
| **Reproducibilidad Académica** | **Total**: Los pesos no cambian; el tribunal puede ejecutarlo sin conexión. | Media: Los modelos en la nube se actualizan y pueden variar respuestas sutilmente. |

---

### 3. Topología de Agentes: ¿Único Agente o Sistema Multiagente?

#### Veredicto Académico y de Ingeniería: **Un único Agente Orquestador (Pipeline Aumentado por Herramientas)**

En un proyecto de Sistemas de Información y BI, **introducir un sistema multiagente (intérprete, resolutor, explicador) para este problema es un antipatrón ("Agentic Theater")** que penalizará tu defensa académica y destruirá la latencia:

```
[Cliente: Lista libre] 
         │
         ▼
[Paso 1: LLM Parser / Extractor] ──> Valida JSON de 30 productos con cantidades canónicas
         │
         ▼
[Paso 2: Determinista (pgvector)] ──> Encuentra candidatos y precios en supermercados de León
         │
         ▼
[Paso 3: Determinista (OSRM/PostGIS)] ──> Matriz de tiempos reales (pie/coche)
         │
         ▼
[Paso 4: Determinista (MIP/HiGHS Solver)] ──> Resuelve: Min(Coste + λ · Minutos) sujeto a ≤ 3 tiendas
         │
         ▼
[Paso 5: LLM Sintetizador] ──> Explica en español natural el desglose y el ahorro obtenido
```

#### Justificación para la Memoria Académica:
1. **Minimización de saltos estocásticos**: Cada llamada a un agente LLM añade latencia de red y riesgo de fallo o alucinación. Si usas 3 agentes encadenados en la nube, la latencia sube a 4-6 segundos solo en LLM; en local CPU se va a minutos.
2. **Defensa metodológica**: En Business Intelligence, la resolución de equivalencias y la optimización combinatoria son problemas matemáticos cerrados. Demostrar ante el tribunal que reservas el LLM **estrictamente para interfaces de lenguaje natural (entrada y salida)** y dejas el núcleo analítico a algoritmos deterministas (Programación Lineal Entera Mixta + Vector Search) demuestra madurez de ingeniería de software.

---

### 4. Tareas a Resolver SIN LLM

El principio rector debe ser: **Si se puede resolver con una función pura en Python o SQL en menos de 1 ms, jamás uses un LLM.**

1. **Extracción de Cantidades y Formatos**:
   - Utiliza librerías deterministas como `quantulum3` o expresiones regulares precompiladas para extraer magnitudes: `"2 kg de naranjas"` $\rightarrow$ `{item: "naranjas", qty: 2.0, unit: "kg"}`.
   - Es 10.000 veces más rápido que un LLM, infalible ante erratas de espaciado y con coste computacional nulo.

2. **Categorización y Taxonomía**:
   - Clasificar productos en categorías (Lácteos, Frutas, Limpieza): si el catálogo del scraping ya tiene categorías de origen (Mercadona, Carrefour, etc.), un mapeo estático de diccionarios/taxonomía (`dict` en memoria) resuelve el 95 % de los casos.
   - Para el 5 % restante sin categoría, un clasificador ultraligero local de Machine Learning clásico (`TF-IDF + LogisticRegression` o `FastText`, <20 MB) clasifica en 0.2 ms en CPU.

3. **Cálculo de Tiempos y Optimización**:
   - Ya decidido: PostGIS para radio de proximidad, OSRM/Valhalla local para matriz de distancias/tiempos, y un solver libre como **HiGHS** (vía `scipy.optimize.milp` o `PuLP`) para resolver la cesta óptima en menos de 50 ms.

---

### 5. Recomendación Concreta para el MVP

#### Arquitectura Recomendada (Diseño Híbrido Pragmático)

```
                           ARQUITECTURA DEL MVP
                           
      +--------------------------------------------------------------+
      | ENTORNO LOCAL (Docker Compose en Servidor / Portátil)        |
      |                                                              |
      |  1. Ingesta Diaria:                                          |
      |     Scraper -> Normalización Regex -> e5-small (ONNX en CPU) |
      |                                                              |
      |  2. Datos & Búsqueda:                                        |
      |     PostgreSQL + pgvector (HNSW) + PostGIS                   |
      |                                                              |
      |  3. Motor Analítico:                                         |
      |     OSRM (León extract) + HiGHS Solver (MIP en Python)       |
      +------------------------------▲-------------------------------+
                                     │
                 Solo texto de lista │ Payload JSON estructurado
                 (Sin ubicación)     │
                                     ▼
      +--------------------------------------------------------------+
      | CAPA EXTERNA (Detrás de la interfaz agnóstica LLMProvider)  |
      |                                                              |
      |  Opción Principal: Gemini 2.0 Flash (API gratuita)           |
      |  - Tarea 1: Parseo de lista a JSON de búsqueda (~1.2 s)      |
      |  - Tarea 2: Generación de resumen explicativo (~0.8 s)       |
      +--------------------------------------------------------------+
```

1. **Embeddings**: **`intfloat/multilingual-e5-small`** ejecutado en local mediante `fastembed` o `onnxruntime`. Dimensión 384, consumo de memoria mínimo (~200 MB), persistencia en `pgvector`.
2. **Orquestador LLM Principal**: **Gemini 2.0 Flash** (o 1.5 Flash) a través de la interfaz abstracta `LLMProvider`. Se encarga únicamente del parseo inicial de texto libre a intención de compra estructurada y de la explicación final en lenguaje natural amigable.
3. **Privacidad**: El orquestador local en Python recibe la petición del usuario, despoja cualquier coordenada o identificador, y envía a Gemini únicamente:
   `"Extrae la lista de la compra: '2 bricks de leche entera, medio kilo de plátanos y algo rico para cenar'"`
   El solver y OSRM operan localmente con las coordenadas reales de León.

#### Plan de Reserva (Fallback Mode para la Defensa Académica)
Debes implementar la clase `LocalOllamaProvider` implementando la misma interfaz `LLMProvider`:
- Si se corta Internet o falla la cuota de la API durante la demostración ante el tribunal, un flag de configuración (`LLM_BACKEND=local`) conmuta a **`Qwen2.5-7B-Instruct-Q4_K_M`** corriendo en Ollama/llama.cpp en tu portátil Intel Core Ultra 7.
- **Narrativa para la memoria**: *"El sistema dispone de un modo resiliente 100 % autónomo y desconectado para entornos críticos de soberanía de datos, asumiendo una degradación controlada de la latencia (18 s vs. 2.5 s) sin perder precisión en la optimización"*.

#### Umbrales Medibles de Decisión (Triggers de Cambio)

| Métrica | Umbral de Alarma | Acción de Cambio en la Arquitectura |
| :--- | :--- | :--- |
| **Error en variantes (Catálogo)** | $> 5\,\%$ de falsos positivos en variantes (ej. asigna leche desnatada a solicitud de entera). | Forzar extracción de tokens de atributo a columnas relacionales dedicadas en PostgreSQL antes de calcular distancias vectoriales. |
| **Latencia Total Recom.** | $> 5.0\text{ s}$ en el percentil p95. | Cachear con Redis/PostgreSQL el parseo de listas frecuentes y paralelizar las consultas de equivalencia en `pgvector`. |
| **Agotamiento de Cuota API** | $> 12\text{ peticiones/minuto}$ (cerca del límite de 15 RPM). | Activar fallback local o encolar peticiones mediante cola FIFO con backoff exponencial. |
| **Fallo de Esquema JSON** | $> 2\,\%$ de respuestas del LLM con JSON malformado. | Forzar modo JSON nativo (`response_mime_type="application/json"` con `response_schema`) o activar validación estricta con Pydantic. |

---

### 6. Advertencias y Supuestos Sujetos a Cambios

1. **Límites de la Capa Gratuita de Google AI Studio**:
   - Actualmente, los modelos Flash en Google AI Studio disponen de un nivel gratuito de hasta 15 RPM (Requests Per Minute) y 1.500 RPD (Requests Per Day). No obstante, las cuotas por modelo cambian frecuentemente y las políticas de uso gratuito estipulan que los datos enviados a la API gratuita pueden ser utilizados para entrenamiento/revisión por parte de Google (garantizando aún más que **nunca** debes enviar datos personales o de ubicación).
2. **Rendimiento de CPU en Servidores de Despliegue**:
   - Las estimaciones de inferencia local de 6-12 t/s asumen un procesador x86 moderno con soporte para instrucciones AVX2/AVX-512. Si el servidor modesto final es un VPS en la nube con 1 o 2 vCPUs compartidas (noisy neighbors), el rendimiento de inferencia local caerá a menos de 2-4 t/s, haciendo el fallback local inviable salvo que se ejecute en el portátil de desarrollo.
3. **Optimización con OSRM en León**:
   - El cálculo de matrices de viaje en León (ciudad de ~120.000 habitantes) con OSRM a pie o en coche tiene un coste computacional despreciable (<10 ms para 10-15 puntos de interés), siempre que el mapa `.osm.pbf` de Castilla y León esté recortado al área urbana para no saturar la memoria RAM del contenedor.
