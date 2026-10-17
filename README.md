# Qhub-api

API de **gestión de turnos con seguimiento en tiempo real**. Un negocio (o una persona) define sus colas con horario de atención, quienes lo necesitan sacan un turno —en el momento o reservado para una franja futura—, y todos los involucrados ven cómo avanza la fila al instante.

Está pensada para que **otro sistema la consuma**: una app móvil, una pantalla de sala de espera, el software de un negocio. Qhub-api no tiene interfaz propia.

**Qué hace**
- Cuentas de dos tipos (empresa e individual), cada una con sus propias colas aisladas de las demás.
- Colas con horario, días de atención, franjas de tiempo y cupos calculados.
- Turnos en vivo o programados, con numeración por día y posición dentro de la franja.
- Ciclo de vida del turno: en espera → atendiendo → finalizado (o cancelado / no-show).
- Eventos en vivo por WebSocket y avisos personales ("tu turno está siendo atendido").
- No-show automático y recordatorios antes de un turno programado.

**Qué NO hace** (a propósito)
- **No gestiona usuarios finales.** Quien integra ya tiene a sus propias personas; las informa por header en cada request y la API solo las usa como referencia.
- **No gestiona roles ni permisos.** El rol (`admin`, `agente`, otro) lo informa el sistema que integra.
- **No tiene IA.** Estimar esperas o detectar picos se hace fuera, leyendo el histórico crudo que expone `GET /turnos`.
- **No envía push, email ni SMS.** Entrega por WebSocket y deja un punto de enganche para canales externos.

---

## Conceptos

| | |
|---|---|
| **Cuenta** | Quien consume la API. Dos tipos al mismo nivel: **empresa** (hasta **6 colas activas**) y **usuario** (cuenta individual, hasta **3**). Hacen exactamente lo mismo; solo cambia el tope. |
| **Cola** | Una fila de espera con horario de atención (p. ej. "Caja 1", lunes a viernes de 8 a 18). Es del negocio, no de una persona. |
| **Franja** | Bloque de tiempo fijo en que se divide el horario (p. ej. 30 min). Todo turno pertenece a una. |
| **Cupos** | Cuántos turnos caben en una franja: `floor(duración de la franja / duración del trámite) × puestos`. Se calculan, no se configuran. |
| **Turno** | Un lugar en una franja de una cola. Tiene `numero` (secuencial **por día**) y `posicion` (orden **dentro de la franja**). |
| **Notificación** | Aviso personal ligado a un turno ("Tu turno #4 está siendo atendido"). |

**Identidad en cada request.** La cuenta viaja firmada en el access token; la persona y su rol, en headers que informa el sistema externo:

```
Authorization: Bearer <access_token>     # de POST /auth/token — identifica a la CUENTA
X-Usuario-Id:  cli-4521                  # quién es la persona, en el sistema de quien integra
X-Usuario-Rol: admin | agente | <otro>   # admin: gestiona colas · agente: atiende · otro: cliente
```

---

## Cómo funciona por dentro

Tres piezas, cada una con un trabajo distinto:

| Pieza | Para qué sirve |
|---|---|
| **Postgres (Supabase)** | Es la **fuente de verdad**: cuentas, colas, turnos, notificaciones. Las reglas que no pueden fallar viven aquí (cupos, numeración, límites de colas), así que dos requests simultáneas nunca se pisan. |
| **RabbitMQ (CloudAMQP)** | El **sistema nervioso**: lleva los eventos y los avisos de un proceso a otro, y reintenta lo que falla. No guarda datos de negocio. |
| **WebSocket** | La **última milla**: el canal abierto con cada cliente para empujarle eventos sin que tenga que preguntar. |

### Qué es una "cola" aquí (dos cosas distintas con el mismo nombre)

1. **La cola de negocio** (`colas` en la base): la fila de espera, con su horario y sus turnos. Es lo que ve el usuario.
2. **Su cola en RabbitMQ**: cada cola de negocio tiene **una cola dedicada en el broker**, con nombre generado por la base: `qhub.{tipo}.{dueño}.{cola}` (p. ej. `qhub.empresa.clinica-norte.caja-1`). Solo transporta los **eventos en vivo** de esa fila.

### El recorrido de un turno

