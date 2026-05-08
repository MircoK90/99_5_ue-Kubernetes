# Eval — User API on Kubernetes

Sample solution. Use as reference if you get stuck.

## What's in here

| File | Purpose |
|---|---|
| `main.py` | Reworked FastAPI source — fixes original syntax errors, reads password from env, uses `text()` for SQLAlchemy 2.x compatibility, uses parameterised query in `/users/{id}` |
| `my-secret-eval.yml` | Secret holding the MySQL root password (`datascientest1234`, base64-encoded) |
| `my-deployment-eval.yml` | Deployment with 3 replicas, each Pod running both MySQL and the FastAPI container |
| `my-service-eval.yml` | ClusterIP Service exposing the API on port 8000 |
| `my-ingress-eval.yml` | Ingress routing external traffic to the Service |

## Key design decisions explained

**1. Why is the password not in the API code anymore?**
Original `main.py` had `mysql_password = ''` as a placeholder — the exercise explicitly says the password must NOT be hardcoded. So `main.py` reads it from env var `MYSQL_ROOT_PASSWORD`, which Kubernetes injects from the Secret using `secretKeyRef`. The Secret stores it base64-encoded (that's the `data:` field; `stringData:` would also work and skip the manual encoding step).

**2. Why localhost in the connection URL?**
Both containers (`mysql` and `api`) run inside the **same Pod**. Containers in a Pod share a network namespace, so they reach each other on `127.0.0.1`. No Service is needed between them. (If MySQL ran in a separate Deployment, you'd give it its own Service — say `mysql-service` — and use that DNS name instead.)

**3. Why 3 replicas of a database — isn't that bad practice?**
Yes. The exercise asks for 3 Pods each containing both containers, so we comply. In reality you'd run MySQL as a single StatefulSet with persistent storage (or use a managed DB), and have only the stateless API scale horizontally. The exercise is testing the multi-container Pod pattern, not production architecture.

**4. Why are the original `main.py` quotes and SQLAlchemy calls fixed?**
Original had three issues:
- `mysql_user = 'root` → missing closing quote (syntax error)
- `username: str = 'daniel` → same
- `connection.execute('SELECT * FROM Users;')` → fails on SQLAlchemy 2.x without `text()`
- `'SELECT * FROM Users WHERE Users.id = {};'.format(user_id)` → SQL injection. Replaced with parameterised query.

**5. Why pin `mysql+mysqldb://` instead of just `mysql://`?**
The driver is auto-resolved from `mysql://` on older SQLAlchemy versions, but newer ones require explicit driver. `mysqlclient` is what `requirements.txt` installs, which exposes itself as the `mysqldb` driver.

## Build & deploy

### 1. Build and push the API image

```bash
# From the directory containing the Dockerfile and a `files/` subdirectory
# holding main.py and requirements.txt:
docker build -t mircok90/user-api:1.0.0 .
docker login
docker push mircok90/user-api:1.0.0
```

Then update the image reference in `my-deployment-eval.yml` if you used a different tag/repo name.

### 2. Apply the manifests in order

The Secret has to exist before the Deployment references it:

```bash
kubectl apply -f my-secret-eval.yml
kubectl apply -f my-deployment-eval.yml
kubectl apply -f my-service-eval.yml
kubectl apply -f my-ingress-eval.yml
```

Or all at once (kubectl handles ordering for `apply` reasonably well):

```bash
kubectl apply -f .
```

### 3. Verify

```bash
kubectl get pod                   # should show 3 pods, READY 2/2 once warm
kubectl get svc
kubectl get ingress
kubectl describe pod <pod-name>   # if any READY column is not 2/2
kubectl logs <pod-name> -c api    # API logs
kubectl logs <pod-name> -c mysql  # MySQL logs
```

### 4. Test

```bash
# Quick test via port-forward (works without Ingress being fully wired up)
kubectl port-forward svc/my-api-service 8000:8000

# In another shell:
curl http://localhost:8000/status
# → 1

curl http://localhost:8000/users
# → list of users from the Main.Users table

curl http://localhost:8000/users/1
# → single user, or 404
```

If using the Ingress IP directly (`kubectl get ingress` → ADDRESS column):

```bash
curl http://<ingress-ip>/status
```

## Common pitfalls during this eval

- **Forgetting to push the rebuilt image to Docker Hub** — Pods will land in `ImagePullBackOff`. Check with `kubectl describe pod`.
- **Wrong image tag in the Deployment** — same symptom.
- **Using `apply` without first creating the Secret** — Pods will be `CreateContainerConfigError`. Apply Secret first.
- **MySQL container not yet ready when API makes first call** — `/status` works (no DB call), `/users` returns 500. Reload after a few seconds. In production you'd add a readiness probe on the API that pings the DB.
- **Mismatched labels** between Deployment selector, Pod template, and Service selector — Service finds 0 endpoints. Check with `kubectl get endpoints my-api-service`.

## What to upload

Per the exam instructions, archive these and upload:

```
main.py
my-deployment-eval.yml
my-service-eval.yml
my-ingress-eval.yml
my-secret-eval.yml
```

Plus the rebuilt Docker image pushed to Docker Hub (the Deployment references it).
