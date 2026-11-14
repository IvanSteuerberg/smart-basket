# Respuesta original de DeepSeek — Señal de Tiempo 8

- Fecha: 14 de noviembre de 2026
- Modelo: deepseek-v4.1-flash a través de OpenCode Go (Claude Code en modo no interactivo como cliente, carpeta vacía, sin contexto previo, con WebSearch y WebFetch; 49 turnos, 781 s). Su búsqueda web volvió a fallar y leyó directamente las páginas oficiales.

## Prompt

```text
Actúa como arquitecto de software especializado en sistemas de recomendación, bases de datos relacionales y de grafos, y protección de datos (RGPD). Diseño cómo guarda y aprende las preferencias del comprador una aplicación que recomienda en qué supermercados de León (España) comprar una lista de la compra para minimizar coste + lambda * minutos de desplazamiento, con un máximo de 3 tiendas.

Decisiones ya tomadas:
- Stack: un único PostgreSQL 18 con PostGIS y pgvector, backend en Python con FastAPI, aplicación web progresiva (PWA) en React, todo con Docker Compose en un portátil. Se decidió no añadir Neo4j salvo que las consultas de varios saltos o los algoritmos de grafos pasen a ser una función central.
- Catálogo: producto canónico sin marca ni formato (por ejemplo, «leche semidesnatada sin lactosa»), con las variantes que cambian la equivalencia como atributos. Cada producto de cada cadena (marca, formato, precio por unidad) se asigna a un canónico. Taxonomía propia de 338 categorías de productos intercambiables; unas 7 cadenas, de 4.500 a 26.000 productos cada una.
- La lista se escribe en texto libre o se arma desde el catálogo; un preprocesador de reglas y, si hace falta, un LLM local la interpretan; un optimizador determinista calcula la cesta. Los precios nunca los produce el LLM.
- Experiencia de uso: se navega por supermercado o por producto genérico; cada línea indica si acepta «este producto» o «cualquier X»; un solo gesto pasa toda la lista a «me da igual la marca» sin tocar las marcas fijadas; fijar una marca es un toque. Se busca el mínimo de pasos: lo ambiguo se pregunta en línea, no en una pantalla aparte.

Preferencias que hay que guardar y aprender (se usan como valores por defecto al interpretar la lista y al calcular la cesta):
1. La elección habitual para términos ambiguos («fruta» → plátanos y mandarinas, o «la de temporada»).
2. Marcas fijadas («leche» → Pascual).
3. Cadenas preferidas o excluidas.
4. Reglas como «sin lactosa siempre».

Dos escenarios:
- (A) MVP académico (asignatura de Sistemas de Información de Gestión y Business Intelligence; uso personal, la aplicación no se publica): sin cuentas de usuario. Las listas y el historial personal viven solo en el navegador; en el servidor solo se guardan recomendaciones anónimas.
- (B) Producto posterior: cuentas de usuario y suscripciones de pago. Las preferencias viven en el servidor y se hacen posibles las recomendaciones entre usuarios.

Requisito: el perfil local de A debe tener la misma forma que el perfil de servidor de B, de modo que al iniciar sesión por primera vez el perfil se suba y después se sincronice.

Compara cuatro opciones:
a) Un perfil local en el navegador aprendido del historial (escenario A).
b) Tablas de PostgreSQL con historial y preferencias (escenario B).
c) Apache AGE (openCypher dentro de PostgreSQL).
d) Neo4j.

Para cada una explica qué permite (sustituciones de varios saltos, «quien compra X también compra Y», perfiles similares), su coste y operación, su impacto en el RGPD (base jurídica y consentimiento, exportación y portabilidad, supresión, perfilado) y cómo se migra de A a B.

Preguntas:
1. Cómo aprender «lo de siempre» a partir del historial: conteos, recencia, umbrales, cuándo preguntar en lugar de suponer, y cómo distinguir una preferencia explícita (fijada por el usuario) de una aprendida.
2. Esquema del perfil: entidades y campos, con un esbozo de JSON para el navegador y de DDL para PostgreSQL, y cómo sincronizar (versiones, conflictos entre dispositivos, borrados).
3. Dónde guardarlo en el navegador (localStorage, IndexedDB, almacenamiento persistente) y riesgos de pérdida de datos.
4. Con cuentas: ¿basta PostgreSQL para el filtrado colaborativo y los perfiles similares (consultas de coocurrencia en SQL, embeddings de perfil con pgvector), o cuándo compensa un grafo? Da umbrales concretos (usuarios, saltos, latencia) que justificarían Apache AGE o Neo4j. Estado actual de Apache AGE (última versión, soporte de PostgreSQL 18, madurez) y de Neo4j Community Edition (licencia, limitaciones).
5. RGPD en el escenario B: qué obliga a hacer guardar preferencias e historial de compra en el servidor. ¿Pueden ser datos de salud del artículo 9 reglas como «sin lactosa» o «sin gluten», o las que se infieren del historial? Cómo diseñar para cumplir desde el principio.

Da una recomendación concreta para A y para B, con lo mínimo necesario y lo que puede esperar. Antes de responder, busca en internet información actual (hoy es 14 de noviembre de 2026) sobre Apache AGE, Neo4j, pgvector y los criterios de las autoridades de protección de datos (AEPD, CEPD/EDPB) sobre datos de salud inferidos y perfilado, y cita las fuentes con URL. Indica qué no has podido verificar. No ejecutes comandos ni modifiques archivos: usa solo la búsqueda web y la lectura de páginas.
```

## Respuesta

