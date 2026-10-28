#!/usr/bin/env bash
set -euo pipefail

DATA_READY=0
if [ -f data/store/snapshot.json ] && [ -f data/index/index_manifest.json ]; then
    DATA_READY=1
fi

build_data() {
    echo "[entrypoint] Building data store from public AEMO/NASA sources..."
    python -m nem_agent.cli build-data
    echo "[entrypoint] Building document index..."
    python -m nem_agent.cli build-index
    echo "[entrypoint] Data build complete."
}

case "${1:-serve}" in
    serve)
        if [ "$DATA_READY" -eq 0 ]; then
            build_data
        fi
        echo "[entrypoint] Starting FastAPI on :8000 and Streamlit on :8501..."
        python -m uvicorn nem_agent.api:app --host 0.0.0.0 --port 8000 &
        python -m streamlit run app/streamlit_app.py \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.headless true &
        wait -n
        ;;
    api)
        if [ "$DATA_READY" -eq 0 ]; then
            build_data
        fi
        exec python -m uvicorn nem_agent.api:app --host 0.0.0.0 --port 8000
        ;;
    app)
        if [ "$DATA_READY" -eq 0 ]; then
            build_data
        fi
        exec python -m streamlit run app/streamlit_app.py \
            --server.port 8501 \
            --server.address 0.0.0.0 \
            --server.headless true
        ;;
    build)
        build_data
        ;;
    test)
        exec python -m pytest -q
        ;;
    demo)
        if [ "$DATA_READY" -eq 0 ]; then
            build_data
        fi
        exec python -m nem_agent.cli demo
        ;;
    shell)
        exec bash
        ;;
    *)
        exec "$@"
        ;;
esac
