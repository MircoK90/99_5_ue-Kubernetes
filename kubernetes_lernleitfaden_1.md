# Kubernetes Lernleitfaden

> Strukturierter Durchgang durch die Kubernetes-Grundlagen — aufbauend auf Docker-Kenntnissen.
> Code-Kommentare in Englisch, Erklärungen in Deutsch.

---

## 0. Mental Model: Wieso K8s über Docker hinausgeht

Mit Docker startest du Container auf **einer** Maschine. `docker run` ist imperativ: "Mach jetzt diesen Container auf." Wenn der Container abstürzt, bleibt er aus. Wenn die Maschine voll ist, ist Schluss.

Kubernetes ist im Kern **deklarativ und Cluster-orientiert**:

- Du beschreibst den **gewünschten Zustand** ("ich will 10 nginx-Pods, immer erreichbar, mit dieser Konfiguration").
- Kubernetes' **Controller** vergleichen den Ist- mit dem Soll-Zustand und reagieren laufend (Pod weg → neuer Pod; Knoten tot → reschedule).
- Das Cluster verteilt die Arbeit über mehrere **Nodes** (Worker-Maschinen).

Das ist der entscheidende mentale Sprung gegenüber Docker. Du sagst nicht mehr "starte mir Container X auf Maschine Y", sondern "sorg dafür, dass X läuft — wo ist mir egal".

### Die Hauptobjekte auf einer Postkarte

| Objekt | Wofür | Analog zu Docker |
|---|---|---|
| **Pod** | Kleinste deploybare Einheit, enthält 1+ Container | Ungefähr ein `docker run` |
| **Deployment** | Verwaltet Pods (Replikas, Updates, Rollback) | Ähnlich Docker Compose `replicas` + Update-Logik |
| **ReplicaSet** | Garantiert N gleiche Pods | Wird vom Deployment erzeugt — direkt anfasst man's selten |
| **Service** | Stabile virtuelle IP/DNS für eine Pod-Gruppe | Ähnlich Compose-Service-Name als DNS |
| **Ingress** | HTTP-Router von außen ins Cluster | Reverse Proxy (Nginx) vor Compose-Services |
| **Namespace** | Logische Trennung von Ressourcen | Etwa wie Compose-Projekte |
| **PV / PVC** | Persistenter Speicher | `volumes:` + Volume-Mount |
| **ConfigMap / Secret** | Konfiguration & Geheimnisse | `.env`-Datei + Docker Secrets |
| **StatefulSet** | Pods mit stabiler Identität & Storage | Etwa wie ein dedizierter DB-Container mit Volume |

**Imperative vs. deklarative Konfiguration** — beides geht:

- **Imperativ:** `kubectl run nginx --image=nginx` — schnell für Tests.
- **Deklarativ:** YAML-Manifest + `kubectl apply -f file.yml` — der Produktions-Weg, weil versionierbar.

Faustregel: Im Lernen/Experimentieren imperativ, in echten Projekten **immer YAML in Git**.

---

## 1. kubectl — Das Schweizer Taschenmesser

### 1.1 Syntax

```
kubectl [COMMAND] [TYPE] [NAME] [FLAGS]
```

- **COMMAND**: was du tun willst — `get`, `describe`, `create`, `apply`, `delete`, `edit`, `exec`, `logs`, `scale`, `rollout`, `expose`...
- **TYPE**: welche Ressourcenart — `pod`, `deployment`, `service`, `pv`, `pvc`, `secret`, `cm` (configmap), `rs` (replicaset), `ns` (namespace)...
- **NAME**: Name der konkreten Ressource (case-sensitive).
- **FLAGS**: zusätzliche Optionen — `-n <namespace>`, `-o yaml`, `--replicas=5`...

### 1.2 Befehle, die du täglich brauchst

```bash
# === Inspecting ===
kubectl get pods                          # list pods in default namespace
kubectl get pods -A                       # all namespaces
kubectl get all                           # everything in current namespace
kubectl get pod my-pod -o yaml            # full YAML of an object
kubectl describe pod my-pod               # detailed status + events (debugging gold)
kubectl logs my-pod                       # stdout/stderr of pod
kubectl logs my-pod -f                    # follow logs (like tail -f)
kubectl logs my-pod -c my-container       # if pod has multiple containers

# === Creating/Modifying ===
kubectl apply -f manifest.yml             # create or update from YAML (idempotent)
kubectl create -f manifest.yml            # create only (errors if exists)
kubectl delete -f manifest.yml            # delete from YAML
kubectl edit deploy my-deploy             # open in $EDITOR, applies on save
kubectl scale deploy my-deploy --replicas=5

# === Interacting ===
kubectl exec -it my-pod -- bash           # shell into a container
kubectl exec my-pod -- ls /etc            # one-off command
kubectl port-forward pod/my-pod 8080:80   # local 8080 -> pod 80

# === Discovery ===
kubectl api-resources                     # list all object types + their shortnames
kubectl explain deployment.spec           # docs for any field, recursive with .field.subfield
```