# Perfil de preferencias: diseño, comparación de opciones y recomendación

**Nota previa sobre las fuentes.** La herramienta de búsqueda de este entorno ha fallado (devolvía texto generado en vez de resultados), así que he ido directamente a las páginas oficiales. He podido verificar con lectura directa: releases de Apache AGE, `CHANGELOG` de pgvector, licencia y manual de Neo4j, nota de prensa de PostgreSQL 18, MDN sobre almacenamiento y una nota reciente de la AEPD. **No he podido renderizar** el texto de las sentencias del TJUE en EUR-Lex/InfoCuria (son aplicaciones JS), ni el PDF de las Directrices 8/2020 del CEPD: lo que digo de C-21/23 y C-184/20 va marcado como no verificado en esta sesión. Lo detallo al final.

---

## 0. La decisión que ordena todo lo demás

Antes de comparar motores: **(a) y (b) no compiten con (c) y (d)**. (a) y (b) son una *ubicación* (cliente vs servidor) y un *modelo* (relacional); (c) y (d) son *motores*. La comparación real es doble: **dónde vive el perfil** y **si el grafo es una necesidad de producto o una optimización prematura**.

Y hay una segunda decisión, que es la que hace posible el requisito A→B: **el perfil no es un documento que se guarda, es un conjunto de hechos con origen distinto**. Diseña tres capas separadas desde el primer día:

| Capa | Naturaleza | ¿Se sincroniza? | ¿Se recalcula? |
|---|---|---|---|
| **Hechos explícitos** (pins, exclusiones, reglas dietéticas, λ, tiendas) | Estado con identidad propia, editable por el usuario | Sí, es la fuente de verdad | Nunca |
| **Eventos** (qué se aceptó, qué se cambió, en qué lista) | Log append-only, idempotente | Sí, se une por unión | Nunca se borran (hasta retención) |
| **Derivados** (confianza, "lo de siempre", embeddings) | Caché | **No** | Siempre, desde eventos + explícitos |

Esta separación resuelve a la vez: el conflicto entre dispositivos (los eventos no confluyen, se acumulan), la distinción explícito/aprendido (es un campo `origin`, no una heurística), el RGPD (base jurídica y plazo distintos por capa) y la portabilidad (el export es el mismo esquema que el sync).

**Regla de oro del optimizador:** las preferencias **no entran en la función objetivo**. El objetivo sigue siendo `coste + λ·minutos`, determinista y explicable. Las preferencias (i) restringen el conjunto de candidatos, (ii) rompen empates entre cestas dentro de ±0,50 € o ±2 min, (iii) generan explicaciones. Si metes pesos de preferencia en el objetivo, pierdes determinismo, explicabilidad y la capacidad de decir "esta cesta cuesta 1,20 € más porque fijaste Pascual".

---

## 1. Las cuatro opciones

### (a) Perfil local en el navegador, aprendido del historial

**Qué permite.** Todo lo que necesita el escenario A: pins, reglas, defaults aprendidos, y el cálculo de la cesta (el servidor recibe la lista ya resuelta a canónicos y devuelve la recomendación anónima). No permite nada entre usuarios: sin perfiles similares, sin "quien compra X también compra Y". Los "varios saltos" existen, pero sobre el **catálogo** (categoría → producto → variante → cadena → tienda), no sobre personas, y eso ya lo resuelve SQL.

**Coste y operación.** Casi cero en servidor. El coste real es de **producto**: el aprendizaje vive en dos implementaciones (la del navegador en TS y la del servidor en Python cuando llegue B). Mitigación: define el algoritmo una vez sobre el esquema de eventos y escribe dos implementaciones pequeñas con los mismos tests dorados; o, mejor, ejecuta el cálculo de derivados **en el servidor también en A** sobre los eventos que el cliente envía en cada petición de cesta (no se persisten), de modo que solo hay una implementación. Esta segunda variante es la que recomiendo.

**RGPD.** El navegador no es una zona franca: el RGPD aplica en cuanto hay datos personales, pero **no hay responsable del tratamiento en el servidor** para el perfil. Lo que sí hay que cuidar: los datos de salud (reglas "sin lactosa") siguen siendo categoría especial aunque vivan en el cliente; el usuario debe poder borrarlos y exportarlos; y cualquier evento que viaje al servidor (para calcular la cesta) es una comunicación de datos al responsable, aunque sea efímera. En A esto se resuelve con transparencia y minimización, no con un consentimiento formal complejo.

**Migración a B.** Es el caso bueno: `POST /v1/profile/import` con el JSON tal cual, `origin: "imported"`, y a partir de ahí sync incremental. Los IDs canónicos ya son del servidor, así que no hay traducción.

### (b) Tablas PostgreSQL con historial y preferencias

**Qué permite.** Todo A, más: coocurrencia por self-join, perfiles similares con `pgvector`, agregados por cohorte, BI real (que es la asignatura). Los "varios saltos" sobre personas (X → Y → Z) se hacen con `WITH RECURSIVE`, y a 2–3 saltos con índices adecuados es perfectamente viable por debajo de cientos de millones de aristas.

**Coste y operación.** Un solo motor, un backup, una migración, un `docker-compose`. Es la opción con menor coste total de propiedad y la única que no añade una segunda copia de datos personales al registro de actividades.

**RGPD.** Es donde mejor se implementa el ciclo de vida: `ON DELETE CASCADE`, borrado lógico con lápidas, particionado por mes para retención, RLS por `user_id`, exportación como vista materializada del esquema público. La contrapartida: al centralizar, aparecen obligaciones formales (art. 30, art. 35, base jurídica explícita) que en A no existían.

