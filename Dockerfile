FROM docker.io/library/node:22-alpine AS ui
WORKDIR /ui
COPY frontend/ ./
RUN if [ -f package.json ]; then npm ci && npm run build; else mkdir -p dist; fi

FROM docker.io/library/python:3.12-slim
COPY --from=docker.io/library/docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker.io/docker/compose-bin:v2.29.7 /docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /app
COPY pyproject.toml ./
COPY backend/ backend/
RUN pip install --no-cache-dir .
COPY catalog/ catalog/
COPY --from=ui /ui/dist frontend/dist
EXPOSE 8080
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
