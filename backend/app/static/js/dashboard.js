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
let baseTiempoMs = null;    // ms por división fijados por el usuario; null = automático

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
    if ($('scope-body').hidden) return;
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
    const ventanaCapturaMs = puntos.length > 1 ? puntos[puntos.length - 1].x : 1;
    // Base de tiempo: automática (la captura llena la pantalla) o fija (ms/div elegidos)
    const msPorDiv = baseTiempoMs === null ? ventanaCapturaMs / DIV_X : baseTiempoMs;
    const ventanaMs = msPorDiv * DIV_X;

    const m = scope.metrics;
    const picoAbs = Math.max(Math.abs(m.imax), Math.abs(m.imin), 0.05);
    const aPorDiv = pasoRedondo(picoAbs * 1.1 / (DIV_Y / 2));

    const visibles = puntos.filter(p => p.x <= ventanaMs);      // lo que cabe en la pantalla
    const ds = scopeChart.data.datasets[0];
    ds.data = visibles;
    ds.pointRadius = visibles.length <= 200 ? 2 : 0;     // se ven los instantes reales de muestreo

    const ex = scopeChart.options.scales.x, ey = scopeChart.options.scales.y;
    ex.min = 0; ex.max = ventanaMs;
    ex.ticks.stepSize = msPorDiv;
    ex.ticks.callback = v => Number(v).toFixed(1);
    ey.min = -aPorDiv * DIV_Y / 2; ey.max = aPorDiv * DIV_Y / 2;
    ey.ticks.stepSize = aPorDiv;
    ey.ticks.callback = v => Number(v).toFixed(aPorDiv < 1 ? 2 : 0);
    scopeChart.update();

    pintarLecturas(m);
    $('sc-escala').textContent = aPorDiv + ' A/div · ' + msPorDiv.toFixed(1) + ' ms/div' + (baseTiempoMs === null ? ' (auto)' : '');
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

// ------------------------------------------------------ base de tiempo (ms/div)
const CLAVE_BASE_TIEMPO = 'scopeBaseTiempo';

function aplicarBaseTiempo(valor) {
    baseTiempoMs = (valor === 'auto' || !(parseFloat(valor) > 0)) ? null : parseFloat(valor);
    $('sel-tiempo').value = baseTiempoMs === null ? 'auto' : String(baseTiempoMs);
    dibujarOsciloscopio(scopeMostrado);
}

$('sel-tiempo').addEventListener('change', ev => {
    aplicarBaseTiempo(ev.target.value);
    try { localStorage.setItem(CLAVE_BASE_TIEMPO, ev.target.value); } catch (e) { /* sin almacenamiento */ }
});

try {
    const guardada = localStorage.getItem(CLAVE_BASE_TIEMPO);
    if (guardada) aplicarBaseTiempo(guardada);
} catch (e) { /* sin almacenamiento */ }

// ------------------------------------------------------- análisis espectral (FFT)
// El backend hace toda la matemática (numpy); aquí solo se dibuja lo que trae /api/espectro.
const COLOR_FUND = '#4fd8ff';
const COLOR_ARM = '#ffb74d';
const COLOR_BIN = '#2e8b5f';

let vistaEspectro = 'armonicos';     // 'armonicos' | 'completo'
let espectroActual = null;           // último JSON recibido
let espectroDibujado = null;         // clave de lo dibujado, para no redibujar sin cambios
let infoBarras = [];                 // texto de los tooltips, una entrada por barra

const specChart = new Chart($('specChart').getContext('2d'), {
    type: 'bar',
    data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderWidth: 0,
                                     categoryPercentage: 1.0, barPercentage: 0.85 }] },
    options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: {
                    title: items => infoBarras[items[0].dataIndex] ? infoBarras[items[0].dataIndex].titulo : '',
                    label: item => infoBarras[item.dataIndex] ? infoBarras[item.dataIndex].detalle : ''
                }
            }
        },
        scales: {
            x: Object.assign(ejeScope('Armónico'), { grid: { display: false } }),
            y: Object.assign({ beginAtZero: true }, ejeScope('Amplitud (A rms)'))
        }
    },
    plugins: [fondoScope]
});

function limpiarEspectro(motivo) {
    specChart.data.labels = [];
    specChart.data.datasets[0].data = [];
    infoBarras = [];
    specChart.update();
    ['sp-thd', 'sp-f1', 'sp-i1', 'sp-nh', 'sp-res'].forEach(id => { $(id).textContent = '—'; });
    $('sp-thd').className = 'ro-valor';
    $('sp-info').textContent = motivo;
}

