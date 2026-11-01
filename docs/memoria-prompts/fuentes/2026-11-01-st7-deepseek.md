# Respuesta original de DeepSeek — Señal de Tiempo 7

- Fecha: 1 de noviembre de 2026
- Modelo: deepseek-v4.1-flash a través de OpenCode Go (Claude Code en modo no interactivo como cliente, carpeta vacía, sin contexto previo, con WebSearch y WebFetch; 32 turnos, 450 s). La respuesta llegó en dos bloques, que se reproducen seguidos.

## Prompt

```text
Actúa como Arquitecto de Datos especializado en sistemas transaccionales y Business Intelligence sobre PostgreSQL. Diseño el modelo de datos de un MVP académico (asignatura de Sistemas de Información de Gestión y Business Intelligence; uso personal, la aplicación no se publica) que recomienda en qué supermercados de León (España) comprar una lista para minimizar coste + lambda * minutos de desplazamiento, con un máximo de 3 tiendas.

Decisiones ya tomadas:
- PostgreSQL único con pgvector (embeddings de productos), PostGIS (ubicación de tiendas) y particionado nativo para el histórico de precios. TimescaleDB solo si las agregaciones lo justifican.
- Modelo de producto canónico: cada producto de cada cadena se asigna a un producto canónico (vecinos más cercanos sobre embeddings con umbral de confianza, más reglas); los productos con el mismo canónico son equivalentes (unión de un solo salto). Las asignaciones dudosas van a una cola de revisión. Formato, cantidad, variante y marca se extraen con reglas y se guardan como columnas.
- Recogida automática y periódica (al menos diaria) con un navegador real: 7 cadenas con tienda online (Mercadona unos 4.500 productos, Carrefour unos 26.000; el resto, entre medias) más ofertas de Aldi en HTML y folletos de Lidl y E.Leclerc. Se guarda cada respuesta en bruto (fecha y hash) para reprocesar.
- El surtido depende de la zona (código postal o almacén); en las muestras, el precio no cambia entre zonas, pero está por confirmar.
- Promociones: precio rebajado con precio anterior, NxM (3x2), segunda unidad al X %, descuentos por volumen, precios con tarjeta de fidelización (Club) y cupones públicos, cada una con su vigencia. Llegan de la web o de folletos y pueden aplicarse a un producto, a varios o a una categoría.
- Tiendas de OpenStreetMap (ubicación, cadena, horario cuando lo hay), ligadas a la zona de su cadena.
- Sin cuentas de usuario: listas e historial personal viven en el navegador. En el servidor solo se guardan las recomendaciones de forma anónima con sus entradas y la fecha de los datos usados, para poder recalcularlas (la ubicación, redondeada o no guardada).
- El recomendador calcula el precio efectivo de cada producto en la fecha de compra (último precio + promociones vigentes según la cantidad y las tarjetas del usuario) y un optimizador elige la cesta.

Requisitos de BI: evolución de precios por producto canónico, categoría y cadena; marca blanca frente a marca de fabricante por categoría y cadena; índice de precios de una cesta de referencia por cadena a lo largo del tiempo; frecuencia y profundidad de las promociones por cadena y categoría; ahorro de las recomendaciones; analítica de uso anónima.

Preguntas:
1. Modelo transaccional: entidades, claves y columnas principales (producto canónico, producto de cadena, observación de precio, promoción, tienda, zona, recomendación, ejecución de ingesta, cola de revisión). Incluye un esbozo de DDL de las tablas centrales.
2. Histórico de precios: ¿una foto diaria por producto y zona o solo los cambios con intervalos de validez (tstzrange/daterange, estilo SCD tipo 2)? Estima el volumen anual de cada opción y recomienda una, con su particionado e índices.
3. Promociones: ¿tabla única con parámetros en JSONB, tablas por tipo o un modelo de reglas? Cómo representar a qué productos aplica y cómo calcular el precio efectivo para una cantidad y una fecha de forma determinista.
4. Granularidad y creación del producto canónico: qué nivel de detalle (¿"leche semidesnatada 1 L" o solo "leche semidesnatada"?), cómo tratar formatos y packs, y cómo crear el catálogo canónico inicial sin trabajo manual excesivo.
5. Separación OLTP/OLAP para el BI: ¿esquema en estrella en el mismo PostgreSQL (esquema aparte, vistas materializadas, refresco tras la ingesta) o un motor aparte como DuckDB? Propón hechos, dimensiones (con su tipo de lentitud de cambio) y granularidad de cada hecho, y qué herramienta de BI gratuita encaja.
6. Riesgos del modelo y umbrales que harían cambiar de diseño.

Da una recomendación concreta y justificada para el MVP, con lo mínimo necesario y lo que puede esperar. Antes de responder, busca en internet información actual (hoy es 1 de noviembre de 2026) sobre las versiones vigentes de PostgreSQL, pgvector y PostGIS y sobre herramientas de BI gratuitas, y cita las fuentes con URL. Indica qué no has podido verificar. No ejecutes comandos ni modifiques archivos: usa solo la búsqueda web y la lectura de páginas.
```

## Respuesta

He consultado las páginas oficiales (el buscador no estaba disponible en esta sesión; he usado lectura directa de páginas y solo fuentes primarias o de referencia). Antes de entrar en el modelo, fijo las versiones que condicionan el DDL.

---

## 0. Resumen de decisiones

| Tema | Recomendación para el MVP |
|---|---|
| Motor | PostgreSQL 18.6 + pgvector 0.8.7 + PostGIS 3.7.0, una sola instancia |
| Histórico de precios | **Solo cambios** (SCD2 cerrado) + tabla `price_current`; partición anual por `valid_from` |
| Promociones | **Tabla única** con columnas tipadas + JSONB residual + tabla de objetivos polimórfica; sin motor de reglas |
| Producto canónico | Brand-agnóstico para commodities, talla exacta, packs como canónicos separados; bootstrap desde el catálogo más limpio + kNN |
| BI | Mismo PostgreSQL, esquema `bi`, hechos **agregados por categoría** (no por producto×día); Metabase OSS |
| TimescaleDB | No en el MVP |
| DuckDB | No en el MVP; sí como escape para analítica ad hoc si los hechos crecen |

La idea central: **el OLTP guarda intervalos de precio, no fotos; el OLAP guarda agregados, no el detalle producto×día**. Así el histórico real ocupa dos órdenes de magnitud menos y el BI sigue respondiendo.

---

## 1. Versiones vigentes a 1 de noviembre de 2026

