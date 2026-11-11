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

const $ = id => document.getElementById(id);
const fmt = (v, dec, unidad) => (v === null || v === undefined) ? '—' : v.toFixed(dec) + (unidad ? ' ' + unidad : '');

// ------------------------------------------------------------ tendencia RMS
const rmsChart = new Chart($('rmsChart').getContext('2d'), {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'Corriente RMS (A)', data: [], borderColor: '#007bff', tension: 0.1, pointRadius: 2 },
            { label: 'Umbral de sobrecarga', data: [], borderColor: '#dc3545', borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 }
        ]
    },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
               scales: { y: { beginAtZero: true, suggestedMax: 25 } } }
});

// -------------------------------------------------------------- osciloscopio
const COLOR_TRAZO = '#39ff88';
const COLOR_TEXTO = '#7fdc9a';
const DIV_X = 10;   // divisiones horizontales
const DIV_Y = 8;    // divisiones verticales

const fondoScope = {
    id: 'fondoScope',
    beforeDraw(chart) {
        const ctx = chart.ctx;
        ctx.save();
        ctx.fillStyle = '#07110c';
        ctx.fillRect(0, 0, chart.width, chart.height);
        ctx.restore();
    }
};

const ejeScope = (titulo) => ({
    title: { display: true, text: titulo, color: COLOR_TEXTO, font: { family: 'monospace' } },
    ticks: { color: COLOR_TEXTO, font: { family: 'monospace', size: 11 } },
    border: { color: '#2b5a40' },
    grid: {
        color: ctx => (ctx.tick && Math.abs(ctx.tick.value) < 1e-9) ? 'rgba(140,255,170,0.55)' : 'rgba(80,200,110,0.18)',
        lineWidth: ctx => (ctx.tick && Math.abs(ctx.tick.value) < 1e-9) ? 1.5 : 1
    }
});

const scopeChart = new Chart($('scopeChart').getContext('2d'), {
    type: 'line',
    data: { datasets: [{ label: 'Corriente', data: [], parsing: false, borderColor: COLOR_TRAZO,
                         backgroundColor: COLOR_TRAZO, borderWidth: 1.6, tension: 0, pointRadius: 2 }] },
    options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'nearest', axis: 'x', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: {
                    title: items => 't = ' + items[0].parsed.x.toFixed(3) + ' ms',
                    label: item => 'i = ' + item.parsed.y.toFixed(3) + ' A   ' +
                        (item.raw.k === null ? '(punto de disparo)' : '(muestra #' + (item.raw.k + 1) + ')')
                }
            }
        },
        scales: {
            x: Object.assign({ type: 'linear', min: 0, max: 1 }, ejeScope('Tiempo (ms)')),
            y: Object.assign({ type: 'linear', min: -1, max: 1 }, ejeScope('Corriente (A)'))
        }
    },
    plugins: [fondoScope]
});

let congelado = false;
let disparoActivo = true;
let scopeActual = null;      // último paquete recibido
let scopeMostrado = null;    // lo que está dibujado (distinto si se congela)
let sinSenalSeg = 5;

// Paso "redondo" 1-2-5 × 10^k, como las escalas de un osciloscopio
function pasoRedondo(minimo) {
    const exp = Math.floor(Math.log10(minimo));
    const f = minimo / Math.pow(10, exp);
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * Math.pow(10, exp);
}

function limpiarLecturas() {
    ['irms', 'ip', 'imax', 'imin', 'ipp', 'freq', 'crest', 'idc'].forEach(k => { $('ro-' + k).textContent = '—'; });
}

function pintarLecturas(m) {
    $('ro-irms').textContent = fmt(m.irms, 2, 'A');
    $('ro-ip').textContent = fmt(m.ip, 2, 'A');
    $('ro-imax').textContent = fmt(m.imax, 2, 'A');
    $('ro-imin').textContent = fmt(m.imin, 2, 'A');
    $('ro-ipp').textContent = fmt(m.ipp, 2, 'A');
    $('ro-freq').textContent = fmt(m.freq, 2, 'Hz');
    $('ro-crest').textContent = fmt(m.crest, 2, '');
    $('ro-idc').textContent = fmt(m.idc, 2, 'A');
}

function dibujarOsciloscopio(scope) {
    if (!scope) {
        scopeChart.data.datasets[0].data = [];
        scopeChart.update();
        limpiarLecturas();
        $('sc-escala').textContent = '—';
        $('sc-info').textContent = 'Aún no llegan ondas de la ESP32';
        return;
    }
    // Disparo: la traza empieza en el primer cruce ascendente por el nivel medio (imagen estable)
    const usarDisparo = disparoActivo && scope.trigger_ms !== null;
    const t0 = usarDisparo ? scope.trigger_ms : scope.t_ms[0];
    const puntos = [];
    if (usarDisparo) {   // la traza arranca exactamente en el punto de disparo (0 ms, nivel medio)
        puntos.push({ x: 0, y: (scope.metrics.imax + scope.metrics.imin) / 2, k: null });
    }
    for (let k = 0; k < scope.t_ms.length; k++) {
        if (scope.t_ms[k] >= t0) puntos.push({ x: scope.t_ms[k] - t0, y: scope.i[k], k: k });
    }
    const ventanaMs = puntos.length > 1 ? puntos[puntos.length - 1].x : 1;

    const m = scope.metrics;
    const picoAbs = Math.max(Math.abs(m.imax), Math.abs(m.imin), 0.05);
    const aPorDiv = pasoRedondo(picoAbs * 1.1 / (DIV_Y / 2));
    const msPorDiv = ventanaMs / DIV_X;

    const ds = scopeChart.data.datasets[0];
    ds.data = puntos;
    ds.pointRadius = puntos.length <= 200 ? 2 : 0;     // se ven los instantes reales de muestreo

    const ex = scopeChart.options.scales.x, ey = scopeChart.options.scales.y;
    ex.min = 0; ex.max = ventanaMs;
    ex.ticks.stepSize = msPorDiv;
    ex.ticks.callback = v => Number(v).toFixed(1);
    ey.min = -aPorDiv * DIV_Y / 2; ey.max = aPorDiv * DIV_Y / 2;
    ey.ticks.stepSize = aPorDiv;
    ey.ticks.callback = v => Number(v).toFixed(aPorDiv < 1 ? 2 : 0);
    scopeChart.update();

    pintarLecturas(m);
    $('sc-escala').textContent = aPorDiv + ' A/div · ' + msPorDiv.toFixed(1) + ' ms/div';
    $('sc-info').textContent = scope.n + ' muestras · ' + scope.fs_real.toFixed(0) + ' SPS reales · tiempos ' + scope.timing +
        (usarDisparo ? ' · disparo ↗' : '');
}

