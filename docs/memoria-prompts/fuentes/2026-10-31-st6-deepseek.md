# Respuesta original de DeepSeek — Señal de Tiempo 6

- Fecha: 31 de octubre de 2026
- Modelo: deepseek-v4.1-flash a través de OpenCode Go (Claude Code en modo no interactivo como cliente, carpeta vacía, sin contexto previo, con WebSearch y WebFetch; 132 turnos, 946 s)

## Prompt

```text
Actúa como Ingeniero de Datos especializado en extracción web y en el marco legal de la reutilización de datos en la UE. Estudio la viabilidad de las fuentes de datos de un MVP académico (asignatura de Sistemas de Información de Gestión y Business Intelligence, uso personal y no comercial, la aplicación no se publica) que recomienda en qué supermercados de León (España) comprar una lista para minimizar coste + tiempo de desplazamiento.

Necesito, de forma automática y sin ningún paso manual (nada de buscar o escanear folletos a mano), una vez al día o a la semana:
- Catálogo con precios de cada cadena (30.000-100.000 productos en total), con marca, formato y, si existe, código EAN.
- Promociones con su vigencia: precio rebajado, NxM, segunda unidad al X %, descuentos por volumen, precios con tarjeta de fidelización y cupones públicos.
- Ubicación y horario de las tiendas de cada cadena en León.

Cadenas: imprescindibles Mercadona, Carrefour, Dia y Lidl; si los datos lo permiten, Alcampo, E.Leclerc, Lupa y Aldi. Indica también si conviene considerar otras cadenas con presencia en León capital (por ejemplo, Gadis, Alimerka o Eroski).

Contexto previo: un TFG de 2023 extrajo precios con requests y BeautifulSoup producto a producto (URLs guardadas a mano por EAN). Funcionó en Dia y Carrefour, pero Alcampo e Hipercor bloquearon las peticiones, descartó Mercadona porque su web pedía iniciar sesión y no extrajo promociones.

Preguntas:
1. Para cada cadena: ¿publica un catálogo online con precios? ¿Depende del código postal o de la tienda (y cómo seleccionar León)? ¿Hay una API interna en JSON o datos estructurados (JSON-LD, sitemaps) más estables que el HTML? ¿Qué campos y qué tipos de promoción se ven? ¿Los precios con tarjeta y los cupones son públicos? ¿Publica folletos descargables automáticamente (PDF o imágenes, en su web o en agregadores como Tiendeo)? ¿Qué dice su robots.txt y sus condiciones de uso sobre el acceso automatizado? ¿Qué medidas antibots usa?
2. Ubicación y horarios de las tiendas: ¿localizador de tiendas de cada cadena, OpenStreetMap u otra fuente abierta?
3. Fuentes alternativas o complementarias: Open Food Facts, proyectos de código abierto que ya extraen estas cadenas, datos abiertos públicos de precios, agregadores. ¿Qué aportan y con qué licencia?
4. Marco legal en España y la UE para este uso: derecho sui generis sobre bases de datos (Directiva 96/9/CE), jurisprudencia relevante del TJUE, condiciones de uso como contrato, robots.txt, propiedad intelectual de imágenes y textos, y cualquier novedad hasta 2026. ¿Qué prácticas mantienen el riesgo bajo para un uso académico y no comercial?
5. Folletos: ¿es viable extraer promociones de PDF o imágenes de folletos de forma automática y fiable (OCR, modelos de visión ligeros que corran en local)? ¿Merece la pena para el MVP?

Da una tabla por cadena (fuente, método, campos, promociones, frecuencia, riesgo técnico y legal), una recomendación concreta de qué cadenas y fuentes entran en el MVP y con qué método, las buenas prácticas de extracción responsable y los riesgos con sus mitigaciones. No propongas técnicas para eludir bloqueos o medidas antibots: si una cadena las aplica, indícalo como riesgo.

Antes de responder, busca en internet información actual (hoy es 31 de octubre de 2026) y consulta directamente las webs de las cadenas y sus robots.txt cuando puedas. Cita las fuentes con su URL e indica qué no has podido verificar. No ejecutes comandos ni modifiques archivos: usa solo la búsqueda web y la lectura de páginas.
```

## Respuesta

# Viabilidad de fuentes de datos para el recomendador de supermercados de León

**Fecha de verificación: 31 de octubre de 2026.** Todo lo que sigue se basa en lectura directa de webs, `robots.txt`, APIs públicas y textos legales. No he ejecutado comandos ni modificado archivos.

---

## 0. Advertencia metodológica (importante para el TFG)

Tres limitaciones han condicionado la investigación y debes declararlas:

1. **La herramienta de búsqueda web falló durante toda la sesión** (devolvía resultados vacíos o texto inventado). Por eso no he podido localizar notas de prensa, sentencias de 2024-2026 ni artículos doctrinales recientes. He suplido la búsqueda con lectura directa de fuentes primarias (EUR-Lex, BOE, webs de cadenas, API de GitHub, Overpass/OSM). **La jurisprudencia y novedades posteriores a 2021 deben revisarse aparte en CENDOJ y Curia.**
2. **Carrefour, Dia y Alimerka devuelven HTTP 403** a peticiones automatizadas, incluso en rutas que deberían ser públicas. No he podido leer sus condiciones de uso ni sus catálogos. Lo indico como hallazgo, no como laguna.
3. **Mercadona, Lidl, Alcampo y Eroski renderizan parte del contenido con JavaScript.** Lo que no aparece en el HTML servido no lo he podido confirmar.

---

## 1. Veredicto en una página