| Componente | Versión | Fecha | Nota |
|---|---|---|---|
| PostgreSQL | **18.6** | 13 ago 2026 | Última estable. 17.11 y 16.15 también soportadas. 14 termina el 12 nov 2026 [1][2] |
| PostgreSQL 19 | RC 1 | 15 oct 2026 | Aún no es GA; no usar en el MVP [1] |
| pgvector | **0.8.7** | 1 oct 2026 | Soporta PG 13+; 0.9.0 aún sin publicar [3][4] |
| PostGIS | **3.7.0** | 30 oct 2026 | Muy reciente; 3.6.4 (jun 2026) es la opción conservadora [5][6] |
| Metabase | **65.2** (`v0.65.2`) | 30 oct (año no mostrado) | Edición OSS bajo AGPL [7][8] |
| Apache Superset | **6.1.0** estable; 7.0.0rc2 en preparación | 13 may (año no mostrado) | Apache 2.0 [9][10] |
| Grafana | **13.3.0** | 27 oct 2026 | Orientado a observabilidad, no a BI de negocio [11] |
| DuckDB | **2.0.0** "Cyanoptera" | 21 oct 2026 | Salto de major; revisar breaking changes antes de adoptarlo [12][13] |

Recomendación de pinning: **PG 18.6 + pgvector 0.8.7 + PostGIS 3.7.0**. Si el TFG se entrega en semanas y quieres evitar sorpresas, PostGIS 3.6.4 es perfectamente válido; 3.7.0 lleva dos días publicado.

**No he podido verificar:** el año exacto de las releases de Metabase y Superset (GitHub no lo muestra en la página consultada); la licencia de Grafana en su página de releases (AGPLv3 desde 2021, pero no lo he releído); la fecha GA de PostgreSQL 19; si pgvector 0.9.0 llegará antes de cerrar el TFG; la compatibilidad explícita de PostGIS 3.7.0 con PG 18; y, sobre todo, si las webs de las cadenas exponen EAN y si el precio varía por zona. EAN y zona son las dos incógnitas que más afectan al diseño.

---

## 2. Modelo transaccional

### 2.1 Entidades y relaciones

```
chain 1─N zone 1─N store
chain 1─N chain_product N─1 canonical_product N─1 category
                                   │
                                   └─ brand (opcional, si brand_locked)
chain_product 1─N price_current (por zone)
chain_product 1─N price_history (por zone, intervalos cerrados)
chain 1─N promotion 1─N promotion_target (producto | canónico | categoría | marca)
                    1─N promotion_zone
chain 1─N ingest_run 1─N raw_response
chain_product 1─N match_review
recommendation 1─N recommendation_item
```

Convenciones:

- **Dinero**: `numeric(10,2)` para precio de venta y `numeric(12,4)` para €/kg o €/L. Nunca `float`.
- **Tiempo**: `timestamptz` en UTC; los `date_key` del BI se calculan en `Europe/Madrid`.
- **Claves**: `bigint identity` para dimensiones internas; `uuidv7()` para identificadores públicos/anónimos (PG 18 lo trae nativo) [14].
- **Vigencia**: intervalos `[valid_from, valid_to)` **siempre cerrados** en histórico; el precio abierto vive en `price_current`. Esto evita la restricción de exclusión sobre tablas particionadas y los problemas de solapamiento entre particiones.
- **Zona**: cada cadena tiene una zona centinela `__chain__` (`kind='chain'`) para precios únicos de cadena. Si mañana el precio varía por CP, se añaden zonas reales sin cambiar el esquema.

### 2.2 DDL de las tablas centrales

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------- Red de tiendas ----------
CREATE TABLE chain (
  id           smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  slug         text NOT NULL UNIQUE,                 -- 'mercadona'
  name         text NOT NULL,
  coverage     text NOT NULL DEFAULT 'full'
               CHECK (coverage IN ('full','partial')), -- Aldi/Lidl: partial
  loyalty_name text,
  has_online   boolean NOT NULL DEFAULT true
);

CREATE TABLE zone (
  id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_id smallint NOT NULL REFERENCES chain(id),
  code     text NOT NULL,                            -- CP, almacén o '__chain__'
  kind     text NOT NULL CHECK (kind IN ('postal_code','warehouse','chain')),
  geom     geometry(MultiPolygon,4326),
  UNIQUE (chain_id, code),
  UNIQUE (id, chain_id)                              -- para FK compuesta desde store
);

CREATE TABLE store (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_id      smallint NOT NULL REFERENCES chain(id),
  zone_id       integer NOT NULL,
  osm_type      char(1) CHECK (osm_type IN ('n','w','r')),
  osm_id        bigint,
  name          text,
  geom          geography(Point,4326) NOT NULL,
  address       jsonb,
  opening_hours jsonb,
  is_active     boolean NOT NULL DEFAULT true,
  FOREIGN KEY (zone_id, chain_id) REFERENCES zone(id, chain_id)
);
CREATE UNIQUE INDEX store_osm_uq ON store (osm_type, osm_id) WHERE osm_id IS NOT NULL;
CREATE INDEX store_geom_gix ON store USING gist (geom);
CREATE INDEX store_zone_ix ON store (zone_id) WHERE is_active;

-- ---------- Taxonomía y marcas ----------
CREATE TABLE category (
  id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  parent_id integer REFERENCES category(id),
  path      text NOT NULL UNIQUE,      -- 'lacteos/leche/semidesnatada'
  name      text NOT NULL,
  level     smallint NOT NULL CHECK (level BETWEEN 1 AND 4)
);

-- Cierre transitivo para "la promo aplica a toda la categoría"
CREATE TABLE category_closure (
  descendant_id integer NOT NULL REFERENCES category(id),
  ancestor_id   integer NOT NULL REFERENCES category(id),
  depth         smallint NOT NULL,
  PRIMARY KEY (descendant_id, ancestor_id)
);

CREATE TABLE brand (
  id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name             text NOT NULL UNIQUE,
  owner_chain_id   smallint REFERENCES chain(id),    -- marca blanca
  is_private_label boolean GENERATED ALWAYS AS (owner_chain_id IS NOT NULL) STORED
);