```
 Cliente / app                    API (cualquier instancia)                 Postgres
     │                                      │                                  │
     │ POST /turnos {cola_id}               │                                  │
     ├─────────────────────────────────────▶│ crear_turno_atomico()            │
     │                                      ├─────────────────────────────────▶│ bloquea la cola,
     │                                      │                                  │ valida franja y cupos,
     │ 201 {numero, posicion, ...}          │◀─────────────────────────────────┤ numera, inserta
     │◀─────────────────────────────────────┤                                  │
     │                                      │
     │                                      │ publica "turno_creado"
     │                                      ▼
     │                         ┌─ exchange qhub.eventos ──────────────┐
     │                         │  routing_key = cola_id                │
     │                         └──────────────┬────────────────────────┘
     │                                        ▼
     │                         cola dedicada  qhub.empresa.clinica-norte.caja-1
     │                                        │  la consume UNA instancia (worker)
     │                                        ▼
     │                         exchange fanout qhub.eventos.difusion
     │                           ┌────────────┴────────────┐
     │                           ▼                         ▼
     │                  instancia A (su cola         instancia B (su cola
     │                  exclusiva y efímera)         exclusiva y efímera)
     │                           │                         │
     │      WS /ws/turnos/{id}   ▼                         ▼
     │◀──────────────────  sockets de A              sockets de B  ──────────▶ otros clientes
     │  {"tipo":"turno_creado", ...}
```

Paso a paso:

1. **La API escribe en la base.** El turno existe en cuanto responde el `201`. Los eventos son un efecto secundario: si el broker se cae, el turno no se pierde.
2. **Publica el evento** en el exchange `qhub.eventos` con `routing_key = cola_id`, y llega a la cola dedicada de esa fila.
3. **Un worker la consume.** Una sola instancia toma cada mensaje de la cola dedicada. Pero los clientes pueden estar conectados a *cualquier* instancia…
4. **…por eso se difunde.** El worker re-publica el evento en un exchange *fanout*; **cada instancia** tiene su propia cola efímera ahí y lo entrega a **sus** WebSockets. Así da igual en qué instancia cayó el `POST` o dónde está conectado cada cliente.
5. **Los clientes reciben el JSON** por el WebSocket de esa cola.

**Sin broker** (`RABBITMQ_URL` vacío, o broker caído): el evento se entrega directamente a los sockets del mismo proceso. Sirve para desarrollo y con una sola instancia; para varias instancias hace falta el broker.

### Los avisos personales (otra ruta, con reintentos)

Un aviso a una persona **sí tiene que llegar**, así que no es un simple evento:

```
PATCH /turnos/{id}/atender
   ├─ la base cambia el estado          → evento "turno_llamado" a los sockets de la cola
   └─ encola un aviso en  qhub.notificaciones  (persistente)
          └─ worker → INSERT en `notificaciones` (idempotente: un reintento no duplica)
                └─ canales de entrega:
                     · websocket → difunde a todas las instancias → /ws/notificaciones de esa persona
                     · log       → deja constancia (aquí se engancha push / email / SMS)
   si algo falla → reintenta hasta 5 veces → cola de errores qhub.dlq
```

El aviso es **eventualmente consistente**: aparece en `GET /notificaciones` milisegundos después de que respondió el endpoint. Sin broker, el aviso se inserta directo en la base (se pierden los reintentos, no el registro).

### Tareas programadas (no-show y recordatorios)

Cada `TAREAS_INTERVALO_SEGUNDOS` (60 s) cada instancia consulta Postgres:
- **No-show automático:** pasa a `no_show` los turnos `en_espera` cuya franja terminó hace más de `NO_SHOW_GRACIA_MINUTOS` (15). No toca los `atendiendo`: esa persona sí se presentó.
- **Recordatorios:** avisa de los turnos **programados** que empiezan dentro de `RECORDATORIO_ANTICIPACION_MINUTOS` (60). `0` los desactiva.

Es Postgres quien decide a quién avisar (en una sola sentencia `UPDATE … RETURNING`, así varias instancias a la vez no avisan dos veces) y el broker quien lo entrega. Marcar los estados no depende del broker.

### Qué hay en el broker

| Cola / exchange | Cuántas | Para qué |
|---|---|---|
| `qhub.{tipo}.{dueño}.{cola}` | una por cola de negocio activa | eventos en vivo de esa fila |
| `qhub.notificaciones` | una | trabajos de aviso (persistente, con reintentos) |
| `qhub.dlq` | una | mensajes que no se pudieron procesar |
| `qhub.eventos.difusion` y `qhub.notificaciones.difusion` | un exchange cada uno; **una cola efímera por instancia** | repartir a todas las instancias |

