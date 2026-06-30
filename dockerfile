FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify Python binary architecture
RUN python -c "import platform; print(f'Python arch: {platform.machine()}')"

CMD ["python", "app.py"]
