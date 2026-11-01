const REFRESH_MS = 1000;
const aviso = document.getElementById('aviso');

function mostrarAviso(texto) {
    aviso.textContent = texto;
    aviso.hidden = !texto;
}

// Si la librería de gráficas no cargó, lo decimos claramente en vez de quedarnos mudos.
if (typeof Chart === 'undefined') {
    mostrarAviso('⚠️ No se cargó Chart.js. Verifica que existe static/js/vendor/chart.umd.js ' +
                 'y que dashboard.html lo carga desde ahí (no desde un CDN externo).');
    throw new Error('Chart.js no está cargado');
}

const rmsChart = new Chart(document.getElementById('rmsChart').getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [{ label: 'Corriente RMS (A)', data: [], borderColor: '#007bff', tension: 0.1 }] },
    options: { responsive: true, scales: { y: { beginAtZero: true, suggestedMax: 25 } } }
});

const waveformChart = new Chart(document.getElementById('waveformChart').getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [{ label: 'Muestras ADC', data: [], borderColor: '#28a745', tension: 0.2 }] },
    options: { responsive: true }
});

function actualizarDatos() {
    fetch('/api/data')
        .then(response => {
            if (response.status === 401) {          // la sesión expiró
                window.location.href = '/login';
                throw new Error('Sesión expirada');
            }
            return response.json();
        })
        .then(data => {
            // Gráfica de tendencia RMS
            rmsChart.data.labels = data.rms_history.map(item => item.timestamp.split(' ')[1]);
            rmsChart.data.datasets[0].data = data.rms_history.map(item => item.rms);
            rmsChart.update();

            // Forma de onda (el eje X se ajusta al nº de muestras que llegue)
            if (data.latest_waveform.length > 0) {
                waveformChart.data.labels = data.latest_waveform.map((_, i) => i + 1);
                waveformChart.data.datasets[0].data = data.latest_waveform;
                waveformChart.update();
                document.getElementById('wf-count').textContent = data.latest_waveform.length;
            }

            // Tarjetas de métricas
            document.getElementById('stat-prom').textContent = data.stats.i_prom.toFixed(2) + ' A';
            document.getElementById('stat-max').textContent = data.stats.i_max.toFixed(2) + ' A';
            document.getElementById('stat-min').textContent = data.stats.i_min.toFixed(2) + ' A';
            document.getElementById('stat-overload').textContent = data.stats.sobrecargas;

            mostrarAviso('');
            document.getElementById('ultima-act').textContent = new Date().toLocaleTimeString();
        })
        .catch(err => {
            console.error('Error actualizando dashboard:', err);
            if (err.message !== 'Sesión expirada') {
                mostrarAviso('⚠️ Sin datos del servidor (' + err.message + '). Reintentando...');
            }
        });
}

actualizarDatos();
setInterval(actualizarDatos, REFRESH_MS);
