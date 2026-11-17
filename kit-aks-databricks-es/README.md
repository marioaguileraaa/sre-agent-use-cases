# Azure SRE Agent · Paquete de despliegue (AKS + Databricks)

Contenido:

| Carpeta | Qué es |
|---|---|
| `01-aks-well-architected-review/` | Caso AKS: revisión de arquitectura y configuración (solo lectura) de **todos los AKS** que puede leer el agente, con informe HTML/JSON/CSV |
| `02-databricks-dependency-review/` | Caso Databricks: dependencias, configuración, seguridad, costes y FinOps (solo lectura) de **todos los workspaces** que puede leer el agente, modo **un solo tenant** |
| `00-sre-usecase-builder-v3/` | Subagente *builder* para crear nuevos casos de uso |

> **Actualización 17 de noviembre de 2026 — modelo de flota.** El kit usa ahora **las mismas herramientas que los
> casos públicos 04 (AKS) y 08 (Databricks)**: el informe sale en **inglés** y el especialista responde en
> **español**. Ya no hay lista de clústeres ni de workspaces aprobados en el `.py`: en cada ejecución la herramienta
> descubre **todos** los AKS / workspaces que puede leer la identidad del agente, en todas las suscripciones, con una
> consulta fija de solo lectura a Azure Resource Graph. Los permisos se dan **una sola vez** en el **Management
> Group** con el script de cada carpeta, y en el `.py` solo hay que poner el tenant y el Client ID. Desde el chat se
> pide todo, una suscripción o recursos por nombre, y sale **un solo informe** con filtros **Subscription** y
> **Cluster** / **Workspace**. El de Databricks trae además la sección de costes: de dónde sale el coste y cómo
> optimizarlo. Si ya teníais los casos creados: ejecutad el script nuevo del paso 1 y volved a pegar el `.py` (con el
> tenant y el Client ID), el `SKILL.md` y las instrucciones del subagente. Los nombres del tool, del skill y del
> subagente no cambian.

> **16 de noviembre de 2026 — nombre del tool y portal nuevo.** El portal limita **Tool Name** a 36 caracteres:
> el tool de Databricks se llama `databricks-dependency-report` (el fichero sigue siendo
> `generate-databricks-dependency-report.py`). Si ya se creó con un nombre cortado, usar exactamente el nombre
> guardado en el skill, en las instrucciones del subagente y en **Choose tools**. Los pasos de abajo son los del
> portal de hoy:
>
> | Antes | Portal de hoy |
> |---|---|
> | *Builder* | **Build + configure** (menú izquierdo) **→ Agent Canvas** |
> | *Settings → Azure settings → Managed Identity* | Ya no existe: portal de Azure → identidad administrada `id-…` del agente → **Overview → Client ID** |
> | Campo *Requirements* | No existe: el entorno del SRE Agent ya trae los paquetes (`requirements.txt` es informativo) |
> | Editor de parámetros / enum | No existe: los parámetros salen solos de `def main(...)` al pegar el código |
> | *Create tool* | En gris hasta pulsar **Test** en *Test playground* (cajas vacías: escribir los valores) |
> | Skill: elegir el tool y pegar el `SKILL.md` | **Primero** pegar el `SKILL.md`, **después** *Choose tools* |
> | *Sub Agents* | **Custom agents** (Table view → tarjeta *Agents*) |
> | `@subagente …` en el chat | **New chat → /agent** → elegir el subagente → chip **Agent: …** → pegar el prompt |

---

## Caso AKS: paso a paso

### Paso 1. Permisos (una sola vez, PowerShell)

Lo ejecuta alguien con **Owner** o **User Access Administrator** (o *Role Based Access Control Administrator*) en el
**Management Group** del que cuelgan las suscripciones de los AKS.