- **No es viable, con riesgo bajo, un pipeline diario, totalmente automático y con las ocho cadenas.** En 2026 dos de las cuatro cadenas "imprescindibles" (Carrefour y Dia) bloquean clientes automatizados, y Mercadona prohíbe expresamente su API en `robots.txt`.
- **Sí es viable un MVP semanal con 4-5 cadenas**: Lidl, Alcampo, Gadis, Eroski y, condicionalmente, Mercadona por páginas de producto (la única ruta que su `robots.txt` permite).
- **El catálogo completo de 30.000-100.000 productos es innecesario y contraproducente.** Un recomendador solo necesita la lista del usuario, sus sustitutos y una cesta candidata. Extraer 300-800 SKU por cadena reduce el riesgo jurídico (extracción de parte no sustancial) y el coste técnico en un orden de magnitud.
- **El EAN casi no existe en las fuentes online.** Ninguna de las APIs verificadas lo expone. Habrá que enriquecer con Open Food Facts y aceptar matching por marca + nombre + formato.
- **Las promociones estructuradas son el punto más débil.** Solo Lidl y Alcampo publican ofertas con vigencia de forma explotable; NxM, 2ª unidad y cupones personalizados requieren login o solo existen en folletos. El modelo de datos debe limitarse a "precio rebajado con vigencia" en el MVP.
- **Los folletos con OCR no compensan para el MVP**, salvo como complemento informativo para E.Leclerc/Aldi/Gadis. El coste de error en precios es alto y la ganancia, marginal frente a las webs.

---

## 2. Tabla comparativa por cadena

| Cadena | Catálogo online y precios / tienda León | Método y campos | Promociones | Frecuencia | Riesgo técnico | Riesgo legal |
|---|---|---|---|---|---|---|
| **Mercadona** | Sí, precios públicos sin login; precios y surtido dependen de almacén (CP). 3 tiendas en León capital (OSM). | API JSON no oficial (`/api/categories/`, `/api/products/{id}/`) **prohibida por robots**; alternativa permitida: páginas `/product/...` + sitemap. Campos: `unit_price`, `bulk_price`, `reference_price`, `unit_size`, `size_format`, `previous_unit_price`; **sin EAN ni campo marca**. | Solo "bajadas de precio" (`price_decreased`, `previous_unit_price`). Sin cupones ni tarjeta verificados. Sin folletos. | Semanal | Bajo técnico / **alto legal si se usa `/api`** | Alto por `robots.txt` (`Disallow: /api`); medio por páginas de producto |
| **Carrefour** | Sí, catálogo amplio; precio online nacional, puede diferir del hipermercado. Hipermercado + Express en León (OSM). | API interna `cloud-api/plp-food-papi/v1` (JSON); páginas de producto y sitemaps food/bodega. Campos: `product_id`, `price`, `price_per_unit`, `measure_unit`, `brand.name`, `category`, `images`; sin EAN. | Mi Club Carrefour (cupones personalizados), ofertas y 2ª unidad; **no verificable** por bloqueo. Folletos online. | Semanal | **Alto**: 403 a cliente automatizado; los repos de la comunidad usan suplantación TLS (`curl_cffi`), que es evasión y no debe usarse. | Medio-alto: condiciones de uso no legibles; el bloqueo activo convierte la insistencia en circunvención |
| **Dia** | Sí, precios online; selección por CP/tienda en la web. 7 tiendas en León capital (OSM). | API interna `/api/v1/plp-back/reduced` (JSON); requiere cookie de navegador (`COOKIE_DIA`). Campos: `object_id`, `display_name`, `prices_price`, `prices_price_per_unit`, `prices_measure_unit`, `url`, `image`; sin EAN ni marca. | Club Dia, cupones y precio tarjeta; **no verificable**. Folletos. | Semanal | **Alto**: 403 incluso en `robots.txt` y en la API. | Alto: condiciones de uso no legibles + bloqueo activo |
| **Lidl** | Sí, precios públicos; surtido limitado (~2.000-3.000 ref., estimación). 3-4 tiendas en León. | HTML de producto + `sitemap.xml` (índice con `product_sitemap.xml.gz` y sitemap de tiendas). Campos: nombre, precio, precio/kg, formato; EAN no verificado. | Ofertas semanales con vigencia ("esta semana"/"próxima"), cupones Lidl Plus públicos, folletos descargables. | Semanal (2× en ofertas) | **Bajo-medio** | **Bajo-medio**: `robots` permite producto; aviso legal prohíbe reproducción con fines comerciales, no el acceso automatizado |
| **Alcampo** | Sí, `compraonline.alcampo.es`; precios y surtido ligados a ubicación de entrega/tienda; parte del catálogo pide login. 2 tiendas en León. | HTML/JSON de la tienda online; sitemap en `compraonline.alcampo.es`. Campos: precio, precio unidad, formato, marca; EAN no verificado. | Ofertas Club, "Alcampo Más", tarjeta Dúa, folletos, ofertas online exclusivas. | Semanal | Medio (gating por ubicación/login) | Medio: condiciones legales no verificadas (URLs 404) |
| **E.Leclerc** | **No vende alimentación online**; solo folletos y listas. Tienda en Trobajo del Camino (León), 09:00-21:30. | Folletos PDF/imagen + OCR. Sin catálogo con precios. | 3×2 vigente 21/10-01/11/2026; folletos por tienda. Tarjeta de fidelización. | Semanal | Medio-alto (OCR) | Medio-alto: aviso legal prohíbe reproducción y "almacenamiento en un sistema de recuperación de información" |
| **Gadis** | `gadisline.com` muestra precios y precio/kg; cobertura León no confirmada; 1 tienda en León capital (OSM). | HTML de Gadisline; `robots` permite con exclusiones; bloquea bots de scraping nominados. Campos: precio, precio/kg, formato. | Oportunigadis diario; folleto 29/10-04/11/2026; aviso de que muchos precios no aplican a Gadisline. | Semanal | Bajo-medio | Medio: aviso legal exige consentimiento escrito para reproducción o almacenamiento |
| **Alimerka** | Web y tienda online **403**; 8 tiendas en León capital (OSM). | No verificable. `robots.txt` con señales Cloudflare (`search=yes, ai-train=no, use=reference`) y bloqueo de crawlers de IA. | No verificable. | — | **Alto** (Cloudflare) | Alto |
| **Eroski** | `supermercado.eroski.es`; precios no visibles sin JS; 18 tiendas en la provincia de León. | HTML/JSON tras JS; `robots` permite. Campos por verificar. | Eroski Club (cupones personalizados), folletos. | Semanal | Medio | Bajo-medio: términos sin prohibición expresa de scraping |
| **Aldi** | Sin e-commerce de alimentación; ofertas semanales y folletos (JS). 1 tienda en León. | Folletos/HTML + OCR. | Ofertas semanales con vigencia; sin programa de fidelización en España. | Semanal | Medio | Bajo-medio (folletos con copyright) |
| **Lupa** | Sin web accesible (fallo DNS); 2 tiendas en León (OSM). | Sin fuente online. | Sin fuente online. | — | Alto | — |

