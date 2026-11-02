# Protocolo MQTT de AmpereWatch (ESP32 → backend)

Este documento es el "contrato" que debe cumplir el firmware de la ESP32.

## Conexión

| Dato | Valor |
|---|---|
| Servidor | nombre o IP de la Raspberry (debe estar en el certificado; ver `scripts/setup_security.sh`) |
| Puerto | **8883** (solo TLS) |
| Certificado | validar el servidor con `certs/ca.crt` (la CA de AmpereWatch) |
| Usuario | `esp32` (la contraseña está en `.env` → `MQTT_DEVICE_PASSWORD`) |
| Permisos | solo **publicar** en los dos topics de abajo (el broker bloquea todo lo demás) |

> La ESP32 necesita la **hora correcta (NTP)** para validar las fechas del certificado TLS.
> La hora de los datos **no** la envía la ESP32: la pone el servidor al recibir cada mensaje.

## Topic `industrial/amperewatch/rms` — cada ~1 s

```json
{"rms": 12.52}
```
`rms`: corriente eficaz en **amperios**, número entre 0 y 1000. Valores negativos, texto, NaN o fuera de rango se descartan.

## Topic `industrial/amperewatch/waveform` — una ventana por segundo

```json
{
  "fs": 860,
  "samples": [0.021, 2.511, 5.874, ...],
  "t_us":    [0, 1103, 2210, ...]
}
```

| Campo | Obligatorio | Descripción |
|---|---|---|
| `samples` | sí | Corriente instantánea en **amperios** (ya convertida y sin offset), entre 16 y 2048 valores. |
| `t_us` | uno de los tres | Instante de cada muestra en **microsegundos**, medido con `micros()`. Mismo largo que `samples`, estrictamente creciente. Puede ser absoluto o relativo: se resta el primero. **Es la opción recomendada.** |
| `dt_us` | | Periodo medio de muestreo en µs (si no se mide cada muestra). |
| `fs` | | Frecuencia de muestreo en Hz (la menos precisa; ver advertencia). |

Prioridad si llegan varios: `t_us` > `dt_us` > `fs`.

### ⚠️ Por qué hay que enviar `t_us`

El reloj interno del ADS1115 tiene una tolerancia de **±10 %** (según su hoja de datos de Texas Instruments)
y además cambia con la temperatura y el voltaje. Configurar "860 SPS" **no significa** que se muestree a 860 SPS.
Con un error de +6 %, un backend que asumiera 860 SPS mediría ~56.6 Hz en una red de 60 Hz.
Midiendo cada muestra con `micros()` (por ejemplo en la interrupción del pin ALERT/RDY) la frecuencia se
calcula con el tiempo real. Si solo puedes medir el inicio y el fin de la ventana, calcula
`dt_us = (t_fin - t_inicio) / (N - 1)` y envíalo como `dt_us`.

### Tamaño de la ventana

Para medir frecuencia el backend necesita **al menos 2 ciclos completos** (≥ 34 ms a 60 Hz).
A 860 SPS eso son ≥ 30 muestras; se recomienda **N = 128 (~9 ciclos)**, que da (en simulación)
errores de ~0.05 % en frecuencia y ~0.5 % en Irms.
Con ventanas de menos de 2 ciclos todo se mide salvo la frecuencia.

## Qué calcula el backend a partir de la ventana

`Irms` (sobre ciclos completos), `Ip` = (Imax − Imin)/2, `Imax`, `Imin`, `Ipp`, `Idc` (offset),
frecuencia (cruces ascendentes con interpolación), factor de cresta y el punto de disparo del osciloscopio.

**Idc es tu medidor de calibración**: si con el motor en marcha marca más de ~0.1–0.2 A, el offset
del sensor (el nivel de reposo del LEM) está mal restado en el firmware.

## Qué se descarta (y se registra en el log del backend)

JSON mal formado · mensajes de más de 64 KB · `samples` fuera de 16–2048 · valores no numéricos, NaN o infinitos ·
|I| > 1000 A · sin información de tiempo · `t_us` no creciente · periodo de muestreo fuera de 20 µs – 100 ms · RMS inválido.
Un mensaje descartado nunca afecta a los demás ni al servicio.
