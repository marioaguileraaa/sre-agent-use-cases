# Azure SRE Agent · Paquete de despliegue (AKS + Databricks)

Contenido:

| Carpeta | Qué es |
|---|---|
| `01-aks-well-architected-review/` | Caso AKS: revisión de arquitectura y configuración (solo lectura) con informe HTML/JSON/CSV |
| `02-databricks-dependency-review/` | Caso Databricks: dependencias, configuración, seguridad y FinOps (solo lectura), modo **un solo tenant** |
| `00-sre-usecase-builder-v3/` | Subagente *builder* para crear nuevos casos de uso |

> **Actualización 16 de noviembre de 2026 — nombre del tool.** El portal limita hoy
> **Tool Name** a 36 caracteres, así que el tool de Databricks se llama ahora
> `databricks-dependency-report`; el fichero `.py` conserva su nombre,
> `generate-databricks-dependency-report.py`. Las capturas y evidencias de ejecuciones
> anteriores muestran el nombre anterior `generate-databricks-dependency-report`, creado
> mediante la API. Si el tool ya se creó con un nombre cortado, usar exactamente el nombre
> guardado en el skill, en las instrucciones del subagente y en **Choose tools**.

> **El portal ha cambiado (16 de noviembre de 2026).** Los pasos de abajo y las capturas de las
> guías de cada carpeta ya son los del portal de hoy:
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

Lo ejecuta alguien con **Owner** o **User Access Administrator** en la suscripción.

