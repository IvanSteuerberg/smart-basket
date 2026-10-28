# Prompt maestro: automatizar mi proyecto de OSF

Copia todo el bloque de abajo y pégalo en tu asistente de IA (uno que pueda ejecutar comandos en tu ordenador, como Claude Code o Antigravity). Cambia antes lo que está entre `<…>`.

```text
Quiero automatizar la publicación de mis documentos en mi proyecto de OSF (osf.io). No sé programar, así que explícame cada paso con palabras sencillas y pídeme permiso antes de cualquier cambio en OSF.

Datos:
- Identificador de mi proyecto: <id de 5 caracteres de la dirección osf.io/xxxxx>
- Carpeta de mi ordenador con los documentos que quiero publicar: <ruta de la carpeta>
- Mi token de OSF está en el archivo .env de esa carpeta, en la línea OSF_TOKEN=...

Reglas que debes cumplir siempre:
1. Nunca muestres, copies ni subas a ningún sitio el contenido del token. Léelo del .env solo para las llamadas a la API. Si la carpeta usa git, comprueba que .env está en .gitignore.
2. Empieza solo leyendo: muéstrame qué carpetas y archivos hay en mi proyecto antes de proponer nada.
3. Nunca borres archivos de OSF. No muevas ni renombres nada sin preguntarme.
4. Antes de subir nada, enséñame una simulación con lo que harías y espera a que te diga que sí.

Lo que quiero que prepares:
A) Un script de publicación. Para cada documento le digo en qué carpeta de OSF va y con qué nombre. Sube siempre con el mismo nombre para que OSF guarde el historial de versiones, y no subas un archivo si no ha cambiado (compara su huella SHA-256 con la que da OSF en extra.hashes.sha256). Por defecto solo simula; con --apply sube.
B) Un script que genere un índice en la página principal de la wiki del proyecto: carpetas, archivos con enlace, fecha de creación, fecha de la última versión y número de versiones. Las descripciones y el estado de cada documento los mantengo yo en un archivo JSON.
C) Un archivo LEEME.txt con las dos órdenes que tendré que pedirte en el día a día.

Detalles técnicos que te ahorrarán errores:
- API: https://api.osf.io/v2 con la cabecera "Authorization: Bearer <token>". Los archivos se suben y descargan por https://files.osf.io/v1/resources/<id>/providers/osfstorage/...
- Las descargas redirigen a un almacenamiento externo: sigue la redirección SIN la cabecera de autorización o fallará con un error 400.
- Para contar las versiones de un archivo usa su enlace relationships.versions; el campo extra.version no siempre viene relleno.
- La wiki se actualiza creando una versión nueva: POST a /v2/wikis/<id de la wiki>/versions/ con {"data": {"type": "wiki-versions", "attributes": {"content": "..."}}}.
- Usa solo la biblioteca estándar de Python si es posible, para no tener que instalar nada.
- Hay una implementación de referencia en https://github.com/IvanSteuerberg/smart-basket/tree/main/scripts (osf_publish.py y osf_index.py). Puedes leerla y adaptarla, pero cambia el identificador del proyecto por el mío.

Cuando termines, haz una prueba en modo simulación y explícame el resultado.
```

## Uso diario

Una vez preparado, basta con pedírselo al asistente:

- «Publica mis documentos en OSF»: primero te enseñará la simulación y, si dices que sí, subirá solo lo que haya cambiado.
- «Actualiza el índice de la wiki de OSF».