*Estimaciones de surtido: no verificadas con conteo de sitemap; tómalas como orden de magnitud.*

---

## 3. Fichas por cadena

### 3.1 Mercadona

**Catálogo y selección de León.** `tienda.mercadona.es` muestra precios sin login desde hace años; el bloqueo del TFG de 2023 ("pedía iniciar sesión") ya no aplica al catálogo, solo al checkout. El surtido y los precios dependen del **almacén** asignado al código postal. La API documentada por la comunidad permite fijarlo con `PUT /api/postal-codes/actions/change-pc/` y `{"new_postal_code":"24001"}`, que devuelve `x-customer-wh` [1][5]. Para León hay que verificar qué almacén sirve (p. ej. `leo1` o `mad1`); **no lo he podido confirmar**.

**Datos estructurados.** La API devuelve JSON muy limpio: `id` interno, `display_name`, `price_instructions.unit_price` (precio del paquete), `bulk_price` (precio por kg/L), `reference_price`, `unit_size`, `size_format`, `previous_unit_price`, `price_decreased`, `is_new` [2][3][5]. **No hay EAN ni campo de marca**: "Hacendado" aparece dentro de `display_name`. `/api/home/` expone secciones de "Bajadas de precio" y "Novedades" [4].

**El problema legal.** `tienda.mercadona.es/robots.txt` dice literalmente: `Allow: /$`, `Allow: /product`, `Disallow: /api`, `Disallow: /legal`, `Disallow: /` [1]. Es decir: **la API es públicamente accesible pero está expresamente excluida para crawlers**. Usarla es la vía más sencilla técnicamente y la más difícil de defender. La ruta permitida es `/product/...`; el `sitemap.xml` está permitido. En mi prueba, la página de producto devolvió el título con nombre y marca, pero **el precio no aparecía en el texto extraído** (probablemente va en `__NEXT_DATA__` o se hidrata en cliente) [6]. Habría que confirmar con un navegador si el HTML servido contiene el precio; si no, Mercadona queda fuera del pipeline automático.

**Promociones.** En la API solo hay bajadas de precio con precio anterior. No he verificado tarjeta de fidelización ni cupones; en los datos consultados no aparece ningún campo de cupón. **No hay folletos** en el sentido tradicional.

**Antibot.** El subdominio `info.mercadona.es` devolvió 403; la tienda y la API respondieron sin cabeceras especiales. Hay CDN con filtrado, pero no es agresivo.

**Recomendación.** No usar `/api`. Si el precio no está en `/product`, excluir Mercadona del MVP automático y documentarlo como limitación, o solicitar autorización. Usar el dataset de `datania/mercadona-catalog` (código MIT, actualización semanal por GitHub Actions) no elimina el problema: los datos se obtuvieron de la misma API [7][8].

---

### 3.2 Carrefour

**Catálogo.** Catálogo enorme (alimentación + bodega + tecnología). Los precios de `carrefour.es` son **precios online nacionales**; pueden no coincidir con el hipermercado de León. En León hay un `Carrefour Planet` (centro comercial) y varios `Carrefour Express` según OSM.

**Vía técnica.** La comunidad usa `https://www.carrefour.es/cloud-api/plp-food-papi/v1` con paginación `?offset=` y JSON con `product_id`, `name`, `price`, `price_per_unit`, `measure_unit`, `brand.name`, `category.display_name`, `images.desktop` [9]. El `robots.txt` **no prohíbe** las páginas de producto ni `/cloud-api` en general: solo excluye `/buscador/`, `?q=`, `?sort=`, `?promoId=`, `?filter=`, endpoints de pago y varios bots nominados; permite expresamente el rastreo de producto [10]. Hay sitemaps de alimentación y bodega, aunque el índice devolvió 403 en mi prueba [11].

**El problema real es el bloqueo.** Tanto el HTML como el sitemap y la página de condiciones devolvieron **403** a un cliente automatizado. El repositorio `HevCuesta/Carrefour-scraper` (MIT) reconoce usar `curl_cffi` con impersonación de Chrome "para evitar bloqueo" [9]. Eso es exactamente una técnica de evasión: **no debe usarse**. Si un cliente educado recibe 403, la conducta correcta es detenerse y documentarlo, no fingerprint-spoofing.

**Promociones.** Mi Club Carrefour y cupones personalizados; ofertas semanales y 2ª unidad. No verificable por bloqueo. Folletos online.

**Recomendación.** Excluir del núcleo. Si se incluye, que sea un adaptador "best-effort" con una sola petición por URL, sin reintentos agresivos ni camuflaje, y con degradación elegante. El TFG puede presentar el 403 como resultado empírico reproducible.

---

### 3.3 Dia

**Catálogo.** Precios online públicos tras seleccionar CP/tienda. La API interna usa `/api/v1/plp-insight/...` y `/api/v1/plp-back/reduced`; el scraper de referencia lee `plp_items` con `object_id`, `display_name`, `prices_price`, `prices_price_per_unit`, `prices_measure_unit`, `url`, `image` [12]. No hay EAN ni marca en ese payload.

