# Kubernetes — HPA & Helm

Ergänzung zum Lernleitfaden. Zwei Themen, die im Tagesgeschäft schnell relevant werden, sobald du echte Workloads betreibst.

---

## 1. Horizontal Pod Autoscaler (HPA)

### 1.1 Was tut der HPA?

Der HPA passt die **Anzahl der Replicas** eines Deployments (oder StatefulSets, ReplicaSets) automatisch an Last an. Klassisch nach **CPU-Auslastung**, optional nach Memory oder beliebigen Custom Metrics (Requests/sec, Queue-Länge, GPU-Util...).

```
        ┌─────────────────┐
Load ↑  │ Metrics Server  │ ← scrapes pod metrics every 15s
        └────────┬────────┘
                 ↓ reads
        ┌─────────────────┐
        │      HPA        │ ← compares current vs target
        └────────┬────────┘
                 ↓ updates spec.replicas
        ┌─────────────────┐
        │   Deployment    │ → ReplicaSet → Pods
        └─────────────────┘
```

Der HPA pollt alle 15s die Metriken, vergleicht mit dem Zielwert und passt die Replica-Zahl an. Standardalgorithmus:

```
desiredReplicas = ceil( currentReplicas × currentMetric / targetMetric )
```

Beispiel: 4 Pods, im Schnitt 80% CPU, Ziel 50% → `ceil(4 × 80 / 50) = 7` Pods.

### 1.2 Voraussetzungen

Drei Dinge müssen stimmen, sonst tut der HPA gar nichts:

1. **`metrics-server` läuft im Cluster.** Bei k3s standardmäßig dabei. Sonst:
   ```bash
   kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
   kubectl top pod                       # check it works
   kubectl top node
   ```

2. **Deployment hat `resources.requests` definiert.** CPU-Prozent wird gegen den Request berechnet — ohne Request gibt's keine Berechnungsbasis.
   ```yaml
   resources:
     requests:
       cpu: "100m"                       # 0.1 CPU = baseline for HPA percentage
       memory: "128Mi"
     limits:
       cpu: "500m"
       memory: "256Mi"
   ```

3. **Workload muss horizontal skalierbar sein.** Stateless APIs: ja. DBs ohne Sharding: nein.

### 1.3 Imperativ erstellen

```bash
kubectl autoscale deploy my-api \
  --cpu-percent=70 \
  --min=2 \
  --max=10
```

Damit existiert ein HPA, der zwischen 2 und 10 Pods skaliert, Ziel 70% CPU.

### 1.4 Deklarativ — der Production-Weg

```yaml
apiVersion: autoscaling/v2                    # v2 supports multiple metrics + custom
kind: HorizontalPodAutoscaler
metadata:
  name: my-api-hpa
spec:
  scaleTargetRef:                             # what to scale
    apiVersion: apps/v1
    kind: Deployment
    name: my-api-deployment
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization                   # percentage of requests
          averageUtilization: 70              # scale up if avg >70%
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:                                   # OPTIONAL: tune scaling speed
    scaleUp:
      stabilizationWindowSeconds: 0           # react fast on spike
      policies:
        - type: Percent
          value: 100                          # double pods at most per step
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300         # wait 5min before scaling down
      policies:
        - type: Percent
          value: 50                           # remove at most half pods per step
          periodSeconds: 60
```

### 1.5 HPA inspizieren

```bash
kubectl get hpa
# NAME          REFERENCE              TARGETS    MINPODS   MAXPODS   REPLICAS
# my-api-hpa    Deployment/my-api      45%/70%    2         10        3

kubectl describe hpa my-api-hpa               # full event log + decisions
```

Wenn `TARGETS` `<unknown>` zeigt: meistens `metrics-server` nicht installiert oder `resources.requests` fehlt im Deployment.

### 1.6 Custom Metrics — kurz erwähnt

Mit `prometheus-adapter` kannst du Prometheus-Metriken als HPA-Quelle nehmen:

```yaml
metrics:
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second        # any Prometheus metric
      target:
        type: AverageValue
        averageValue: "100"                   # scale at 100 req/s/pod
```

Für ML-Inferencing oft sinnvoller als CPU — eine Inference-API mit GPU-Backend ist nicht CPU-bound, sondern Queue-bound. Da skalierst du auf Queue-Tiefe oder Latenz.

### 1.7 Häufige Fallen

