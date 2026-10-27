# Azure SRE Agent · Paquete de despliegue (AKS + Databricks)

Contenido:

| Carpeta | Qué es |
|---|---|
| `01-aks-well-architected-review/` | Caso AKS: revisión de arquitectura y configuración (solo lectura) con informe HTML/JSON/CSV |
| `02-databricks-dependency-review/` | Caso Databricks: dependencias, configuración, seguridad y FinOps (solo lectura), modo **un solo tenant** |
| `00-sre-usecase-builder-v3/` | Subagente *builder* para crear nuevos casos de uso |

---

## Caso AKS: paso a paso

### Paso 1. Permisos (una sola vez, PowerShell)

Lo ejecuta alguien con **Owner** o **User Access Administrator** en la suscripción.

1. [sre.azure.com](https://sre.azure.com) → su agente → **Settings → Azure settings → Managed Identity → Go to Identity** → en **Overview** copiar el **Client ID** (no el Object ID).
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

Ir a **Builder → Agent Canvas → Create → Tool → Python tool**.

- **Name:** `generate-aks-waf-report`
- **Description:**
  `Read-only AKS architecture/configuration review for the fixed approved clusters and associated resources. Collect source-qualified ARM, Kubernetes and optional ActualCost evidence; return offline HTML, complete JSON, failed-findings CSV and inventory CSV, or bounded typed queries. No remediation.`
- **Code:** pegar el `.py` completo, ya editado.
- **Requirements:** el contenido de `requirements.txt`.
- **Timeout:** `900`.
- **Parameters:** los 12 de `tool-parameters.schema.json`. En el enum de `cluster_name`, poner `""` más los nombres de vuestros AKS.
- **Identity:** **Off**, porque el código ya usa el Client ID.
- Para terminar: **Test** con `operation=list_clusters` y después **Create**.

### Paso 4. Crear el skill

Ir a **Create → Skill**.

- **Name:** `aks-waf-live`
- **Body:** pegar `skills/aks-waf-live/SKILL.md`.
- **Tool adjunto:** solo `generate-aks-waf-report`.

### Paso 5. Crear el subagente

Ir a **Create → Custom Agent**.

- **Name:** `aks-waf-live`
- **Instructions:** la sección de instrucciones de `subagent-instructions-and-prompts.md`.
- **Tools:** solo `generate-aks-waf-report`.
- **Skills:** solo `aks-waf-live`.

### Paso 6. Probar en un chat nuevo

```
@aks-waf-live Genera la revisión completa de arquitectura y configuración de AKS para <nombre-aks-1> con operation=report.
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

Ir a **Create → Tool → Python tool**.

- **Name:** `generate-databricks-dependency-report`
- **Description:**
  `Read-only Azure Databricks dependency, configuration, security and FinOps review for the fixed approved workspaces. Collect source-qualified ARM, Databricks workspace and Unity Catalog evidence; return offline HTML, complete JSON, findings CSV and inventory CSV, or bounded typed queries. No remediation.`
- **Code:** pegar el `.py` editado.
- **Requirements:** el contenido de `requirements.txt`.
- **Timeout:** `900`.
- **Parameters:** los 12 de `tool-parameters.schema.json`. En el enum de `workspace_name`, poner `""` más el nombre del workspace.
- **Identity:** **Off**.
- **Test** con `operation=list_workspaces` y después **Create**.

### Paso 4. Crear el skill

- **Name:** `databricks-dependency-live`
- **Body:** pegar `skills/databricks-dependency-live/SKILL.md`.
- **Tool adjunto:** solo `generate-databricks-dependency-report`.

### Paso 5. Crear el subagente

- **Name:** `databricks-dependency-live`
- **Instructions:** las de `subagent-instructions-and-prompts.md`.
- **Tool y skill:** solo los dos anteriores.

### Paso 6. Probar en un chat nuevo

```
@databricks-dependency-live Genera el informe completo de dependencias y configuración de Databricks para <workspace> con operation=report.
```

> El `README.md` de la carpeta es la guía técnica completa en inglés, con capturas. Explica
> también el modo *cross-tenant*, que aquí **no** se necesita.

---

## Builder v3 (`00-sre-usecase-builder-v3/`)

No necesita permisos. Ver su `README.md`. En resumen:

1. **Tool** Python `sre-usecase-builder-kit`:
   - **Code:** pegar `sre-usecase-builder-kit.py` sin editarlo.
   - **Timeout:** `300`.
   - **Identity:** **Off**.
2. **Skill** `sre-usecase-builder`: pegar `skills/sre-usecase-builder/SKILL.md` y adjuntar ese tool.
3. **Subagente** `sre-usecase-builder`:
   - **Instructions:** las de `skills/subagent-instructions.md`.
   - **Tool y skill:** solo los dos anteriores.