`describe` und `logs` sind deine zwei wichtigsten Debug-Tools. **Wann immer was nicht läuft, fang mit `describe` an** — das Events-Feld am Ende sagt dir meistens direkt, was kaputt ist (ImagePullBackOff, CrashLoopBackOff, Pending wegen kein Knoten passt...).

---

## 2. Pods

Ein **Pod** ist die kleinste deploybare Einheit. Meist ein Container drin, manchmal mehrere (Sidecar-Pattern: z.B. App + Log-Shipper).

### 2.1 Imperativ erstellen

```bash
# Quick & dirty — only for testing
kubectl run nginx --image=nginx
kubectl get pod
```

Output:
```
NAME    READY   STATUS    RESTARTS   AGE
nginx   1/1     Running   0          2m
```

Spalten lesen:
- **READY**: `1/1` = 1 von 1 Container im Pod läuft.
- **STATUS**: `Running`, `Pending`, `CrashLoopBackOff`, `ImagePullBackOff`, `Completed`...
- **RESTARTS**: wie oft der Container neu gestartet wurde — `>0` ist meist ein Warnsignal.

### 2.2 Deklarativ via YAML

Jedes K8s-Objekt hat dieselbe Grundstruktur — vier Top-Level-Keys:

```yaml
apiVersion: v1          # API group + version (varies per kind)
kind: Pod               # what kind of object
metadata:               # name, labels, annotations, namespace
  name: wordpress
spec:                   # the desired state — content depends on kind
  containers:
    - name: wordpress
      image: wordpress
      ports:
        - containerPort: 80
```

Anwenden:
```bash
kubectl apply -f wordpress.yml
kubectl get pod
kubectl delete pod wordpress
```

**Merke:** Pods erstellst du in der Praxis **nie** direkt. Wenn der Pod stirbt, kommt nichts hinterher — er ist nicht überwacht. Du benutzt **Deployments** (oder StatefulSets/DaemonSets), die Pods für dich verwalten.

---

## 3. Deployments & ReplicaSets

### 3.1 Was macht ein Deployment?

Ein Deployment beschreibt:

1. **Welche Pods** (Template).
2. **Wie viele** Replicas.
3. **Wie wird geupdated** (RollingUpdate, Recreate).

Es erzeugt im Hintergrund einen **ReplicaSet**, der wiederum die Pods erzeugt:

```
Deployment  →  ReplicaSet  →  Pod, Pod, Pod, ...
```

Wenn du das Image-Tag im Deployment änderst, erstellt das Deployment einen neuen ReplicaSet, fährt Pods aus dem neuen hoch und Pods aus dem alten runter — ohne Downtime.

### 3.2 Imperativ

```bash
kubectl create deployment nginx-deployment --image=nginx --replicas=10
kubectl get all   # see deployment, replicaset, and 10 pods
```

Du erkennst die Pods an ihrem Namen: `nginx-deployment-<rs-hash>-<pod-id>`.

### 3.3 Deklarativ — der Produktions-Weg

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: web
spec:
  replicas: 10
  selector:
    matchLabels:
      app: web                  # MUST match template.metadata.labels below
  strategy:
    type: RollingUpdate          # default — alternative: Recreate (downtime!)
    rollingUpdate:
      maxSurge: 2                # how many extra pods during update
      maxUnavailable: 1          # how many pods may be down during update
  template:                      # this is the Pod template
    metadata:
      labels:
        app: web                 # selector above must match this
    spec:
      containers:
        - name: nginx
          image: nginx:1.25
          ports:
            - containerPort: 80
```

**Wichtig:** `spec.selector.matchLabels` **muss** mit `spec.template.metadata.labels` matchen. Sonst findet das Deployment seine eigenen Pods nicht. Das ist einer der häufigsten Anfänger-Stolpersteine.

### 3.4 Selbstheilung erleben

```bash
kubectl get pod
kubectl delete pod nginx-deployment-<some-id>
kubectl get pod                  # within seconds: a new pod replaces it
```

Das ist der Witz an Controllern: Du hast einen Soll-Zustand definiert (10 Replicas), und das Cluster sorgt selbständig dafür, dass er gehalten wird.

### 3.5 Skalieren

```bash
# Imperative
kubectl scale deploy nginx-deployment --replicas=3