Al **desactivar** una cola de negocio se borra su cola del broker (si no tiene eventos pendientes), y al reactivarla se vuelve a crear: las colas desactivadas no ocupan lugar.

> **Límite del plan free de CloudAMQP: 150 colas.** Cada cola de negocio *activa* ocupa una; contando las compartidas y las de cada instancia, caben unas ~140 colas activas (≈ 23 empresas completas de 6 colas). Para más, un plan mayor.

---

## Empezar rápido

```bash
API=http://127.0.0.1:8000

# 1. Registrar una cuenta (empresa). Sin Authorization crea la empresa y su primera cuenta.
curl -s -X POST $API/auth/registro -H 'Content-Type: application/json' -d '{
  "tipo_cuenta": "empresa", "nombre_empresa": "Clínica Norte",
  "nombre": "Ana", "apellido": "Gómez", "nombre_usuario": "anagomez",
  "email": "ana@clinica.com", "password": "clave-segura-1",
  "pais": "Ecuador", "ciudad": "Quito", "acepto_terminos": true }'

# 2. Login → access token (60 min). Es obligatorio antes de usar cualquier otro endpoint.
TOKEN=$(curl -s -X POST $API/auth/token -H 'Content-Type: application/json' \
  -d '{"identificador":"anagomez","password":"clave-segura-1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
ADMIN=(-H "Authorization: Bearer $TOKEN" -H "X-Usuario-Id: admin-1" -H "X-Usuario-Rol: admin" -H 'Content-Type: application/json')

# 3. Crear una cola y definir su horario (trámite de 10 min, 2 ventanillas → 6 cupos por franja de 30 min)
COLA=$(curl -s -X POST $API/colas "${ADMIN[@]}" -d '{"nombre":"Caja 1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
curl -s -X PUT $API/colas/$COLA/horario "${ADMIN[@]}" -d '{
  "hora_apertura":"08:00:00","hora_cierre":"18:00:00","duracion_franja_minutos":30,
  "dias_atencion":[1,2,3,4,5],"duracion_turno_minutos":10,"puestos":2,"dias_anticipacion_maxima":7 }'

# 4. Una persona saca un turno (en vivo) y otro reservado para una franja futura
CLI=(-H "Authorization: Bearer $TOKEN" -H "X-Usuario-Id: cli-4521" -H 'Content-Type: application/json')
curl -s -X POST $API/turnos "${CLI[@]}" -d "{\"cola_id\":\"$COLA\"}"
curl -s -X POST $API/turnos "${CLI[@]}" -d "{\"cola_id\":\"$COLA\",\"franja_inicio\":\"2026-11-03T15:07:00-05:00\"}"   # cae en la franja de las 15:00

# 5. Un agente lo atiende y lo finaliza ($TURNO = id que devolvió el POST)
AG=(-H "Authorization: Bearer $TOKEN" -H "X-Usuario-Id: agente-7" -H "X-Usuario-Rol: agente")
curl -s -X PATCH $API/turnos/$TURNO/atender "${AG[@]}"
curl -s -X PATCH $API/turnos/$TURNO/finalizar "${AG[@]}"

# 6. Ver los eventos en vivo (otra terminal): npm i -g wscat
wscat -c "ws://127.0.0.1:8000/ws/turnos/$COLA?token=$TOKEN:cli-4521"
```

La documentación interactiva (todos los campos y ejemplos) está en **`/docs`** con el servidor corriendo.

---

## Endpoints

Todos los de negocio exigen `Authorization: Bearer` + `X-Usuario-Id`. Lo que no es de la cuenta responde **404** (nunca 403: no se revela que existe).