-- ---------- Producto canónico ----------
CREATE TABLE canonical_product (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name            text NOT NULL,                     -- 'leche semidesnatada'
  category_id     integer NOT NULL REFERENCES category(id),
  variant_key     text NOT NULL DEFAULT '',          -- 'semidesnatada|sin_lactosa'
  brand_locked    boolean NOT NULL DEFAULT false,
  brand_id        integer REFERENCES brand(id),
  base_quantity   numeric(12,3) NOT NULL CHECK (base_quantity > 0), -- contenido total
  base_unit       text NOT NULL CHECK (base_unit IN ('g','ml','ud')),
  pack_count      smallint NOT NULL DEFAULT 1 CHECK (pack_count >= 1),
  packaging       text,                              -- brick, botella, lata (no entra en la clave)
  embedding       vector(1024),
  embedding_model text,
  status          text NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','merged','retired')),
  merged_into_id  bigint REFERENCES canonical_product(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (brand_locked = (brand_id IS NOT NULL)),
  CHECK (merged_into_id IS NULL OR merged_into_id <> id)
);
CREATE UNIQUE INDEX canonical_natural_uq
  ON canonical_product (category_id, variant_key, base_quantity, base_unit,
                        pack_count, COALESCE(brand_id, 0))
  WHERE status = 'active';
CREATE INDEX canonical_embedding_hnsw ON canonical_product
  USING hnsw (embedding vector_cosine_ops)
  WHERE status = 'active' AND embedding IS NOT NULL;

-- ---------- Producto de cadena ----------
CREATE TABLE chain_product (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_id         smallint NOT NULL REFERENCES chain(id),
  external_id      text NOT NULL,
  name_raw         text NOT NULL,
  url              text,
  image_url        text,
  category_raw     text,
  brand_id         integer REFERENCES brand(id),
  brand_raw        text,
  variant_key      text,
  format_raw       text,                             -- '1 L', 'pack 6 x 1,5 L'
  base_quantity    numeric(12,3),
  base_unit        text,
  pack_count       smallint,
  canonical_id     bigint REFERENCES canonical_product(id),
  match_status     text NOT NULL DEFAULT 'pending'
                   CHECK (match_status IN ('pending','auto','review','confirmed','rejected')),
  match_method     text CHECK (match_method IN ('ean','rule','embedding','manual','seed')),
  match_confidence numeric(4,3) CHECK (match_confidence BETWEEN 0 AND 1),
  embedding        vector(1024),
  embedding_model  text,
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  is_active        boolean NOT NULL DEFAULT true,
  UNIQUE (chain_id, external_id),
  CHECK (canonical_id IS NULL OR match_status IN ('auto','confirmed'))
);
CREATE INDEX chain_product_canonical_ix ON chain_product (canonical_id)
  WHERE canonical_id IS NOT NULL AND is_active;
CREATE INDEX chain_product_embedding_hnsw ON chain_product
  USING hnsw (embedding vector_cosine_ops) WHERE embedding IS NOT NULL;

-- Surtido por zona
CREATE TABLE chain_product_zone (
  chain_product_id bigint NOT NULL REFERENCES chain_product(id),
  zone_id          integer NOT NULL REFERENCES zone(id),
  is_available     boolean NOT NULL,
  first_seen_at    timestamptz NOT NULL DEFAULT now(),
  last_seen_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chain_product_id, zone_id)
);
```

```sql
-- ---------- Ingesta y evidencia ----------
CREATE TABLE ingest_run (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_id        smallint REFERENCES chain(id),
  zone_id         integer REFERENCES zone(id),
  kind            text NOT NULL CHECK (kind IN ('catalog','prices','promotions','flyer','stores')),
  status          text NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','ok','partial','failed')),
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  scraper_version text NOT NULL,
  items_seen      integer NOT NULL DEFAULT 0,
  prices_changed  integer NOT NULL DEFAULT 0,
  errors          integer NOT NULL DEFAULT 0,
  error           jsonb
);

CREATE TABLE raw_response (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ingest_run_id bigint NOT NULL REFERENCES ingest_run(id),
  url           text NOT NULL,
  fetched_at    timestamptz NOT NULL,
  http_status   smallint,
  content_type  text,
  content_hash  bytea NOT NULL,        -- sha256 del cuerpo
  storage_uri   text NOT NULL,         -- file:///... o s3://...
  size_bytes    bigint,
  UNIQUE (url, content_hash)           -- dedupe; el cuerpo se guarda una vez por hash
);
```

```sql
-- ---------- Precio actual e histórico ----------
CREATE TABLE price_current (
  chain_product_id bigint NOT NULL REFERENCES chain_product(id),
  zone_id          integer NOT NULL REFERENCES zone(id),
  price            numeric(10,2) NOT NULL CHECK (price >= 0),
  price_per_unit   numeric(12,4),      -- €/kg o €/L
  currency         char(3) NOT NULL DEFAULT 'EUR',
  valid_from       timestamptz NOT NULL,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  ingest_run_id    bigint NOT NULL REFERENCES ingest_run(id),
  PRIMARY KEY (chain_product_id, zone_id)
);

CREATE TABLE price_history (
  id               bigint GENERATED ALWAYS AS IDENTITY,
  chain_product_id bigint NOT NULL REFERENCES chain_product(id),
  zone_id          integer NOT NULL REFERENCES zone(id),
  price            numeric(10,2) NOT NULL CHECK (price >= 0),
  price_per_unit   numeric(12,4),
  currency         char(3) NOT NULL DEFAULT 'EUR',
  valid_from       timestamptz NOT NULL,
  valid_to         timestamptz NOT NULL,          -- siempre cerrado, exclusivo
  observed_at      timestamptz NOT NULL,
  ingest_run_id    bigint NOT NULL REFERENCES ingest_run(id),
  PRIMARY KEY (id, valid_from),                   -- incluye la clave de partición
  CHECK (valid_to > valid_from)
) PARTITION BY RANGE (valid_from);

CREATE TABLE price_history_2026 PARTITION OF price_history
  FOR VALUES FROM ('2026-01-01 00:00:00+01') TO ('2027-01-01 00:00:00+01');
CREATE TABLE price_history_2027 PARTITION OF price_history
  FOR VALUES FROM ('2027-01-01 00:00:00+01') TO ('2028-01-01 00:00:00+01');

-- Búsqueda "precio vigente en t": valid_from <= t, orden descendente, limit 1
CREATE UNIQUE INDEX price_history_lookup_uq
  ON price_history (chain_product_id, zone_id, valid_from)
  INCLUDE (valid_to, price, price_per_unit);
