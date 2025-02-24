FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install

COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY app app/

# Copy built frontend (now in the out directory after build)
COPY --from=frontend-builder /frontend/out ./frontend/out

# Cloud Run will provide the port
ENV PORT=8000

# Start both services using a shell script
COPY start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"] 