# Or edit YAML and apply again
```

### 3.6 Rollouts & Rollbacks

```bash
kubectl rollout status deploy/nginx-deployment       # is the rollout done?
kubectl rollout history deploy/nginx-deployment      # version history
kubectl rollout undo deploy/nginx-deployment         # rollback to previous
kubectl rollout restart deploy/nginx-deployment      # restart all pods (e.g. to pick up new ConfigMap)
```

---

## 4. Services — Pods erreichbar machen

### 4.1 Das Problem

Pods sind **flüchtig**. Sie haben IPs, aber wenn ein Pod neu gestartet wird, bekommt er eine andere IP. Du kannst dich nicht direkt an Pod-IPs hängen — sonst bricht alles bei jedem Restart.

**Service = stabile virtuelle IP + DNS-Name + Load-Balancing** über eine Gruppe von Pods, ausgewählt über **Labels** (Selector-Pattern).

### 4.2 Selectors — das Schlüsselkonzept

Jeder Pod kann beliebige `labels` tragen (siehe oben: `app: web`). Ein Service hat einen `selector`, der diese Labels matcht. Der Service routet Traffic auf alle gematchten Pods, ohne dass du IPs kennen musst.

```bash
kubectl get pod --show-labels   # see what labels your pods have
```

### 4.3 Drei Service-Typen

#### ClusterIP (Default — nur intern)

Interne IP innerhalb des Clusters. Für Service-zu-Service-Kommunikation.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: ClusterIP                  # default — can be omitted
  selector:
    app: web                       # match pods with label app=web
  ports:
    - protocol: TCP
      port: 80                     # port of the service
      targetPort: 8080             # port on the pod
```

Imperativ:
```bash
kubectl expose deploy nginx-deployment --port=80 --type=ClusterIP
```

Andere Pods im Cluster können dann unter `my-service:80` (DNS!) oder unter der ClusterIP zugreifen.

#### NodePort (extern via Knoten-IP)

Öffnet einen Port auf **jedem** Cluster-Knoten. Erreichbar von außen unter `<NodeIP>:<NodePort>`. Port-Range standardmäßig 30000–32767.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-nodeport-svc
spec:
  type: NodePort
  selector:
    app: web
  ports:
    - protocol: TCP
      port: 80                     # cluster-internal port
      targetPort: 80               # pod port
      nodePort: 30000              # external port on every node (optional, else random)
```

Gut für Dev/Test, in Produktion meist nicht direkt — da nimmt man LoadBalancer oder Ingress.

#### LoadBalancer (extern via Cloud-LB)

Setzt auf NodePort auf, fordert zusätzlich einen externen Load Balancer an. Bei Cloud-Providern (AWS, GCP, Azure) wird automatisch ein LB provisioniert. On-Prem brauchst du **MetalLB** oder ähnliches.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-lb-svc
spec:
  type: LoadBalancer
  selector:
    app: web
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
```

### 4.4 Service-Typen — wann was?

| Typ | Use-Case |
|---|---|
| **ClusterIP** | Interne Services (DBs, internal APIs) |
| **NodePort** | Dev/Test, Quick-and-dirty external |
| **LoadBalancer** | Production-external in Cloud |
| **Ingress** (separates Objekt!) | HTTP(S)-Routing, mehrere Services hinter einer IP |

Für HTTP/HTTPS in Prod nutzt man fast immer **Ingress** (siehe Abschnitt 10).

### 4.5 Service vom Pod aus testen

```bash
# Spawn a temporary debug pod with curl
kubectl run curl --image=curlimages/curl -it --rm -- sh
# Then inside:
curl my-service                  # uses cluster DNS
curl 10.43.139.215               # or use the ClusterIP directly
```

---

## 5. Namespaces

**Logische Cluster-Unterteilung** — wie virtuelle Mini-Cluster im selben echten Cluster. Ressourcennamen müssen pro Namespace eindeutig sein, aber nicht über Namespaces hinweg.

### 5.1 Default Namespaces

```bash
kubectl get namespace          # short: kubectl get ns
```

```
default          # your stuff lands here unless specified
kube-system      # the control plane components — DON'T TOUCH
kube-public      # publicly readable cluster info
kube-node-lease  # node heartbeat objects
```

### 5.2 Eigenen Namespace erstellen und nutzen

```bash
kubectl create namespace mlops-dev

# Run things in a namespace
kubectl get pod -n mlops-dev
kubectl apply -f deployment.yml -n mlops-dev

# Or set namespace inside the manifest
```

```yaml
metadata:
  name: my-deployment
  namespace: mlops-dev          # pin this object to a namespace
```

### 5.3 Default-Namespace wechseln (Komfort)

```bash
kubectl config set-context --current --namespace=mlops-dev
# now all kubectl commands target mlops-dev without -n
```

