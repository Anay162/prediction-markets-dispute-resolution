# prediction-markets-dispute-resolution

AI-powered adversarial audit tool for prediction market contracts. Identifies resolution vulnerabilities before markets go live and produces a Resolution Clarity Score (0–100) with concrete rewrites for each issue found.

## What it does

Prediction market contracts fail to resolve cleanly for predictable reasons. This tool runs every contract through six adversarial analyzers — each embodying a different failure mode — and returns a structured vulnerability report with rewritten clauses that close each loophole.

**Six failure categories:**
1. **Source failure** — resolution source becomes unavailable or changes methodology
2. **Definitional ambiguity** — key terms undefined, preventing mechanical yes/no resolution
3. **Threshold gaming** — numeric thresholds manipulable or dependent on revised data
4. **Scope creep** — subject entity changes via M&A, delisting, or political withdrawal
5. **Timing ambiguity** — unspecified timezones, fiscal vs calendar year confusion
6. **Adversarial resolution** — language a bad-faith position holder can exploit textually

---

## Quick start

```bash
# 1. Clone and configure
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and OPENAI_API_KEY in .env

# 2. Start the full stack
docker compose up

# 3. Run migrations (first time only)
docker compose run api alembic upgrade head

# 4. Submit your first audit
curl -X POST http://localhost:8000/v1/audit \
  -H "X-API-Key: dev-insecure-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{
    "contract": {
      "question": "Will US GDP growth exceed 2% in 2025?",
      "resolution_criteria": "Resolves YES if GDP exceeds 2%.",
      "resolution_source": "https://bea.gov/gdp",
      "close_date": "2025-12-31"
    },
    "sync": false
  }'

# 5. Poll for results using the returned job_id
curl http://localhost:8000/v1/audit/{job_id}/status \
  -H "X-API-Key: dev-insecure-key-change-me"
```

---

## Architecture

```
POST /v1/audit
      │
      ▼
EntityExtractor          ← LLM parses contract into typed elements
      │
      ▼
Six Analyzers (parallel) ← Each runs an adversarial LLM prompt
  ├── SourceFailureAnalyzer
  ├── DefinitionalAmbiguityAnalyzer
  ├── ThresholdGamingAnalyzer
  ├── ScopeCreepAnalyzer
  ├── TimingAmbiguityAnalyzer
  └── AdversarialResolutionAnalyzer
      │
      ▼
EnrichmentClient         ← Source probe, entity lookup, dispute similarity
      │
      ▼
ClauseRewriter           ← LLM rewrites each vulnerable clause
      │
      ▼
DiffGenerator            ← Word-level diff for each rewrite
      │
      ▼
RCSCalculator            ← Deterministic score: 100 − Σ(penalties)
      │
      ▼
ReportOutput             ← JSON + PDF
```

---

## File structure

```
contract-auditor/
├── api/                    FastAPI application
│   ├── auth/               API key hashing, rate limiting
│   ├── routers/            audit, contracts, reports, health
│   └── schemas/            Pydantic input/output models
├── core/                   Audit engine
│   ├── analyzers/          Six vulnerability analyzers + runner
│   ├── enrichment/         Source probe, entity lookup, dispute search
│   ├── parser/             Entity extractor → ParsedContract
│   ├── pipeline.py         End-to-end orchestrator
│   ├── prompts/            System prompts for each analyzer
│   ├── report/             Report builder + PDF renderer
│   ├── rewriter/           Clause rewriter + diff generator
│   └── scoring/            RCS calculator
├── data/                   Data layer
│   ├── cache/              Redis client
│   ├── embeddings/         Embedding encoder
│   ├── migrations/         Alembic migrations (001–004)
│   ├── models/             SQLAlchemy ORM models
│   ├── repositories/       DB read/write logic
│   └── scrapers/           Polymarket, UMA, Manifold, Augur scrapers
├── infra/
│   ├── k8s/                Kubernetes manifests
│   └── nginx/              Reverse proxy config
├── integrations/
│   ├── llm/                Anthropic + OpenAI client with retry
│   └── external_apis/      Wayback, OpenCorporates, SEC, Polygon
├── scripts/                Ops CLI tools
├── tests/
│   ├── evals/              LLM quality eval harness + golden set
│   ├── fixtures/           Sample contracts (clean, ambiguous, adversarial…)
│   ├── integration/        Pipeline + API integration tests
│   └── unit/               Parser, analyzer, scoring, rewriter tests
└── worker/                 Celery tasks + beat schedule
```

