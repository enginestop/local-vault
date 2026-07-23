FROM node:24-alpine AS frontend
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements-runtime.txt /app/backend/requirements-runtime.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-runtime.txt
COPY backend /app/backend
COPY --from=frontend /app/backend/localvault/static /app/backend/localvault/static
ENV PYTHONPATH=/app/backend LOCALVAULT_HOST=0.0.0.0 LOCALVAULT_PORT=8741
EXPOSE 8741
CMD ["python", "/app/backend/run.py"]