### 5.4 Wann Namespaces sinnvoll sind

- **Team-Trennung** (Frontend-Team vs. ML-Team).
- **Environment-Trennung** im selben Cluster (dev / staging — aber Prod meist eigenes Cluster).
- **Resource Quotas** — pro Namespace begrenzen.
- **RBAC** — Berechtigungen pro Namespace vergeben.

**Was Namespaces nicht sind:** Echte Multi-Tenancy. Pods können in andere Namespaces hineinkommunizieren (es sei denn, du blockst mit Network Policies). Für harte Isolation braucht es separate Cluster.

### 5.5 Welche Ressourcen sind namespaced?

```bash
kubectl api-resources              # column NAMESPACED says true/false
```

Nicht-namespaced (cluster-weit): **Nodes, PersistentVolumes, StorageClasses, Namespaces selbst, ClusterRoles**.

---

## 6. Storage — Daten überleben Pod-Restarts

### 6.1 Das Konzept in einem Satz

Ein **PersistentVolume (PV)** ist Speicherplatz im Cluster. Ein **PersistentVolumeClaim (PVC)** ist eine Anforderung an Speicherplatz. Ein Pod mountet einen **PVC** als Volume — und Kubernetes verbindet den PVC mit einem passenden PV.

```
Pod  →  PVC (declares "I need 10Gi RWO")
                    ↓ binding
                   PV (actual 10Gi storage somewhere)
```

Eine **StorageClass** kann das Ganze automatisieren: Sie provisioniert PVs **on demand**, sobald ein PVC kommt — du musst keine PVs mehr von Hand anlegen.

### 6.2 AccessModes

| Mode | Bedeutung |
|---|---|
| **ReadWriteOnce (RWO)** | Ein Knoten kann lesen+schreiben (mehrere Pods auf dem Knoten ok) |
| **ReadWriteMany (RWX)** | Mehrere Knoten können lesen+schreiben (z.B. NFS) |
| **ReadOnlyMany (ROX)** | Mehrere Knoten lesen nur |
| **ReadWriteOncePod** | Nur **ein** Pod im ganzen Cluster — strikteste Isolation |

Welche Modes gehen, hängt vom Storage-Backend ab. Block-Storage (EBS, GCE PD) ist meist RWO; File-Storage (NFS, EFS) kann RWX.

### 6.3 PV manuell anlegen (selten — meist via StorageClass)

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: my-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  hostPath:                       # ONLY for single-node testing!
    path: /mnt/data
  storageClassName: slow
```

```bash
kubectl apply -f pv.yml
kubectl get pv
```

### 6.4 PVC + StorageClass — der echte Workflow

Welche StorageClasses existieren?
```bash
kubectl get storageclass
```

PVC schreiben:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path     # k3s default; on AWS often "gp2" / "gp3"
  resources:
    requests:
      storage: 128Mi               # how much you need
```

```bash
kubectl apply -f pvc.yml
kubectl get pvc
kubectl get pv                     # a PV was auto-created and bound!
```

### 6.5 PVC im Pod mounten

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  containers:
    - name: nginx
      image: nginx
      volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html   # path inside container
  volumes:
    - name: data                              # name referenced by volumeMounts
      persistentVolumeClaim:
        claimName: my-pvc                     # the PVC we created above
```

Persistenz testen:
```bash
kubectl exec -it my-pod -- bash
echo "MIRCO TEST" > /usr/share/nginx/html/index.html
exit

kubectl delete pod my-pod
kubectl apply -f pod.yml          # recreate

kubectl exec -it my-pod -- cat /usr/share/nginx/html/index.html
# Output: MIRCO TEST  →  data survived!
```

### 6.6 Praxistipp für ML-Workloads

Für trainings-Daten und Model-Artefakte willst du in der Regel:

- **RWX** (NFS, EFS) wenn mehrere Worker parallel auf Daten zugreifen.
- **RWO** auf SSDs (IOPS!) für DB-Backings (Postgres, MLflow-Backend).
- **Object Storage außerhalb K8s** (S3, MinIO) für große, immutable Artefakte — dann nur S3-Credentials per Secret in den Pod.

In deinem Rakuten-Setup mit MinIO ist genau Letzteres der Pattern: MinIO speichert die ~250K Bilder, Pods brauchen kein PVC dafür — sie greifen über S3-API zu.

---

## 7. Secrets & ConfigMaps

Beide haben **denselben Zweck**: Konfiguration in Pods reichen, ohne sie ins Image zu backen. Unterschied:

- **ConfigMap**: nicht-sensible Daten (Config-Files, Feature-Flags, URLs). Klartext.
- **Secret**: sensible Daten (Passwörter, API-Keys, Tokens). Base64-kodiert, optional verschlüsselt-at-rest.

> Wichtig: Base64 ist **keine** Verschlüsselung — nur Encoding. Sicherheit kommt durch RBAC, etcd-Encryption-at-Rest und Vermeidung von Secrets in Git.

### 7.1 Secret erstellen

#### Aus Literalen (imperativ — am häufigsten)

```bash
kubectl create secret generic db-credentials \
  --from-literal=MYSQL_USER=mlflow \
  --from-literal=MYSQL_PASSWORD='Sup3rS3cret!'