```

El contrato de escritura es una función transaccional `record_price_change(cp, zone, new_price, at, run)`:

1. bloquea la fila de `price_current`;
2. si el precio no cambia, solo actualiza `updated_at`;
3. si cambia, inserta en `price_history` el intervalo **anterior** `[current.valid_from, at)` y actualiza `price_current` a `(new_price, at)`.

Así el histórico contiene solo intervalos cerrados, no hay solapamientos y la unicidad `(producto, zona, valid_from)` es global porque `valid_from` es la clave de partición. No hace falta `btree_gist` ni restricciones de exclusión.

```sql
-- ---------- Promociones ----------
CREATE TABLE promotion (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_id         smallint NOT NULL REFERENCES chain(id),
  kind             text NOT NULL CHECK (kind IN
                   ('unit_price','percent_off','nxm','second_unit',
                    'volume_tier','loyalty_price','coupon')),
  title            text NOT NULL,
  valid            tstzrange NOT NULL,
  requires_loyalty boolean NOT NULL DEFAULT false,
  coupon_code      text,
  stackable        boolean NOT NULL DEFAULT false,
  applied_in_price boolean NOT NULL DEFAULT false,  -- el precio observado ya la incluye
  priority         smallint NOT NULL DEFAULT 100,
  reference_price  numeric(10,2),                   -- precio anterior / de referencia
  promo_price      numeric(10,2),
  percent          numeric(5,2) CHECK (percent BETWEEN 0 AND 100),
  amount           numeric(10,2) CHECK (amount >= 0),
  buy_n            smallint CHECK (buy_n >= 2),
  pay_m            smallint CHECK (pay_m >= 1),
  tiers            jsonb CHECK (tiers IS NULL OR jsonb_typeof(tiers) = 'array'),
  source           text NOT NULL CHECK (source IN ('web','flyer','manual')),
  raw_response_id  bigint REFERENCES raw_response(id),
  confidence       numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
  status           text NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','expired','rejected')),
  CHECK (NOT isempty(valid)),
  CHECK (buy_n IS NULL OR pay_m IS NULL OR pay_m <= buy_n),
  CHECK (kind <> 'nxm' OR (buy_n IS NOT NULL AND pay_m IS NOT NULL)),
  CHECK (kind NOT IN ('percent_off','second_unit') OR percent IS NOT NULL),
  CHECK (kind NOT IN ('unit_price','loyalty_price') OR promo_price IS NOT NULL),
  CHECK (kind <> 'volume_tier' OR tiers IS NOT NULL)
);

CREATE TABLE promotion_target (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  promotion_id     bigint NOT NULL REFERENCES promotion(id) ON DELETE CASCADE,
  target_type      text NOT NULL
                   CHECK (target_type IN ('chain_product','canonical','category','brand')),
  chain_product_id bigint REFERENCES chain_product(id),
  canonical_id     bigint REFERENCES canonical_product(id),
  category_id      integer REFERENCES category(id),
  brand_id         integer REFERENCES brand(id),
  CHECK (
    (target_type = 'chain_product') = (chain_product_id IS NOT NULL) AND
    (target_type = 'canonical')     = (canonical_id IS NOT NULL) AND
    (target_type = 'category')      = (category_id IS NOT NULL) AND
    (target_type = 'brand')         = (brand_id IS NOT NULL)
  )
);
CREATE INDEX promotion_target_promo_ix ON promotion_target (promotion_id);
CREATE INDEX promotion_target_cp_ix ON promotion_target (chain_product_id)
  WHERE chain_product_id IS NOT NULL;
CREATE INDEX promotion_target_canon_ix ON promotion_target (canonical_id)
  WHERE canonical_id IS NOT NULL;
CREATE INDEX promotion_target_cat_ix ON promotion_target (category_id)
  WHERE category_id IS NOT NULL;

CREATE TABLE promotion_zone (
  promotion_id bigint NOT NULL REFERENCES promotion(id) ON DELETE CASCADE,
  zone_id      integer NOT NULL REFERENCES zone(id),
  PRIMARY KEY (promotion_id, zone_id)
);
```

```sql
-- ---------- Revisión de matching ----------
CREATE TABLE match_review (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_product_id       bigint NOT NULL REFERENCES chain_product(id),
  suggested_canonical_id bigint REFERENCES canonical_product(id),
  confidence             numeric(4,3),
  candidates             jsonb NOT NULL,     -- top-k: [{canonical_id, distance, reason}]
  reason                 text,
  status                 text NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open','accepted','reassigned','created_new','rejected')),
  created_at             timestamptz NOT NULL DEFAULT now(),
  resolved_at            timestamptz,
  resolved_by            text,
  note                   text
);
CREATE UNIQUE INDEX match_review_open_uq
  ON match_review (chain_product_id) WHERE status = 'open';