**Migración a B.** Es B. La migración desde A es importación + merge (sección 3).

### (c) Apache AGE (openCypher dentro de PostgreSQL)

**Qué permite.** Consultas de patrón variables (`MATCH (u)-[:BUY*1..3]->(p)`) sin salir de Postgres, con SQL y Cypher en la misma transacción. Para "quien compra X también compra Y" y para caminos de 2–3 saltos es cómodo y expresivo. **No** trae algoritmos de grafos: ni Louvain, ni similaridad de nodos, ni PageRank. Para perfiles similares sigues necesitando pgvector o calcularlo tú.

**Coste y operación.** Una extensión más que compilar y actualizar **por versión mayor de PostgreSQL**: AGE publica ramas por major (`PG18/v1.8.0-rc0`). Ese sufijo `-rc0` es el dato importante: a fecha de hoy, la compilación para PG18 que figura como la más reciente en la página de releases está marcada como *release candidate*, no como versión final [1]. Es decir: **AGE sobre PostgreSQL 18 todavía no es una base estable**. Además, Cypher se traduce a SQL sobre un esquema propio (`ag_catalog`), sin estadísticas del planificador para patrones, lo que produce regresiones de plan difíciles de diagnosticar; y el proyecto tiene una cadencia de publicación lenta y una base de mantenedores pequeña.

**RGPD.** Neutro respecto a (b): mismos datos, misma obligación. Solo añade una copia lógica (los nodos del grafo) que hay que incluir en supresión y portabilidad.

**Migración a B.** ETL de eventos a nodos/aristas. No ahorra nada: el problema de A→B es el mismo.

### (d) Neo4j

**Qué permite.** Lo mismo que (c) más el ecosistema que justifica el salto: **GDS** (Louvain/Leiden para comunidades de compradores, similaridad de nodos, FastRP para embeddings de grafo), recorridos profundos con buen rendimiento y un lenguaje maduro. Si algún día el producto es "descubre qué compran personas como tú" con detección de comunidades, Neo4j es el sitio natural.

**Coste y operación.** Los tres problemas concretos de Community Edition, verificados en la documentación: licencia **GPLv3** [2]; **una sola base de datos estándar** ("Installations of Community Edition can have exactly one standard database") [3]; y sin clustering, sin RBAC/LDAP y sin backup en caliente, que son capacidades de Enterprise [4]. Para un SaaS multiinquilino, la ausencia de RBAC y de multi-base significa aislamiento a nivel de aplicación y backups con parada. Enterprise es licencia comercial (Acuerdo de Software de Neo4j), con precio que no es público: hay que pedir presupuesto. Añade un segundo store: segundo backup, segunda ruta de upgrade, doble escritura, y una **segunda copia de datos personales** en el registro de actividades.

**RGPD.** Coste indirecto pero real: cada copia adicional amplía el ámbito de la supresión, la portabilidad y el contrato de encargado; y la sincronización entre Postgres y Neo4j es un punto donde la supresión puede fallar silenciosamente. Es un argumento infravalorado en las comparativas puramente técnicas.

**Migración a B.** Igual que (c): ETL. Pero aquí hay un coste específico: el perfil local tendría que mapearse a un modelo de nodos, y ese mapeo se convierte en deuda si el grafo se abandona.

### Tabla resumen

| | (a) Local | (b) Postgres | (c) AGE | (d) Neo4j |
|---|---|---|---|---|
| Varios saltos sobre el catálogo | Sí (cliente) | Sí (SQL) | Sí | Sí |
| Varios saltos sobre personas | No | Sí (recursivo, 2–3) | Sí, cómodo | Sí, mejor |
| "Quien compra X también Y" | No | Sí (self-join/materializada) | Sí | Sí |
| Perfiles similares | No | Sí (pgvector) | Solo con pgvector aparte | Sí (+ GDS) |
| Algoritmos de grafo (comunidades) | No | No (o SQL manual) | No | **Sí (GDS)** |
| Coste operativo | Mínimo | Bajo | Medio | Alto |
| Madurez hoy con PG18 | — | Nativa | **RC, no estable** | N/A |
| Añade copia de datos personales | No | No | Sí (lógica) | Sí (física) |
| Migración A→B | Trivial | Directa | ETL | ETL |

---

## 2. Cómo aprender "lo de siempre"

### Qué se registra

Cada interacción con una línea de la lista produce un evento con: término normalizado, canónico elegido, variante elegida (marca/formato), acción (`accepted`, `replaced`, `removed`, `pinned`, `unpinned`), cadena, precio en ese momento, y contexto (lista, hora). El evento es la unidad atómica; **nunca guardes solo el agregado**, porque entonces no puedes recalcular cuando cambies el decaimiento ni auditar por qué el sistema supuso algo.

Señales con peso distinto, porque cuestan distinto al usuario:

| Señal | Peso | Motivo |
|---|---|---|
| Fijar una marca (`pinned`) | ∞ (no es evidencia, es una orden) | Es una decisión explícita |
| Reemplazar lo sugerido | **2×** | Corregir cuesta esfuerzo; es la señal más informativa |
| Eliminar una línea | 1,5× en negativo | Puede ser "no lo quiero" o "ya lo tengo" |
| Aceptar sin tocar | 1× | Señal débil: puede ser indiferencia |
| Tiempo hasta aceptar | 0,3× | Muy débil; útil solo como desempate |

### Conteo con recencia

No cuentes; cuenta con decaimiento exponencial. Semividas propuestas:

- **Marca y formato**: 60 días. El consumo cambia con las promociones y el cansancio.
- **Elección por defecto dentro de una categoría** ("fruta" → plátanos): 90 días, con corrección estacional (ver abajo).
- **Cadena preferida**: 120 días.
- **Cadena excluida y reglas dietéticas**: sin decaimiento. Son explícitas; si el usuario las quiere cambiar, las cambia.

`n_eff = Σ 2^(-Δdías / H)` y `p_top = peso_top / Σ pesos`. Dos guardas: exige que el patrón aparezca en **≥ 2 listas distintas** (una compra de cumpleaños no es una preferencia) y trata los rechazos como evidencia negativa del canónico, no de la marca.

### Cuándo suponer y cuándo preguntar

| Condición | Comportamiento |
|---|---|
| `n_eff ≥ 5`, `p_top ≥ 0,70`, margen sobre el segundo `≥ 0,25` | Aplicar en silencio, con "asumido: plátanos · cambiar" visible |
| `0,45 ≤ p_top < 0,70`, o `n_eff` entre 3 y 5 | Preseleccionar y preguntar en línea con un chip: "¿Plátanos? ▾" |
| `p_top < 0,45` o `n_eff < 3` | Sin defecto; ofrecer 2–3 opciones |
| La alternativa no cambia la cesta óptima | **No preguntar**: resolver como "cualquier equivalente" y dejar que el optimizador elija lo más barato |

Esa última fila es la más importante para el objetivo de "mínimos pasos". La ambigüedad solo merece una pregunta si cambia la decisión. Mide el impacto: recalcula la cesta con cada interpretación y pregunta solo si la diferencia supera **0,50 € o 2 minutos** o si cambia el número de tiendas. Y pon un techo: **máximo dos preguntas por lista**; a partir de ahí, resuelve con "cualquier equivalente" y explica la suposición.

Añade exploración: en ~10 % de las listas, muestra la segunda opción aunque no sea la de mayor confianza (epsilon-greedy). Sin esto, el perfil se cierra sobre sí mismo, deja de tener datos para corregirse y el usuario queda atrapado en una preferencia de hace un año. Es un problema de calidad de datos (art. 5.1.d: exactitud) además de producto.

### "La de temporada"

No es una preferencia aprendida: es una **regla de resolución** (`seasonal: true`) que consulta un calendario de temporada por categoría. Guárdala como explícita y no la infieras del historial, o en enero concluirás que al usuario no le gustan las fresas.

### Explícito vs. aprendido

No es una cuestión de grado de confianza: son **dos tablas y dos semánticas**.

- `origin: "explicit"` → nunca decae, nunca lo sobrescribe un aprendido, gana siempre en el merge, se exporta y se borra como dato de configuración.
- `origin: "learned"` → decae, se recalcula, se puede descartar sin consecuencias legales, y **nunca se sincroniza como verdad** (solo sus eventos).

Cuando el aprendido contradice fuertemente a un explícito (por ejemplo, el usuario fija Pascual pero lleva 8 compras eligiendo otra marca), no cambies nada: muestra **una** sugerencia ("¿Seguimos usando Pascual?") como máximo cada 90 días. Un sistema que "corrige" al usuario en silencio es un sistema que el usuario deja de entender.

**Excepción absoluta: las reglas de salud.** "Sin lactosa", "sin gluten", "sin frutos secos" **solo pueden ser explícitas**. El sistema no las infiere del historial, no las sugiere a partir de patrones y no las muestra como inferencia. Motivo legal en la sección 6; motivo de producto: un falso positivo en un alérgeno es un daño real, y un falso positivo inferido además revela que el sistema sospechaba una condición de salud.

---

## 3. Esquema del perfil y sincronización

### JSON del navegador (`perfil.v1`)

```json
{
  "schema": "perfil.v1",
  "schema_minor": 3,
  "profile_id": "018f3c2a-...",
  "device_id": "dev-a1b2",
  "catalog_version": "2026-11-01",
  "rev": { "t": 1763114602123, "c": 3, "d": "dev-a1b2" },
  "settings": { "lambda": 0.35, "max_tiendas": 3, "radio_max_min": 25 },

  "chains": {
    "prefer": [{ "chain": "mercadona", "origin": "explicit", "rev": {"t":1763...,"c":0,"d":"dev-a1b2"} }],
    "exclude": [{ "chain": "carrefour", "origin": "explicit", "reason": "user", "rev": {...} }]
  },

  "pins": [
    { "id": "p_01", "scope": { "type": "term", "value": "leche" },
      "target": { "type": "brand", "value": "Pascual" },
      "origin": "explicit", "pinned_at": "2026-09-02T18:11:00Z", "rev": {...} }
  ],

  "rules": [
    { "id": "r_01", "kind": "exclude_attribute", "attribute": "lactosa",
      "scope": "global", "origin": "explicit", "consent_ref": "c_2026_09_02",
      "created_at": "2026-09-02T18:09:00Z", "rev": {...} }
  ],

  "defaults": [
    { "scope": { "type": "term", "value": "fruta" },
      "choice": [{ "canonical_id": "c_platan", "w": 0.62 }, { "canonical_id": "c_mandarina", "w": 0.24 }],
      "stats": { "n": 12, "n_eff": 7.4, "last": "2026-11-08T10:02:00Z" },
      "origin": "learned", "confidence": 0.71, "computed_at": "2026-11-14T08:00:00Z" }
  ],

  "events": [
    { "id": "018f3d...", "list_id": "l_88", "term": "fruta",
      "action": "accepted", "canonical_id": "c_platan", "variant_id": "v_123",
      "chain": "mercadona", "at": "2026-11-08T10:02:00Z", "rev": {...} }
  ],

  "tombstones": [
    { "entity": "pin", "id": "p_00", "deleted_at_rev": {"t":1762...,"c":1,"d":"dev-a1b2"} }
  ]
}
```