```

#### Aus Datei

```bash
kubectl create secret generic tls-cert \
  --from-file=tls.crt \
  --from-file=tls.key
```

#### Per YAML

Wert vorher base64-encoden:
```bash
echo -n 'Datascientest2023@!!!' | base64
# RGF0YXNjaWVudGVzdDIwMjNAISE=
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mariadb-rootpass
type: Opaque
data:
  password: RGF0YXNjaWVudGVzdDIwMjNAISE=    # base64 of the actual password
```

### 7.2 Secret inspizieren / dekodieren

```bash
kubectl get secret db-credentials
kubectl describe secret db-credentials              # only sizes shown, not values
kubectl get secret db-credentials -o yaml           # base64 values

# Decode a single key
kubectl get secret db-credentials \
  -o jsonpath='{.data.MYSQL_PASSWORD}' | base64 --decode
```

### 7.3 ConfigMap erstellen

```bash
# From literal
kubectl create configmap app-config \
  --from-literal=ENVIRONMENT=production \
  --from-literal=LOG_LEVEL=INFO

# From file (key = filename, value = file content)
kubectl create configmap mariadb-config \
  --from-file=max_allowed_packet.cnf
```

YAML:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  ENVIRONMENT: production
  LOG_LEVEL: INFO
  config.json: |                    # multi-line file content
    {
      "feature_x": true,
      "max_workers": 4
    }
```

### 7.4 In Pods nutzen — drei Wege

#### A) Einzelne Env-Variable aus Secret/ConfigMap

```yaml
spec:
  containers:
    - name: app
      image: my-app:1.0
      env:
        - name: DB_PASSWORD                          # env var name in container
          valueFrom:
            secretKeyRef:
              name: db-credentials                   # the Secret's name
              key: MYSQL_PASSWORD                    # the key inside it
        - name: ENVIRONMENT
          valueFrom:
            configMapKeyRef:
              name: app-config
              key: ENVIRONMENT
```

#### B) Alle Keys auf einmal als Env-Variablen

```yaml
spec:
  containers:
    - name: app
      image: my-app:1.0
      envFrom:
        - secretRef:
            name: db-credentials                     # all keys become env vars
        - configMapRef:
            name: app-config
```

Praktisch wenn du z.B. 10 Konfig-Werte auf einen Schlag injecten willst.

#### C) Als Datei mounten (Volume)

Für Config-Files oder Zertifikate, die als Datei vorliegen müssen:

```yaml
spec:
  containers:
    - name: mariadb
      image: mariadb:10.4
      volumeMounts:
        - name: db-config
          mountPath: /etc/mysql/conf.d              # files appear here
  volumes:
    - name: db-config
      configMap:
        name: mariadb-config
        items:
          - key: max_allowed_packet.cnf            # key in the ConfigMap
            path: max_allowed_packet.cnf            # filename inside mountPath
```

Result: `/etc/mysql/conf.d/max_allowed_packet.cnf` enthält den Wert des Keys. Das Gleiche funktioniert mit Secrets (ersetze `configMap:` durch `secret:` und `name:` durch `secretName:`).

### 7.5 ConfigMap geändert — was nun?

Pods sehen Änderungen in **gemounteten Volumes** automatisch (mit ein paar Sekunden Delay). Aber **Env-Variablen werden beim Start gesetzt** und ändern sich nie. Wenn du eine ConfigMap-basierte Env-Variable änderst, musst du Pods neu starten:

```bash
kubectl rollout restart deploy my-deployment
```

Das ist auch der Grund, warum man kritische Settings lieber als Volume mountet als als Env-Variable.

---

## 8. StatefulSets (am MariaDB-Beispiel)

**Deployments** sind perfekt für stateless Apps — Pod 1 und Pod 2 sind austauschbar. Aber bei einer DB? Pod 1 ist der Master, Pod 2 ist eine Replica, sie haben verschiedene Daten — Reihenfolge zählt, Identität zählt.

Hier kommen **StatefulSets** ins Spiel:

