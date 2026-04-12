FROM python:3.11-slim

WORKDIR /app

# Dependencias do sistema para pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo da aplicacao
COPY app/ /app/
COPY templates/ /templates/

# Criar diretorio temporario
RUN mkdir -p /tmp/cnis

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