### DDL en PostgreSQL

```sql
create table app_user (
  id uuid primary key,
  email citext unique,
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table profile (
  user_id uuid primary key references app_user(id) on delete cascade,
  schema_version text not null default 'perfil.v1',
  settings jsonb not null default '{}',
  catalog_version text not null,
  updated_at timestamptz not null default now()
);

-- Una fila por hecho explícito. Los aprendidos NO viven aquí.
create table preference (
  id uuid primary key,
  user_id uuid not null references app_user(id) on delete cascade,
  scope_type text not null check (scope_type in ('term','category','chain','global')),
  scope_key  text not null,
  kind text not null check (kind in ('pin_brand','pin_variant','default_choice',
                                     'prefer_chain','exclude_chain','attribute_rule')),
  target jsonb not null,
  origin text not null check (origin in ('explicit','imported')),
  hlc_wall bigint not null,
  hlc_counter int not null default 0,
  device_id text not null,
  consent_ref text,
  created_at timestamptz not null default now(),
  deleted_at timestamptz,
  unique (user_id, scope_type, scope_key, kind, (target->>'value'))
);
create index on preference (user_id, deleted_at);

-- Log append-only, particionado por mes.
create table profile_event (
  event_id uuid not null,
  user_id uuid not null references app_user(id) on delete cascade,
  list_id uuid,
  term_norm text,
  action text not null check (action in ('accepted','replaced','removed','pinned')),
  canonical_id text,
  variant_id text,
  chain text,
  occurred_at timestamptz not null,
  hlc_wall bigint not null,
  device_id text not null,
  primary key (event_id, occurred_at)
) partition by range (occurred_at);
create index on profile_event (user_id, occurred_at desc);

-- Derivados: se pueden borrar y recalcular.
create table profile_default (
  user_id uuid references app_user(id) on delete cascade,
  scope_type text, scope_key text,
  canonical_id text not null,
  weight real not null, n_eff real not null, confidence real not null,
  computed_at timestamptz not null,
  primary key (user_id, scope_type, scope_key, canonical_id)
);

alter table preference enable row level security;
create policy pref_owner on preference
  using (user_id = current_setting('app.user_id')::uuid);
```

### Mapa JSON ↔ DDL

| JSON | Tabla |
|---|---|
| `pins`, `rules`, `chains.*` | `preference` (una fila por hecho) |
| `events` | `profile_event` |
| `defaults` | `profile_default` (derivado, nunca sincronizado) |
| `settings` | `profile.settings` |
| `tombstones` | `deleted_at` + `hlc` en `preference` |
| `rev` | `hlc_wall`, `hlc_counter`, `device_id` |
| `catalog_version` | `profile.catalog_version` |

Un único `profile.schema.json` como fuente de verdad, con modelos Pydantic y tipos TypeScript generados. Si el esquema se define dos veces, divergirá en tres semanas.

### Sincronización

**Reloj.** HLC (reloj lógico híbrido): `{t: ms físicos, c: contador, d: device_id}`. Ordena causalmente sin depender del reloj del dispositivo. Para el 99 % de los casos basta `t` + desempate por `device_id`.

**Dos mecanismos distintos, no uno:**

- **Eventos**: conjunto creciente. Se suben en lotes, idempotentes por `event_id` (UUIDv7), y se mergean por **unión**. No hay conflictos posibles. `sync_cursor` = máximo `(hlc_wall, hlc_counter)` confirmado.
- **Explícitos**: por ítem, no por documento. **Nunca hagas LWW del perfil entero**: dos dispositivos que editan cosas distintas se pisarían.

**Matriz de conflicto:**

| Caso | Resolución |
|---|---|
| explícito vs. explícito | Gana el HLC mayor |
| explícito vs. aprendido | Gana el explícito, siempre |
| borrado vs. actualización | Gana el borrado si su HLC es mayor; si la actualización es explícita y posterior al borrado, revive |
| importación vs. existente | Merge; si choca, gana el explícito del servidor salvo que el importado sea más reciente |

**Borrados.** Lápida con HLC, propagación en el siguiente `GET ?since=`; purga física a los 30 días. Sin lápidas, un dispositivo offline resucita lo borrado.

**Versión de esquema.** El servidor acepta `1.x` y rechaza `2.x` con `409` y `min_client_version`; el cliente guarda el JSON original antes de migrar. La migración de esquema es la operación más frágil de todo el sistema: versiona desde la primera línea.

**Primer login (A→B).** `POST /v1/profile/import` con el JSON completo y `If-Match: perfil.v1`. El servidor valida, marca `origin: "imported"`, asigna `device_id`, devuelve el perfil canónico con revisiones por ítem; el cliente sustituye su copia y empieza a empujar eventos. Tres detalles que se olvidan y duelen:

1. **Consentimiento explícito en la importación**, con granularidad: subir pins y reglas sí/no, subir historial sí/no. Las reglas de salud necesitan consentimiento específico (sección 6).
2. **`catalog_version`**: el perfil local referencia canónicos del servidor. Si el catálogo evoluciona (dos canónicos se fusionan), hay que remapear. Ten una tabla `canonical_alias(old_id, new_id, valid_from)` y aplica la migración al importar y en cada sync.
3. **Idempotencia del import**: si el usuario reintenta, no debe duplicar.