- **Stabile Pod-Namen**: `mysql-0`, `mysql-1`, `mysql-2` (statt random hashes).
- **Stabiler PV per Pod**: jeder Pod hat sein eigenes persistentes Volume, das auch nach Restart wieder genau ihm zugewiesen wird.
- **Geordnetes Hochfahren**: `mysql-0` zuerst, dann `mysql-1`, dann `mysql-2`.

### 8.1 Komplettes Beispiel — MariaDB mit Secret + ConfigMap

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mariadb
  labels:
    app: mariadb
spec:
  serviceName: mariadb              # headless service for stable DNS
  replicas: 1
  selector:
    matchLabels:
      app: mariadb
  template:
    metadata:
      labels:
        app: mariadb
    spec:
      containers:
        - name: mariadb
          image: docker.io/mariadb:10.4
          ports:
            - containerPort: 3306
          # --- single env var from a Secret key ---
          env:
            - name: MYSQL_ROOT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: mariadb-rootpass
                  key: password
          # --- bulk env vars from another Secret ---
          envFrom:
            - secretRef:
                name: mariadb-user-credentials       # MYSQL_USER + MYSQL_PASSWORD
          volumeMounts:
            - name: data
              mountPath: /var/lib/mysql
            - name: config
              mountPath: /etc/mysql/conf.d           # MariaDB reads any *.cnf here
      volumes:
        - name: data
          emptyDir: {}                                # NOT persistent — see note below!
        - name: config
          configMap:
            name: mariadb-config
            items:
              - key: max_allowed_packet.cnf
                path: max_allowed_packet.cnf
```

**Note:** `emptyDir` überlebt Pod-Restart **nicht**. Für echte DBs nutzt man `volumeClaimTemplates` (StatefulSet-spezifisch — erzeugt automatisch ein PVC pro Pod):

```yaml
spec:
  # ... rest as above ...
  volumeClaimTemplates:                   # auto-creates a PVC per pod replica
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: local-path
        resources:
          requests:
            storage: 5Gi
```

Im `volumeMounts` referenzierst du dann `name: data` und das Volume kommt automatisch.

### 8.2 Werte verifizieren

```bash
# Check env vars are set
kubectl exec -it mariadb-0 -- env | grep MYSQL

# Check config file mount
kubectl exec -it mariadb-0 -- cat /etc/mysql/conf.d/max_allowed_packet.cnf

# Connect to DB and check setting
kubectl exec -it mariadb-0 -- mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "SHOW VARIABLES LIKE 'max_allowed_packet';"
```

---

## 9. Health Checks (Probes)

Kubernetes weiß nicht, ob deine App **wirklich** funktioniert — nur, ob der Container-Prozess läuft. Probes sind die Brücke.

### 9.1 Drei Probe-Typen

| Probe | Frage | Was passiert bei Fehlschlag |
|---|---|---|
| **livenessProbe** | "Lebt der Container noch?" | K8s **killt und restartet** den Container |
| **readinessProbe** | "Kann der Container Traffic annehmen?" | Pod wird **aus Service-Endpoints entfernt** (kein Restart) |
| **startupProbe** | "Ist der Start abgeschlossen?" | Liveness/Readiness werden ignoriert, bis Startup grün ist |

**Mental Model:**
- Liveness sagt: "Wenn die App eingefroren ist, hilft nur Neustart." → Restart.
- Readiness sagt: "Die App rödelt gerade einen großen Index, bitte keine Anfragen." → Aus dem LB nehmen, aber nicht killen.

### 9.2 Probe-Methoden

| Methode | Beispiel | Wann |
|---|---|---|
| `httpGet` | GET auf einen Pfad, prüft 2xx/3xx | HTTP-Apps (REST, FastAPI) |
| `tcpSocket` | TCP-Connect auf Port | DBs, generische TCP-Services |
| `exec` | Shell-Command, exit code 0 = ok | Custom Health-Logik |

### 9.3 Beispiel — beides kombiniert

```yaml
spec:
  containers:
    - name: app
      image: my-fastapi:1.0
      ports:
        - containerPort: 8000

      # === Did the container even finish booting? ===
      startupProbe:
        httpGet:
          path: /health
          port: 8000
        failureThreshold: 30           # 30 * 10s = 5 min boot tolerance
        periodSeconds: 10

      # === Is the container alive? Restart if not ===
      livenessProbe:
        httpGet:
          path: /health
          port: 8000
        initialDelaySeconds: 5         # wait this long after start
        periodSeconds: 10              # check every N seconds
        failureThreshold: 3            # N failures => restart container
        timeoutSeconds: 1

      # === Should this pod receive traffic right now? ===
      readinessProbe:
        httpGet:
          path: /ready                 # often a separate, "deeper" check
          port: 8000
        initialDelaySeconds: 5
        periodSeconds: 3
        failureThreshold: 3
