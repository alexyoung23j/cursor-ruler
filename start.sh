#!/bin/bash

# Start the backend (which will serve the static frontend)
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000 