**Bloqueo.** `https://www.dia.es/api/v1/` devuelve **403**, y `https://www.dia.es/robots.txt` también devuelve **403** [13]. El scraper necesita una cookie de sesión de navegador (`COOKIE_DIA`), que caduca [12]. Es un WAF que exige contexto de navegador real.

**Promociones.** Club Dia, cupones y precio tarjeta; folletos. No verificable.

**Recomendación.** Excluir. Es el caso más claro de "la fuente existía en 2023 y se ha cerrado en 2026". No intentar resolver la cookie con automatización de navegador: eso es evasión.

---

### 3.4 Lidl

**Catálogo.** Precios públicos en HTML, sin login. Surtido limitado y rotación alta (buena parte es marca blanca y bazar). `robots.txt` permite el sitio salvo `/user-api/*`, búsquedas (`*search?q=*`), paginación (`?offset=`), `idsOnly`, `productsOnly`, `id=`, `pageId`, `advisor`, `sort`; declara sitemap [14]. El sitemap es un índice con `product_sitemap.xml.gz`, páginas y `tiendas/sitemap.xml` [15]. Es la fuente más "civilizada" de las cuatro grandes.

**Promociones.** La web publica "Esta semana" y "Próxima semana", ofertas diarias, cupones Lidl Plus y folletos descargables [16]. Los cupones son públicos en la web, aunque su activación requiere cuenta. El aviso legal **no prohíbe** el acceso automatizado; prohíbe "la reproducción, distribución y comunicación pública... con fines comerciales" sin autorización [17]. Un TFG no publicado y no comercial encaja mal en esa prohibición, pero conviene citar la fuente y no redistribuir el catálogo.

**Tiendas.** El localizador lista 3 tiendas en León: C/ El Encinar 3, Av. Ing. Sáenz de Miera y Av. Padre Isla 135; **sin horarios** en el HTML [18]. OSM registra 4.

**Recomendación.** Núcleo del MVP. Método: sitemap → páginas de producto → parseo de HTML/JSON-LD, sin tocar búsqueda ni endpoints de usuario.

---

### 3.5 Alcampo

**Catálogo.** `compraonline.alcampo.es` carga sin bloqueo, pero el catálogo y los precios están condicionados a "Elige ubicación de entrega" y parte del surtido pide login ("ver todos los productos disponibles") [19]. `robots.txt` permite todo salvo cuatro bots (CazoodleBot, MJ12bot, dotbot, Gigabot) y declara sitemap [20]. Tiene ofertas Club, "Alcampo Más", tarjeta Dúa y folletos.

**Riesgo.** El gating por ubicación/login es el obstáculo: sin sesión, la cobertura puede ser parcial. No he podido verificar las condiciones legales (las URLs probadas dan 404).

**Recomendación.** Segundo adaptador del MVP, con CP de León y solo catálogo público; si el precio exige login, excluir esos SKU.

---

### 3.6 E.Leclerc

**Catálogo.** **No hay venta de alimentación online**: la web ofrece folletos, listas de la compra y selección de tienda. La tienda de León (Trobajo del Camino) figura con horario 09:00-21:30 [21]. Los folletos sí tienen vigencia y promociones (3×2 del 21/10 al 01/11/2026; folleto hasta 31/10/2026) [21][22]. `robots.txt` es WordPress/Yoast, permite todo y publica sitemaps locales, incluido León [23].

**Legal.** El aviso legal es restrictivo: prohíbe la reproducción total o parcial, la transmisión electrónica y "su registro o almacenamiento en un sistema de recuperación de información", y limita el contenido a uso personal no comercial [24]. Irónicamente, el uso del TFG es personal y no comercial, pero el "almacenamiento" está prohibido expresamente.

**Recomendación.** Solo folletos, y solo si el TFG acepta el riesgo contractual; nunca como fuente principal de precios.

---

### 3.7 Gadis

**Catálogo.** `gadisline.com` muestra precios y precio/kg, sin selector de CP visible [25]. La cobertura de León no está confirmada, aunque Gadis opera en Castilla y León y OSM registra una tienda en la capital. La web general advierte que muchos precios y promociones del folleto **no son válidos para Gadisline** [26], lo que obliga a distinguir canal online y tienda.

**Promociones.** Oportunigadis diario y folleto semanal (29/10-04/11/2026) [26].

**Robots/ToS.** `robots.txt` permite con exclusiones de parámetros y bloquea bots de scraping nominados [27]. El aviso legal exige **consentimiento previo y escrito** para reproducción o almacenamiento, total o parcial [28].

**Recomendación.** Incluir como cadena secundaria si se confirma León; asumir que el folleto y la web online pueden discrepar.

---

### 3.8 Alimerka

Web y tienda online devuelven **403**; `robots.txt` sí se pudo leer y contiene señales Cloudflare (`search=yes, ai-train=no, use=reference`) y bloqueo explícito de crawlers de IA [29]. OSM registra 8 tiendas en León capital, así que la cadena es relevante físicamente pero **no es una fuente de datos viable**. Excluir.

---

### 3.9 Eroski

`supermercado.eroski.es` existe, pero los precios no aparecen en el HTML estático (JS). El localizador permite filtrar por León y muestra **18 tiendas en la provincia**, sin detalle en el HTML [30]. `robots.txt` permite el sitio con exclusiones habituales [31]. Los términos de uso no contienen prohibición expresa de scraping, solo la cláusula genérica de no copiar/modificar/distribuir [32]. Eroski Club y folletos están disponibles [33].

**Recomendación.** Tercer adaptador, condicionado a verificar que hay tienda en León capital y que el precio es accesible sin login.

---

### 3.10 Aldi

Sin e-commerce de alimentación; ofertas semanales y folletos, renderizados con JS. `robots.txt` permite con exclusiones de regiones y filtros [34]. Sin programa de fidelización en España. **Solo OCR/folletos**; baja prioridad.

### 3.11 Lupa

Sin web accesible (fallo DNS persistente). OSM registra 2 tiendas en León. **Sin fuente online**: excluir.

