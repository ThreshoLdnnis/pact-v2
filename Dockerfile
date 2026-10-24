FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY apps/workbench/package*.json ./
RUN npm ci
COPY apps/workbench/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home pact
COPY pact/ pact/
COPY contracts/ contracts/
COPY services/ services/
COPY --from=web /web/dist apps/workbench/dist
RUN mkdir -p data && chown -R pact:pact data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "pact.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
