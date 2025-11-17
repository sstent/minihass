# Stage 1: Builder for all architectures
FROM --platform=$BUILDPLATFORM python:3.11-slim as builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final image using architecture-specific Python
ARG TARGETPLATFORM
FROM --platform=$TARGETPLATFORM python:3.11-slim

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

# Verify Python binary architecture
RUN python -c "import platform; print(f'Python arch: {platform.machine()}')"

CMD ["python", "app.py"]