### 3.12 Otras cadenas con presencia en León

OSM muestra, además, **Covirán, Froiz, masymas, Primaprix y Familia** en la capital, y **18 Eroski** en la provincia. Ninguna ofrece catálogo online nacional con precios estable; no las incluiría en el MVP. **Hipercor/El Corte Inglés** no se ha evaluado; el antecedente del TFG (bloqueo) aconseja no incluirlo.

---

## 4. Ubicación y horarios de tiendas

**OpenStreetMap es la mejor fuente abierta**, con licencia ODbL (atribución y compartir igual). Consulta Overpass usada (ejemplo para León capital):

```
[out:json][timeout:40];
nwr["shop"="supermarket"]["brand"~"Mercadona|Carrefour|Dia|Lidl|Alcampo|Leclerc|Aldi|Gadis|Alimerka|Eroski|Lupa",i]
  (42.54,-5.66,42.66,-5.48);
out tags center;
```

Resultados verificados en el área de León capital: **Alcampo 2, Alimerka 8, Dia 7, E.Leclerc 1 (Express), Lupa 2, Mercadona 3**, más Covirán, Froiz, masymas, Primaprix y Familia. Una segunda consulta por nombre añadió **Lidl 4, Aldi 1, Gadis 1** y **Carrefour Planet + Express**. Eroski aparece en el área metropolitana [35].

**Limitaciones de OSM:** los horarios (`opening_hours`) son incompletos y a veces obsoletos; las direcciones no siempre están etiquetadas. Para horarios, la fuente correcta es el localizador oficial:

- Mercadona: `info.mercadona.es/es/supermercados/` (403 a clientes automatizados).
- Carrefour: localizador en `carrefour.es` (bloqueado).
- Dia: localizador en `dia.es` (bloqueado).
- Lidl: `lidl.es/s/es-ES/tiendas/leon/` — 3 tiendas, sin horarios en HTML [18].
- Alcampo: localizador en `alcampo.es` (ruta no verificada).
- E.Leclerc: `e-leclerc.es/leon/` — dirección y horario completos [21].
- Gadis: `gadis.es/localizador`.
- Eroski: `eroski.es/tiendas/buscador-de-tiendas/` — 18 en la provincia [30].
- Aldi: localizador en `aldi.es`.

**Recomendación:** OSM como base (gratuita, ODbL, sin riesgo), localizador oficial como validación semestral. No raspar los localizadores que bloquean.

---

## 5. Fuentes alternativas y complementarias

| Fuente | Qué aporta | Licencia | Uso recomendado |
|---|---|---|---|
| **Open Food Facts** | EAN, marca, nombre, formato, nutrición, imágenes | Base: **ODbL**; contenidos: DbCL; imágenes: **CC-BY-SA** [36] | Enriquecer EAN y normalizar nombres. **No sirve para precios.** |
| **Open Prices** (Open Food Facts) | Precios colaborativos geolocalizados, API REST pública (`/api/v1/prices`) [37] | No he podido verificar la licencia exacta en la documentación consultada; el proyecto la presenta como "dataset público para investigación" | Complemento puntual; cobertura en León probablemente muy dispersa |
| **`datania/mercadona-catalog`** | Catálogo Mercadona en JSON, actualizado los lunes | Código MIT; datos derivados de la API de Mercadona [7][8] | Útil como snapshot, pero no elimina el problema de `robots.txt` |
| **`jtayped/mercapy`**, **`m0wer/mercaapi`** | Clientes Python de la API de Mercadona | MIT / sin licencia | Referencia técnica, no fuente legal |
| **`joseluam97/Supermarket-Price-Scraper`** | Scrapers Mercadona/Carrefour/Dia | Sin licencia | Referencia de endpoints; obsoleto y con cookies |
| **`HevCuesta/Carrefour-scraper`** | Scraper Carrefour con `curl_cffi` | MIT | **No reutilizar**: usa impersonación para evitar bloqueo |
| **Soysuper** | Comparador con páginas por ciudad, incluida León | `robots.txt` bloquea GPTBot/ChatGPT-User y muchas rutas; permite páginas de ciudad concretas [38] | Solo consulta manual; su web es JS ("Cargando…") |
| **Tiendeo / Ofertia** | Agregador de folletos | `robots.txt` no verificable (fallo TLS); Ofertia redirige a Tiendeo | No automatizar sin revisar ToS |
| **Datos abiertos públicos de precios** | No existe un registro oficial español de precios de supermercado | — | Descartado |

**Conclusión:** Open Food Facts es el complemento ideal para EAN y normalización; **no hay una fuente abierta que sustituya los precios de las cadenas**.

---

## 6. Marco legal aplicable (España y UE)

### 6.1 Derecho sui generis sobre bases de datos

La Directiva 96/9/CE protege la **inversión sustancial en obtener, verificar o presentar** el contenido, no los datos en sí (art. 7; considerandos 39-46) [39]. En España, arts. 133-137 TRLPI [40]:

- **Art. 133:** prohíbe la extracción o reutilización de la totalidad o parte sustancial; también la extracción **repetida y sistemática de partes no sustanciales** que conflictúe con la explotación normal o lesione injustificadamente al fabricante.
- **Art. 134:** el usuario legítimo puede extraer partes no sustanciales, con independencia del fin; es nulo todo pacto en contrario.
- **Art. 135:** excepción para **enseñanza o investigación científica**, con objetivo no comercial e indicación de la fuente.
- **Art. 136:** duración de **15 años** desde el 1 de enero siguiente a la fabricación o puesta a disposición; las modificaciones sustanciales generan nuevo plazo.

**Jurisprudencia clave:**

