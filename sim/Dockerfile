FROM python:3.9-slim
WORKDIR /app
RUN pip install --no-cache-dir paho-mqtt
COPY sim_esp32.py .
CMD ["python3", "sim_esp32.py"]
