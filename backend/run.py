from app import create_app, init_mqtt_client

# Crear la aplicación Flask usando el patrón de factoría
app = create_app()

if __name__ == '__main__':
    print("🚀 Iniciando servicio backend de AmpereWatch...")
    
    # Inicializar y arrancar el cliente MQTT en segundo plano
    init_mqtt_client(app)
    
    # Ejecutar el servidor Flask escuchando en todas las interfaces (puerto 5000)
    app.run(host='0.0.0.0', port=5000, debug=False)