- **C-203/02, British Horseracing Board c. William Hill:** la inversión en **crear** los datos no cuenta; solo la inversión en **obtenerlos, verificarlos o presentarlos**. Los precios los crea la cadena, no los "obtiene" de terceros. Esto debilita mucho la protección sui generis del *precio* en sí [41].
- **C-202/12, Innoweb c. Wegener:** un metabuscador dedicado que permite consultar toda la base ajena en tiempo real reutiliza una parte sustancial, aunque cada consulta devuelva pocos resultados. Un comparador que ofrezca una búsqueda sustitutiva del catálogo completo se parece a este supuesto [42].
- **C-762/19, CV-Online Latvia c. Melons:** exige un **equilibrio** entre el interés del fabricante y la libertad de información/competencia; un agregador que añade valor y transparencia de precios no infringe automáticamente, pero sí si amenaza la recuperación de la inversión [43].
- **C-30/14, Ryanair c. PR Aviation:** si la base **no** está protegida por copyright ni sui generis, el titular **puede imponer restricciones contractuales**; la Directiva no lo impide [44].

**Lectura para el TFG:** el precio es un hecho no protegible y la inversión en fijarlo es "creación", no "obtención". Pero el catálogo como conjunto (descripciones, selección, imágenes, presentación) sí puede estar protegido. La extracción íntegra y sistemática semanal es el supuesto de riesgo; la extracción de una cesta de 300-800 referencias es defendible como parte no sustancial, y aún más al amparo del art. 135 TRLPI (investigación no comercial con indicación de fuente).

### 6.2 Condiciones de uso como contrato

Aunque no haya derecho sui generis, las ToS pueden obligar contractualmente (Ryanair). En España son contratos de adhesión; su oponibilidad exige aceptación y control de abusividad, pero **ignorarlas es un factor de mala fe** y puede fundamentar competencia desleal.

Cláusulas verificadas:

- **E.Leclerc:** prohíbe reproducción total o parcial, transmisión electrónica y "registro o almacenamiento en un sistema de recuperación de información"; limita a uso personal no comercial [24].
- **Gadis:** reproducción o almacenamiento, total o parcial, requiere consentimiento previo y escrito [28].
- **Lidl:** prohíbe reproducción, distribución y comunicación pública con fines comerciales sin autorización; no menciona scraping [17].
- **Eroski:** no prohíbe expresamente el scraping; cláusula genérica de no copiar/modificar/distribuir [32].
- **Carrefour y Dia:** no verificables (403).

### 6.3 robots.txt

No es una norma jurídica, pero es **la manifestación más clara de la voluntad del titular** y un estándar técnico reconocido. Ignorarlo debilita la buena fe y refuerza una eventual reclamación contractual o de competencia desleal. En el caso de Mercadona, `Disallow: /api` es una **reserva expresa** que además activa el opt-out del art. 4 de la Directiva DSM (ver 6.4).

### 6.4 Minería de textos y datos (TDM)

Directiva (UE) 2019/790, arts. 3, 4 y 7 [45], transpuesta en España por el **Real Decreto-ley 24/2021** [46]:

- **Art. 3:** excepción obligatoria para **organismos de investigación** e instituciones de patrimonio cultural, con acceso legítimo, para investigación científica. No puede excluirse por contrato (art. 7).
- **Art. 4:** excepción general, incluso comercial, salvo **reserva expresa del titular por medios legibles por máquina** (robots.txt, metadatos, ToS).
- **Art. 7:** las cláusulas contrarias al art. 3 son inaplicables; el art. 4 sí admite opt-out.

**Consecuencias prácticas:**

- Si un `robots.txt` prohíbe la ruta (Mercadona `/api`), hay reserva expresa y **el art. 4 no cubre** esa extracción.
- El art. 3 podría amparar a un estudiante universitario que actúe dentro de un organismo de investigación y con acceso legítimo, pero **no autoriza a saltarse bloqueos técnicos** ni a publicar la base. Un TFG no publicado encaja mejor en el art. 135 TRLPI (excepción sui generis) que en el art. 3 DSM.
- La excepción cubre **reproducción/extracción**, no la puesta a disposición del público del dataset. Publicar el catálogo en abierto quedaría fuera.

*Nota:* el RDL 24/2021 regula la TDM en un precepto que la versión consultada numera como art. 67; la numeración consolidada del TRLPI que leí no muestra un "67 bis". **Verifica la numeración exacta antes de citarla en el TFG**; el contenido (excepción para investigación + opt-out legible por máquina) sí está confirmado [46].

### 6.5 Competencia desleal y otras capas

- **Ley 3/1991, de Competencia Desleal:** art. 4 (buena fe), 11 (imitación), 15 (violación de normas) y 16 (inducción a la infracción contractual). Es la vía habitual en litigios entre agregadores y portales. No he podido cargar el texto consolidado en esta sesión, así que **cítala con verificación previa**.
- **Art. 197 bis CP:** acceso ilícito a sistemas si se vulneran medidas de seguridad. Saltarse un WAF con suplantación TLS o resolución de CAPTCHA es el supuesto a evitar.
- **Art. 160 TRLPI:** elusión de medidas tecnológicas de protección.
- **RGPD/LOPDGDD:** los precios no son datos personales; no recojas nombres de empleados, reseñas ni imágenes de personas.
- **Data Act (Reg. 2023/2854), aplicable desde el 12/09/2025:** regula datos de productos conectados y servicios de datos; **no cubre el scraping de escaparates web** [47].
- **AI Act (Reg. 2024/1689):** obligaciones de transparencia para modelos de propósito general; **no afecta** a usar un OCR local en inferencia [48].
- **Novedades 2024-2026:** no he podido verificar sentencias o reformas posteriores por el fallo de la búsqueda. Las claves siguen siendo BHB, Innoweb, Ryanair, CV-Online y la transposición DSM. **Revisa CENDOJ y Curia antes de cerrar el marco teórico.**

### 6.6 Prácticas que mantienen el riesgo bajo