- **HPA flappt** (skaliert ständig hoch und runter): `stabilizationWindowSeconds` erhöhen, vor allem für Scale-Down.
- **CPU-Limit < CPU-Request × HPA-Target**: Pod kann das Target gar nicht erreichen → HPA skaliert ewig hoch. Limit großzügiger setzen.
- **Cold Starts**: Wenn neue Pods 30s zum Hochfahren brauchen, sind sie zur Spitze nutzlos. → `readinessProbe` korrekt setzen, sonst kriegen sie sofort Traffic; `minReplicas` so wählen, dass Spike abgefedert wird, bevor neue Pods da sind.
- **HPA + manuelles `kubectl scale`**: Sobald HPA aktiv ist, überschreibt er deine manuelle Skalierung. Nicht beides nutzen.

### 1.8 VPA und KEDA — kurz zur Einordnung

- **VPA (Vertical Pod Autoscaler)**: Skaliert Pod-Größe (CPU/RAM-Requests) statt Pod-Anzahl. Komplementär zu HPA, aber nicht für denselben Workload mischen.
- **KEDA**: Event-driven Autoscaling — skaliert auf 0 wenn keine Last, scale-from-zero. Liest Kafka-Lag, SQS-Queue-Tiefe, RabbitMQ etc. Für ML-Batch-Jobs und Async-Worker oft besser als nativer HPA.

---

## 2. Helm

### 2.1 Wozu Helm?

Sobald du dasselbe Deployment in **Dev / Staging / Prod** mit leichten Variationen ausrollst — andere Replica-Zahlen, andere Image-Tags, andere Hostnames im Ingress — wird YAML-Copy-Paste zur Hölle. Helm ist die Antwort:

- **Templating-Engine**: YAML mit Platzhaltern. Werte kommen aus `values.yaml`.
- **Package Manager**: `helm install`, `upgrade`, `rollback`, `uninstall` — wie `apt` für Kubernetes-Apps.
- **Charts** (= die Pakete): selbst geschrieben oder vom Hub (Bitnami, Artifact Hub).

Du installierst MLflow, Postgres, Prometheus etc. produktionsreif mit einem einzigen `helm install`-Befehl statt 20 Manifesten zu basteln.

### 2.2 Installation

```bash
# Linux
curl https://baltocdn.com/helm/signing.asc | sudo gpg --dearmor -o /usr/share/keyrings/helm.gpg
# ... or simpler:
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh && ./get_helm.sh

helm version
```

### 2.3 Bestehendes Chart benutzen — der schnellste Weg

```bash
# Add a repo (Bitnami has hundreds of well-maintained charts)
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Search what's available
helm search repo postgresql
helm search repo mlflow

# See what values you can override BEFORE installing
helm show values bitnami/postgresql > my-values.yaml
# ... edit my-values.yaml ...

# Install
helm install my-pg bitnami/postgresql \
  -f my-values.yaml \
  -n databases --create-namespace

# Inspect
helm list -A                                  # all releases across namespaces
helm status my-pg -n databases
helm get values my-pg -n databases            # what values were applied
helm get manifest my-pg -n databases          # what YAML actually got rendered

# Update
helm upgrade my-pg bitnami/postgresql -f my-values.yaml -n databases

# Rollback
helm history my-pg -n databases               # revision history
helm rollback my-pg 2 -n databases            # back to revision 2

# Remove
helm uninstall my-pg -n databases
```

`-f my-values.yaml` ist der wichtigste Flag — damit overridest du die Defaults des Charts ohne das Chart selbst zu forken.

### 2.4 Eigenes Chart bauen

```bash
helm create my-app                            # scaffolds a chart
```

Das erzeugt:

```
my-app/
├── Chart.yaml                # chart metadata (name, version, appVersion)
├── values.yaml               # default values
├── templates/                # YAML templates with {{ ... }} placeholders
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── _helpers.tpl          # reusable template snippets
│   └── NOTES.txt             # printed after install
└── charts/                   # subcharts (dependencies)
```

#### Beispiel: `Chart.yaml`

```yaml
apiVersion: v2
name: my-app
description: My FastAPI service
type: application
version: 0.1.0                                # CHART version (bump on chart changes)
appVersion: "1.2.3"                           # APP version (the docker image tag)
```

#### `values.yaml` — Defaults

```yaml
replicaCount: 3

image:
  repository: mircok90/my-api
  tag: "1.0.0"
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 8000

ingress:
  enabled: true
  host: api.example.com

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

env:
  LOG_LEVEL: INFO
```