| | Endpoint | Qué hace | Rol |
|---|---|---|---|
| **Auth** | `POST /auth/registro` | Crea una empresa nueva, suma una cuenta a **tu** empresa (con token) o crea una cuenta individual | — |
| | `POST /auth/token` | Login: `{identificador, password}` o header `X-Api-Key` → access token | — |
| **Colas** | `POST /colas` | Crea una cola (admite el horario opcional) | admin |
| | `GET /colas` · `GET /colas/{id}` | Lista (incluye las eliminadas, con `activa: false`; `?activa=true\|false` filtra) / detalle | — |
| | `PATCH /colas/{id}` · `DELETE /colas/{id}` | Renombrar o reactivar / **eliminar** (archiva la cola: libera un lugar y su nombre, y borra su cola del broker) | admin |
| | `GET /colas/limite` | Cuántas colas tiene y cuántas le quedan | — |
| | `GET /colas/{id}/horario` · `PUT /colas/{id}/horario` | Horario, franjas y cupos derivados / redefinirlo | — / admin |
| | `GET /colas/{id}/franjas?fecha=` | Calendario del día: cada franja con cupos, ocupados y disponibles | — |
| | `GET /colas/{id}/estado` | Cuántos esperan y cuántos se están atendiendo | — |
| **Turnos** | `POST /turnos` | Saca un turno. Sin `franja_inicio` = en vivo; con ella = programado | — |
| | `GET /turnos` | Turnos de la cuenta. Filtros `cola_id`, `estado`, `fecha`; paginación `limite` (≤1000, def. 500) y `desde` | — |
| | `GET /turnos/mios` · `GET /turnos/{id}` | Los de esta persona / detalle | — |
| | `PATCH /turnos/{id}/posponer` | Lo manda al final de **su franja** | — |
| | `PATCH /turnos/{id}/cancelar` | Cancela y libera el cupo | — |
| | `PATCH /turnos/{id}/atender` · `/finalizar` · `/no-show` | Ciclo de atención | agente |
| **Avisos** | `GET /notificaciones` | Los avisos de esta persona, del más nuevo al más viejo (`limite`, `desde`) | — |
| | `PATCH /notificaciones/{id}/leida` · `DELETE /notificaciones/{id}` | Marcar leído / borrar | — |
| **Tiempo real** | `WS /ws/turnos/{cola_id}` | Eventos de una cola | — |
| | `WS /ws/notificaciones` | Avisos personales | — |
| **Admin de plataforma** | `POST/GET /empresas`, `GET/PATCH /empresas/{id}`, `POST /empresas/{id}/rotar-api-key` | Alta manual de una empresa (con api key, sin ninguna persona), listar, renombrar/desactivar, rotar la key. Header `X-Admin-Api-Key` | `ADMIN_API_KEY` |
| **Salud** | `GET /` · `GET /listo` | Vivo / listo (Supabase y RabbitMQ responden; `503` si no) | — |

### Estados del turno

```
en_espera ──atender──▶ atendiendo ──finalizar──▶ finalizado
    │                      │
    ├─cancelar─▶ cancelado ◀┤
    └─no-show──▶ no_show ◀──┘
```
Solo **cancelado** y **no_show** liberan el cupo de la franja: quien ya fue atendido usó su lugar. Una transición inválida responde `400`.

### Códigos de error que conviene manejar

| Código | Cuándo |
|---|---|
| `400` | Fuera del horario, día no laborable, franja ya pasada, más allá de `dias_anticipacion_maxima`, transición de estado inválida, cola inactiva |
| `401` | Sin token, token inválido o vencido (se repite el login; no hay refresh) |
| `403` | El rol no alcanza (`admin` / `agente`) |
| `404` | No existe **o es de otra cuenta** |
| `409` | Franja llena o cupo diario agotado (elegir otra franja u otro día; **nunca se reasigna en silencio**), límite de colas, email/usuario ya registrado |
| `422` | Datos inválidos |
| `429` | Demasiados requests (por cuenta; y por IP en `/auth/*`) |

---

## Tiempo real

Se conecta con el access token y la persona: `?token=<access_token>:<usuario_id>[:<rol>]` (o se envía ese mismo texto como primer mensaje). Si el token es inválido **o la cola es de otra cuenta**, el servidor cierra con el código **4401**. Cada `WS_HEARTBEAT_INTERVAL` (30 s) manda `{"tipo":"ping"}`; si el envío falla, cierra la conexión.

**`/ws/turnos/{cola_id}`** — eventos de esa fila:

| `tipo` | Cuándo |
|---|---|
| `turno_creado` | alguien sacó un turno |
| `turno_llamado` | un agente lo empezó a atender |
| `turno_pospuesto` · `turno_cancelado` | la persona lo pospuso / lo canceló |
| `turno_no_show` | el barrido lo marcó como no presentado |
| `cola_actualizada` | se finalizó o se marcó no-show a mano (la fila cambió) |

```json
{ "tipo": "turno_llamado", "cola_id": "…",
  "payload": { "id": "…", "numero": 4, "estado": "atendiendo", "posicion": 0,
               "usuario_id": "cli-4521", "agente_id": "agente-7",
               "franja_inicio": "2026-10-20T15:00:00Z", "hora_atencion": "…", … } }
```

**`/ws/notificaciones`** — al conectar: `{"tipo":"conectado","usuario_id":"…","no_leidas":2}`; después, cada aviso:

```json
{ "tipo": "notificacion",
  "notificacion": { "id": "…", "mensaje": "Tu turno #4 está siendo atendido", "turno_id": "…",
                    "tipo_aviso": "turno_llamado", "leida": false, "creada_en": "…" } }
```
Tipos de aviso: `turno_llamado`, `turno_pospuesto`, `turno_no_show`, `recordatorio`. Solo recibe los avisos de **esa** persona de **esa** cuenta.

---

## Reglas de negocio que conviene saber

- **Cupos por franja** (franja de 30 min, 1 puesto): trámite de 3 min → 10 · 5 → 6 · 10 → 3 · 15 → 2 · 20 → 1. Se redondea hacia abajo y no puede configurarse un trámite más largo que la franja. `capacidad_diaria` es un tope **opcional** del día (`0` = sin tope).
- **Franja llena → `409`.** No se reasigna a otra: el cliente elige (`GET /colas/{id}/franjas` muestra la disponibilidad).
- **Programar:** `franja_inicio` se normaliza al comienzo de su franja (`15:07` → franja de las `15:00`).
- **Zona horaria** de la cola: sale del país con el que se registró la cuenta (Latinoamérica y España; otro país → UTC) y se corrige con `PUT /colas/{id}/horario`. Todo el cálculo de franjas es en hora local de la cola.
- **Numeración:** `numero` se reinicia cada día ("turno #5 de hoy"); `posicion` es el orden dentro de la franja.
- **Cambiar el horario no mueve** los turnos ya creados.
- **Límite de colas** (6 empresa / 3 usuario): cuenta solo las **activas**; eliminar (desactivar) una libera un lugar y reactivarla vuelve a contar.
- **Gestionar colas:** `POST /colas` crea; `PATCH /colas/{id}` renombra, cambia la descripción o reactiva; `PUT /colas/{id}/horario` cambia el horario; `DELETE /colas/{id}` la elimina. Eliminar **archiva** la cola (queda en la base con `activa: false`, para no perder el historial de turnos) y **borra su cola del broker**. **Su nombre queda libre**: otra cola puede llamarse igual. Reactivar una archivada cuyo nombre ya tomó otra cola activa responde `409` (hay que renombrarla).
- **Nombres de cola:** únicos entre las colas **activas** de una cuenta, no globales (dos negocios pueden tener "Caja 1", y el nombre de una eliminada se puede reusar).

---

## Seguridad

- **Login obligatorio y único.** `POST /auth/token` cambia la credencial (password o api key) por un token de corta duración (HS256, 60 min por defecto). La credencial de larga vida viaja una sola vez; en el resto solo viaja el token.
- **Aislamiento entre cuentas.** Cada consulta filtra por `propietario_tipo` **y** `propietario_id` (y la función que crea turnos lo repite dentro de la transacción). Una cuenta nunca ve ni toca datos de otra.
- **La base solo habla con el backend.** RLS activo y **ningún permiso** para `anon`/`authenticated`: aunque se filtre la clave pública de Supabase, no sirve para nada. El backend usa la `service_role`, que **nunca** debe llegar a un frontend.
- **Freno de requests.** Por cuenta (`RATE_LIMIT_REQUESTS_POR_MINUTO`, 300) y por IP en `POST /auth/token` y `/auth/registro` (`RATE_LIMIT_AUTH_POR_MINUTO`, 20) contra fuerza bruta de contraseñas y registros masivos. Es en memoria: con varias instancias el tope es **por instancia**.
- **Login sin pistas.** Responde igual (y tarda parecido) si el usuario no existe o la contraseña es incorrecta.
- **Contraseñas** con bcrypt; **api keys** guardadas solo como sha256.
- **WebSocket por query string:** el token puede quedar en logs de proxies. Si eso importa, enviarlo como primer mensaje.
- La identidad de la **persona** (`X-Usuario-Id`) la informa el sistema que integra y la API la cree: quien tenga un token de la cuenta puede actuar como cualquier persona de esa cuenta. El token debe quedar en el backend del integrador, no en una app pública.

---

## Configuración

Todo en un único `.env` (en `qhub-api/`). Sin `SUPABASE_*` o `JWT_SECRET_KEY` la API arranca pero no puede operar.