1. **Extracción de parte no sustancial**, no del catálogo completo: cesta + sustitutos.
2. **Respetar `robots.txt`** y no acceder a rutas prohibidas (Mercadona `/api`, Lidl `/user-api`, búsquedas).
3. **No eludir 403, CAPTCHA, Cloudflare ni fingerprint TLS.** Si bloquea, se documenta y se excluye.
4. **Frecuencia baja** (semanal), user-agent identificable con contacto, una petición por URL, caché y `If-Modified-Since`.
5. **Minimizar campos**: precio, precio/unidad, formato, marca, EAN si existe, tienda y fecha. Sin imágenes ni descripciones.
6. **No republicar** el catálogo; publicar solo agregados (coste de cesta, ranking).
7. **Indicar la fuente** y enlazar a la ficha original.
8. **Usar OSM (ODbL) y Open Food Facts (ODbL)** con atribución y share-alike donde corresponda.
9. **Documentar la finalidad académica** y no comercial; conservar logs y correspondencia.
10. **Consultar al servicio jurídico de la universidad** si el TFG se publica en repositorio abierto.

---

## 7. Folletos: viabilidad técnica y utilidad real

**Qué se puede hacer:**

- PDF con capa de texto → `pdftotext`/PyMuPDF: fiable y barato.
- PDF escaneado o imagen → OCR local: Tesseract, PaddleOCR, docTR; modelos de visión ligeros (Florence-2, Qwen2.5-VL 3B, LayoutLMv3) para layout y tablas.
- Detección de vigencia por regex sobre "válido del X al Y".

**Por qué no basta:**

- Los folletos mezclan precio unitario, precio/kg, "2ª unidad al 50%", "3×2", "ahorra X€" y referencias cruzadas; un OCR con 95% de precisión en texto puede fallar en el 5-10% de los precios, y **un solo error invierte la recomendación de compra**.
- No hay EAN: el matching con la web es por nombre y formato, con ambigüedad alta.
- Los folletos son regionales y por tienda; el de León puede no ser el nacional.
- Copyright: las imágenes y el diseño del folleto están protegidos; extraer para análisis interno es defendible, republicar no.

**Recomendación:** **no incluir OCR en el núcleo del MVP.** Úsalo solo como módulo experimental para E.Leclerc/Aldi/Gadis, con umbral de confianza y descarte de ítems dudosos. Si el TFG necesita demostrar "promociones de folleto", hazlo sobre un único folleto semanal y valida manualmente una muestra; el resto, fuera.

---

## 8. MVP recomendado

### 8.1 Alcance

| Cadena | ¿Entra? | Método | Motivo |
|---|---|---|---|
| **Lidl** | **Sí, núcleo** | Sitemap → HTML de producto; ofertas semanales | Fuente estable, `robots` permisivo, sin bloqueo |
| **Alcampo** | **Sí, condicional** | HTML de `compraonline` con CP de León | Catálogo amplio; verificar gating |
| **Gadis** | **Sí, secundaria** | HTML de Gadisline + folleto | Cercanía; ToS restrictivas, usar con moderación |
| **Eroski** | **Sí, condicional** | HTML/JSON tras JS; validar tienda en León capital | 18 tiendas en provincia; ToS permisivas |
| **Mercadona** | **Condicional** | Solo `/product/...` permitido por robots; si el precio no está en HTML, fuera | API prohibida; no evadir |
| **Carrefour** | **No** | — | 403 + necesidad de evasión |
| **Dia** | **No** | — | 403 + cookie de navegador |
| **Alimerka** | **No** | — | 403/Cloudflare |
| **E.Leclerc** | **No para precios** | Folletos (opcional) | Sin e-commerce; ToS prohíbe almacenamiento |
| **Aldi** | **No para catálogo** | Folletos (opcional) | Sin e-commerce; solo ofertas |
| **Lupa** | **No** | — | Sin web |

**Cobertura resultante:** 3-5 cadenas, no 8. Es una limitación real que el TFG debe explicar: la recomendación óptima se calcula sobre el conjunto disponible, y se advierte al usuario de que Carrefour y Dia no están incluidos.

### 8.2 Arquitectura mínima

1. **Orquestador semanal** (cron domingo noche), no diario.
2. **Un adaptador por cadena** con: `robots_check(url)`, `fetch(url)` con UA identificable, `parse()`, `normalize()`.
3. **Snapshot crudo inmutable** (HTML/JSON con hash y fecha) para auditoría y reproducibilidad.
4. **Normalización:** EAN si existe; si no, `brand + normalized_name + size`; enriquecimiento con Open Food Facts.
5. **Modelo de promoción mínimo:** `{sku, tipo: "precio_rebajado", precio_anterior, precio_actual, valido_desde, valido_hasta, fuente}`. NxM y 2ª unidad solo si aparecen estructurados.
6. **Motor de cesta:** coste + tiempo de desplazamiento (OSM/OSRM) + disponibilidad.
7. **Trazabilidad:** cada precio guarda URL, fecha/hora, cadena, tienda/almacén y método.
8. **Kill switch por cadena** y registro de bloqueos.

### 8.3 Frecuencia

- Catálogo/cesta: **semanal**.
- Ofertas Lidl: **2×/semana** (miércoles y domingo).
- Tiendas/horarios: **mensual**.
- No hacer diario: no aporta valor proporcional al riesgo.

---

## 9. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Reclamación por derechos sui generis | Media | Alto | Cesta reducida, no catálogo completo; art. 135 TRLPI; indicar fuente |
| Incumplimiento contractual (E.Leclerc, Gadis) | Media | Medio | No usar esas fuentes para precios; o pedir permiso |
| Bloqueo técnico (Carrefour, Dia, Alimerka) | Alta | Medio | Excluir; documentar el 403; no evadir |
| Cambio de HTML/API | Alta | Medio | Adaptadores desacoplados, tests de contrato, snapshots |
| Precio online ≠ precio en tienda | Alta | Alto | Etiquetar canal y almacén; no prometer precio de tienda |
| Falta de EAN | Alta | Medio | Matching difuso + Open Food Facts; aceptar cobertura parcial |
| Promociones mal modeladas | Alta | Alto | Limitar tipos; validar con vigencia; excluir dudosas |
| OCR erróneo en folletos | Alta | Alto | Fuera del núcleo; umbral de confianza; muestreo manual |
| Publicación del dataset | Baja | Alto | Publicar solo agregados y código; no datos crudos |
| Cambio legislativo 2026 | Baja | Medio | Revisión semestral; cláusula de salvaguarda en el TFG |