1. [Portal de Azure](https://portal.azure.com) → grupo de recursos del agente → su identidad administrada (`id-…`) → en **Overview** copiar el **Client ID** (no el Object ID). En el portal del agente ya no hay *Settings*.
2. En PowerShell, dentro de la carpeta `01-aks-well-architected-review`:

```powershell
az login
.\grant-aks-permissions.ps1 -IdentityClientId "PEGAR-AQUI-EL-CLIENT-ID"
```

Usa la suscripción activa y detecta **todos sus AKS**. Opcional: `-SubscriptionId "<id>"`,
`-Clusters "<rg>/<aks>"` para limitarlo, o `-IncludeCost` para costes.

Roles que asigna (todos de solo lectura):

| Rol | Dónde |
|---|---|
| Reader | Suscripción |
| Azure Kubernetes Service Cluster User Role | Cada AKS |
| Azure Kubernetes Service RBAC Reader | Cada AKS |
| Cost Management Reader (opcional) | Suscripción |

Al final el script muestra el bloque de configuración que hay que copiar en el `.py`.

> **Nota:** para leer los workloads del cluster, el AKS necesita **Entra ID + Azure RBAC**
> (el script lo indica). Si no lo tiene, el informe funciona igual, pero los workloads
> aparecerán como *No evaluado*.

### Paso 2. Editar el `.py`

Abrir `generate-aks-waf-report.py` y, en el bloque **CONFIGURACION** del principio,
pegar lo que mostró el script (`SUBSCRIPTION_ID`, `TENANT_ID`, `MANAGED_IDENTITY_CLIENT_ID`,
`APPROVED_CLUSTERS`). Opcional: `CLIENT_NAME` y `CLIENT_LOGO_DATA_URI` para poner vuestro nombre y logo en el informe.

### Paso 3. Crear el tool (portal)

Ir a **Build + configure → Agent Canvas → Create ▾** (la flecha, no el botón) **→ Tool › → Python tool**.

- **Tool Name:** `generate-aks-waf-report` (máximo 36 caracteres)
- **Description:**
  `Read-only AKS architecture/configuration review for the fixed approved clusters and associated resources. Collect source-qualified ARM, Kubernetes and optional ActualCost evidence; return offline HTML, complete JSON, failed-findings CSV and inventory CSV, or bounded typed queries. No remediation.`
- **Code:** pegar el `.py` completo, ya editado.
- **Timeout (seconds):** `900`.
- No hay campo *Requirements* ni editor de parámetros: los 12 parámetros salen de `def main(...)` al pegar el código, y el código solo acepta los nombres de `APPROVED_CLUSTERS`.
- **Identity:** **Off**, porque el código ya usa el Client ID.
- Para terminar: en **Test playground** (cajas vacías) escribir `operation` = `list_clusters` y pulsar **Test**; **Create tool** sigue en gris hasta entonces. Después, **Create tool**.

### Paso 4. Crear el skill

Ir a **Create ▾ → Skill**.

- **Primero** pegar `skills/aks-waf-live/SKILL.md` en el editor: rellena **Name** (`aks-waf-live`) y **Description**.
- **Después**, **Choose tools** → buscar → desplegar **PythonFunctionTool** → marcar solo `generate-aks-waf-report` → **Close panel**.

### Paso 5. Crear el subagente

Pulsar el botón **Create** (o **Create ▾ → Custom agent**).

- **Custom agent name:** `aks-waf-live`
- **Instructions:** la sección de instrucciones de `subagent-instructions-and-prompts.md`.
- **Tools:** solo `generate-aks-waf-report`.
- **Skills:** solo `aks-waf-live`.

### Paso 6. Probar en un chat nuevo

**New chat** → escribir `/agent` → elegir `aks-waf-live` (aparece el chip **Agent: aks-waf-live**) → pegar:

```
Genera la revisión completa de arquitectura y configuración de AKS para <nombre-aks-1> con operation=report.
```

Varios clusters a la vez: `cluster_names="<aks-1>,<aks-2>"` (sin espacios).

---

## Caso Databricks: paso a paso (un solo tenant)

SRE Agent y Databricks están en el **mismo tenant**. No hace falta App Registration,
credencial federada, Lighthouse ni secretos: la identidad del SRE Agent se usa directamente.

### Paso 1. Permisos (una sola vez, PowerShell)

Lo ejecuta alguien con **Owner** o **User Access Administrator** en la suscripción
y que además sea **Workspace Admin** en Databricks.

```powershell
az login
.\grant-databricks-permissions.ps1 -IdentityClientId "PEGAR-AQUI-EL-CLIENT-ID"
```

Es el mismo Client ID que el del AKS. El script detecta todos los workspaces de la suscripción.
Para limitarlo: `-Workspaces "<rg>/<workspace>"`.

Permisos que da (todos de solo lectura):

| Dónde | Permiso |
|---|---|
| Azure, suscripción | Reader (cubre también el RG gestionado `databricks-rg-*`) |
| Workspace Databricks | Añade la identidad como *service principal* (Entra ID managed), solo `workspace-access`, **sin admin** |
| Jobs, pipelines, SQL warehouses | `CAN_VIEW` (no puede ejecutar ni arrancar nada) |
| Unity Catalog, cada catálogo | `BROWSE`, `USE_CATALOG`, `USE_SCHEMA` (solo metadatos, **sin** `SELECT` ni ficheros) |

Al final el script muestra el bloque de configuración para pegar en el `.py`.

> Si quien ejecuta el script no es Workspace Admin, lo de Databricks se hace a mano desde
> el workspace: **Settings → Identity and access → Service principals → Add → Microsoft Entra ID managed**,
> pegar el Client ID y luego dar `CAN_VIEW` en jobs/pipelines/warehouses.
> Si no se hace, el informe sale igual con la parte Azure, y lo interno de Databricks aparece como *No evaluado*.

### Paso 2. Editar el `.py`

Abrir `generate-databricks-dependency-report.py` y, en el bloque **CONFIGURACION**,
pegar lo que mostró el script. Debe quedar `auth_mode: "same_tenant_uami"`, `SRE_TENANT_ID` y
`TARGET_TENANT_ID` con el **mismo** valor y `FEDERATED_APP_CLIENT_ID = ""`.

### Paso 3. Crear el tool

Ir a **Build + configure → Agent Canvas → Create ▾ → Tool › → Python tool**.

- **Tool Name:** `databricks-dependency-report` (máximo 36 caracteres)
- **Description:**
  `Read-only Azure Databricks dependency, configuration, security and FinOps review for the fixed approved workspaces. Collect source-qualified ARM, Databricks workspace and Unity Catalog evidence; return offline HTML, complete JSON, findings CSV and inventory CSV, or bounded typed queries. No remediation.`
- **Code:** pegar el `.py` editado.
- **Timeout (seconds):** `900`.
- No hay campo *Requirements* ni editor de parámetros: los 12 parámetros salen de `def main(...)` al pegar el código, y el código solo acepta los nombres de `APPROVED_WORKSPACES`.
- **Identity:** **Off**.
- En **Test playground** (cajas vacías) escribir `operation` = `list_workspaces` y pulsar **Test**; después, **Create tool**.

### Paso 4. Crear el skill

**Create ▾ → Skill**:

- **Primero** pegar `skills/databricks-dependency-live/SKILL.md`: rellena **Name** (`databricks-dependency-live`) y **Description**.
- **Después**, **Choose tools** → solo `databricks-dependency-report`.

### Paso 5. Crear el subagente

Botón **Create** (o **Create ▾ → Custom agent**):

- **Custom agent name:** `databricks-dependency-live`
- **Instructions:** las de `subagent-instructions-and-prompts.md`.
- **Tool y skill:** solo los dos anteriores.

### Paso 6. Probar en un chat nuevo

**New chat** → `/agent` → `databricks-dependency-live` (chip **Agent: databricks-dependency-live**) → pegar:

```
Genera el informe completo de dependencias y configuración de Databricks para <workspace> con operation=report.
```

### Problemas frecuentes

| Síntoma | Solución |
|---|---|
| El nombre del tool se corta al escribirlo | El portal limita hoy **Tool Name** a 36 caracteres y el nombre anterior `generate-databricks-dependency-report` (37 caracteres) se queda en `generate-databricks-dependency-repor`. Usar `databricks-dependency-report`. Si el tool ya se guardó con un nombre cortado, usar exactamente ese nombre guardado en el skill, en las instrucciones del subagente y en **Choose tools**. |

> El `README.md` de la carpeta es la guía técnica completa en inglés, con capturas. Explica
> también el modo *cross-tenant*, que aquí **no** se necesita.

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