---

## 4. Dónde guardarlo en el navegador

| Almacén | Tamaño | Riesgo | Uso recomendado |
|---|---|---|---|
| `localStorage` | 5 MiB por origen | Evicción, borrado al limpiar datos, síncrono | Solo punteros: `device_id`, `rev`, flag de consentimiento. Nunca el perfil |
| `IndexedDB` | ~60 % del disco (Chrome) | Evicción LRU si el origen es *best-effort* | **El perfil y el log de eventos** |
| `navigator.storage.persist()` | — | Firefox pregunta; Chrome y Safari deciden en silencio según interacción | Pedirlo tras la primera lista completada |
| Fichero exportado | — | Manual | Copia de seguridad + portabilidad (art. 20) |

Los números y el comportamiento están en MDN [5]: la evicción es **por origen y todo o nada** (IndexedDB, Cache API, OPFS y Web Storage caen juntos); el valor por defecto es *best-effort*; y Safari, con la prevención de rastreo, **borra los datos creados por scripts de orígenes sin interacción en los últimos 7 días**. Ese último punto es el que hay que decir en voz alta: una PWA de lista de la compra que el usuario abre cada dos semanas puede perder el perfil en iOS.

Mitigaciones, en orden:

1. `persist()` tras la primera interacción significativa (no al cargar: Safari lo deniega sin engagement).
2. **Exportar/importar JSON** visible en ajustes ("Guardar copia"). Es la red de seguridad real y, de paso, cumple portabilidad.
3. Un **resumen compacto** (pins + reglas + top-20 defaults, ~20–50 KB) replicado en `localStorage`, que sobrevive a la evicción de IndexedDB en algunos escenarios y permite reconstruir lo esencial.
4. Si hay cuenta, el servidor es la copia de verdad y el cliente es caché. En A no hay red: por eso el punto 2 no es opcional.
5. Aviso explícito en la UI: "si borras los datos del navegador, se pierde el historial; guarda una copia".

No uses OPFS ni Cache API para esto: no aportan nada sobre IndexedDB y complican el borrado.

---

## 5. ¿Basta PostgreSQL para el filtrado colaborativo y los perfiles similares?

**Sí, para el alcance descrito, con margen de dos órdenes de magnitud.** Los números:

**Coocurrencia.** 10.000 usuarios × 30 listas × 40 líneas ≈ 12 M filas en `basket_item`. El self-join por `list_id` con índice en `(list_id, canonical_id)` tarda segundos; se materializa de noche en `item_cooccurrence(a, b, n)` con `n ≥ 5` y se sirve en memoria o en una tabla indexada. A 50 M filas sigue siendo batch nocturno viable. El punto de ruptura no es el tamaño, es **querer coocurrencia en línea con filtros arbitrarios**.

**Perfiles similares.** Vector de 384 dimensiones (features de canónicos comprados + cadenas + franjas; o un embedding de texto de la lista). `pgvector` 0.8.7 (1 de octubre de 2026) soporta PostgreSQL 13–18 [6]; HNSW con `m=16`, `ef_construction=64` da top-50 en milisegundos con 1 M de perfiles. Límite técnico a recordar: HNSW indexa hasta 2.000 dimensiones en `vector` y 4.000 en `halfvec`; irrelevante aquí. La 0.9.0 está sin publicar y elimina PG13/14, así que hoy la elección estable es 0.8.7.

**Umbrales concretos que justificarían un grafo:**

| Señal | Postgres puro | AGE a evaluar | Neo4j |
|---|---|---|---|
| Usuarios activos | < 20.000 | 20.000–200.000 | > 200.000 |
| Aristas de interacción | < 50 M | 50–500 M | > 500 M |
| Saltos por consulta | ≤ 2 | 2–3 frecuentes en línea | ≥ 3, o variables |
| Latencia p95 del recorrido | < 150 ms con CTE recursivo | 150–300 ms y subiendo | Requisito < 50 ms sostenido |
| Algoritmos | Ninguno | Ninguno | Louvain/Leiden, similaridad, FastRP |
| Equipo | 1–2 personas | 2–3 | Equipo con operación de graph DB |

Regla de decisión: **si el recorrido es batch nocturno, no necesitas grafo**; un CTE recursivo sobre 100 M de aristas tarda minutos y da igual. Solo compensa cuando el recorrido de varios saltos está en la ruta crítica de cada request.

**Estado actual de las piezas (verificado hoy):**

- **Apache AGE**: la compilación para PG18 es `PG18/v1.8.0-rc0`, marcada como *release candidate* en la página de releases [1]. GitHub la etiqueta como "Latest" por ser la más reciente, pero el sufijo `-rc0` indica que no es final. Las releases se publican por rama de major de PostgreSQL, lo que obliga a casar la build de la extensión con la versión del servidor. Madurez: extensión usable, comunidad pequeña, sin algoritmos de grafo, sin estadísticas para Cypher. **Para un TFG en noviembre de 2026, es un riesgo innecesario.**
- **Neo4j Community**: GPLv3 [2]; una sola base de datos estándar [3]; sin clustering, RBAC/LDAP ni backup en caliente (Enterprise) [4]. Para SaaS multiinquilino, la falta de RBAC y multi-base es un problema de arquitectura, no una limitación menor. La GPL no obliga en SaaS (no hay distribución), pero conviene revisarlo si algún día se distribuye.
- **pgvector**: 0.8.7 estable, PG13–18 [6].
- **PostgreSQL 18**: publicada el 25 de septiembre de 2025, con `uuidv7()` (útil para los `event_id`), E/S asíncrona y columnas generadas virtuales [7].

