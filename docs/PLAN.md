# Plan de Implementación — Catálogo Desguaces Rovira en Piezalia

> **Documento vivo**: se irá actualizando durante el desarrollo. Cada sección tiene un estado
> que marca el progreso actual.

## Estado General

| Fase | Rama | Estado |
|---|---|---|
| Esqueleto + Infraestructura | `main` | ✅ Completado |
| Importación del feed | `feature/import` | ✅ Completado |
| Sincronización con Piezalia | `feature/sync` | ✅ Completado |
| Consulta de estado | `feature/status` | ✅ Completado |
| Tests | `feature/tests` | ✅ Completado |
| Documentación final | `docs/final` | ✅ Completado |

---

## Resumen del Problema

Portal Hero sincroniza catálogos de desguaces con el marketplace Piezalia. Desguaces Rovira
(Castellón) tiene **4 cuentas** en Piezalia (una por nave). Su programa de gestión exporta un
CSV ("feed") varias veces al día con el catálogo completo. Nuestra app debe hacer que lo que
hay en Piezalia sea exactamente lo que dice el feed.

---

## Análisis del Feed

- **feed_dia1.csv**: 600 productos, sin trampas aparentes
- **feed_dia2.csv**: 604 productos con trampas intencionadas:
  - Líneas vacías intercaladas (línea 5, 28, etc.)
  - Espacios en `store_id`: `" 2 | 3 "` (producto 10053900)
  - Precio con coma decimal española: `"443,90"` (producto 312042G) → inválido para la API
  - Producto `0129700043` desaparece (hay que retirarlo)
  - Producto `108042E` desaparece (1081004 cambia de cuentas)
  - Cambios de precio: `065032` de 10.00 → 11.00
  - Cambios de título: `108111B` añade "REVISADO"
  - Producto nuevo: `04306000` aparece en día 2
  - Producto `10053900` cambia de cuentas `3|4` → `2|3`

---

## Datos del Simulador

- **~180 seed listings** ya publicados (algunos son de productos del feed, otros no)
- **4 anuncios manuales** (sku=null) → NO TOCAR
- **Cuenta 4 arranca con token expirado**
- **Failures configurados**: rate_limit cada 40 peticiones, transient cada 25 escrituras,
  reglas específicas de 503 y 504

---

## Reglas de Negocio Clave

1. **Feed = verdad absoluta**: pieza que no viene → retirar de Piezalia (pero protección ante
   feeds truncados)
2. **No borrar y recrear**: actualizar anuncios existentes (conservar posición y visitas)
3. **No tocar anuncios manuales** (sku=null): son de Jordi
4. **Protección contra feeds truncados**: el programa de gestión es viejo, a veces exporta a
   medias
5. **Marta necesita visibilidad**: comando `status` para consulta inmediata

---

## Arquitectura (Clean Architecture)

```
src/
├── domain/                    # Capa de dominio (sin dependencias externas)
│   ├── models.py              # Entidades: Product, Listing, SyncAction
│   └── exceptions.py          # Excepciones de dominio
├── application/               # Casos de uso
│   ├── import_feed.py         # UC: importar feed a Postgres
│   ├── sync_catalog.py        # UC: sincronizar catálogo con Piezalia
│   └── product_status.py      # UC: consultar estado de un producto
├── infrastructure/            # Adaptadores e implementaciones
│   ├── database/
│   │   ├── connection.py      # Pool de conexiones Postgres
│   │   ├── repositories.py    # Implementaciones de repositorios
│   │   └── migrations.py      # Esquema SQL
│   ├── portal/
│   │   ├── client.py          # Cliente HTTP para API Piezalia
│   │   └── rate_limiter.py    # Gestión de rate limiting y reintentos
│   └── csv/
│       └── feed_parser.py     # Parser del CSV del feed
├── config.py                  # Configuración (env vars, accounts.csv)
└── cli.py                     # Punto de entrada CLI (import/sync/status)
```

---

## Esquema de Base de Datos