1. [Portal de Azure](https://portal.azure.com) → grupo de recursos del agente → su identidad administrada (`id-…`) →
   en **Overview** copiar el **Client ID** (no el Object ID). En el portal del agente ya no hay *Settings*.
2. Portal de Azure → **Management groups** → copiar el **ID** del Management Group (no el nombre visible).
3. En PowerShell, dentro de la carpeta `01-aks-well-architected-review`:

```powershell
az login
.\grant-aks-permissions.ps1 -IdentityClientId "PEGAR-AQUI-EL-CLIENT-ID" -ManagementGroupId "ID-DEL-MANAGEMENT-GROUP" -AksRolesAtScope -IncludeCost
```

Añadiendo `-WhatIf` muestra lo que haría sin cambiar nada. Otros alcances, en lugar de `-ManagementGroupId`:
`-SubscriptionId "<id>"` (por ejemplo, una suscripción que no cuelga del Management Group),
`-SubscriptionIds "<id-1>","<id-2>"` o `-AllSubscriptions`; sin ninguno usa la suscripción activa de `az login`.

Roles que asigna (todos de solo lectura):

| Rol | Dónde |
|---|---|
| Reader | Management Group: lo heredan todas sus suscripciones, también las futuras |
| Cost Management Reader (con `-IncludeCost`) | Management Group |
| Azure Kubernetes Service Cluster User Role | Management Group con `-AksRolesAtScope` (cubre los AKS futuros); sin esa opción, cada AKS encontrado |
| Azure Kubernetes Service RBAC Reader | Igual que el anterior |

**No hay nada que pegar en el `.py`.** El script lista los AKS que encuentra por suscripción y si leen Kubernetes
con Entra ID + Azure RBAC, y lo guarda en `aks-clusters.csv` y `aks-auth-modes.csv`. Volver a ejecutarlo es seguro
(no duplica nada). Los permisos tardan 5–10 minutos en aplicarse.

> **Nota:** por defecto el `.py` no lee Kubernetes (`kubernetes_enabled: False` en `CLUSTER_DEFAULTS`), así que los
> workloads aparecen como *Not evaluated*; el resto del informe sale igual. Para leerlos hace falta un AKS con
> Entra ID + Azure RBAC (lo indica `aks-auth-modes.csv`), red desde el agente hasta la API del clúster y poner
> `kubernetes_enabled: True`.

### Paso 2. Editar el `.py`

Abrir `generate-aks-waf-report.py` y, en el bloque **OPERATOR CONFIGURATION** del principio, cambiar solo estos 2
valores:

```python
TENANT_ID = "<YOUR_TENANT_ID>"                         # -> vuestro tenant
MANAGED_IDENTITY_CLIENT_ID = "<YOUR_AGENT_CLIENT_ID>"  # -> el Client ID del paso 1
```

No hay lista de clústeres que rellenar y `SUBSCRIPTION_ID` (`"<YOUR_SUBSCRIPTION_ID>"`) puede quedarse como está.
Opcional: `CLIENT_NAME` (por defecto `"Customer"`), `CLIENT_LOGO_DATA_URI` y `CLIENT_LOGO_ALT` para poner vuestro
nombre y logo en el informe; una entrada en `APPROVED_CLUSTERS` para ajustar un clúster concreto (por ejemplo
`"environment": "PRODUCTION"`, con su `resource_group` y `subscription_id`; las claves que empiezan por `<` se
ignoran); `DISCOVERY_SUBSCRIPTION_IDS` para limitar el descubrimiento a algunas suscripciones; `CLUSTER_DEFAULTS`
para cambiar los valores de todos los clústeres (lectura de Kubernetes, coste del RG de nodos…).

### Paso 3. Crear el tool (portal)

Ir a **Build + configure → Agent Canvas → Create ▾** (la flecha, no el botón) **→ Tool › → Python tool**.

- **Tool Name:** `generate-aks-waf-report` (máximo 36 caracteres)
- **Description:**
  `Read-only AKS architecture/configuration review of the AKS clusters the agent identity can read (all, one subscription or named clusters) and their associated resources. Collect source-qualified ARM, Kubernetes and ActualCost evidence; return one offline HTML with fleet filters, complete JSON, failed-findings CSV and inventory CSV, or bounded typed queries. No remediation.`
- **Code:** pegar el `.py` completo, ya editado.
- **Timeout (seconds):** `900`.
- No hay campo *Requirements* ni editor de parámetros: los **13 parámetros** salen de `def main(...)` al pegar el
  código (entre ellos `cluster_names` y `subscription`). El código no tiene lista de clústeres: acepta los que
  descubre.
- **Identity:** **Off**, porque el código ya usa el Client ID.
- Para terminar, en **Test playground** (cajas vacías) escribir `operation` = `list_clusters`, `view` = `summary`,
  `area`, `level`, `severity` y `status` = `all`, `limit` = `25` y `offset` = `0`, dejar vacías las demás y pulsar
  **Test**: deben salir vuestros AKS con su suscripción y región. **Create tool** sigue en gris hasta entonces.
  Después, **Create tool**.

> El *Test playground* corta las llamadas hacia los **100 segundos** (HTTP 504) aunque el timeout del tool sea
> 900: probad ahí `list_clusters` y lanzad los informes desde el chat (paso 6).

### Paso 4. Crear el skill

Ir a **Create ▾ → Skill**.

- **Primero** pegar `skills/aks-waf-live/SKILL.md` en el editor: rellena **Name** (`aks-waf-live`) y **Description**.
- **Después**, **Choose tools** → buscar → desplegar **PythonFunctionTool** → marcar solo `generate-aks-waf-report` → **Close panel**.

### Paso 5. Crear el subagente

Pulsar el botón **Create** (o **Create ▾ → Custom agent**).

- **Custom agent name:** `aks-waf-live`
- **Instructions:** el bloque de instrucciones de `subagent-instructions-and-prompts.md` (en inglés; ya incluye que
  responda en español).
- **Tools:** solo `generate-aks-waf-report`.
- **Skills:** solo `aks-waf-live`.

### Paso 6. Probar en un chat nuevo

**New chat** → escribir `/agent` → elegir `aks-waf-live` (aparece el chip **Agent: aks-waf-live**) → pegar uno de estos:

```
Lista los clústeres AKS que puedes ver, agrupados por suscripción.
```

```
Genera el informe de AKS de todos los clústeres de todas las suscripciones con operation=report.
```

```
Genera el informe de AKS de todos los clústeres de la suscripción <nombre o ID> con operation=report.
```

```
Genera el informe de AKS de <aks-1>,<aks-2> con operation=report.
```

Sale **un solo informe en inglés** (HTML, JSON completo, CSV de hallazgos y CSV de inventario) para toda la
selección, hasta 100 clústeres; con más, pedidlo por suscripción. El especialista lo resume en español. El HTML abre
con la vista de flota (**AKS fleet in this snapshot**): arriba los filtros **Subscription**, **Cluster** y **Search**;
después los indicadores de los clústeres visibles (estado de la recogida, hallazgos por severidad, índice local,
cobertura y coste real del periodo por divisa), una fila por clúster y sus hallazgos. Al elegir un clúster se abre su
revisión detallada. Un clúster que no se ha podido leer sale como error, nunca como sano. Con muchos clústeres tarda
unos minutos. Más prompts en `subagent-instructions-and-prompts.md`.

---

## Caso Databricks: paso a paso (un solo tenant)

SRE Agent y Databricks están en el **mismo tenant**. No hace falta App Registration, credencial federada,
Lighthouse ni secretos: la identidad del SRE Agent se usa directamente.

### Paso 1. Permisos (una sola vez, PowerShell)

Lo ejecuta alguien con **Owner** o **User Access Administrator** (o *Role Based Access Control Administrator*) en el
**Management Group** y que además sea **Workspace Admin** en los workspaces. Si no es la misma persona, que lo
ejecuten las dos con el mismo comando: cada una completa la parte para la que tiene permisos y lo que ya está hecho
no se repite.

```powershell
az login
.\grant-databricks-permissions.ps1 -IdentityClientId "PEGAR-AQUI-EL-CLIENT-ID" -ManagementGroupId "ID-DEL-MANAGEMENT-GROUP" -IncludeCost
```

Es el mismo Client ID que en el AKS (y normalmente el mismo Management Group). Añadiendo `-WhatIf` muestra lo que
haría sin cambiar nada. Otros alcances: `-SubscriptionId "<id>"`, `-SubscriptionIds "<id-1>","<id-2>"` o
`-AllSubscriptions`. Para limitarlo a unos workspaces: `-Workspaces "<suscripción>/<rg>/<workspace>"`.
`-SkipDatabricksGrants` da solo los roles de Azure y `-SkipUnityCatalog` no toca Unity Catalog. `-IncludeCost` hace
falta para el coste del periodo y para la sección de costes del informe.

Permisos que da (todos de solo lectura):

| Dónde | Permiso |
|---|---|
| Azure, Management Group | Reader (cubre también el RG gestionado `databricks-rg-*`) y, con `-IncludeCost`, Cost Management Reader |
| Cada workspace | Alta de la identidad como *service principal* (Entra ID managed) con `workspace-access` y `databricks-sql-access`, **sin admin** |
| Jobs, pipelines y SQL warehouses | `CAN_VIEW` en los que existen (no puede ejecutar ni arrancar nada) |
| Unity Catalog, cada catálogo | `BROWSE`, `USE_CATALOG`, `USE_SCHEMA` (solo metadatos, **sin** `SELECT` ni ficheros) |

**No hay nada que pegar en el `.py`.** El script descubre los workspaces del Management Group, da los permisos y al
final muestra un resumen por workspace que guarda en `databricks-access-summary.csv`. En la columna **Estado**:
`OK`; `SIN ACCESO: tu usuario no es Workspace Admin` (que lo ejecute un Workspace Admin de ese workspace);
`SIN ACCESO: no se llega al workspace (red privada o DNS)` (el informe saldrá solo con la parte de Azure);
`SIN INICIALIZAR` (abrirlo una vez con **Launch Workspace** y repetir). Volver a ejecutarlo es seguro y conviene
repetirlo de vez en cuando: los jobs, pipelines y warehouses nuevos no tienen `CAN_VIEW` hasta entonces. Los
permisos tardan 5–10 minutos en aplicarse.

> Un workspace donde la identidad no está dada de alta, o al que no se llega por red, sale en el informe con
> **In-workspace access** = `No` y el aviso **No access inside the workspace**, con el motivo, y conserva su revisión
> del lado Azure (ARM, red, recursos asociados, Advisor y costes); lo interno de Databricks queda *Not evaluated*.
> El alta a mano: en el workspace, **Settings → Identity and access → Service principals → Add → Microsoft Entra ID
> managed**, pegar el Client ID, marcar `workspace-access` y `databricks-sql-access` y dar `CAN_VIEW` en jobs,
> pipelines y warehouses.

### Paso 2. Editar el `.py`

Abrir `generate-databricks-dependency-report.py` y, en las constantes del principio del fichero, cambiar solo estos 3
valores:

```python
SRE_TENANT_ID = "<YOUR_SRE_AGENT_TENANT_ID>"              # -> vuestro tenant
TARGET_TENANT_ID = "<YOUR_TARGET_DATABRICKS_TENANT_ID>"   # -> el MISMO tenant
MANAGED_IDENTITY_CLIENT_ID = "<YOUR_SRE_UAMI_CLIENT_ID>"  # -> el Client ID del paso 1
```

Deben quedar vacíos `FEDERATED_APP_CLIENT_ID`, `KEYVAULT_OAUTH_SECRET_URI`, `CROSS_TENANT_CERT_KEYVAULT_URL` y
`CROSS_TENANT_CERT_NAME` (solo son para cross-tenant); `WORKSPACE_DEFAULTS` ya trae `auth_mode: "same_tenant_uami"`.
No hay lista de workspaces que rellenar: la entrada de ejemplo `<APPROVED_DATABRICKS_WORKSPACE_NAME>` de
`APPROVED_WORKSPACES` se ignora y `SUBSCRIPTION_ID` (`"<YOUR_TARGET_SUBSCRIPTION_ID>"`) puede quedarse como está.
Opcional: `CLIENT_NAME` (por defecto `"Customer"`), `CLIENT_LOGO_DATA_URI` y `CLIENT_LOGO_ALT`; una entrada en
`APPROVED_WORKSPACES` para ajustar un workspace concreto (por ejemplo `"environment": "PRODUCTION"`, con su
`resource_group` y `subscription_id`); `DISCOVERY_SUBSCRIPTION_IDS` para limitar el descubrimiento a algunas
suscripciones; y, para la sección de costes, `COST_METRIC` (`"AmortizedCost"` o `"ActualCost"`),
`COST_ALLOCATION_TAGS` (vuestras etiquetas de reparto, por defecto `team`, `project` y `cost_center`), los umbrales
`COST_*` y `REPORT_FOCUS = "costs"` para que el informe se abra por los costes.

### Paso 3. Crear el tool

Ir a **Build + configure → Agent Canvas → Create ▾ → Tool › → Python tool**.

- **Tool Name:** `databricks-dependency-report` (máximo 36 caracteres)
- **Description:**
  `Read-only Azure Databricks dependency mapping, configuration, security, FinOps and optimization for every workspace the agent can read: all, one subscription or named workspaces. Four complete artifacts or bounded source-qualified queries. Fails closed before authentication when setup is missing. No SQL, compute starts, source writes, IAM or tasks.`
- **Code:** pegar el `.py` editado.
- **Timeout (seconds):** `900`.
- No hay campo *Requirements* ni editor de parámetros: los **13 parámetros** salen de `def main(...)` al pegar el
  código (entre ellos `workspace_names` y `subscription`). El código no tiene lista de workspaces: acepta los que
  descubre.
- **Identity:** **Off**.
- En **Test playground** (cajas vacías) escribir `operation` = `list_workspaces`, `view` = `summary`,
  `classification`, `area`, `level`, `severity` y `status` = `all`, `limit` = `25` y `offset` = `0`, dejar vacías
  `workspace_name`, `workspace_names`, `workload_name` y `subscription` y pulsar **Test** (unos 2 segundos): deben
  salir vuestros workspaces con su suscripción y un bloque `"discovery": {"mode": "auto", …}`. Después,
  **Create tool**.

> Igual que en el AKS, el *Test playground* corta hacia los **100 segundos** (HTTP 504): probad ahí
> `list_workspaces` y lanzad los informes desde el chat (paso 6).

### Paso 4. Crear el skill

**Create ▾ → Skill**:

- **Primero** pegar `skills/databricks-dependency-live/SKILL.md`: rellena **Name** (`databricks-dependency-live`) y **Description**.
- **Después**, **Choose tools** → solo `databricks-dependency-report`.

### Paso 5. Crear el subagente

Botón **Create** (o **Create ▾ → Custom agent**):

- **Custom agent name:** `databricks-dependency-live`
- **Instructions:** el bloque de instrucciones de `subagent-instructions-and-prompts.md` (en inglés; ya incluye que
  responda en español).
- **Tool y skill:** solo los dos anteriores.

### Paso 6. Probar en un chat nuevo

**New chat** → `/agent` → `databricks-dependency-live` (chip **Agent: databricks-dependency-live**) → pegar uno de estos:

```
Lista los workspaces de Databricks que puedes ver, agrupados por suscripción.
```

```
Genera el informe de Databricks de todos los workspaces de todas las suscripciones con operation=report.
```

```
Genera el informe de Databricks de todos los workspaces de la suscripción <nombre o ID> con operation=report.
```

```
Genera el informe de Databricks de <ws-1>,<ws-2> con operation=report.
```

```
Del workspace <ws-1>, usa query con view=costs: ¿de dónde sale el coste de Databricks del último mes cerrado (DBU frente a infraestructura, clústeres, jobs, SQL warehouses y pools) y qué cambios ahorrarían más? Indica cómo se estima cada ahorro.
```

Sale **un solo informe en inglés** (HTML, JSON completo, CSV de hallazgos y CSV de dependencias) para toda la
selección, hasta 50 workspaces; con más, pedidlo por suscripción. El especialista lo resume en español. El HTML abre
con la vista de flota (**Azure Databricks fleet review**): arriba los filtros **Subscription**, **Workspace** y
**Search**; después los indicadores de los workspaces visibles (estado de la recogida, **No access inside the
workspace**, hallazgos, índice local, cobertura y **Period cost**), una fila por workspace con su **In-workspace
access** y los hallazgos. Al elegir un workspace se abre su revisión detallada (dependencias, cómputo, jobs, Unity
Catalog, costes y fuentes). Las preguntas concretas (`query`) admiten hasta 5 workspaces. Más prompts (dependencias,
cobertura, demo con `self_test`) en `subagent-instructions-and-prompts.md`.

**Costes de Databricks (sección 6 del informe y `view=costs`).** Explica de dónde sale el coste: el último mes cerrado
frente al anterior, DBU frente a infraestructura, los clústeres, jobs, SQL warehouses y pools que lo concentran (según
las etiquetas que Databricks pone en el cómputo y vuestras etiquetas de reparto) y la parte que ninguna etiqueta
explica; y cómo optimizarlo, con señales cuyo ahorro estimado indica su fórmula. Necesita **Cost Management Reader**
(`-IncludeCost` en el paso 1). El análisis detallado solo se hace en informes de **hasta 5 workspaces**; en informes
más grandes cada workspace conserva su coste del periodo. Opcional y desactivado por defecto:
`system_tables_warehouse_id` añade el detalle por ejecución y por usuario desde las tablas del sistema, pero consume
DBUs de un SQL warehouse existente.

---

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| Falta una suscripción, un AKS o un workspace en la lista o en el informe | La identidad no puede leerlo: volver a ejecutar el script del paso 1 en el Management Group (o con `-SubscriptionId "<id>"` si la suscripción no cuelga de él) y esperar 5–10 minutos. Un workspace de otro tenant no se descubre. |
| `no_clusters_visible` / `no_workspaces_visible` | Aún no hay permisos de lectura: ejecutar el script del paso 1 y esperar 5–10 minutos. |
| `configuration_required` | Quedan valores `<YOUR_…>` sin cambiar en el paso 2 (tenant y Client ID). |
| `identity_mismatch` | El tenant o el Client ID del paso 2 no son los de la identidad del agente. |
| Workspace con **In-workspace access** = `No` (**No access inside the workspace**) | Estado `denied` (HTTP 401/403): la identidad no está dada de alta en el workspace o le faltan permisos; que un Workspace Admin ejecute el script (`-Workspaces "<suscripción>/<rg>/<workspace>"`). Estado `unreachable` (`No (network)`): workspace privado o sin ruta de red desde el agente; es lo esperado y el informe mantiene la parte de Azure. |
| HTTP 504 hacia los 100 s en el *Test playground* | Es el límite del playground, no un fallo del tool: probar ahí `list_clusters` / `list_workspaces` y pedir los informes desde el chat (timeout de 900 s). |
| Coste **Throttled (HTTP 429)** o **Not available** (Databricks) o **Not evaluated** con el error `throttled` (AKS); sección de costes `Partial` | Cost Management limita las consultas cuando hay muchos recursos: ese coste es **desconocido, no cero**. Repetir el informe más tarde o pedir menos recursos (una suscripción). |
| La sección de costes dice que el análisis detallado se omitió | El informe tiene más de 5 workspaces: pedir un informe (o `query` con `view=costs`) de hasta 5. |
| Sección de costes `Denied` | Falta **Cost Management Reader**: volver a ejecutar el script del paso 1 con `-IncludeCost`. |
| `too_many_clusters` (más de 100) / `too_many_workspaces` (más de 50) | Pedir el informe por suscripción o por nombres. |
| `ambiguous_cluster_name` / `ambiguous_workspace_name` | El mismo nombre existe en dos suscripciones: añadir la suscripción en el prompt o usar el nombre con prefijo que devuelve la lista. |
| Workloads de AKS como *Not evaluated* | Es lo normal: la lectura de Kubernetes está desactivada por defecto (nota del paso 1 del AKS). |
| El nombre del tool se corta al escribirlo | El portal limita **Tool Name** a 36 caracteres y el nombre anterior `generate-databricks-dependency-report` (37 caracteres) se queda en `generate-databricks-dependency-repor`. Usar `databricks-dependency-report`. Si el tool ya se guardó con un nombre cortado, usar exactamente ese nombre guardado en el skill, en las instrucciones del subagente y en **Choose tools**. |

> El `README.md` de cada carpeta es la guía técnica completa en inglés, con capturas (casos 04 y 08 del repositorio
> público); las capturas del informe son del mismo informe que genera este kit. La de Databricks explica también el
> modo *cross-tenant*, que aquí **no** se necesita.

---

## Builder v3 (`00-sre-usecase-builder-v3/`)

No necesita permisos. Ver su `README.md`. En resumen:

1. **Tool** Python `sre-usecase-builder-kit` (**Create ▾ → Tool › → Python tool**):
   - **Code:** pegar `sre-usecase-builder-kit.py` sin editarlo.
   - **Timeout (seconds):** `300`.
   - **Identity:** **Off**.
   - **Test** con `operation` = `catalog` antes de **Create tool**.
2. **Skill** `sre-usecase-builder`: pegar `skills/sre-usecase-builder/SKILL.md` y **después** adjuntar ese tool.
3. **Subagente** `sre-usecase-builder`:
   - **Instructions:** las de `skills/subagent-instructions.md`.
   - **Tool y skill:** solo los dos anteriores.