```

### 9.4 Häufige Fehler

- **Liveness zu aggressiv** → endlose Restart-Schleife → `CrashLoopBackOff`. Setze `initialDelaySeconds` großzügig.
- **`/health` und `/ready` gleichgesetzt** → bei DB-Ausfall startet die App neu, anstatt nur aus dem LB zu fliegen. Trenne sie semantisch:
  - `/health` (liveness): "Bin ich nicht im Deadlock?" — nur App-interne Checks.
  - `/ready` (readiness): "Kann ich jetzt sinnvoll antworten?" — inkl. DB-Connection, externe Deps.
- **HTTP-Probe auf einer App, die HTTPS erzwingt** → 301-Redirect zählt als Erfolg, aber 401 als Fehlschlag. Achte auf Status-Codes.

---

## 10. End-to-End: Eine FastAPI deployen

Setzen wir alles zusammen. Eine einfache FastAPI mit `/status`, `/environment`, `/predict` Endpunkten.

### 10.1 Deployment

```yaml
# my-api.yml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-sentiment-deployment
  labels:
    app: my-sentiment-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-sentiment-api
  template:
    metadata:
      labels:
        app: my-sentiment-api
    spec:
      containers:
        - name: api
          image: datascientest/fake-api:1.0.0
          ports:
            - containerPort: 8000
```

```bash
kubectl apply -f my-api.yml
kubectl get deploy
# my-sentiment-deployment   3/3   3   3   48s
```

### 10.2 Service (ClusterIP — intern)

```yaml
# my-svc.yml
apiVersion: v1
kind: Service
metadata:
  name: my-sentiment-service
  labels:
    app: my-sentiment-api
spec:
  type: ClusterIP
  selector:
    app: my-sentiment-api
  ports:
    - port: 8001                      # service port (different from container, on purpose)
      protocol: TCP
      targetPort: 8000                # pod port
```

```bash
kubectl apply -f my-svc.yml
```

Jetzt erreichbar **innerhalb** des Clusters unter `my-sentiment-service:8001`.

### 10.3 Ingress (HTTP-Router von außen)

```yaml
# my-ingress.yml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-sentiment-ingress
spec:
  defaultBackend:
    service:
      name: my-sentiment-service
      port:
        number: 8001
```

Mit Routing nach Pfad/Host (richtige Produktion):
```yaml
spec:
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /sentiment
            pathType: Prefix
            backend:
              service:
                name: my-sentiment-service
                port:
                  number: 8001
```

```bash
kubectl apply -f my-ingress.yml
kubectl get ingress
# my-sentiment-ingress  <none>  *  192.168.49.2  80  17m
```

### 10.4 ConfigMap für `ENVIRONMENT_TYPE`

```bash
kubectl create configmap my-config-map \
  --from-literal=ENVIRONMENT_TYPE=production
```

Im Deployment einbinden — nur die relevante Stelle:

```yaml
      containers:
        - name: api
          image: datascientest/fake-api:1.0.0
          ports:
            - containerPort: 8000
          envFrom:                          # all keys of the ConfigMap as env vars
            - configMapRef:
                name: my-config-map
```

```bash
kubectl apply -f my-api.yml
# Test: curl http://<ingress-ip>/environment  =>  {"environment": "production"}
```

ConfigMap geändert? **Pods restarten:**
```bash
kubectl rollout restart deploy my-sentiment-deployment
```

### 10.5 Secret für sensible Werte

```bash
kubectl create secret generic my-secret --from-literal=my-key=my-value
```

Im Deployment:
```yaml
      containers:
        - name: api
          image: datascientest/fake-api:1.0.0
          env:
            - name: ENVIRONMENT_TYPE         # name of env var in container
              valueFrom:
                secretKeyRef:
                  name: my-secret             # the Secret
                  key: my-key                 # the key inside it
```

### 10.6 Lokal testen via Port-Forward

Wenn Ingress noch nicht steht oder du nur schnell testen willst:
```bash
kubectl port-forward svc/my-sentiment-service 8001:8001
# Now: curl localhost:8001/status  =>  {"status": 1}
```

Das ist **gold** zum Debuggen. Funktioniert auch direkt auf Pod-Ebene:
```bash
kubectl port-forward pod/my-sentiment-deployment-xxxxx 8000:8000
```

---

## 11. Cheat Sheet

### 11.1 Befehle, die du auswendig brauchst

```bash
# Cluster
kubectl get nodes
kubectl cluster-info