```sql
-- Productos tal como vienen en el feed
CREATE TABLE products (
    product_id TEXT NOT NULL,
    title TEXT NOT NULL,
    price NUMERIC(7,2) NOT NULL,
    store_ids INTEGER[] NOT NULL,   -- cuentas destino
    feed_file TEXT,                  -- fichero de origen
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (product_id)
);

-- Anuncios que conocemos en Piezalia (espejo local)
CREATE TABLE listings (
    listing_id TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    sku TEXT,                       -- null = anuncio manual
    title TEXT NOT NULL,
    price NUMERIC(7,2) NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (listing_id)
);

-- Log de operaciones de sync para trazabilidad
CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    product_id TEXT,
    account_id INTEGER,
    action TEXT NOT NULL,           -- 'create', 'update', 'delete'
    status TEXT NOT NULL,           -- 'success', 'error', 'skipped'
    detail TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Estrategia de Ramas y Commits

```
main ─────●───●───●───●───●───●───────────────●──────────●────────●──────────●───────●── ✅
          1   2   3   4   5   6               merge     merge    merge     merge   merge
                                               ↑         ↑        ↑         ↑       ↑
feature/import ───────────────────●───●────────┘         |        |         |       |
                                  7   8                  |        |         |       |
                                                         |        |         |       |
feature/sync ────────────────────────────────●───●──────┘        |         |       |
                                              9   10             |         |       |
                                                                 |         |       |
feature/status ─────────────────────────────────────────●───────┘         |       |
                                                         11               |       |
                                                                          |       |
feature/tests ───────────────────────────────────────────────────●───●───┘       |
                                                                  12  13         |
                                                                                 |
docs/final ─────────────────────────────────────────────────────────────●───●───┘
                                                                        14  15