function dibujarEspectro(esp) {
    if (!esp || !esp.disponible) {
        limpiarEspectro(esp && esp.motivo ? esp.motivo : 'Aún no llegan ondas de la ESP32');
        return;
    }
    const ds = specChart.data.datasets[0];
    const ex = specChart.options.scales.x;

    if (vistaEspectro === 'armonicos') {
        specChart.data.labels = esp.armonicos.map(a => String(a.orden));
        ds.data = esp.armonicos.map(a => a.rms_a);
        ds.backgroundColor = esp.armonicos.map(a => a.orden === 1 ? COLOR_FUND : COLOR_ARM);
        infoBarras = esp.armonicos.map(a => ({
            titulo: (a.orden === 1 ? 'Fundamental' : 'Armónico ' + a.orden) + ' · ' + a.freq_hz.toFixed(1) + ' Hz',
            detalle: a.rms_a.toFixed(3) + ' A rms' + (a.orden === 1 ? '' : ' · ' + a.pct_fundamental.toFixed(2) + ' % de la fundamental')
        }));
        ex.title.text = 'Orden del armónico (1 = fundamental)';
        ex.ticks.autoSkip = false;
    } else {
        const f = esp.espectro.freq_hz;
        specChart.data.labels = f.map(v => v.toFixed(0));
        ds.data = esp.espectro.rms_a;
        ds.backgroundColor = f.map(() => COLOR_BIN);
        // Resalta la barra más cercana a cada armónico (la fundamental en otro color)
        esp.armonicos.forEach(a => {
            let mejor = 0;
            f.forEach((v, i) => { if (Math.abs(v - a.freq_hz) < Math.abs(f[mejor] - a.freq_hz)) mejor = i; });
            ds.backgroundColor[mejor] = a.orden === 1 ? COLOR_FUND : COLOR_ARM;
        });
        infoBarras = f.map((v, i) => ({
            titulo: v.toFixed(1) + ' Hz',
            detalle: esp.espectro.rms_a[i].toFixed(3) + ' A rms'
        }));
        ex.title.text = 'Frecuencia (Hz)';
        ex.ticks.autoSkip = true;
        ex.ticks.maxTicksLimit = 14;
        ex.ticks.maxRotation = 0;
    }
    specChart.update();

    $('sp-thd').textContent = esp.thd_pct.toFixed(2) + ' %';
    $('sp-thd').className = 'ro-valor thd-' + esp.thd_nivel;
    $('sp-f1').textContent = fmt(esp.fundamental.freq_hz, 2, 'Hz');
    $('sp-i1').textContent = fmt(esp.fundamental.rms_a, 2, 'A');
    $('sp-nh').textContent = esp.muestreo.armonicos_analizados;
    $('sp-res').textContent = fmt(esp.muestreo.resolucion_hz, 1, 'Hz');
    $('sp-info').textContent = esp.muestreo.n + ' muestras · ' + esp.muestreo.fs_hz.toFixed(0) + ' SPS · ' +
        esp.muestreo.ciclos + ' ciclos · armónicos hasta ' + esp.muestreo.armonicos_hasta_hz.toFixed(0) + ' Hz';
}

function pintarEstadoEspectro() {
    const el = $('sp-estado');
    const edad = espectroActual ? espectroActual.age_s : null;
    const sinSenal = edad === null || edad === undefined || edad > sinSenalSeg;
    $('spec-wrap').classList.toggle('sin-senal', sinSenal);
    el.className = 'sc-estado ' + (sinSenal ? 'sinsenal' : 'vivo');
    el.textContent = sinSenal
        ? (edad === null || edad === undefined ? '⚠ SIN DATOS' : '⚠ SIN SEÑAL (hace ' + Math.round(edad) + ' s)')
        : '● EN VIVO · captura hace ' + edad.toFixed(1) + ' s';
}

function cambiarVistaEspectro(vista) {
    vistaEspectro = vista;
    $('btn-vista-arm').classList.toggle('activo', vista === 'armonicos');
    $('btn-vista-esp').classList.toggle('activo', vista === 'completo');
    $('btn-vista-arm').setAttribute('aria-pressed', String(vista === 'armonicos'));
    $('btn-vista-esp').setAttribute('aria-pressed', String(vista === 'completo'));
    espectroDibujado = null;
    dibujarEspectro(espectroActual);
}
$('btn-vista-arm').addEventListener('click', () => cambiarVistaEspectro('armonicos'));
$('btn-vista-esp').addEventListener('click', () => cambiarVistaEspectro('completo'));

function actualizarEspectro() {
    fetch('/api/espectro')
        .then(resp => {
            if (resp.status === 401) { window.location.href = '/login'; throw new Error('Sesión expirada'); }
            return resp.json();
        })
        .then(esp => {
            espectroActual = esp;
            const clave = vistaEspectro + '|' + esp.timestamp + '|' + esp.disponible;
            if (clave !== espectroDibujado) { espectroDibujado = clave; dibujarEspectro(esp); }
            pintarEstadoEspectro();
        })
        .catch(err => {
            if (err.message !== 'Sesión expirada') $('sp-estado').textContent = '⚠ Sin respuesta del servidor';
        });
}

actualizarEspectro();
setInterval(actualizarEspectro, REFRESH_MS);

// ------------------------------------------------- mostrar / ocultar osciloscopio
const CLAVE_SCOPE_OCULTO = 'scopeOculto';

function aplicarVisibilidadScope(oculto) {
    $('scope-body').hidden = oculto;
    $('btn-congelar').hidden = oculto;
    $('lbl-tiempo').hidden = oculto;
    $('btn-disparo').hidden = oculto;
    const b = $('btn-ocultar');
    b.textContent = oculto ? '👁 Mostrar' : '🙈 Ocultar';
    b.classList.toggle('activo', oculto);
    b.setAttribute('aria-expanded', String(!oculto));
    if (!oculto) {              // el canvas estaba sin tamaño: se reajusta y se redibuja
        scopeChart.resize();
        dibujarOsciloscopio(scopeMostrado);
    }
}

$('btn-ocultar').addEventListener('click', () => {
    const oculto = !$('scope-body').hidden;
    aplicarVisibilidadScope(oculto);
    try { localStorage.setItem(CLAVE_SCOPE_OCULTO, oculto ? '1' : '0'); } catch (e) { /* sin almacenamiento */ }
});

try {   // recuerda la preferencia entre visitas
    if (localStorage.getItem(CLAVE_SCOPE_OCULTO) === '1') aplicarVisibilidadScope(true);
} catch (e) { /* sin almacenamiento */ }

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
