from app import create_app, init_mqtt_client, init_scheduler

app = create_app()

if __name__ == '__main__':
    print("🚀 Iniciando servicio backend de AmpereWatch...")
    init_mqtt_client(app)
    init_scheduler(app)
    app.run(host='0.0.0.0', port=5000, debug=False)