---

## 6. RGPD en el escenario B

### Qué obliga a hacer

Guardar preferencias e historial en el servidor convierte al operador en **responsable del tratamiento** con todas las consecuencias: registro de actividades (art. 30), información por capas (arts. 12–14), base jurídica por finalidad, contrato de encargado si hay proveedores (art. 28), y **evaluación de impacto (art. 35)** casi con seguridad, porque concurren perfilado sistemático, categoría especial de datos y escala.

**Bases jurídicas, por finalidad y por capa:**

| Tratamiento | Base | Comentario |
|---|---|---|
| Cuenta y preferencias explícitas | Art. 6.1.b (contrato) | Es el servicio que el usuario pide |
| Historial para calcular la cesta de *esa* lista | Art. 6.1.b | Necesario para la prestación |
| Historial para **perfilar y personalizar** más allá de la lista actual | Art. 6.1.f (interés legítimo) con LIA documentado, **o** consentimiento | La vía segura y recomendada es consentimiento granular |
| Reglas de salud ("sin lactosa") | **Art. 9.2.a (consentimiento explícito)** | No cabe interés legítimo |
| Recomendaciones entre usuarios | Consentimiento, opt-in, por defecto off | Es una finalidad nueva y no evidente |
| Analítica agregada | Interés legítimo, con anonimización real | Cuidado: agregar no es anonimizar |

**Sí, "sin lactosa" y "sin gluten" son datos de salud.** El TJUE ha adoptado una lectura amplia: son datos de categoría especial no solo los que revelan directamente una condición, sino los que permiten **inferirla**. En C-184/20 (asunto *OT*, 1 de agosto de 2022) el Tribunal extendió el art. 9 a datos que permiten deducir indirectamente información sobre la salud; en C-21/23 (*Lindenapotheke*, 4 de octubre de 2024) confirmó que los datos de compra de medicamentos de farmacia son datos de salud aunque no se nombre la enfermedad. **No he podido verificar el texto de ambas sentencias en esta sesión** (ver sección 8), así que trátalo como criterio consolidado pendiente de cita literal.

La consecuencia práctica: "sin lactosa" puede ser una preferencia de sabor, pero el diseño prudente es tratarla como salud. "Sin gluten" es aún más claro. Y lo más importante: **inferir "este usuario es intolerante" a partir de ocho compras de leche sin lactosa es exactamente el supuesto que el TJUE considera categoría especial**. Si infieres, procesas art. 9 sin base jurídica.

**Regla de diseño que se deriva:** no infieras atributos de salud. El motor de reglas solo acepta reglas dietéticas creadas explícitamente, con consentimiento explícito registrado (`consent_ref` en la fila), revocable de un toque, y separadas en su propia tabla con permisos más estrictos y auditoría de acceso. Si en el futuro quieres sugerir "¿añado sin lactosa?", hazlo como pregunta neutra sobre la lista ("¿alguna preferencia alimentaria?") y nunca como "hemos notado que…".

### Cómo diseñar para cumplir desde el principio

1. **Minimización real**: guarda `canonical_id` y `variant_id`, no el texto del ticket ni la marca del histórico. El historial de eventos es suficiente para aprender y mucho menos revelador que un recibo.
2. **Separación de capas** (la del apartado 0): las reglas de salud en tabla aparte, con RLS, cifrado a nivel de columna si es viable, y log de auditoría de lectura. Los derivados no se exportan ni se replican.
3. **Consentimiento granular y no condicionado** (art. 7.4): la app funciona sin ceder el historial; el consentimiento de salud es una casilla separada, con fecha, versión del texto y `consent_ref` enlazado desde la regla.
4. **Retención**: eventos crudos 24 meses, agregados anonimizados después; borrado en cascada ≤ 30 días; backups 30–90 días con el mismo compromiso documentado.
5. **Derechos**: acceso (15), rectificación (16), supresión (17), **portabilidad (20) con el mismo `perfil.v1`** que usa el sync —un solo formato, documentado, exportable en JSON—, limitación (18) y oposición (21) al perfilado por interés legítimo.
6. **Art. 22**: una recomendación que el usuario puede ignorar no produce "efectos significativos". Si algún día hay pedido automático o precios personalizados, cambia el análisis y necesitas intervención humana y explicación.
7. **Explicabilidad**: cada cesta debe poder responder "¿por qué esta tienda?" y "¿por qué este producto?". Es requisito de transparencia (arts. 13–15) y de confianza; y es otra razón para no meter preferencias en la función objetivo.
8. **Sin transferencias internacionales**: el LLM local evita enviar texto libre (que puede contener datos de salud) a un tercero. Si algún día se usa un LLM en la nube, es una cesión a encargado con art. 28 + SCC y, probablemente, un problema de art. 9.
9. **DPIA** antes del lanzamiento de B: perfilado + categoría especial + escala. La AEPD mantiene guías y criterios actualizados; su nota de 5 de noviembre de 2026 sobre entornos de tratamiento seguro de datos de salud con la autoridad helénica es un buen indicador de hacia dónde va el criterio [8].

---

## 7. Recomendación

### Escenario A (TFG): mínimo imprescindible

