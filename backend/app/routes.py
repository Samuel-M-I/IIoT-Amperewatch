from flask import Blueprint, render_template
import sqlite3
import os

main_bp = Blueprint('main', __name__)
DB_PATH = os.path.join(os.path.dirname(__file__), '../corriente_data.db')

@main_bp.route('/')
def index():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT timestamp, rms FROM rms_readings ORDER BY id DESC LIMIT 15')
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        rows = []

    # Puedes retornar una vista HTML o renderizar una plantilla básica
    html_content = """
    <html>
        <head>
            <title>AmpereWatch Dashboard</title>
            <meta http-equiv="refresh" content="3">
            <style>
                body { font-family: Arial; background: #121212; color: #fff; text-align: center; padding-top: 50px; }
                table { margin: 0 auto; border-collapse: collapse; width: 60%; background: #1e1e1e; }
                th, td { border: 1px solid #333; padding: 10px; }
                th { background: #333; }
            </style>
        </head>
        <body>
            <h1>⚡ AmpereWatch IIoT - Monitor de Motor ⚡</h1>
            <h3>Últimas lecturas de Corriente RMS (10 Hz)</h3>
            <table>
                <tr><th>Timestamp</th><th>Corriente RMS (A)</th></tr>
                {% for row in rows %}
                <tr><td>{{ row[0] }}</td><td>{{ row[1] }} A</td></tr>
                {% endfor %}
            </table>
        </body>
    </html>
    """
    from flask import render_template_string
    return render_template_string(html_content, rows=rows)
