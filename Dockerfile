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

ENV TWILIO_SID=ACdf4f31bbd04400119b690f6c7c09f53a
ENV TWILIO_AUTH=54c63729d62b0c710c6ffec7a61a696a

# Comando para ejecutar la app
CMD ["python", "app.py"]