#### `templates/deployment.yaml` — Template

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "my-app.fullname" . }}     # helper from _helpers.tpl
  labels:
    {{- include "my-app.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}        # from values.yaml
  selector:
    matchLabels:
      {{- include "my-app.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "my-app.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: app
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: {{ .Values.service.port }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          env:
            {{- range $key, $value := .Values.env }}
            - name: {{ $key }}
              value: {{ $value | quote }}
            {{- end }}
```

Die wichtigsten Template-Konstrukte:

| Syntax | Bedeutung |
|---|---|
| `{{ .Values.x }}` | Wert aus `values.yaml` |
| `{{ .Release.Name }}` | Name der Helm-Release (`helm install <name> ...`) |
| `{{ .Chart.Version }}` | Aus `Chart.yaml` |
| `{{- ... -}}` | Whitespace stripping (Bindestrich = strip) |
| `{{ if .Values.foo }}...{{ end }}` | Bedingung |
| `{{ range ... }}...{{ end }}` | Schleife |
| `{{ include "tpl.name" . }}` | Anderes Template einbinden |
| `\| nindent 4` | Pipe für Einrückung |
| `\| quote` | In Anführungszeichen setzen |

### 2.5 Vor dem Apply prüfen — wichtig!

```bash
# Lint — catches YAML errors
helm lint ./my-app

# Render templates locally without installing — see what WOULD be applied
helm template my-release ./my-app -f values-prod.yaml > rendered.yml
less rendered.yml

# Dry-run install via API server (validates against actual cluster schema)
helm install my-release ./my-app -f values-prod.yaml --dry-run --debug
```

Vor allem `helm template` ist Gold beim Lernen: Du siehst direkt, welche YAML aus deinem Chart rauskommt.

### 2.6 Multi-Environment-Pattern

```
my-app/
├── Chart.yaml
├── values.yaml                # sensible defaults
├── values-dev.yaml            # dev overrides
├── values-staging.yaml
├── values-prod.yaml
└── templates/...
```

Deploy:
```bash
helm upgrade --install my-app ./my-app -f values.yaml -f values-prod.yaml -n prod
```

Mehrere `-f` werden in Reihenfolge gemerged — späte überschreiben frühe. So hat dein Default-`values.yaml` die Common-Werte und `values-prod.yaml` nur die Unterschiede.

`upgrade --install` (statt `install`) ist idempotent: installiert wenn nicht da, upgradet wenn schon da. Standard-Pattern in CI.

### 2.7 Dependencies

Charts können andere Charts einbinden — z.B. dein App-Chart pulled Postgres + Redis als Subcharts:

```yaml
# Chart.yaml
dependencies:
  - name: postgresql
    version: "12.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: postgresql.enabled
  - name: redis
    version: "17.x.x"
    repository: https://charts.bitnami.com/bitnami
    condition: redis.enabled
```

```bash
helm dependency update                        # downloads to charts/
```

In `values.yaml` konfigurierst du die dependencies dann unter ihrem Namen:
```yaml
postgresql:
  enabled: true
  auth:
    database: mlflow
    username: mlflow
```

### 2.8 Häufige Gotchas

- **Secrets in `values.yaml` checked into Git**: Don't. Nutze `--set` für Secrets in CI, oder besser **sealed-secrets** / **external-secrets-operator** / **SOPS**.
- **Chart-Version vs. App-Version verwechseln**: `version` in `Chart.yaml` ist die Chart-Version (bumpst du bei Chart-Änderungen), `appVersion` ist die der App. Beim Upgraden bumpst du beide entsprechend.
- **`helm upgrade` bei Schema-Änderungen** (z.B. immutable Selectors): kann fehlschlagen. Manchmal Delete + Install nötig.
- **CRDs**: Helm verwaltet CRDs nur eingeschränkt. Charts mit CRDs (Operators) installieren CRDs in `crds/` — die werden bei `upgrade` **nicht** geupdatet, beim `uninstall` **nicht** entfernt. Deren Updates musst du manuell handhaben.

### 2.9 Was als Nächstes nach Helm?

- **Kustomize**: Alternative zu Helm — patcht Base-YAMLs ohne Templating. Bei kleinen Setups oft ausreichend, ohne Helm-Komplexität. `kubectl apply -k ./` baut's nativ ein.
- **Helmfile**: Orchestriert mehrere Helm-Releases (z.B. "deploy 5 charts in dieser Reihenfolge mit diesen values"). Praktisch für MLOps-Stack: `mlflow + minio + postgres + grafana + prometheus` in einem Rutsch.
- **Argo CD / Flux**: GitOps. Helm-Charts + values-Files in Git, Argo synct kontinuierlich Cluster ↔ Git.

---

## 3. HPA + Helm zusammen

In einem Helm-Chart machst du HPA optional:

```yaml
# values.yaml
autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

```yaml
# templates/hpa.yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "my-app.fullname" . }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "my-app.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
```

Dazu solltest du `replicaCount` im Deployment-Template **weglassen**, wenn HPA aktiv ist — sonst überschreibt sich beides gegenseitig. Lösung mit Conditional:

```yaml
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
```

Standard-Pattern — siehst du genau so im Default-`helm create` Scaffold.