# Pods
kubectl get pod                                # default ns
kubectl get pod -A                             # all namespaces
kubectl get pod -o wide                        # +IP, +node
kubectl describe pod <name>                    # debug events
kubectl logs <pod>                             # logs
kubectl logs <pod> -f                          # follow
kubectl logs <pod> --previous                  # logs of crashed previous instance
kubectl exec -it <pod> -- bash

# Deployments
kubectl get deploy
kubectl scale deploy <name> --replicas=5
kubectl rollout status deploy/<name>
kubectl rollout history deploy/<name>
kubectl rollout undo deploy/<name>
kubectl rollout restart deploy/<name>

# Services
kubectl get svc
kubectl expose deploy <name> --port=80 --type=ClusterIP

# Apply / delete
kubectl apply -f file.yml
kubectl apply -f ./manifests/                  # whole directory
kubectl delete -f file.yml

# Storage
kubectl get pv,pvc,storageclass

# Configs
kubectl get cm
kubectl get secret
kubectl create configmap NAME --from-literal=K=V --from-file=path
kubectl create secret generic NAME --from-literal=K=V

# Debugging
kubectl describe <kind> <name>
kubectl get events --sort-by='.lastTimestamp'
kubectl explain <kind>.spec.field

# Port-forward (life-saver for debugging)
kubectl port-forward svc/<name> 8080:80
kubectl port-forward pod/<name> 8080:8080
```

### 11.2 YAML-Boilerplates

#### Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: NAME
spec:
  replicas: 3
  selector:
    matchLabels:
      app: NAME
  template:
    metadata:
      labels:
        app: NAME
    spec:
      containers:
        - name: NAME
          image: IMAGE:TAG
          ports:
            - containerPort: 8000
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
```

#### Service (ClusterIP)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: NAME-svc
spec:
  selector:
    app: NAME
  ports:
    - port: 80
      targetPort: 8000
```

#### Ingress
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: NAME-ingress
spec:
  rules:
    - host: HOST.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: NAME-svc
                port:
                  number: 80
```

#### PVC
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: NAME-pvc
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-path
  resources:
    requests:
      storage: 1Gi
```

### 11.3 Mentale Modelle zum Mitnehmen

1. **Soll-Zustand statt Befehle.** Du beschreibst, was sein soll. Kubernetes kümmert sich um den Weg dahin. Wenn etwas kaputt geht, frag nicht "wie repariere ich es", sondern "wie korrigiert das Cluster sich selbst".

2. **Labels & Selectors sind das Bindemittel.** Services finden Pods nicht über Namen, sondern über Labels. Deployments finden ihre Pods über Labels. Wenn etwas nicht zusammenfindet, sind fast immer Labels schuld.

3. **Drei Schichten zwischen Pod und Welt.** Pod → Service → Ingress. Jede Schicht hat einen Job: Pod = Workload, Service = stabile interne Adresse, Ingress = Außenwelt-Routing.

4. **`describe` und Events sind die Wahrheit.** Wenn `get` sagt "Pending" oder "CrashLoopBackOff", liegt der Grund im `describe`-Output unter Events. **Da fängst du an, nicht beim Googeln.**

5. **Stateful ist anders.** Deployments für stateless. StatefulSets + PVCs für DBs, MLflow-Backends, sonst was mit Persistenz und stabiler Identität.

6. **Konfiguration nie ins Image.** ConfigMaps für non-sensitive, Secrets für sensitive. Image ist immutable, Config ist environment-spezifisch.

---

## 12. Was als Nächstes?

Wenn diese Grundlagen sitzen, sind die nächsten Schritte:

- **Helm** — Templating für YAML. Sobald du dasselbe Deployment in dev/staging/prod variiert deployst, willst du Helm.
- **Network Policies** — Firewall-Regeln zwischen Pods.
- **HPA (Horizontal Pod Autoscaler)** — automatische Replicas-Skalierung nach CPU/Memory/Custom-Metrics.
- **Resource Quotas + Limits** — vermeiden, dass ein Team das Cluster monopolisiert.
- **RBAC** — wer darf was im Cluster.
- **Operators / CRDs** — eigene Custom Resources (z.B. ein `MLflowExperiment`-Objekt).
- **Service Mesh** (Istio, Linkerd) — mTLS, Tracing, Traffic-Policies — meist erst bei richtig vielen Services relevant.
- **Argo CD / Flux** — GitOps. YAML in Git ist die Source of Truth, der Cluster zieht sich automatisch.

Für dein MLOps-Setup speziell relevant:
- **Kubeflow Pipelines** oder **Argo Workflows** für Trainings-Pipelines auf K8s.
- **KServe / Seldon** für Model-Serving mit Auto-Scaling.
- **NVIDIA GPU Operator** für GPU-Scheduling auf Kubernetes (statt Docker-GPU-Compose).