| Variable | Qué es |
|---|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | Proyecto y clave **service_role** (nunca la anon) |
| `JWT_SECRET_KEY` | Firma los access tokens. **≥ 32 caracteres**; sin ella nadie puede loguearse |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTOS` | Duración del token (60) |
| `ADMIN_API_KEY` | Protege `/empresas`. **≥ 32 caracteres** |
| `RABBITMQ_URL` | Broker. Vacío = sin eventos entre instancias ni reintentos de avisos |
| `RABBITMQ_EXCHANGE`, `RABBITMQ_DLX`, `RABBITMQ_DLQ`, `RABBITMQ_NOTIFICACIONES_QUEUE` | Infraestructura compartida (`qhub.eventos`, `qhub.dlx`, `qhub.dlq`, `qhub.notificaciones`) |
| `RABBITMQ_EVENTOS_FANOUT`, `RABBITMQ_NOTIFICACIONES_FANOUT` | Exchanges de difusión entre instancias (`qhub.eventos.difusion`, `qhub.notificaciones.difusion`) |
| `NOTIFICACIONES_MAX_INTENTOS`, `NOTIFICACIONES_REINTENTO_SEGUNDOS` | Reintentos de un aviso antes de ir a la DLQ (5 y 5) |
| `NOTIFICACIONES_CANALES` | Canales de entrega: `websocket,log` |
| `TAREAS_INTERVALO_SEGUNDOS`, `NO_SHOW_GRACIA_MINUTOS`, `RECORDATORIO_ANTICIPACION_MINUTOS` | Barridos (60, 15, 60; `0` desactiva recordatorios) |
| `WS_HEARTBEAT_INTERVAL` | Segundos entre pings (30) |
| `RATE_LIMIT_REQUESTS_POR_MINUTO`, `RATE_LIMIT_AUTH_POR_MINUTO` | 300 por cuenta, 20 por IP en `/auth/*` (`0` desactiva) |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma (`*` por defecto) |
| `APP_NAME`, `APP_ENV`, `DEBUG` | Con `APP_ENV=production` se avisan en el log las configuraciones débiles |
| `WEB_CONCURRENCY` | Procesos por contenedor (uvicorn lo lee solo) |

---

## Ejecutar

**Local** (con el entorno virtual de la raíz):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r qhub-api/requirements.lock.txt
cd qhub-api && uvicorn main:app --reload
```

**Docker** (desde la raíz del repo; Supabase y CloudAMQP son externos y no se levantan):

```bash
docker compose up --build         # imagen reproducible: instala requirements.lock.txt
curl http://127.0.0.1:8000/listo  # {"supabase":"ok","rabbitmq":"ok"}
```
El `.env` no se hornea en la imagen: entra en runtime por `env_file`. El contenedor corre sin privilegios y el `healthcheck` consulta `GET /`.

**Base de datos.** El esquema vive solo en Supabase (7 tablas, triggers y funciones); la API no crea tablas. Respaldarlo con `pg_dump --schema-only` (Project Settings → Database) y cambiarlo siempre con migraciones.

### Escalar

La API **no comparte estado en memoria** salvo el freno de requests: se puede correr más de un proceso (`WEB_CONCURRENCY=N`) o varias instancias detrás de un balanceador, siempre con el mismo `RABBITMQ_URL`. Los eventos y los avisos se reparten entre procesos por el broker. Usar `GET /listo` como chequeo de salud del balanceador. Detrás de un proxy, `FORWARDED_ALLOW_IPS=<ip del proxy>` hace que el freno por IP vea la IP real del cliente.

### Antes de producción

`APP_ENV=production` · `DEBUG=false` · `CORS_ORIGINS` con los orígenes reales · `JWT_SECRET_KEY` y `ADMIN_API_KEY` largas y distintas a las de desarrollo · rotar cualquier clave que haya salido de tu máquina · respaldar el esquema.

---

## Estructura del código

Clean Architecture bajo `qhub-api/app/`, con la dependencia apuntando siempre hacia adentro: `api` e `infrastructure` → `application` → `domain`.

```
app/
├── domain/          entidades, reglas puras (cupos, estados), modelos de comandos e interfaces (puertos)
├── application/     casos de uso (auth, colas, turnos, notificaciones, barridos) y servicios
├── infrastructure/  Supabase, RabbitMQ (publishers, workers, topología), seguridad, WebSocket, scheduling
├── api/             routers HTTP y WebSocket, schemas, middleware, auth
├── config/          Settings (.env)
└── dependencies/    composición con dependency-injector: UN solo grafo para HTTP, WebSocket y workers
```

Las rutas HTTP, los WebSockets y los workers comparten el mismo contenedor: **una conexión a Supabase y una a RabbitMQ por proceso**. El diseño completo está en [`CLAUDE.md`](CLAUDE.md).
