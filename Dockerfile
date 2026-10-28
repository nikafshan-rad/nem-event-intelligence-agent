# NEM Event Intelligence Agent
#
# Two-stage build: (1) install dependencies in a builder, (2) copy into a slim runtime.
# Data is built at container start (not at image build) because the raw AEMO/NASA files
# are ~100 MB and building them into the image would make it unnecessarily large.
#
# Usage:
#   docker compose up              # builds data + index on first run, then starts API + UI
#   docker compose up --build      # rebuild after code changes
#
# Or standalone:
#   docker build -t nem-agent .
#   docker run -p 8000:8000 -p 8501:8501 nem-agent

FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.lock pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir -r requirements.lock \
    && pip install --no-cache-dir --no-deps -e .


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

COPY . .

RUN pip install --no-cache-dir --no-deps -e .

VOLUME ["/app/data/raw", "/app/data/store", "/app/data/index", "/app/data/models"]

EXPOSE 8000 8501

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
