# AIOps Guardian

A train-booking API on Kubernetes, watched by a **guardian** that tells normal
overload apart from real faults and fixes each one the right way:

| Diagnosis        | Guardian action                                   |
|------------------|---------------------------------------------------|
| Overload         | Raise the HPA floor; shrink search slots at max   |
| CPU hog          | Roll back if recently deployed, else restart      |
| Memory leak      | Rolling restart; roll back if recently deployed   |
| Bad release      | `helm rollback booking` and block the image tag   |
| Slow dependency  | Cache mode for `/search`; no scaling              |

It starts with ordered rules and moves to a random-forest classifier, with the
rules kept as a fallback. Changes ship through Jenkins → Docker Hub → Helm.
Secrets live in Vault, logs go to ELK and metrics to Prometheus.

> Status: Phase 0 (repository initialised). See the implementation guide for
> the 54-commit schedule.

## Quick start

```bash
git clone <repo-url> aiops-guardian
cd aiops-guardian
make help        # list every target
make versions    # compare your installed tools with the table below
```

## Pinned versions

Both members confirm these at commit 1. If a machine differs, update this table.

| Tool                         | Version                                       |
|------------------------------|-----------------------------------------------|
| Python / FastAPI             | 3.11 / 0.115 (one uvicorn worker per pod)     |
| Postgres                     | 16                                            |
| Minikube / Kubernetes        | 1.34 (Docker driver) / 1.31                   |
| Helm / Ansible               | 3.16 / 2.17                                   |
| Jenkins                      | LTS 2.479                                     |
| Elastic stack (all 4 parts)  | 8.15.3                                        |
| Prometheus chart             | `prometheus-community/prometheus` 25.x        |
| Vault chart                  | `hashicorp/vault` 0.28, dev mode              |
| k6 / scikit-learn            | 0.54 / 1.5                                    |

Never use `latest` for infrastructure images. The app image is also pushed as
`latest` for convenience, but deploys always use the commit SHA.

## Repository layout

```
aiops-guardian/
├── app/            # Booking API (FastAPI): search, book, payment, /health, /metrics
├── guardian/       # Collector, features, rules, ML classifier, actions, control loop
├── ml/             # Scenario runner, training script, data card, training data
├── helm/
│   ├── booking/    # App, Postgres, HPA
│   └── guardian/   # Guardian, ServiceAccount, RBAC, guardian-control ConfigMap
├── ansible/        # site.yml + roles: minikube, elk, monitoring, vault, app
├── elk/            # Docker Compose ELK, Logstash pipeline, Kibana dashboards
├── k8s/            # Filebeat DaemonSet
├── load/           # k6: smoke.js, steady.js, rush.js
├── demo/           # Notes for demo/bad-release and demo/leak branches
├── docs/           # Report, diagrams, demo script, setup guides
├── Jenkinsfile
├── docker-compose.dev.yml
├── .env.example
└── Makefile
```

Kubernetes namespaces: `booking` (app + Postgres), `guardian`, `monitoring`
(Prometheus), `vault`.

## Team conventions

| Member | Leads                                                    | Also commits to                                  |
|--------|----------------------------------------------------------|--------------------------------------------------|
| A      | Booking app, fault switches, guardian logic, ML          | Jenkins pipeline, `booking` chart, Kibana        |
| B      | Ansible, Minikube, Vault, ELK, Prometheus, guardian chart | App metrics/logging, load tests, guardian actions/RBAC |

- **Branching:** `main` is always deployable. Each commit row of the guide is
  made on a short branch `<member>/<phase>-<topic>` (e.g. `a/p1-search-queue`)
  and merged by PR. The other member reviews every PR.
- **Commit messages:** [Conventional Commits](https://www.conventionalcommits.org/)
  `type(scope): summary`. Types: `feat`, `fix`, `test`, `ci`, `build`,
  `infra`, `docs`, `chore`.
- **Before pushing:** run `make test`. Never break the pipeline on `main`.
- **Checkpoints:** each phase ends with a checkpoint both members verify
  together before moving on.
- **Stuck for more than half a day:** switch to the commit's listed fallback
  and move on.
- **Guardian safety:** keep the guardian in dry-run unless you are
  deliberately testing its actions.