---

## 10. Lo que no he podido verificar

- **Condiciones de uso y `robots.txt` de Dia y Carrefour:** 403 en todas las rutas probadas.
- **Precios y promociones de Carrefour, Dia y Alimerka:** bloqueo.
- **Precio de Mercadona en HTML sin JS:** la página `/product/4241/` devolvió título pero no precio en el texto extraído.
- **Cobertura de Gadisline en León** y **de Eroski en León capital** (solo provincia).
- **Horarios** de Lidl, Mercadona, Dia, Carrefour, Alcampo y Aldi en León (localizadores JS o bloqueados).
- **Licencia exacta de Open Prices** (la documentación consultada no la explicita).
- **Numeración consolidada del precepto de TDM** en el TRLPI tras el RDL 24/2021.
- **Jurisprudencia y novedades legislativas 2023-2026:** la búsqueda web falló; revisar CENDOJ/Curia.
- **`robots.txt` de Tiendeo:** fallo de handshake TLS; Ofertia redirige a Tiendeo.
- **Recuentos reales de SKU** por cadena: no verificados; las cifras son estimaciones.

---

## 11. Fuentes

**Cadenas y datos técnicos**

1. Mercadona, `robots.txt`: https://tienda.mercadona.es/robots.txt
2. Mercadona, API de categorías: https://tienda.mercadona.es/api/categories/
3. Mercadona, categoría 112: https://tienda.mercadona.es/api/categories/112/
4. Mercadona, API home: https://tienda.mercadona.es/api/home/
5. `datania/mercadona-catalog`, documentación de la API: https://github.com/datania/mercadona-catalog/blob/main/api.md
6. Mercadona, página de producto: https://tienda.mercadona.es/product/4241/
7. `datania/mercadona-catalog`: https://github.com/datania/mercadona-catalog
8. Dataset en Hugging Face: https://huggingface.co/datasets/datania/mercadona-catalog
9. `HevCuesta/Carrefour-scraper`: https://github.com/HevCuesta/Carrefour-scraper
10. Carrefour, `robots.txt`: https://www.carrefour.es/robots.txt
11. Carrefour, índice de sitemap food: https://www.carrefour.es/crs/cdn-static/sitemap-food/index.xml
12. `joseluam97/Supermarket-Price-Scraper`, `dia.py`: https://github.com/joseluam97/Supermarket-Price-Scraper/blob/main/supermarket/dia.py
13. Dia, API: https://www.dia.es/api/v1/
14. Lidl, `robots.txt`: https://www.lidl.es/robots.txt
15. Lidl, sitemap: https://www.lidl.es/static/sitemap.xml
16. Lidl, ofertas y folletos: https://www.lidl.es/c/descubre-nuevas-ofertas-cada-semana-folletos-lidl/s10087402
17. Lidl, aviso legal: https://www.lidl.es/c/aviso-legal/s10075786
18. Lidl, tiendas de León: https://www.lidl.es/s/es-ES/tiendas/leon/
19. Alcampo, compra online: https://www.compraonline.alcampo.es/
20. Alcampo, `robots.txt`: https://www.alcampo.es/robots.txt
21. E.Leclerc, tienda de León: https://e-leclerc.es/leon/
22. E.Leclerc, folletos: https://e-leclerc.es/folletos/
23. E.Leclerc, `robots.txt`: https://www.e-leclerc.es/robots.txt
24. E.Leclerc, aviso legal: https://e-leclerc.es/aviso-legal/
25. Gadisline: https://www.gadisline.com/
26. Gadis, web general y folleto: https://www.gadis.es/
27. Gadis, `robots.txt`: https://www.gadis.es/robots.txt
28. Gadis, aviso legal: https://www.gadis.es/aviso-legal
29. Alimerka, `robots.txt`: https://www.alimerka.es/robots.txt (la web devuelve 403)
30. Eroski, buscador de tiendas: https://www.eroski.es/tiendas/buscador-de-tiendas/
31. Eroski, `robots.txt`: https://www.eroski.es/robots.txt
32. Eroski, términos y condiciones: https://www.eroski.es/terminos-y-condiciones-de-uso/
33. Eroski, supermercado online: https://supermercado.eroski.es/
34. Aldi, `robots.txt`: https://www.aldi.es/robots.txt
35. OpenStreetMap Overpass API: https://overpass-api.de/api/interpreter
36. Open Food Facts, datos y licencias: https://world.openfoodfacts.org/data
37. Open Prices, API: https://prices.openfoodfacts.org/api/v1/prices
38. Soysuper, `robots.txt`: https://soysuper.com/robots.txt

**Marco legal**

39. Directiva 96/9/CE: https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:31996L0009
40. TRLPI, arts. 133-137: https://www.boe.es/buscar/act.php?id=BOE-A-1996-8930
41. TJUE, C-203/02 (BHB c. William Hill): https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62002CJ0203
42. TJUE, C-202/12 (Innoweb c. Wegener): https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62012CJ0202
43. TJUE, C-762/19 (CV-Online c. Melons): https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62019CJ0762
44. TJUE, C-30/14 (Ryanair c. PR Aviation): https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:62014CJ0030
45. Directiva (UE) 2019/790, arts. 3, 4 y 7: https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32019L0790
46. Real Decreto-ley 24/2021: https://www.boe.es/buscar/act.php?id=BOE-A-2021-17910
47. Reglamento (UE) 2023/2854 (Data Act): https://eur-lex.europa.eu/eli/reg/2023/2854/oj
48. Reglamento (UE) 2024/1689 (AI Act): https://eur-lex.europa.eu/eli/reg/2024/1689/oj