```

---

### 🟢 Rama `main` — Esqueleto, dominio e infraestructura

Todo lo que es base compartida para los tres casos de uso.

| Commit | Descripción | Estado |
|---|---|---|
| 1 | Esqueleto del proyecto y configuración | ✅ |
| 2 | Capa de dominio (modelos y excepciones) | ✅ |
| 3 | Infraestructura — Base de datos | ✅ |
| 4 | Infraestructura — Parser CSV del feed | ✅ |
| 5 | Infraestructura — Cliente API Piezalia | ✅ |
| 6 | CLI base | ✅ |

**Commit 1: Esqueleto del proyecto y configuración**
- `docker-compose.yml` (Postgres + portal-sim)
- `requirements.txt`, `Dockerfile` de la app
- Estructura de carpetas Clean Architecture
- `config.py` para cargar `accounts.csv` y env vars
- `.gitignore`

**Commit 2: Capa de dominio (modelos y excepciones)**
- Entidades `Product`, `Listing`, `SyncAction`
- Excepciones de dominio (`TruncatedFeedError`, `PortalApiError`, etc.)

**Commit 3: Infraestructura — Base de datos**
- Conexión a Postgres, migraciones, repositorios

**Commit 4: Infraestructura — Parser CSV del feed**
- Parser robusto del feed con validación y limpieza
- Manejo de trampas del feed_dia2 (líneas vacías, precios con coma, espacios)

**Commit 5: Infraestructura — Cliente API Piezalia**
- Cliente HTTP con reintentos, rate limiting, manejo de 504
- Lógica de Retry-After y backoff exponencial

**Commit 6: CLI base**
- Punto de entrada con argparse, subcomandos `import`, `sync`, `status` (stubs vacíos)
- De esta forma ya se puede ejecutar `python -m src.cli --help`

---

### 🔵 Rama `feature/import` (desde `main`)

Caso de uso de importación del feed a Postgres.

| Commit | Descripción | Estado |
|---|---|---|
| 7 | Caso de uso — `import <feed>` | ✅ |
| 8 | Verificación manual del import | ✅ |

**Commit 7: Caso de uso — `import <feed>`**
- Leer feed con el parser, validar, guardar/actualizar productos en Postgres
- Detección de feed truncado (umbral de seguridad)
- Conectar el subcomando `import` del CLI con el caso de uso

**Commit 8: Verificación manual del import**
- Ajustes y fix tras probar con `feed_dia1.csv` y `feed_dia2.csv` contra Postgres

→ **Merge a `main`**

---

### 🟣 Rama `feature/sync` (desde `main` actualizado)

Caso de uso de sincronización del catálogo con Piezalia.

| Commit | Descripción | Estado |
|---|---|---|
| 9 | Caso de uso — `sync` | ✅ |
| 10 | Verificación del sync | ✅ |

**Commit 9: Caso de uso — `sync`**
- Lógica de reconciliación por cuenta: crear, actualizar, eliminar
- Respetar anuncios manuales (sku=null)
- Gestión de tokens expirados (skip cuenta, logear error)
- Espejo local de listings en Postgres
- Conectar el subcomando `sync` del CLI

**Commit 10: Verificación del sync**
- Probar ciclo completo: import feed_dia1 → sync → import feed_dia2 → sync
- Ajustes y fix

→ **Merge a `main`**

---

### 🟠 Rama `feature/status` (desde `main` actualizado)

Caso de uso de consulta de estado de un producto (lo que necesita Marta).

| Commit | Descripción | Estado |
|---|---|---|
| 11 | Caso de uso — `status <product_id>` | ✅ |

**Commit 11: Caso de uso — `status <product_id>`**
- Consulta a Postgres: datos del producto, en qué cuentas debería estar, estado real de
  cada listing
- Salida legible para Marta (no técnica)
- Conectar el subcomando `status` del CLI

→ **Merge a `main`**

---

### 🟡 Rama `feature/tests` (desde `main` actualizado)

Tests unitarios y de integración.

| Commit | Descripción | Estado |
|---|---|---|
| 12 | Tests unitarios | ✅ |
| 13 | Tests de integración | ✅ |

**Commit 12: Tests unitarios**
- Tests del parser CSV (trampas del feed_dia2)
- Tests de la lógica de reconciliación (sync)
- Tests del caso de uso de import (feed truncado, etc.)

**Commit 13: Tests de integración**
- Test E2E con portal-sim: import → sync → verificar estado

→ **Merge a `main`**

---

### 🔴 Rama `docs/final` (desde `main` actualizado)

Documentación de entrega.

| Commit | Descripción | Estado |
|---|---|---|
| 14 | README.md | ✅ |

**Commit 14: README.md**
- Instrucciones para arrancar (docker-compose), ejecutar los 3 comandos, y correr tests

→ **Merge a `main`** — Entrega final ✅

---

## Decisiones Técnicas Clave

| Decisión | Razonamiento |
|---|---|
| **ORM y Frameworks** | Se elige SQLAlchemy 2.0 (Data Mapper) en lugar de Django (Active Record) para respetar Clean Architecture de forma no invasiva, dejando entidades puras en Dominio. Se añade interfaz FastAPI ligera para consulta web/Swagger para soporte. |
| **Truncado de títulos a 80 caracteres** | Piezalia rechaza títulos > 80 chars (422). Los seed listings muestran que el sistema anterior truncaba a 80 chars. Se trunca en parser para garantizar compatibilidad exacta. |
| **Feed truncado**: no borrar si el feed tiene menos del 50% de productos vs. lo que ya tenemos | Protección contra exportaciones parciales del programa viejo |
| **SKU como clave de matching**: product_id del feed = sku en Piezalia | Es la referencia que conecta ambos sistemas |
| **Precio con coma → error de parseo**: no adivinar, logear warning y saltar la línea | Preferible no publicar a publicar mal |
| **Reintentos con backoff exponencial** para 429 (con Retry-After) y 503 | La API lo permite y el enunciado dice que una sync puede tardar horas |
| **504 (gateway_timeout): verificar estado antes de reintentar** | La operación puede haberse aplicado o no; hay que comprobarlo |
| **Sincronización por cuenta**: procesar cada cuenta independientemente | Un token expirado no debe bloquear las demás |
| **psycopg2 (sync)** en vez de asyncpg | Simplicidad; el cuello de botella es la API (rate limiting), no la DB |

---

## Notas de Desarrollo

_Sección para anotar cambios de rumbo, problemas encontrados o decisiones tomadas sobre la
marcha durante el desarrollo._

<!-- Ejemplo:
- 2026-11-07: Descubierto que el simulador devuelve X en vez de Y → ajustado el parser
-->