---

## API reference

### `POST /v1/audit`

Submit a contract for audit.

**Request body:**
```json
{
  "contract": {
    "question": "string",
    "resolution_criteria": "string",
    "resolution_source": "string (URL or description)",
    "close_date": "YYYY-MM-DD",
    "platform": "generic | kalshi | polymarket | manifold | metaculus"
  },
  "sync": false
}
```

Set `sync: true` for small contracts (<2000 chars) to get a blocking response with the full report. Default is async.

**Response (async):**
```json
{
  "job_id": "uuid",
  "status": "pending",
  "estimated_seconds": 30
}
```

### `GET /v1/audit/{job_id}/status`

Poll job status. When `status == "complete"`, the full `report` object is included.

### `GET /v1/reports/{report_id}/pdf`

Download the audit report as a PDF.

### `GET /v1/contracts`

List all audited contracts. Supports `?platform=kalshi&limit=50&offset=0`.

---

## Resolution Clarity Score

```
RCS = max(0, 100 − Σ(penalty × category_multiplier))

Penalties:
  Critical: 25 pts   High: 12 pts   Medium: 5 pts   Low: 2 pts

Category multipliers (default):
  adversarial_resolution: 1.2×
  threshold_gaming: 1.1×
  all others: 1.0×

Hard caps:
  ≥1 critical finding  → score capped at 50
  ≥2 critical findings → score capped at 25

Score labels:
  85–100  Well-specified
  70–84   Minor issues
  50–69   Moderate risk
  30–49   High risk
  0–29    Critical — do not publish
```

Weights are tunable via `scripts/calibrate_weights.py` once you have real outcome data.

---

## Development

```bash
# Run unit tests (no external services needed)
pytest tests/unit -v

# Run all tests with services
docker compose up postgres redis -d
pytest tests/ -v

# Run the eval harness against the golden set
python -m tests.evals.run_evals --verbose

# Seed the dispute corpus (run once after migrations)
python -m scripts.seed_disputes --limit 200

# Calibrate scoring weights against outcome data
python -m scripts.calibrate_weights --dry-run

# Export a report to PDF
python -m scripts.export_report --report-id <uuid>

# Backfill embeddings after model change
python -m scripts.backfill_embeddings --table disputes
```

---

## Environment variables

See `.env.example` for the full list with descriptions. Required:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Primary LLM (Claude) |
| `OPENAI_API_KEY` | Embeddings + fallback LLM |
| `DATABASE_URL` | PostgreSQL with pgvector (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis for cache and job status |
| `SECRET_KEY` | JWT / session signing |
| `API_KEY_SALT` | API key hashing salt |

---

## Deployment

**Docker Compose (single server):**
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Kubernetes:**
```bash
# Create namespace and secrets first
kubectl create namespace contract-auditor
kubectl apply -f infra/k8s/secrets.yaml   # Fill in real values first

# Deploy
kubectl apply -f infra/k8s/api-deployment.yaml
kubectl apply -f infra/k8s/worker-deployment.yaml
kubectl apply -f infra/k8s/ingress.yaml
```

Use `infra/k8s/postgres.yaml` and `infra/k8s/redis.yaml` for self-hosted data stores, or point `DATABASE_URL` / `REDIS_URL` at managed services (RDS + ElastiCache recommended for production).