CREATE TABLE product_match (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chain_product_id bigint NOT NULL REFERENCES chain_product(id),
  canonical_id     bigint NOT NULL REFERENCES canonical_product(id),
  method           text NOT NULL,
  confidence       numeric(4,3),
  model_version    text,
  decided_at       timestamptz NOT NULL DEFAULT now(),
  decided_by       text,
  is_current       boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX product_match_current_uq
  ON product_match (chain_product_id) WHERE is_current;
```

```sql
-- ---------- Recomendaciones anónimas ----------
CREATE TABLE recommendation (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  created_at     timestamptz NOT NULL DEFAULT now(),
  session_id     uuid NOT NULL,                  -- aleatorio, vive en el navegador
  origin_cell    text,                           -- H3 r8 / geohash-7; nunca coordenada exacta
  origin_geom    geography(Point,4326),          -- opcional, redondeada ~500 m
  lambda         numeric(8,4) NOT NULL CHECK (lambda >= 0),
  max_stores     smallint NOT NULL DEFAULT 3 CHECK (max_stores BETWEEN 1 AND 3),
  basket         jsonb NOT NULL,                 -- [{canonical_id, qty}]
  loyalty_chains smallint[] NOT NULL DEFAULT '{}',
  coupons        text[] NOT NULL DEFAULT '{}',
  data_as_of     timestamptz NOT NULL,
  engine_version text NOT NULL,
  total_cost     numeric(10,2) NOT NULL,
  baseline_cost  numeric(10,2),
  travel_minutes numeric(6,1),
  savings        numeric(10,2)
                 GENERATED ALWAYS AS (baseline_cost - total_cost) STORED,
  result         jsonb NOT NULL                  -- asignación y justificación
);

CREATE TABLE recommendation_item (
  recommendation_id uuid NOT NULL REFERENCES recommendation(id) ON DELETE CASCADE,
  line_no           smallint NOT NULL,
  canonical_id      bigint NOT NULL REFERENCES canonical_product(id),
  qty               numeric(10,3) NOT NULL CHECK (qty > 0),
  store_id          integer REFERENCES store(id),
  chain_product_id  bigint REFERENCES chain_product(id),
  unit_price        numeric(10,2) NOT NULL,
  line_total        numeric(10,2) NOT NULL,
  promotion_ids     bigint[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (recommendation_id, line_no)
);
```

**Nota sobre privacidad:** `session_id` es un UUID aleatorio del navegador, no una cuenta. No se guarda IP ni la coordenada exacta; `origin_cell` permite recalcular con precisión suficiente y agregar analítica por zona. `basket` guarda solo `canonical_id + qty`, sin nombres ni identidad.

---

## 3. Histórico de precios: ¿foto diaria o solo cambios?

### 3.1 Estimación de volumen

Supuestos: **100.000 series** (producto de cadena × zona; redondeo conservador para 7 cadenas y 1-2 zonas por cadena) y una fila de histórico de ~100-110 bytes con sus índices.

| Opción | Filas/año | Tamaño aproximado/año |
|---|---:|---:|
| Foto diaria, 100k series | **36,5 M** | 4-6 GB tabla + 4-6 GB índices ≈ **8-12 GB** |
| Foto diaria, 200k series | **73 M** | ≈ **16-24 GB** |
| Solo cambios, 1 %/día | **365k** | ≈ 40 MB + 60 MB índices |
| Solo cambios, 3 %/día | **1,1 M** | ≈ 120 MB + 180 MB índices |
| Solo cambios, 5 %/día | **1,83 M** | ≈ 200 MB + 300 MB índices |

La foto diaria es 100× más grande y no aporta nada que no se pueda reconstruir: el intervalo ya dice qué precio estaba vigente cualquier día. Además, la foto diaria obliga a escribir 36-73 M de filas al año para detectar cambios que son el 1-5 %.

### 3.2 Recomendación

**Solo cambios con intervalos de validez, más una tabla `price_current`.** Es un SCD tipo 2, pero partido en dos:

- `price_history`: append-only, intervalos cerrados `[valid_from, valid_to)`. Se escribe **solo cuando el precio cambia**.
- `price_current`: una fila por `(chain_product_id, zone_id)` con el precio vigente y `valid_from`. Es la que lee el recomendador; 100k filas, siempre en caché.
- `price_as_of(cp, zone, t)` consulta primero `price_current` y, si `t` es anterior, `price_history`.

Ventajas frente a la foto:

- 50-100× menos filas.
- El histórico es la fuente de verdad de los cambios, no una repetición diaria.
- Las correcciones se hacen cerrando/insertando intervalos, no reescribiendo millones de fotos.
- Los gráficos de evolución son directamente los escalones del intervalo.

Riesgo que hay que cubrir: **ausencia de observación ≠ precio sin cambios**. Si un día falla el scraper, el intervalo sigue abierto y el precio se arrastra. Por eso `ingest_run` registra cobertura y el recomendador debe rechazar datos con `data_as_of` mayor de 36 h. Si un producto desaparece del surtido, se cierra su intervalo en `price_current` y se marca `is_active=false`.

### 3.3 Particionado e índices

- **Partición `RANGE (valid_from)` anual** para el MVP. Con 1-2 M filas/año, una sola partición por año es suficiente y evita el coste de planificación. Si superas ~10 M cambios/año, pasa a mensual.
- La clave primaria `(id, valid_from)` incluye la clave de partición, como exige PostgreSQL [15].
- Índice único `(chain_product_id, zone_id, valid_from) INCLUDE (valid_to, price, price_per_unit)`: resuelve el "as-of" con un `ORDER BY valid_from DESC LIMIT 1` y evita ir a la tabla.
- Índice en `price_current (zone_id)` si consultas por zona; la PK ya cubre producto+zona.
- No hace falta BRIN ni GiST: el patrón de acceso es siempre por producto y fecha, no por rango amplio.
- `pg_partman` es opcional; con dos particiones anuales creadas a mano y una función `ensure_price_partition(year)` vas sobrado.

**TimescaleDB no se justifica.** A 1-2 M filas/año, las continuous aggregates y la compresión columnar no compensan la dependencia, la licencia TSL de algunas funciones y la pérdida de portabilidad. Revisar si el histórico supera 50 M filas o si necesitas refresco sub-minuto de agregados.

---

## 4. Promociones

### 4.1 Modelo: tabla única con columnas tipadas, no motor de reglas

Tres opciones:

1. **JSONB puro**: flexible, pero el BI no puede agregar "profundidad media por tipo" sin extraer claves, y no hay validación.
2. **Tabla por tipo**: 7 tablas y 7 uniones cada vez que calculas el precio efectivo. Coste de consulta y de mantenimiento alto para un MVP.
3. **Tabla única + columnas tipadas + JSONB residual**: es la recomendada.

`promotion.kind` identifica la mecánica; las columnas `percent`, `amount`, `promo_price`, `buy_n`, `pay_m`, `reference_price` cubren los casos frecuentes y son agregables; `tiers` (JSONB) guarda los escalones de volumen, que son pocos y no se agregan por BI. Los `CHECK` impiden combinaciones inválidas. No hay motor de reglas: la lógica de aplicación vive en una función SQL determinista y versionada.

Añadir `applied_in_price` es importante: algunas webs ya muestran el precio rebajado como precio de shelf. Si la promo es un descuento instantáneo y el precio observado ya lo incluye, aplicarla otra vez produce un precio efectivo falso. La política:

- `unit_price`, `percent_off`, `loyalty_price` → normalmente `applied_in_price=true`; sirven para BI y para "precio anterior".
- `nxm`, `second_unit`, `volume_tier`, `coupon` → `applied_in_price=false`; se aplican siempre sobre el precio base porque dependen de la cantidad.

### 4.2 ¿A qué productos aplica?

`promotion_target` con cuatro tipos: producto de cadena, canónico, categoría y marca. Para categorías se usa `category_closure`, de modo que una promo en `lacteos/leche` aplica a todas sus hojas. La restricción `CHECK` garantiza exactamente un objetivo por fila.

- Producto de cadena: el caso normal de la web.
- Canónico: una promo de folleto que dice "leche semidesnatada 1 L" y se resuelve contra el canónico; luego se aplica a todos los productos de cadena de ese canónico en la cadena.
- Categoría: "todos los yogures".
- Marca: "toda la marca Hacendado".

`promotion_zone` restringe por zona; si no hay filas, aplica a toda la cadena. `promotion_zone` vacío + zona `__chain__` cubre el caso de precio único.

### 4.3 Precio efectivo determinista

Firma:

```sql
effective_price(
  p_chain_product bigint,
  p_zone          integer,
  p_at            timestamptz,
  p_qty           integer,
  p_cards         text[],      -- programas de fidelización del usuario
  p_coupons       text[]
) RETURNS TABLE (unit_price numeric, line_total numeric, applied_promotion_ids bigint[])
```

Algoritmo:

1. **Precio base**: `price_as_of(p_chain_product, p_zone, p_at)`. Si no hay intervalo, el producto no está disponible y se devuelve `NULL`.
2. **Candidatas**: promociones de la misma cadena con `valid @> p_at`, zona compatible, objetivo que case con producto/canónico/categoría ancestro/marca, y requisitos satisfechos (`requires_loyalty` → `p_cards` contiene el programa; `coupon_code` → `p_coupons` lo contiene).
3. **Coste de línea por mecánica**, sobre `qty`:
   - `unit_price` / `loyalty_price`: `promo_price × qty`.
   - `percent_off`: `base × qty × (1 - percent/100)`.
   - `nxm`: `pay_units = qty - floor(qty / buy_n) × (buy_n - pay_m)`; `base × pay_units`.
   - `second_unit`: `pairs = floor(qty/2)`; `pairs × (base + base × (1 - percent/100)) + (qty % 2) × base`.
   - `volume_tier`: elige el tier con `min_qty <= qty` más alto; `tier_unit_price × qty`.
   - `coupon`: `percent` o `amount` sobre el coste de línea, una vez.
4. **Selección**: la promo con menor `line_total`; desempate por `priority` y luego `id`. Si `applied_in_price=true` y la mecánica es de unidad, no se vuelve a aplicar (su efecto ya está en el base), pero sí se registra para BI.
5. **Resultado**: `unit_price = line_total / qty`, `applied_promotion_ids`.

La determinación es total: todas las entradas son explícitas (`at`, `qty`, tarjetas, cupones), no se usa `now()` ni `random()`, y el desempate es estable. Guárdalo en `engine_version` y en `recommendation.result` para poder reproducir una recomendación.

Política de apilamiento para el MVP: **no apilar**. Se elige la mejor mecánica por línea. `stackable=true` queda reservado para una fase posterior (por ejemplo, precio de socio + cupón), con un orden definido: mecánica base → precio de socio → cupón al final. Documentar la no-apilabilidad es más honesto que un motor que produce resultados inesperados.

---

## 5. Granularidad y creación del

producto canónico

### 5.1 Nivel de detalle

**Canónico = "unidad de sustitución realista": tipo de producto + variante + contenido neto + unidad + nº de envases**, no la marca para commodities.

- Correcto: `leche semidesnatada | 1.000 ml | pack 1`.
- Incorrecto: `leche semidesnatada` a secas, porque 1 L, 1,5 L y el pack de 6 no son intercambiables ni tienen el mismo €/L.
- Incorrecto para commodities: `leche semidesnatada Pascual 1 L` como canónico, porque rompe la comparación entre cadenas y multiplica el catálogo: acabarías con ~100k canónicos en vez de ~12-18k.
- Excepción: `brand_locked=true` cuando la marca **es** el producto (cola, snacks de marca, cerveza) o cuando el matching brand-agnóstico genera errores graves.

La marca se guarda en `chain_product.brand_id` (y en `brand.is_private_label`), no en el canónico. Eso permite el informe "marca blanca vs fabricante" sin contaminar la unidad de comparación de precios.

### 5.2 Formatos, packs y variantes

- Normaliza siempre a unidad base: `g`, `ml`, `ud`. `base_quantity` es el contenido **total**; `base_unit` la unidad; `pack_count` el número de envases. Para un pack 6×1,5 L: `base_quantity=9000`, `base_unit='ml'`, `pack_count=6`. Para una botella de 9 L: `9000 ml`, `pack_count=1`. Son canónicos distintos.
- El tipo de envase (`packaging`: brick, botella, lata) **no** entra en la clave: no cambia la sustituibilidad para el comprador y complica el matching. Se guarda como atributo.
- `variant_key` es una cadena ordenada de tokens normalizados (`semidesnatada|sin_lactosa`, `zero|limon`). Los tokens se extraen con reglas y un diccionario; el orden canónico evita duplicados por "sin lactosa semidesnatada" vs "semidesnatada sin lactosa".
- Las variantes de marketing ("nueva imagen", "edición limitada") no crean canónico; las que cambian el producto (sabor, grasa, azúcar, gluten) sí.
- Para comparar precios entre formatos, usa `price_per_unit` (€/kg o €/L) calculado en la ingesta. El optimizador, en cambio, compara por canónico exacto: no debe sustituir 1 L por 1,5 L sin que el usuario lo haya pedido.
- Fase 2 opcional: `family_key` (p. ej. `leche-semidesnatada`) que agrupa tallas y packs para permitir sustitución por tamaño cuando la lista lo admita. No lo metas en el MVP: añade una dimensión y un caso de uso que todavía no está validado.

### 5.3 Creación del catálogo canónico sin trabajo manual

Pipeline en cinco pasos, con el mínimo juicio humano:

1. **Taxonomía semilla (1 vez, 2-3 h)**: 120-200 categorías hoja de 3 niveles, copiadas/adaptadas del árbol de Mercadona o Carrefour. Es el único trabajo manual relevante y condiciona todo el matching.
2. **Universo inicial**: no inventes canónicos desde cero. Toma el catálogo más limpio (Mercadona, ~4.500) como base y añade Carrefour; si hay EAN en las fichas, únelos por EAN antes de nada. Si no hay EAN, deduplica por `(categoría, variante, cantidad, unidad, marca)`.
3. **Extracción por reglas** de cantidad/unidad/pack (`(\d+[.,]?\d*)\s*(kg|g|l|ml|cl|ud|uds)`, `pack\s*(\d+)`, `(\d+)\s*[x×]\s*(\d+...)`), variante (diccionario de ~200 términos) y marca (diccionario + marcas blancas por cadena: Hacendado→Mercadona, Carrefour→Carrefour, Dia→Dia...).
4. **Embedding y bloqueo**: vector de `nombre normalizado + marca + variante + tamaño`, modelo multilingüe (384-1024 dimensiones), normalizado para coseno. **Compara solo dentro de la misma categoría hoja y misma unidad base**; si no, el kNN mezcla leche con detergente. Top-10 por HNSW.
5. **Decisión**:
   - EAN exacto → confianza 1,0, automático.
   - Misma marca + misma `variant_key` + cantidad dentro de ±2 % + misma unidad → automático.
   - Similitud ≥ umbral alto y margen ≥ 0,04 sobre el segundo → automático.
   - Zona gris → `match_review` (cola de revisión).
   - Por debajo → candidato a canónico nuevo; se crea automáticamente tras N avistamientos (p. ej. 3) para no crear ruido con errores de scraping.

Calibra los umbrales con una muestra etiquetada de 300-500 pares; no los fijes a ojo. Prioriza **precisión sobre recall**: un falso merge (dos productos distintos unidos) envenena la comparación de precios y el ahorro; un falso split solo duplica una fila y se puede revisar después. Objetivo: precisión > 0,98 y cola de revisión < 10 % de los SKU.

Los canónicos "singleton" (un solo producto de cadena) son válidos y no bloquean la ingesta; se fusionan cuando aparecen equivalentes. Toda fusión se registra en `product_match` y se resuelve con `merged_into_id`; **nunca se borra** un canónico, para no romper el histórico ni las recomendaciones pasadas.

---

## 6. Separación OLTP/OLAP y BI

### 6.1 ¿Mismo PostgreSQL o motor aparte?

**Mismo PostgreSQL, esquema `bi` separado, con tablas de hechos agregadas y refresco incremental tras la ingesta.** No hace falta DuckDB ni un almacén columnar para 100k SKU y ~1-2 M intervalos de precio.

Razones:

- El volumen analítico es pequeño si se agrega en la granularidad correcta (ver abajo): menos de 2 M filas/año en los hechos grandes.
- Una sola copia de seguridad, un solo motor, una sola transacción entre OLTP y BI.
- Metabase conecta nativamente con PostgreSQL y no requiere infraestructura extra.
- Las vistas materializadas no son la herramienta principal: el refresco completo de un hecho de 30 M filas tras cada ingesta es caro y bloquea. Mejor **tablas de hechos append-only con recomputación de una ventana** (hoy y los últimos 3-7 días) y MVs solo para rollups mensuales.

DuckDB entra más adelante, como mucho, para analítica ad hoc sobre Parquet exportado, no como capa servida al BI. Umbral: hechos > 100 M filas, o contención entre ingesta y consultas analíticas, o necesidad de análisis sobre 5+ años de detalle producto×día.

### 6.2 Esquema en estrella

**Dimensiones**

| Dimensión | Grano | SCD | Nota |
|---|---|---|---|
| `dim_date` | 1 fila/día | estática | Año, mes, semana ISO, festivo en León, campaña |
| `dim_chain` | 1 fila/cadena | 0 | Prácticamente inmutable |
| `dim_zone` | 1 fila/zona | 1 | Cambia si se redefine la zona |
| `dim_store` | 1 fila/tienda×versión | 2 | Horario, zona, ubicación, activa |
| `dim_category` | 1 fila/categoría | 1 | Jerarquía aplanada L1-L3 |
| `dim_brand` | 1 fila/marca×versión | 2 | Cambio de titularidad o de marca blanca |
| `dim_product` | 1 fila/canónico×versión | 2 | Categoría, marca, tamaño; los merges se resuelven con `merged_into_id` |
| `dim_promotion_kind` | 1 fila/tipo | 0 | unit_price, nxm, etc. |

`dim_product` en SCD2 es importante porque una reclasificación de categoría no debe reescribir el pasado. En el MVP puedes empezar con SCD1 si las reclasificaciones son raras, pero deja `valid_from/valid_to` desde el principio: añadirlos después obliga a rehacer los hechos.

**Hechos**

| Hecho | Grano | Medidas | Volumen anual estimado |
|---|---|---|---:|
| `fact_price_category_daily` | día × categoría L3 × cadena × tipo de marca × zona | €/kg o €/L medio, mediana, mín, máx, nº productos, nº promos | ~0,4-1,5 M |
| `fact_price_index_daily` | día × cadena × cesta de referencia | índice base 100, cobertura, nº ítems | ~2.500 |
| `fact_promotion_daily` | día × cadena × categoría × tipo | nº promos, nº productos, profundidad media/máx, % con fidelización | ~0,5-2 M |
| `fact_recommendation` | 1 fila/recomendación | coste total, coste base, ahorro, minutos, nº tiendas, lambda, antigüedad del dato | ~decenas de miles |
| `fact_recommendation_line` | 1 fila/línea de recomendación | cantidad, precio unitario, importe, promo aplicada | ~10× el anterior |
| `fact_usage_daily` | día × evento | eventos, sesiones, duración media | ~1.000 |

**Decisión clave:** el hecho de precios es **por categoría, no por producto×día**. La evolución por producto canónico se sirve con una vista `bi.v_price_asof` sobre `price_history` (drill-down de un producto concreto, barato por el índice). Así evitas 30-70 M filas/año y respondes igual a los seis requisitos:

1. Evolución por producto: vista as-of; por categoría y cadena: `fact_price_category_daily`.
2. Marca blanca vs fabricante: `brand_type` en el hecho de categoría.
3. Índice de cesta: `fact_price_index_daily`.
4. Frecuencia y profundidad de promos: `fact_promotion_daily`.
5. Ahorro de recomendaciones: `fact_recommendation`.
6. Uso anónimo: `fact_usage_daily`.

DDL mínimo de los dos hechos principales:

```sql
CREATE SCHEMA bi;

CREATE TABLE bi.fact_price_category_daily (
  date_key              date    NOT NULL,
  category_id           integer NOT NULL,
  chain_id              smallint NOT NULL,
  brand_type            text    NOT NULL
                        CHECK (brand_type IN ('private_label','manufacturer','unknown')),
  zone_id               integer NOT NULL DEFAULT 0,   -- 0 = precio único de cadena
  avg_price_per_unit    numeric(12,4),
  median_price_per_unit numeric(12,4),
  min_price_per_unit    numeric(12,4),
  max_price_per_unit    numeric(12,4),
  n_products            integer NOT NULL,
  n_promos              integer NOT NULL DEFAULT 0
);

CREATE INDEX fact_price_cat_date_ix
  ON bi.fact_price_category_daily (date_key, chain_id);
CREATE INDEX fact_price_cat_cat_ix
  ON bi.fact_price_category_daily (category_id, date_key);

CREATE TABLE bi.fact_price_index_daily (
  date_key      date     NOT NULL,
  chain_id      smallint NOT NULL,
  basket_id     smallint NOT NULL,
  index_value   numeric(8,3) NOT NULL,     -- base 100 en la fecha de referencia
  coverage_pct  numeric(5,2) NOT NULL,     -- % de ítems de la cesta con precio
  n_items       integer NOT NULL
);
```

**Cesta de referencia**: `ref_basket` y `ref_basket_item (canonical_id, weight)`. El índice se calcula con las ponderaciones y se publica con `coverage_pct`; si una cadena no tiene un ítem, no lo imputes con el precio de otra: baja la cobertura y documenta el sesgo.

**Refresco**: al terminar cada `ingest_run`, un job SQL (pg_cron o el propio orquestador del scraper) recomputa la ventana de hoy y los últimos 3-7 días, hace `INSERT ... ON CONFLICT` y recalcula el índice de cesta. Las MVs mensuales se refrescan `CONCURRENTLY` por la noche. Nada de refrescar el hecho completo en cada ingesta.

### 6.3 Herramienta de BI

**Metabase OSS 65.2**, en Docker, contra un rol `bi_reader` con acceso solo al esquema `bi`. Es la que mejor encaja en un TFG:

- Instalación de un contenedor, sin Redis ni workers.
- Preguntas y dashboards sin SQL; el tribunal puede navegar sin conocer el esquema.
- Conector PostgreSQL nativo y buen manejo de filtros por fecha/cadena/categoría.
- AGPL, gratuita para uso personal/académico.

Superset 6.1.0 es más potente para SQL y para dashboards grandes, pero exige más infraestructura (metadata DB, Redis, worker) y usuarios con más soltura. Grafana 13.3.0 no es una herramienta de BI de negocio: es observabilidad. Si quieres dashboards versionados en el repositorio, Evidence (dashboards como código) es una alternativa interesante, pero añade otra pieza; no la metas en el MVP.

---

## 7. Riesgos y umbrales que cambian el diseño

| Riesgo | Impacto | Mitigación | Umbral que obliga a cambiar |
|---|---|---|---|
| El precio sí varía por zona | Series ×Z; hechos sesgados | `zone_id` ya está en el modelo; zona centinela `__chain__` | > 2 % de SKU con precio distinto entre zonas, o > 5 zonas/cadena → scrape por zona y `zone_id` en el hecho |
| Matching erróneo | Recomendación y ahorro falsos | Umbral alto, revisión, EAN si existe, validación €/unidad | Tasa de error > 2 % en muestra, o cola > 10 % → mejorar modelo o pasar a EAN |
| Promo mal parseada | Precio efectivo peor que sin promo | `confidence`, `applied_in_price`, validar `promo_price < reference_price` | > 20 % de promos rechazadas → parser específico o fuente estructurada |
| Scraper caído | Precios obsoletos presentados como vigentes | `ingest_run`, `data_as_of`, bloqueo si > 36 h | Fallos > 2 días seguidos → alerta y modo "sin datos" |
| Cambios de precio muy frecuentes | Crecimiento del histórico | SCD2 sigue siendo correcto | > 10 M cambios/año → partición mensual; > 50 M → valorar Timescale/columnar |
| Crecimiento del BI | Consultas lentas | Hechos agregados | > 100 M filas de hechos o p95 > 5 s → DuckDB/Parquet o réplica |
| Cambio de modelo de embeddings | Vectores incomparables | `embedding_model` versionado, re-embed completo | Cambio de modelo → reindexar y recalibrar umbrales |
| DST / zona horaria | Días duplicados o perdidos | `timestamptz` + `date_key` en `Europe/Madrid` | — |
| Legalidad/ToS del scraping | Bloqueo o reclamación | Ritmo bajo, User-Agent identificable, uso académico, no republicar | Cambio de términos → revisar fuentes y frecuencia |
| Doble descuento | Precio efectivo irreal | `applied_in_price` y política de no apilamiento | Si el usuario exige apilar → modelo de reglas con orden explícito |

Umbrales globales para revisar la arquitectura: **> 500k SKU**, **> 20 zonas**, **> 50 M intervalos**, **> 10 usuarios concurrentes de BI** o **necesidad de tiempo real**. Ninguno es probable en este MVP.

---

## 8. Qué es el mínimo y qué puede esperar

**MVP (imprescindible)**

- Tablas: `chain`, `zone`, `store`, `category` + `category_closure`, `brand`, `canonical_product`, `chain_product`, `chain_product_zone`, `price_current`, `price_history` (una partición), `promotion`, `promotion_target`, `promotion_zone`, `match_review`, `product_match`, `ingest_run`, `raw_response`, `recommendation`, `recommendation_item`.
- Extracción por reglas + embeddings + cola de revisión.
- Función `effective_price` con no apilamiento y `engine_version`.
- Tres hechos BI (`price_category_daily`, `price_index_daily`, `promotion_daily`) y la vista as-of.
- Metabase con un dashboard por requisito.

**Puede esperar**

- SCD2 en `dim_product`/`dim_store`/`dim_brand` (empieza SCD1 y migra).
- Hecho de precios a grano producto×día.
- `family_key` y equivalencia entre packs y singles.
- Precio por zona real y scrape multipzona.
- Cupones a nivel de cesta, apilamiento y motor de reglas.
- Matriz de tiempos de viaje cacheada por celda (OSRM en caliente es suficiente para ~100 tiendas).
- DuckDB, TimescaleDB, réplica de lectura, pg_partman.
- Marca bloqueada en canónicos (`brand_locked`) más allá de los casos que fallen.

---

## 9. Fuentes

1. PostgreSQL — portada y versiones: https://www.postgresql.org/
2. PostgreSQL — política de versiones y EOL: https://www.postgresql.org/support/versioning/
3. pgvector — repositorio y versión: https://github.com/pgvector/pgvector
4. pgvector — changelog (0.8.7, 1 oct 2026; 0.9.0 sin publicar): https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md
5. PostGIS — noticias (3.7.0, 30 oct 2026): https://postgis.net/news/
6. PostGIS — Wikipedia (3.6.4, 8 jun 2026; página desactualizada): https://en.wikipedia.org/wiki/PostGIS
7. Metabase — releases (65.2, 30 oct): https://github.com/metabase/metabase/releases
8. Metabase — licencia AGPL: https://github.com/metabase/metabase
9. Apache Superset — releases (6.1.0; 7.0.0rc2): https://github.com/apache/superset/releases
10. Apache Superset — licencia Apache 2.0: https://superset.apache.org/
11. Grafana — releases (13.3.0, 27 oct 2026): https://github.com/grafana/grafana/releases
12. DuckDB — releases (2.0.0, 21 oct 2026): https://github.com/duckdb/duckdb/releases
13. DuckDB — documentación 2.0: https://duckdb.org/docs/stable/
14. PostgreSQL 18 — release notes (`uuidv7()`, columnas generadas virtuales, AIO, skip scan, particionado): https://www.postgresql.org/docs/18/release-18.html
15. PostgreSQL 18 — limitaciones del particionado (clave de partición en PK/unique): https://www.postgresql.org/docs/18/ddl-partitioning.html
16. endoflife.date — PostgreSQL (contraste de fechas): https://endoflife.date/postgresql

**No verificado:** años exactos de Metabase 65.2 y Superset 6.1.0; licencia de Grafana en su página de releases; fecha GA de PostgreSQL 19; compatibilidad explícita PostGIS 3.7.0/PostgreSQL 18; disponibilidad de EAN en las webs de las cadenas; variación real de precios por zona; términos de uso concretos de cada cadena. Estos dos últimos son los que más pueden mover el diseño y conviene comprobarlos con una muestra antes de implementar el scraper completo.