function pintarEstado() {
    const el = $('sc-estado');
    const wrap = $('scope-wrap');
    const edad = scopeActual ? scopeActual.age_s : null;
    const sinSenal = !scopeActual || edad === null || edad > sinSenalSeg;
    wrap.classList.toggle('sin-senal', sinSenal && !congelado);
    el.className = 'sc-estado';
    if (congelado) {
        el.textContent = '⏸ CONGELADO';
        el.classList.add('congelado');
    } else if (sinSenal) {
        el.textContent = scopeActual ? '⚠ SIN SEÑAL (hace ' + Math.round(edad) + ' s)' : '⚠ SIN DATOS';
        el.classList.add('sinsenal');
    } else {
        el.textContent = '● EN VIVO · captura hace ' + edad.toFixed(1) + ' s';
        el.classList.add('vivo');
    }
}

$('btn-congelar').addEventListener('click', () => {
    congelado = !congelado;
    const b = $('btn-congelar');
    b.textContent = congelado ? '▶ Continuar' : '⏸ Congelar';
    b.classList.toggle('activo', congelado);
    if (!congelado) { scopeMostrado = scopeActual; dibujarOsciloscopio(scopeMostrado); }
    pintarEstado();
});

$('btn-disparo').addEventListener('click', () => {
    disparoActivo = !disparoActivo;
    const b = $('btn-disparo');
    b.textContent = 'Disparo: ' + (disparoActivo ? 'ON' : 'OFF');
    b.classList.toggle('activo', disparoActivo);
    b.setAttribute('aria-pressed', String(disparoActivo));
    dibujarOsciloscopio(scopeMostrado);
});

// ------------------------------------------------------- umbral de sobrecarga
const inputUmbral = $('input-umbral');
const msgUmbral = $('umbral-msg');
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
let umbralEditado = false;      // el usuario está escribiendo: no pisar su valor con el del servidor

function mensajeUmbral(texto, clase) {
    msgUmbral.textContent = texto;
    msgUmbral.className = 'umbral-msg' + (clase ? ' ' + clase : '');
}

inputUmbral.addEventListener('input', () => { umbralEditado = true; mensajeUmbral(''); });

$('form-umbral').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const valor = parseFloat(inputUmbral.value.replace(',', '.'));
    if (!Number.isFinite(valor)) { mensajeUmbral('Escribe un número válido.', 'error'); return; }

    const btn = $('btn-umbral');
    btn.disabled = true;
    try {
        const resp = await fetch('/api/umbral', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
            body: JSON.stringify({ umbral: valor })
        });
        if (resp.status === 401) { window.location.href = '/login'; return; }
        const data = await resp.json();
        if (!resp.ok) { mensajeUmbral(data.error || 'No se pudo guardar.', 'error'); return; }
        umbralEditado = false;
        inputUmbral.value = data.umbral_sobrecarga;
        mensajeUmbral('✔ Guardado', 'ok');
        actualizarDatos();      // refresca ya la línea roja de la gráfica
    } catch (err) {
        mensajeUmbral('Error de red: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
    }
});

// ------------------------------------------------------------ ciclo de datos
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
            sinSenalSeg = data.sin_senal_seg;

            // Tendencia RMS + umbral de sobrecarga
            rmsChart.data.labels = data.rms_history.map(item => item.timestamp.split(' ')[1].split('.')[0]);
            rmsChart.data.datasets[0].data = data.rms_history.map(item => item.rms);
            rmsChart.data.datasets[1].data = data.rms_history.map(() => data.umbral_sobrecarga);
            rmsChart.update();

            // Umbral vigente en el servidor
            $('umbral-actual').textContent = data.umbral_sobrecarga + ' A';
            if (!umbralEditado && document.activeElement !== inputUmbral) {
                inputUmbral.value = data.umbral_sobrecarga;
            }

            // Osciloscopio (si está congelado se conserva la imagen)
            scopeActual = data.scope;
            if (!congelado) {
                const nueva = !scopeMostrado || !scopeActual || scopeMostrado.timestamp !== scopeActual.timestamp;
                scopeMostrado = scopeActual;
                if (nueva) dibujarOsciloscopio(scopeMostrado);
            }
            pintarEstado();

            // Tarjetas de métricas del día
            $('stat-prom').textContent = data.stats.i_prom.toFixed(2) + ' A';
            $('stat-max').textContent = data.stats.i_max.toFixed(2) + ' A';
            $('stat-min').textContent = data.stats.i_min.toFixed(2) + ' A';
            $('stat-overload').textContent = data.stats.sobrecargas;

            mostrarAviso('');
            $('ultima-act').textContent = new Date().toLocaleTimeString();
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
