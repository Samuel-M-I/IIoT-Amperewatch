FROM python:3.9-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar e instalar dependencias primero (para aprovechar el caché de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código modularizado del backend
COPY . .

# Exponer el puerto de Flask
EXPOSE 5000

# Comando para ejecutar la aplicación usando el nuevo run.py
CMD ["python3", "run.py"]