- **IndexedDB** con dos almacenes: `profile` (documento `perfil.v1`) y `events`. Nada de perfiles en servidor.
- **Explícitos**: pins, exclusiones de cadena, reglas dietéticas (con un aviso claro de que son datos de salud y se quedan en el dispositivo), λ y radio.
- **Aprendidos**: calculados al vuelo en la interpretación, con decaimiento; **no se persisten como verdad**. Si quieres persistirlos para velocidad, guárdalos como caché con `computed_at` y bórralos sin miedo.
- **Servidor**: solo recomendaciones anónimas (hash de la lista canónica + resultado), sin `device_id`, TTL 30 días, para el análisis de BI de la asignatura.
- **Export/import JSON** visible. Es tu seguro contra la evicción de Safari y tu historia de portabilidad.
- **Tests dorados** del algoritmo de aprendizaje sobre un fixture de eventos, para que la implementación de B sea la misma.

**Puede esperar**: embeddings, perfiles similares, sync multi-dispositivo, cuentas, cualquier grafo.

### Escenario B: mínimo imprescindible

- **PostgreSQL 18 + PostGIS + pgvector. Sin AGE ni Neo4j.**
- Esquema de la sección 3: `preference` (explícitos), `profile_event` (particionado), `profile_default` (derivado), `basket_item`, y `item_cooccurrence` como vista materializada nocturna con `n ≥ 5`.
- **pgvector con 384 dimensiones** para "perfiles similares", si el producto lo pide; no antes.
- Sync por HLC + eventos idempotentes + lápidas; import desde A con consentimiento granular.
- RGPD: consentimiento separado para salud y para recomendaciones entre usuarios (opt-in), DPIA, retención, export en `perfil.v1`, RLS.

**Puede esperar**: Apache AGE cuando exista una versión **estable** para PG18 y una consulta de 2–3 saltos en línea que el CTE recursivo no aguante por debajo de ~150 ms p95. Neo4j solo si aparecen comunidades de compradores o similaridad de grafo como funcionalidad central, con >200.000 usuarios y equipo para operarlo. Mientras tanto, el coste de añadirlos es una segunda copia de datos personales y una segunda ruta de borrado que puede fallar en silencio.

**Lo que no debe esperar**: la separación explícito/aprendido/eventos y el esquema versionado. Eso es lo que hace que A→B sea una importación y no una reescritura.

---

## 8. Qué he verificado y qué no

**Verificado por lectura directa:**
- Apache AGE: releases y ramas por major; `PG18/v1.8.0-rc0` como build para PG18, marcada *release candidate* [1].
- pgvector: 0.8.7 (2026-10-01), PG13–18; 0.9.0 sin publicar [6].
- Neo4j: Community GPLv3 [2]; una sola base de datos estándar en Community [3]; clustering, RBAC/LDAP y backup en caliente como capacidades Enterprise [4].
- PostgreSQL 18: 25 de septiembre de 2025, `uuidv7()`, E/S asíncrona [7].
- MDN: cuotas, evicción por origen, `persist()`, regla de 7 días de Safari [5].
- AEPD: nota de 5 de noviembre de 2026 sobre entornos de tratamiento seguro de datos de salud [8]; existencia de guías sobre perfilado y decisiones automatizadas en su catálogo [9].
- Texto del art. 9(1), 9(2)(a), 22(1) y 22(3) del RGPD [10].

**No verificado en esta sesión (cítalo con cautela):**
- El texto literal y los párrafos de **C-21/23** (*Lindenapotheke*, 4 de octubre de 2024) y **C-184/20** (*OT*, 1 de agosto de 2022). EUR-Lex e InfoCuria no renderizan su contenido a la herramienta de lectura. La descripción de su *holding* proviene de conocimiento previo, no de la fuente en esta sesión. Enlaces canónicos: [11] y [12].
- El contenido de las **Directrices 8/2020 del CEPD** sobre redes sociales (perfilado y datos inferidos): solo he podido confirmar su existencia y periodo de consulta [13].
- El año exacto de las releases de AGE (la página no lo muestra; el pie indica © 2026).
- Precios de Neo4j Enterprise (no públicos) y número de versión actual de Neo4j.
- Que la guía de perfilado de la AEPD diga algo concreto: el listado filtrado devolvió 503 en dos intentos.

---

## Fuentes

1. Apache AGE — releases: https://github.com/apache/age/releases
2. Neo4j — licensing: https://neo4j.com/licensing/
3. Neo4j Operations Manual — database administration (una sola BD en Community): https://neo4j.com/docs/operations-manual/current/database-administration/
4. Neo4j Operations Manual — introduction (CE vs EE): https://neo4j.com/docs/operations-manual/current/introduction/
5. MDN — Storage quotas and eviction criteria: https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria
6. pgvector — CHANGELOG: https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md
7. PostgreSQL 18 released (25-09-2025): https://www.postgresql.org/about/news/postgresql-18-released-3142/
8. AEPD — nota de prensa AEPD/Autoridad Helénica sobre entornos de tratamiento seguro (05-11-2026): https://www.aepd.es/prensa-y-comunicacion/notas-de-prensa/la-aepd-y-la-autoridad-helenica-de-proteccion-de-datos
9. AEPD — catálogo de guías: https://www.aepd.es/guias-y-herramientas/guias
10. RGPD, arts. 9 y 22: https://gdpr-info.eu/art-9-gdpr/ · https://gdpr-info.eu/art-22-gdpr/
11. TJUE, C-21/23 (*Lindenapotheke*), 04-10-2024: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62023CJ0021
12. TJUE, C-184/20 (*OT*), 01-08-2022: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62020CJ0184
13. CEPD — Directrices 08/2020 sobre segmentación de usuarios de redes sociales: https://www.edpb.europa.eu/public-consultations/guidelines-082020-on-the-targeting-of-social-media-users_en
