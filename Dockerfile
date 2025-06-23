FROM python:3.8-slim

# Instala las dependencias necesarias para opencv-python (libGL)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Crea y usa el directorio de la app
WORKDIR /app

# Copia archivos del proyecto
COPY . /app

# Instala las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Expone el puerto
EXPOSE 5000

# Comando para ejecutar la app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]
