# NEM Event Intelligence Agent — reproducible entry points. All targets run from a clean checkout.
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
SYSTEM_PY ?= python3
REGION ?= SA1
API_PORT ?= 8000
APP_PORT ?= 8501

.PHONY: help setup probe verify data data-check index demo api app smoke lint typecheck test eval retrieval-eval refresh-check sources eval-live live-smoke safety rolloff-sim ml clean-derived

help:
	@echo "make setup      - create .venv and install pinned dependencies (requirements.lock)"
	@echo "make probe      - G0: rediscover publisher files and write data/source_selection.json (network)"
	@echo "make verify     - G0: verify the committed selection against the publisher"
	@echo "make data       - G1: fetch the selected AEMO/NASA files and build the Parquet/DuckDB store"
	@echo "make index      - G3: fetch the public document corpus and build the hybrid (FTS5 + embedding) index"
	@echo "make demo       - run the replay investigation for the primary real event and write artifacts/"
	@echo "make api / app  - start FastAPI (port $(API_PORT)) / Streamlit (port $(APP_PORT))"
	@echo "make smoke      - start the API, POST the real-event question, validate, stop"
	@echo "make lint typecheck test eval safety  (make eval-live / live-smoke need OPENAI_API_KEY)"
	@echo "make ml         - optional separate time-series experiment (our model, not AEMO's)"

setup:
	$(SYSTEM_PY) -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.lock
	$(PIP) install -q --no-deps -e .
	@$(PY) -c "import nem_agent, sys; print('nem_agent', nem_agent.__version__, 'python', sys.version.split()[0])"

probe:
	$(PY) scripts/source_probe.py --output data/source_selection.json

verify:
	$(PY) scripts/verify_selection.py data/source_selection.json --allow-cached --allow-rolled-off --report artifacts/g0_verify.json

data:
	$(PY) -m nem_agent.cli build-data

data-check:
	$(PY) -m nem_agent.cli data-check

index:
	$(PY) -m nem_agent.cli build-index

demo:
	$(PY) -m nem_agent.cli demo

api:
	$(PY) -m uvicorn nem_agent.api:app --host 0.0.0.0 --port $(API_PORT)

app:
	$(PY) -m streamlit run app/streamlit_app.py --server.port $(APP_PORT) --server.address 0.0.0.0 --server.headless true

smoke:
	$(PY) scripts/smoke_api.py --port 8765

lint:
	$(PY) -m ruff check src tests scripts app

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m nem_agent.cli eval --mode replay --out artifacts/eval/offline.json

refresh-check:
	$(PY) -m nem_agent.cli refresh-check --eval

sources:
	$(PY) -m nem_agent.cli sources

retrieval-eval:
	$(PY) -c "import json; from nem_agent.evaluation.retrieval_eval import evaluate; open('artifacts/eval/retrieval_eval.json', 'w').write(json.dumps(evaluate(), indent=2) + '\\n')"

safety:
	$(PY) -m nem_agent.cli safety-suite

eval-live:
	@test -n "$$OPENAI_API_KEY" || (echo "OPENAI_API_KEY not set: hosted evaluation is UNVERIFIED" && exit 2)
	$(PY) -m nem_agent.cli eval --mode live --budget-usd $${NEM_AGENT_EVAL_BUDGET_USD:-1.00} --out artifacts/eval/live.json

live-smoke:
	$(PY) -m nem_agent.cli live-smoke

rolloff-sim:
	$(PY) scripts/simulate_rolloff.py --home /tmp/nem_rolloff_home --out artifacts/rolloff_simulation.json

ml:
	$(PY) -m nem_agent.ml.experiment --out artifacts/ml/experiment.json

clean-derived:
	rm -rf data/store data/index data/case_notes artifacts/traces
