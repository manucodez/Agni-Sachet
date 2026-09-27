.PHONY: up down logs backend-shell db-shell migrate seed ingest pipeline test lint fmt weak-labels circularity-audit evaluate-verified

up:            ## Start postgis + backend + frontend
	docker compose up --build

down:          ## Stop and remove containers
	docker compose down

logs:          ## Tail logs from all services
	docker compose logs -f

backend-shell: ## Shell into the running backend container
	docker compose exec backend bash

db-shell:      ## psql into the postgis container
	docker compose exec postgis psql -U $${POSTGRES_USER:-agni} -d $${POSTGRES_DB:-agni_sachet}

migrate:       ## Run Alembic migrations inside the backend container
	docker compose exec backend alembic upgrade head

revision:      ## Autogenerate a new Alembic migration (usage: make revision m="add alerts table")
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

seed:          ## Load a small demo dataset so the dashboard isn't empty on first run
	docker compose exec backend python -m scripts.seed_demo_data

ingest:        ## Run one full ingestion pass (FIRMS + OSM + WorldCover + WorldPop + power plants)
	docker compose exec backend python -m app.jobs.run_ingestion

pipeline:      ## Run discovery -> anomaly -> classification -> graph -> risk, end to end
	docker compose exec backend python -m app.jobs.run_pipeline

weak-labels:       ## Bootstrap labels.csv from ingested hotspots via the deterministic rule (app/ml/weak_labeling.py)
	docker compose exec backend python -m scripts.generate_weak_labels

circularity-audit: ## Honesty check: how much of the model's accuracy is it just reciting the weak-labeling rule?
	docker compose exec backend python -m scripts.circularity_audit --labels data/processed/labeled_clusters.csv

evaluate-verified: ## Check the trained model against data/reference/verified_events.csv (real, cited incidents)
	docker compose exec backend python -m scripts.evaluate_verified_labels

test:          ## Run backend test suite
	docker compose exec backend pytest -v

lint:          ## Ruff lint check
	docker compose exec backend ruff check app

fmt:           ## Ruff autoformat
	docker compose exec backend ruff format app
