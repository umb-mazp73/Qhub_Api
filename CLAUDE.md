# Qhub-api — CLAUDE.md

API de gestión de turnos con FastAPI, WebSockets y RabbitMQ.

**Enfoque:** monolito FastAPI organizado con Clean Architecture bajo `app/`. Dominio y aplicación permanecen independientes de frameworks y proveedores; infraestructura y presentación (`app/api`) apuntan hacia esos contratos.

**La IA NO vive en esta API.** La estimación de espera, la detección de picos y el agente conversacional se implementan en la **aplicación** (proyecto aparte, Flutter + un backend propio que consume esta API como cliente). La API llega hasta un punto donde cualquiera la puede consumir: turnos, colas, notificaciones y tiempo real. Nada de `/ia/*`, ningún módulo de IA, ninguna tabla de configuración de IA. Si algún día hace falta, la app lee el histórico crudo que ya exponen `GET /turnos` y `GET /colas` y calcula lo que necesite por su cuenta.

**Usuarios finales: la API NO los gestiona, punto.** No hay tabla de usuarios finales, no hay endpoint de registro para las personas que sacan turno ni para los agentes que atienden. Cada cliente que se integra **ya tiene sus propios usuarios** en su propio sistema. Lo único que la API hace con ellos es **leer** la identidad que le llega por header (`X-Usuario-Id`/`X-Usuario-Rol`) y usarla como referencia, sin ser nunca dueña de esa información.

⚠️ No confundir la tabla `usuarios` con eso: `usuarios` es un **tipo de cuenta que consume la API** (una persona individual, en vez de una empresa), no la gente que hace fila.

**Login obligatorio.** `POST /auth/token` es requisito antes de usar cualquier endpoint de negocio: cambia la credencial de la cuenta (api key, o email/usuario + password) por un access token de corta duración. Es el único mecanismo de auth.

**Roles: la API no los gestiona.** `X-Usuario-Rol` es lo que el sistema externo *informa* sobre su propio usuario; no hay tabla de roles ni permisos propios. Por eso ninguna función de la API depende de que exista un "rol admin" en la base.

---

## Arquitectura, composición y lifecycle

La dirección de dependencias es `api/infrastructure -> application -> domain`:

- `app/domain`: entidades, value objects, enums, invariantes puras, `models.py` (comandos/resultados que cruzan los puertos) e `interfaces/` (ports).
- `app/application`: errores, casos de uso y servicios.
- `app/infrastructure`: adapters Supabase/PostgREST, RabbitMQ, bcrypt/JWT, entrega, reloj, scheduling, rate limiting y WebSocket.
- `app/api`: DTOs (`schemas/`) y routers HTTP, middleware, auth y routers WebSocket, más `core/` (plumbing de app).
- `app/dependencies`: `Dependencies.py`, el composition root con `dependency-injector`.

**Un solo grafo.** `build_container(settings, resources)` (en `Dependencies.py`) ensambla el único grafo de la aplicación: repositorios, publishers, casos de uso y workers. Lo usan **las rutas HTTP** (`api/core/deps.py` devuelve los casos de uso del contenedor vía `request.app.state.container`), **los WebSockets** y **los workers**, así que comparten **una conexión a Supabase y una a RabbitMQ por proceso**. Antes las rutas armaban adaptadores nuevos en cada request y cada evento abría y cerraba su propia conexión al broker (el plan free de CloudAMQP topea en 20 conexiones); ese puente "legacy" se eliminó por completo.

Cada `create_app()` obtiene managers WebSocket/rate-limit propios, invoca una sola vez su factory y no abre conexiones; el lifespan inicia Supabase y workers, revierte startups parciales en orden inverso y al cerrar intenta liberar todos los recursos aunque uno falle. El entrypoint es `main.py`, un one-liner: `app = create_app()`. Con `APP_ENV=production`, `create_app` avisa en el log las configuraciones débiles (`Settings.production_warnings()`).

### WebSockets, fanout y entrega

`/ws/turnos/{cola_id}` difunde eventos tipados de una cola y `/ws/notificaciones` entrega avisos aislados por cuenta+usuario. Cada app tiene su propio `ConnectionManager` (las conexiones viven en la memoria del proceso), admite múltiples sockets por identidad y limpia heartbeat/conexiones al cerrar.

**Los dos caminos usan el mismo patrón de difusión** para funcionar con varios procesos: lo que sale del broker se re-publica en un exchange **fanout** y **cada instancia** tiene una cola exclusiva y efímera ligada a él, desde donde entrega a **sus propios** sockets.

- Eventos de cola: API → exchange `qhub.eventos` (`routing_key = cola_id`) → cola dedicada → `EventWorker` (una instancia, consumidores competidores) → `QueueEventDistributor` → exchange `qhub.eventos.difusion` → `FanoutWorker` de cada instancia → `ConnectionManager`.
- Avisos personales: `NotificationUseCases.request` → cola de trabajo `qhub.notificaciones` (reintentos/DLQ) → `NotificationWorker` → INSERT + canales → canal `websocket` → exchange `qhub.notificaciones.difusion` → `FanoutWorker` de cada instancia → `ConnectionManager`.

**Sin broker** (o si publicar falla) hay fallback local en los dos caminos: los eventos los entrega `ResilientTurnEventPublisher` a los sockets del mismo proceso, y los avisos se insertan directo y se entregan localmente. La cola de trabajos `qhub.notificaciones` conserva reintentos/DLQ y no debe confundirse con los fanouts en vivo.

### Gate de verificación

El repo **no incluye suite de tests, scripts de prueba ni `schema.sql`** (se eliminaron a propósito el 2026-10-17, después de validar todo contra Supabase y CloudAMQP reales). Lo que queda para comprobar que la app está sana, desde `qhub-api/` (el venv está en la raíz del repo, de ahí el `../`):

```bash
cd qhub-api
../.venv/bin/python -m compileall -q app main.py
SUPABASE_URL= SUPABASE_KEY= RABBITMQ_URL= timeout 5s ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8765
```

El arranque con Uvicorn es exitoso si completa startup y luego `timeout` lo termina. **Nunca se corren los barridos globales (`expirar_turnos_vencidos`, `marcar_turnos_para_recordar`) contra datos reales**: tocan todas las cuentas.

## Los dos tipos de cuenta

La API la consumen **dos tipos de cuenta, al mismo nivel**, y las dos hacen exactamente lo mismo con los mismos endpoints. Lo único que cambia es el tope de colas.

| | Empresa | Usuario |
|---|---|---|
| Tablas | `empresas` + `control_empresas` | `usuarios` (una sola) |
| Api keys | `api_keys` (compartida) | `api_keys` (compartida) |
| **Límite de colas** | **6** | **3** |
| Dueño de las colas | la entidad `empresas` | la persona misma |

### Por qué Empresa necesita dos tablas y Usuario una

- **`empresas`** es la **entidad** (el negocio). Es la dueña de las colas y los turnos.
- **`control_empresas`** son las **personas** que administran esa empresa y las que hacen login.

Están separadas por cuatro razones concretas:

1. **Una empresa puede tener varias personas administrándola** (`empresa_id` no es único → relación 1:N). Las tres operan sobre las **mismas** colas. Si fueran una sola tabla, tener dos administradores obligaría a duplicar el negocio, y cada copia tendría colas separadas.
2. **Las colas son del negocio, no de la persona.** Si se desactiva a alguien, las colas siguen siendo de la empresa y el resto sigue operando.
3. **Son ciclos de vida distintos.** Desactivar una persona no es dar de baja el negocio.
4. **Una empresa puede existir sin ninguna persona**: el alta manual (`POST /empresas` con `ADMIN_API_KEY`) crea la entidad y una api key, sin ninguna fila en `control_empresas`. Con una sola tabla habría que inventar un email y una password falsos.

En una cuenta de tipo **usuario** ninguna de las cuatro aplica: la persona **es** la dueña, no hay negocio que sobreviva a la persona ni varios administradores posibles. Una tabla alcanza.

---

## Propiedad polimórfica: `propietario_tipo` + `propietario_id`

Como hay dos tipos de dueño posible, `colas`, `turnos`, `notificaciones` y `api_keys` **no tienen `empresa_id`**. Tienen el par:

- `propietario_tipo` — enum `'empresa'` | `'usuario'`
- `propietario_id` — uuid del dueño

**Por qué así y no dos columnas nullable con un CHECK:** con dos columnas, cada query y cada índice del sistema necesitaría un `OR` (`WHERE empresa_id = X OR usuario_id = X`), y agregar un tercer tipo de cuenta obligaría a tocar todas las tablas otra vez. Con un par de columnas hay **un filtro y un índice** por tabla.

**El precio:** `propietario_id` no puede tener FK física (apunta a una de dos tablas según el tipo). Ese hueco lo tapa el trigger `valida_propietario()`, que verifica que el dueño exista y esté activo — lanza `QPRO1` si no existe, `QPRO2` si está inactivo.

### ⚠️ Regla obligatoria: filtrar SIEMPRE por la cuenta

Es el punto más fácil de romper por error y el más grave: **cada query debe incluir `propietario_tipo` Y `propietario_id`**. Si se omite en un solo endpoint, una cuenta podría leer o modificar datos de otra (IDOR/BOLA). Para eso el filtro vive en los repositorios de `app/infrastructure/persistence/supabase/` (`queue_repository`, `turn_repository`, `notification_repository`): reciben un `OwnerId` y aplican `propietario_tipo` + `propietario_id` en cada consulta, así que ningún router escribe el filtro a mano. Un repositorio nuevo debe seguir el mismo patrón. Cualquier endpoint nuevo debe responder 404 (no 403) ante un recurso de otra cuenta.

Cuando algo no pertenece a la cuenta se responde **404, no 403**: no se revela que el recurso existe pero es ajeno.

`crear_turno_atomico()` además **repite la validación dentro de la transacción** (defensa en profundidad): si un endpoint se olvidara el filtro, la función igual rechaza con `QNFD1`.

---

## Una cola de RabbitMQ por cada cola de negocio

Cada fila de `colas` tiene **su propia cola dedicada** en el broker. Antes había una única cola compartida para toda la API.

El nombre lo genera un **trigger de Postgres** (no la aplicación, para que no puedan divergir) y vive en `colas.rabbitmq_queue_name`, con el patrón `qhub.{tipo}.{dueño}.{cola}`:

```
qhub.empresa.peluqueria-el-corte.caja-1
qhub.empresa.clinica-san-rafael.caja-1
qhub.usuario.anagomez.ventanilla-1
```

Separado por **puntos**, que es lo idiomático en RabbitMQ, para que se lea como una jerarquía de izquierda a derecha: proyecto → tipo de cuenta → qué cuenta → qué cola. Dentro de cada segmento se usa **guion**, así el punto queda reservado como separador y nunca se confunde con parte de un nombre.

`slugificar()` normaliza cada segmento a `[a-z0-9-]` traduciendo acentos a mano, sin depender de la extensión `unaccent` (que Supabase no trae habilitada).

Los nombres de la infraestructura compartida son cortos y se configuran en el `.env`: exchange `qhub.eventos`, dead-letter exchange `qhub.dlx`, dead-letter queue `qhub.dlq`.

**Por qué incluye al dueño y no es solo el nombre de la cola:** `colas.nombre` es único **por dueño entre sus colas activas** (`uq_colas_propietario_nombre_activas`), no globalmente. Dos negocios que no se conocen van a elegir nombres obvios como "Caja 1" o "Ventanilla 1", y es correcto que puedan. Si la cola del broker se llamara solo `caja_1`, el segundo negocio en usar ese nombre no podría crear su cola, porque chocaría contra el UNIQUE de `rabbitmq_queue_name` (`uq_colas_rabbitmq_queue_name_activas`).

**Por qué se mantiene el prefijo del tipo:** una empresa y un usuario podrían slugificar al mismo texto (una empresa llamada "anagomez" y un usuario `anagomez`). El prefijo elimina esa clase de choque.

**Colisión residual conocida:** dos dueños del mismo tipo cuyos nombres slugifiquen igual (ej. dos empresas "El Corte" y "el-corte"). Es mucho menos probable que dos "Caja 1", y el UNIQUE la atrapa antes de llegar al broker. La traducción de errores de Postgres (`error_mapping.py`) distingue ese caso por el nombre del índice y responde un 409 que explica que hay que cambiarle el nombre a la cola — si no lo distinguiera, diría "ya tenés una cola con ese nombre" a alguien que no la tiene.

**Cuenta de colas en el broker:** N colas de negocio + **una sola** cola de dead-letter compartida (`qhub.dlq`) + **una sola** cola de trabajo de notificaciones (`qhub.notificaciones`). No hay un DLQ por cola a propósito: serían 2N y el plan free de CloudAMQP topea en 150, sin ganar nada (un mensaje irrecuperable es igual de irrecuperable en un DLQ compartido).

**Routing:** el publisher usa `routing_key = cola_id` y cada cola dedicada se liga con ese mismo valor. Así el publisher no necesita conocer el nombre de la cola en el broker.

**Worker dinámico** (`EventWorker`): al arrancar lee la tabla `colas` (paginada, de a 1000) y engancha un consumidor por cada cola activa; después re-barre cada 30 s (5 s si el barrido falló) para tomar las nuevas **y soltar las desactivadas**. El alta por endpoint declara la cola en el broker **y engancha su consumidor en el acto** (`SubscribingQueueProvisioner`), así el primer evento de una cola nueva llega en ~1 s y no espera al barrido (antes tardaba hasta 30 s); el barrido queda como red de seguridad (colas creadas con el broker caído, u otra instancia). **Al desactivar una cola** (`DELETE` o `PATCH activa=false`) la instancia que atiende el request suelta su consumidor y **borra la cola del broker si está vacía** (`drop_subscription`); las demás instancias lo hacen en su siguiente barrido (borrar una cola ya borrada es inocuo, y una instancia que aún la tenía puede resucitarla unos segundos hasta su barrido). **Al reactivarla** (`PATCH activa=true`) se vuelve a declarar y enganchar. Sin esto, una cuenta que creara y desactivara colas con nombres nuevos iría llenando los 150 lugares del broker, que comparten todas las cuentas. Lo que **no** se limpia solo: si se borran filas de `colas` directamente en la base, sus colas quedan en el broker (AMQP no permite listarlas) y hay que borrarlas a mano. La **base es la fuente de verdad** de qué colas existen, no una lista en memoria: así el worker se reconstruye solo tras un reinicio.

Que la declaración en el broker sea **best-effort** es deliberado: si CloudAMQP no responde, la cola ya quedó creada en la base y el worker la toma en el próximo barrido — no tiene sentido fallar el request por eso.

---

## Los dos usos del broker: fan-out vs. cola de trabajo

Las colas de negocio y la cola de notificaciones tienen semántica **opuesta**, y conviene no confundirlas:

| | Colas de negocio (`qhub.empresa.x.caja-1`) | Cola de notificaciones (`qhub.notificaciones`) |
|---|---|---|
| Para qué | Fan-out de eventos a los WebSockets | Entregar un aviso a una persona |
| Cuántas | Una por fila de `colas` | Una para toda la API |
| Mensaje fallido | Va directo al DLQ, sin reintentar | Se reintenta 5 veces, después al DLQ |
| Persistencia | Transitorio | `delivery_mode=PERSISTENT` |
| Publica | `ResilientTurnEventPublisher` | `RabbitNotificationJobPublisher` |
| Consume | `EventWorker` | `NotificationWorker` |

Un evento que nadie escucha no sirve de nada (si el cliente no estaba conectado, reintentar el broadcast no cambia nada), así que reintentar sería trabajo perdido. Un aviso a una persona sí tiene que llegar.

**Por qué dos saltos para un evento.** Una cola dedicada la consume **una sola** instancia (los consumidores compiten), pero los WebSockets de esa cola pueden estar repartidos entre todas. Si la instancia que toma el mensaje lo entregara solo a sus sockets, los clientes conectados a las demás nunca lo recibirían. Por eso el consumidor lo re-publica en el fanout (`qhub.eventos.difusion`) y cada instancia entrega a los suyos. La cola dedicada conserva su papel: buffer duradero por cola de negocio (si ninguna instancia está consumiendo, los eventos esperan en el broker). Verificado con 3 procesos reales: un evento publicado en A llega una sola vez a los sockets de A y de B.

### Camino de una notificación

```
endpoint / barrido
   └─ NotificationUseCases.request()    encola y responde al instante
        └─ exchange qhub.eventos  (routing_key = "notificacion")
             └─ cola qhub.notificaciones
                  └─ NotificationWorker → NotificationUseCases.deliver_job()
                       ├─ INSERT en `notificaciones`   (idempotente por clave)
                       └─ DeliveryDispatcher → canales (NOTIFICACIONES_CANALES)
                            ├─ websocket → fanout qhub.notificaciones.difusion → sockets de cada instancia
                            └─ log       ← molde para enganchar push / email / SMS
```

**Antes** el `INSERT` era inline en el request y un fallo se perdía con un log (`_notificar_best_effort`). **Ahora** el aviso se encola y el worker lo entrega con reintentos y DLQ.

Lo que se paga a cambio: `GET /notificaciones` pasa a ser consistente **eventualmente** (la fila aparece milisegundos después de que el endpoint respondió). Se aceptó porque una notificación es un efecto secundario, no el resultado de la operación.

**Sin broker no se pierde nada:** `NotificationUseCases.request()` cae al `INSERT` directo y entrega localmente. Se pierde la entrega externa, no el registro — estrictamente mejor que el comportamiento anterior, nunca peor.

**Idempotencia** (`notificaciones.clave_idempotencia`, UNIQUE): la genera el **productor**, no el worker, para que sobreviva a los reintentos. Si un intento falló *después* del `INSERT` (típico: la API de push devolvió 503), el reintento choca con el UNIQUE, se recupera la fila existente y se repite **solo** la entrega. Sin esto, cada reintento crearía una notificación duplicada.

**Reintentos sin reencolar:** el contador viaja en el header `qhub-intentos`. No se usa `nack(requeue=True)` porque RabbitMQ no permite modificar los headers de un mensaje reencolado — volvería con el contador en cero y giraría para siempre. En su lugar se republica una copia con el contador incrementado y se ack-ea el original.

**Cuándo un mensaje va al DLQ sin gastar intentos:** cuando el handler lanza `DescartarNotificacion` (payload sin los campos obligatorios, `propietario_tipo` inválido). Reintentar algo que nunca va a funcionar solo retrasa los avisos que sí se podían entregar.

El canal `log` (`LogNotificationChannel`) **solo deja constancia**, a propósito: esta API no sabe cómo contactar a los clientes finales de un negocio. Es el molde para enganchar FCM/APNs/email: una clase con `name` y `async deliver(notification, notice_type)` que se agrega en `Dependencies._select_channels` y se activa con `NOTIFICACIONES_CANALES`. Va del lado del worker y no del request, porque es I/O contra terceros y acá ya tiene los reintentos y la DLQ resueltos.

---

## Barridos periódicos (`ScheduledSweepWorker` + `SweepUseCases`)

Dos tareas que corren cada `TAREAS_INTERVALO_SEGUNDOS` (default 60):

- **No-show automático** (`expirar_turnos_vencidos()`): marca `no_show` los turnos `en_espera` cuya franja terminó hace más de `NO_SHOW_GRACIA_MINUTOS` (default 15). Sin esto quedan "en espera" para siempre: el cliente los ve eternos en `GET /turnos/mios` y las métricas no distinguen "vino y lo atendieron" de "no apareció".
- **Recordatorios** (`marcar_turnos_para_recordar()`): avisa de los turnos **programados** que empiezan dentro de `RECORDATORIO_ANTICIPACION_MINUTOS` (default 60). `0` los desactiva.

**Por qué barridos y no mensajes diferidos en RabbitMQ:** programar un mensaje para dentro de N días necesita el plugin `rabbitmq-delayed-message-exchange`, que CloudAMQP solo habilita en **planes dedicados**. El workaround sin plugin (TTL por mensaje + DLX) expira los mensajes **en orden de cola**: un recordatorio para dentro de 10 minutos encolado detrás de uno para dentro de 6 días no se dispara a tiempo. Con reservas mezcladas de horas y días —el caso de esta API, que permite reservar hasta 7 días adelante— eso no sirve.

Así que el reparto es: **Postgres decide qué avisar** (es donde vive el estado y donde la decisión se puede tomar atómicamente) y **el broker lo entrega**.

**Exactly-once sin locks explícitos:** las dos funciones SQL seleccionan y marcan en **una sola sentencia** (`UPDATE ... RETURNING`). En READ COMMITTED, si dos instancias barren a la vez, la segunda espera el lock de fila y después **re-evalúa el WHERE** contra la versión nueva; como la primera ya cambió `estado` / `recordatorio_enviado_en`, la fila deja de matchear y no vuelve a salir en el `RETURNING`. Leyendo primero y escribiendo después, las dos instancias verían la misma fila y avisarían dos veces.

**`turnos.recordatorio_enviado_en`** es el candado del recordatorio: `NULL` = pendiente. Sin él, un barrido cada 60s mandaría el mismo aviso una vez por minuto durante la última hora.

**El no-show automático solo toca `en_espera`.** Un turno que quedó en `atendiendo` es otro problema (el agente lo abrió y no lo cerró), y marcarlo `no_show` sería falso: esa persona sí se presentó. Queda pendiente y a la vista.

**Los barridos no dependen del broker:** corren igual sin `RABBITMQ_URL` (los avisos caen al `INSERT` directo). Marcar los no-show es una operación de base que no debería quedar suspendida porque el broker está caído.

El aviso de recordatorio habla en **minutos restantes** ("empieza en 45 minutos") y no en hora absoluta: la hora local exigiría la zona de la cola, que vive en `colas.zona_horaria` y no en `turnos`. Mostrar una hora en la zona equivocada es peor que no mostrarla.

---

## Franjas horarias

Cada cola tiene un **horario de atención** que se divide en **franjas** de duración fija. Todo turno pertenece a una franja, y hay dos formas de conseguir una:

- **En vivo** — `POST /turnos` sin `franja_inicio`. Se asigna la franja que contiene "ahora". Si el negocio está cerrado en ese momento, responde 400 con el horario y la sugerencia de programar.
- **Programado** — `POST /turnos` con `franja_inicio`. El valor se normaliza al comienzo de su franja, así el cliente puede mandar `15:07` y cae en la de las `15:00` sin tener que conocer los límites de cada bloque.

### La capacidad de cada franja se calcula, no se configura

```
cupos_por_franja = floor(duracion_franja_minutos / duracion_turno_minutos) × puestos
```

`duracion_turno_minutos` es cuánto tarda atender un turno según el trámite de esa cola (default **3 min = trámite rápido**), y `puestos` cuántos se atienden en paralelo (ventanillas, sillas, agentes).

Con franjas de 30 min y un puesto:

| Trámite | Cupos por franja | Turnos/día (18 franjas) |
|---|---|---|
| **3 min** (rápido) | **10** | 180 |
| 5 min | 6 | 108 |
| 10 min | 3 | 54 |
| 15 min | 2 | 36 |
| 20 min | 1 | 18 |

**Por qué derivarlo y no configurar un cupo a mano:** la capacidad real de un negocio depende de lo que tarda su trámite, no de un número inventado. Un cupo fijo habría que recalcularlo cada vez que cambia la duración de la franja; con la duración del trámite como entrada, los cupos se ajustan solos.

Se redondea **hacia abajo**: un turno que no cabe entero en la franja no se ofrece. Y un CHECK impide configurar un turno más largo que su franja.

`capacidad_diaria` queda como **tope opcional del día** (`0` = sin tope, el default), para el negocio que además quiera un techo por debajo de lo que darían las franjas. Se validan los dos: primero el cupo de la franja (`QCAP1`), después el del día (`QCAP2`).

### Si la franja está llena no se reasigna nada

Se responde 409 y el cliente elige otra franja u otro día (`GET /colas/{id}/franjas` muestra la disponibilidad). Reasignar en silencio le daría al cliente un horario que no pidió.

### Zona horaria

Se deriva del **país con el que se registró la cuenta** (`zona_horaria_por_pais()` cubre Latinoamérica y España; cualquier otro país cae en UTC) y se copia a `empresas.zona_horaria`/`usuarios.zona_horaria`. Al crear una cola, un trigger la hereda en `colas.zona_horaria`.

Sin zona horaria, "las 3 de la tarde" no significa nada sobre un `timestamptz`. Se denormaliza en la cola para que el cálculo de franjas no necesite un JOIN, y `PUT /colas/{id}/horario` la puede corregir — útil para cadenas con sucursales en husos distintos.

### Numeración

- **`numero`** es secuencial por cola y **día**, y se reinicia cada jornada: "turno #5 de hoy" es lo que entiende una persona, y un contador global crecería para siempre.
- **`posicion`** es el orden dentro de la **franja**: "sos el 2º de las 15:00". Por eso `compact_waiting_positions()` (repositorio de turnos) renumera por `(cola_id, franja_inicio)` y no por cola entera.
- **`turnos.franja_fecha`** guarda la fecha local de la franja, porque calcularla exige la zona horaria de la cola (otra tabla). La usan el índice único de `numero` y el tope diario.

### Cambiar el horario no mueve los turnos ya creados

Si se recorta el horario, los turnos que queden fuera del nuevo rango siguen existiendo con su franja original. Cambiar la configuración no debería cancelarle el turno a nadie por su cuenta.

---

## Límite de colas: 6 empresa / 3 usuario

Lo hace cumplir el trigger `colas_valida_limite()` en Postgres, no la aplicación. Tres detalles que importan:

1. **Cuenta solo colas activas.** Como `DELETE /colas/{id}` es un soft-delete, desactivar una cola **libera un lugar**.
2. **Se dispara también al reactivar** (`activa` false → true), que es la otra forma de superar el tope.
3. **Toma un advisory lock por cuenta.** Sin él, dos requests simultáneas podrían leer "4 colas" a la vez y crear la 5ª y la 6ª. Es el mismo tipo de race condition que `crear_turno_atomico` evita con `select ... for update`.

Lanza `QLIM1` → 409, con un mensaje que explica cómo liberar lugar. `GET /colas/limite` informa el cupo para que quien integra no descubra su tope chocándose con un error.

Los valores viven en `limite_colas_por_tipo()` (función en la base), que es la fuente de verdad; `domain/enums.py::LIMITE_COLAS_POR_TIPO` los replica solo para poder informarlos en las respuestas y en el mensaje del 409. **Al cambiar un límite hay que cambiar los dos** (migración + constante).

**Gestión de colas desde la API:** crear (`POST`), editar nombre/descripción/reactivar (`PATCH`), editar horario (`PUT .../horario`) y eliminar (`DELETE`, soft-delete). Renombrar cambia `rabbitmq_queue_name` (lo recalcula un trigger): el caso de uso libera la cola vieja del broker y declara la nueva. **Eliminar archiva** la cola (`activa=false`, la fila se conserva por el historial de turnos), borra su cola del broker, y **libera su nombre**: los dos índices únicos (`uq_colas_propietario_nombre_activas`, `uq_colas_rabbitmq_queue_name_activas`) son *parciales* (`where activa`), así que otra cola puede usar el mismo nombre —y el mismo nombre en el broker— apenas se elimina la anterior. Reactivar una archivada cuyo nombre ya tomó otra cola activa responde 409 (hay que renombrarla). Solo una cola **activa** es dueña de una cola del broker: eliminar o renombrar una ya archivada no toca la cola de otra con su nombre, y el `EventWorker` identifica cada consumidor por nombre **y** `queue_id` para no entregar eventos de una cola nueva a un consumidor de la vieja. `GET /colas?activa=true|false` filtra; sin filtro devuelve también las archivadas.

---

## Auth

### `POST /auth/registro` — tres casos, un endpoint

| Request | Qué hace |
|---|---|
| `tipo_cuenta=empresa`, **sin** `Authorization` | crea la entidad `empresas` + su primera cuenta (RPC `registrar_empresa`, atómica) |
| `tipo_cuenta=empresa`, **con** `Authorization: Bearer` | **no crea otra empresa**: agrega una cuenta más a la empresa del token |
| `tipo_cuenta=usuario` | crea una cuenta individual en `usuarios` (RPC `registrar_usuario`) |

El segundo caso es el que evita duplicar una empresa ya registrada. El `empresa_id` sale del **token firmado**, nunca del body, así que es imposible engancharse a una empresa ajena. **No hace falta ningún rol**: alcanza con haber iniciado sesión en esa empresa — coherente con que esta API no gestiona roles.

**Nunca se empareja por nombre de empresa.** Dos negocios distintos pueden llamarse igual y siguen siendo dueños separados; emparejarlos por nombre dejaría entrar a cualquiera que adivine el nombre del negocio.

Validaciones (Pydantic + CHECK en la base): `nombre_usuario` mínimo 3 caracteres sin espacios, `email` válido, `password` mínimo 8, `acepto_terminos` **tiene que ser true** (constraint a nivel de base, no solo de aplicación). `email`/`nombre_usuario` únicos **entre las dos tablas de cuenta** — si no, el login quedaría ambiguo (`AccountRepository.identifier_exists`).

### `POST /auth/token` — login

Dos formas de credencial, el mismo resultado para los dos tipos de cuenta:

1. Body `{identificador, password}` — `identificador` es el email o el nombre_usuario, case-insensitive.
2. Header `X-Api-Key`.

Devuelve `{access_token, token_type, expires_in}` (JWT propio, HS256, `JWT_SECRET_KEY`, default 60 min). De ahí en adelante: `Authorization: Bearer <access_token>` en todos los demás endpoints. Cuando expira, se repite el login (no hay refresh token).

**Claims del JWT:** `propietario_tipo`, `propietario_id`, `iss`, `iat`, `exp`. Nunca `usuario_id`/`rol`: esos siguen viniendo por header en cada request porque son información que solo el sistema externo conoce sobre su propio usuario.

El `propietario_tipo` **viaja firmado** y no se infiere: un id de empresa y uno de usuario podrían coincidir.

**Por qué el login es obligatorio y no opcional:** los sistemas que integran esta API son cajas negras — nunca van a tocar este código, así que el contrato de auth tiene que ser una regla fija desde el primer día. Además evita que la credencial de larga vida viaje en cada request; solo viaja una vez.

No existe ningún adaptador hacia JWT de terceros (Auth0, Supabase Auth, Keycloak). Se evaluó y se descartó: Supabase Auth no reemplazaría `api_keys` (que existen para credenciales de máquina, no de personas), tampoco las tablas de perfil, y el mayor beneficio de Supabase Auth es combinarlo con RLS — que esta API no usa, porque accede con la service_role key y filtra en la aplicación.

### `security.py` — resumen

- `buscar_cuenta_por_api_key(db, api_key)` → `{propietario_tipo, propietario_id}`. Consulta `api_keys` (activa) y verifica aparte que la cuenta dueña esté activa. Se consulta en dos pasos y no con un embed de PostgREST porque `api_keys` no tiene FK física a ninguna de las dos tablas de cuenta.
- `buscar_cuenta_por_credenciales(db, identificador, password)` → busca en `control_empresas` y en `usuarios`. **Para una empresa devuelve el `empresa_id`, no el id de la persona**: el dueño de las colas es la entidad.
- `hashear_password` / `verificar_password`: **bcrypt** (contraseña elegida por una persona). `hashear_api_key`: **sha256** (secreto de alta entropía generado por el sistema, y hay que poder buscarlo por igualdad).
- `emitir_access_token(propietario_tipo, propietario_id)` / `_validar_access_token_propio(token)` → devuelve la tupla `(propietario_tipo, propietario_id)`.
- `get_current_user()`: el único punto que usan todos los routers de negocio. Exige `Authorization: Bearer` + `X-Usuario-Id`.
- `get_cuenta_opcional()`: sesión **opcional** y sin exigir `X-Usuario-Id` — la usa `POST /auth/registro` para distinguir sus dos casos (en el registro todavía no hay un usuario final del cual hablar).
- `resolver_token_websocket(token)`: variante para WS.
- `verificar_admin(x_admin_api_key)`: mecanismo aparte para `empresas_router.py`, no pasa por login.

---

## Creación atómica de turnos: `crear_turno_atomico()`

`POST /turnos` no calcula `numero`/`posicion` desde la aplicación — eso tenía una race condition real: dos requests concurrentes podían calcular el mismo `numero` (dos queries HTTP separadas, sin transacción) y el segundo INSERT fallaba con un error de unicidad no controlado.

La función hace `select ... for update` sobre la fila de la cola, lo que serializa las transacciones concurrentes. Valida en la misma transacción:

| errcode | HTTP | Significado |
|---|---|---|
| `QNFD1` | 404 | cola inexistente **o de otra cuenta** |
| `QINA1` | 400 | cola inactiva |
| `QFRA1` | 400 | fuera del horario de atención, o día no laborable |
| `QFRA2` | 400 | la franja ya pasó |
| `QFRA3` | 400 | más allá de `dias_anticipacion_maxima` |
| `QCAP1` | 409 | franja llena (hay que elegir otra franja u otro día) |
| `QCAP2` | 409 | cupo diario agotado |

`turnos_router.py` los traduce con el diccionario `_ERRCODE_A_HTTP` en vez de dejar burbujear un 500 crudo de PostgREST — importante porque quien integra es una caja externa: nunca debería recibir un error interno sin explicación.

Los mensajes de `QFRA*`/`QCAP*` se reenvían tal cual desde la base, porque traen el detalle real (el horario de la cola, los cupos usados) y son más útiles que un texto genérico para quien integra.

**Solo `cancelado` y `no_show` liberan el cupo de la franja.** `atendiendo` y `finalizado` lo siguen consumiendo: en un sistema de turnos por franja, quien ya fue atendido usó su lugar. Es un cambio respecto del modelo viejo de fila en vivo, donde atender liberaba espacio.

---

## Checklist de endpoints

### Auth (`auth_router.py`)
- [x] `POST /auth/registro` — empresa nueva, cuenta extra en empresa existente (con sesión), o cuenta de usuario
- [x] `POST /auth/token` — login, requisito previo para todo lo demás

### Empresas (`empresas_router.py`) — protegido con `ADMIN_API_KEY`
- [x] `POST /empresas` — crea la entidad y su api key (sin ninguna persona)
- [x] `GET /empresas` (paginado: `limite`, `desde`), `GET /empresas/{id}`, `PATCH /empresas/{id}`
- [x] `POST /empresas/{id}/rotar-api-key` — revoca las activas y emite una nueva (en ese orden: al revés, la revocación en bloque desactivaría la recién creada)

### Colas (`colas_router.py`) — filtrado por cuenta
- [x] `POST /colas` (rol admin) — límite 6/3 vía trigger; acepta el horario opcionalmente
- [x] `GET /colas` — incluye las eliminadas (archivadas, `activa=false`); `?activa=true|false` filtra
- [x] `GET /colas/{id}/horario` — el horario más `franjas_por_dia` y `cupos_por_franja` derivados
- [x] `PUT /colas/{id}/horario` (admin) — define horario de atención y franjas. Es PUT y no PATCH porque el horario es un bloque coherente que se valida entre sí
- [x] `GET /colas/{id}/franjas?fecha=` — el calendario del día: cada franja con cupos, ocupados y disponibles. Vacío si el día no es laborable
- [x] `GET /colas/limite` — cupo de la cuenta
- [x] `GET /colas/{id}`, `PATCH /colas/{id}` (admin)
- [x] `DELETE /colas/{id}` (admin) — **soft-delete**: archiva la cola, libera un lugar del límite y su nombre, y borra su cola del broker
- [x] `GET /colas/{id}/estado`

### Turnos (`turnos_router.py`) — filtrado por cuenta
- [x] `POST /turnos` — vía `crear_turno_atomico()`
- [x] `GET /turnos/mios`, `GET /turnos?cola_id=&estado=&fecha=`, `GET /turnos/{id}`. Los dos listados son **paginados** (`limite` ≤ 1000, default 500; `desde`) con orden total estable: sin paginar, Supabase cortaría en silencio en 1000 filas
- [x] `PATCH /turnos/{id}/posponer` — conserva el lugar en la cola
- [x] `PATCH /turnos/{id}/cancelar`
- [x] `PATCH /turnos/{id}/atender` (rol agente)
- [x] `PATCH /turnos/{id}/finalizar` (rol agente)
- [x] `PATCH /turnos/{id}/no-show` (rol agente)

### Notificaciones (`notificaciones_router.py`) — filtra por `usuario_id` **y** por cuenta
- [x] `GET /notificaciones` (paginado, del más nuevo al más viejo), `PATCH /notificaciones/{id}/leida`, `DELETE /notificaciones/{id}`

### Salud
- [x] `GET /` — liveness: el proceso vive
- [x] `GET /listo` — readiness: Supabase responde y, si hay broker, RabbitMQ también; `503` si no (para el balanceador)

Filtrar solo por `usuario_id` sería un bug: dos cuentas distintas pueden usar el mismo `usuario_id` (son identificadores de sistemas externos, no globales).

Los avisos los crea `NotificationUseCases` (encolando o, sin broker, insertando directo), no el router. Se disparan **best-effort** (`TurnUseCases._notify`: un fallo al solicitar el aviso no rompe el endpoint que lo disparó) en `atender` y `posponer`, y desde los barridos (`turno_no_show`, `recordatorio`). No se crean en `cancelar`/`finalizar`/`no-show` manual (alcance acotado a los eventos con más valor para quien espera).

### WebSocket (`routers/websocket.py`)
- [x] `WS /ws/turnos/{cola_id}` — exige el access_token (`?token=` o primer mensaje, formato `access_token:usuario_id[:rol]`) y verifica que la cola pertenezca a la cuenta del token. Cierra con 4401 tanto si el token es inválido como si la cola es ajena.
- Heartbeat: `{"tipo":"ping"}` cada `WS_HEARTBEAT_INTERVAL` (default 30s). Si el envío falla, cierra la conexión — así se limpian conexiones zombie.

Eventos: `turno_creado`, `turno_llamado`, `turno_pospuesto`, `turno_cancelado`, `turno_no_show` (barrido), `cola_actualizada` (finalizar y no-show manual).

#### Escalabilidad

La API se puede correr con **varios procesos** (`WEB_CONCURRENCY=N`) o varias instancias detrás de un balanceador, siempre con el mismo `RABBITMQ_URL`: `ConnectionManager` guarda los sockets en la memoria de cada proceso, pero los eventos y los avisos llegan a todos por los exchanges fanout (ver "WebSockets, fanout y entrega"). Verificado con 3 procesos reales y con el contenedor Docker como una de las instancias, y con `WEB_CONCURRENCY=3`.

Lo que **sigue siendo por proceso**: el freno de requests (`MemoryRateLimiter`, ventana en memoria). Con N instancias el tope efectivo es N × el configurado; para un tope exacto haría falta un almacén compartido (Redis), que hoy no se justifica. Las entradas inactivas se purgan solas (cada 1000 llamadas) para que la memoria no crezca con cada IP o cuenta que pasó una vez.

**Techo del broker:** cada cola de negocio ocupa una cola en CloudAMQP (plan free: 150). Contando las compartidas y las 2 colas efímeras por instancia, caben ~140 colas activas (≈ 23 empresas completas de 6 colas).

---

## Modelos (base en Supabase) — referencia rápida

7 tablas:

- **empresas:** id, nombre, activa, creada_en, actualizado_en
- **control_empresas:** id, empresa_id, **nombre_empresa**, nombre, apellido, nombre_usuario (único), email (único), password_hash (bcrypt), pais, ciudad, acepto_terminos, acepto_terminos_en, activa, creada_en, actualizado_en
- **usuarios:** mismas columnas que control_empresas menos empresa_id/nombre_empresa
- **api_keys:** id, propietario_tipo, propietario_id, api_key_hash (único), activa, creada_en, revocada_en
- **colas:** id, propietario_tipo, propietario_id, propietario_nombre, nombre, descripcion, activa, zona_horaria, hora_apertura, hora_cierre, duracion_franja_minutos, dias_atencion, **duracion_turno_minutos, puestos**, capacidad_diaria, dias_anticipacion_maxima, rabbitmq_queue_name (único), creada_en, actualizado_en
- **turnos:** id, cola_id, propietario_tipo, propietario_id, **propietario_nombre**, usuario_id, agente_id, franja_inicio, franja_fecha, programado, numero, estado, posicion, hora_creacion, hora_atencion, hora_finalizacion, actualizado_en
- **notificaciones:** id, propietario_tipo, propietario_id, usuario_id, turno_id (opcional), mensaje, leida, creada_en

### `propietario_nombre` en `colas` y `turnos` — de qué cuenta es cada fila

`propietario_id` es un UUID: mirando la tabla no se sabe de qué negocio es una cola o un turno. `propietario_nombre` guarda el nombre legible de la cuenta dueña — `empresas.nombre` si es una empresa, `usuarios.nombre_usuario` si es una cuenta individual (la función `nombre_de_propietario()` centraliza ese criterio, y la reusa también el nombre de la cola en RabbitMQ).

**La aplicación nunca lo escribe.** En `colas` lo pone el trigger `trg_colas_propietario_nombre`; si el cliente manda un valor, se sobreescribe con el real. En `turnos` lo copia `crear_turno_atomico()` desde la cola, que ya está bloqueada en esa transacción — sale gratis y evita otra consulta.

Es un dato **mutable**, así que se sincroniza: `empresas_propaga_nombre()` y `usuarios_propaga_nombre()` actualizan `colas` y `turnos` cuando la cuenta se renombra. Propagar a `turnos` puede ser un UPDATE grande si hay mucho histórico, pero renombrar un negocio es rarísimo, y la alternativa (un JOIN en cada lectura de turnos) se paga en todas las consultas en vez de una sola vez.

Lo que **no** se renombra es `colas.rabbitmq_queue_name`: la cola ya existe en el broker con ese nombre y renombrarla ahí no es una operación que Postgres pueda hacer. Queda con el nombre original a propósito.

### `control_empresas.nombre_empresa` — la otra copia de un dato mutable

Es una copia de `empresas.nombre`, y **la aplicación no la escribe nunca**: dos triggers la mantienen sincronizada. Al insertar, `control_empresas_set_nombre_empresa()` la rellena leyendo `empresas` (si se le manda un valor a mano, lo sobreescribe con el real). Al renombrar una empresa, `empresas_propaga_nombre()` actualiza todas sus filas.

Existe porque el nombre de una empresa **sí cambia** con el tiempo, a diferencia del resto de la desnormalización del esquema: una copia escrita a mano quedaría desactualizada el día que alguien renombre el negocio.

### Constraints que hacen cumplir reglas de negocio en la base

- `uq_colas_propietario_nombre_activas` — dos colas **activas** del mismo dueño no pueden llamarse igual (dueños distintos sí pueden reusar nombres, y el nombre de una eliminada queda libre). Índice único parcial, igual que `uq_colas_rabbitmq_queue_name_activas`
- `uq_turnos_cola_numero` — numeración única por cola
- `chk_turnos_estado_tiempos` — **máquina de estados**: `en_espera` exige ambos timestamps null, `atendiendo` exige `hora_atencion` y `hora_finalizacion` null, `finalizado` exige los dos. Hace imposible guardar un turno finalizado que nunca fue atendido.
- `chk_turnos_orden_tiempos` — `hora_atencion >= hora_creacion`, `hora_finalizacion >= hora_atencion`
- `chk_api_keys_revocacion` — una key inactiva **tiene** que tener `revocada_en`, y una activa no puede tenerla
- `chk_*_acepto_terminos` — imposible registrarse sin aceptar términos

### RLS y permisos

Activado en las 7 tablas, **sin policies**. El backend accede con la service_role key (que ignora RLS por diseño), así que no cambia el comportamiento: blinda las tablas por si se filtra la anon key o algo llama a PostgREST directo. El aislamiento real sigue viviendo en la aplicación.

**Además, `anon` y `authenticated` no tienen ningún permiso** sobre tablas, secuencias ni funciones (migración `cerrar_acceso_anon_authenticated`), y los privilegios por defecto del esquema `public` tampoco se los dan a objetos futuros. Antes, Supabase les concedía `EXECUTE` en todas las funciones: con la publishable key (que es pública por diseño) se podían invocar por PostgREST `registrar_empresa`, `crear_turno_atomico` o los barridos globales, y solo el RLS lo frenaba. Hoy solo `service_role` (el backend) entra. Una función o tabla nueva queda cerrada por defecto.

---

## Infraestructura

- **Base de datos → Supabase (plan free)**: Postgres administrado. El backend accede vía **supabase-py** (cliente async, PostgREST) con la **service_role key** — no SQLAlchemy/asyncpg, no hay connection string en el `.env`. El esquema vive **solo en Supabase**: no hay archivo de esquema en el repo. Para respaldarlo o recrearlo en otro proyecto, exportarlo con `pg_dump --schema-only` (connection string en Project Settings → Database) o con los Backups del dashboard. Los cambios se hacen con migraciones.
- **RabbitMQ → CloudAMQP (plan free "Little Lemur")**: 1M mensajes/mes, **150 colas**, hasta 20 conexiones, 28 días de inactividad antes de eliminar una cola vacía. El límite de 150 colas es lo que condiciona el diseño de un DLQ compartido en vez de uno por cola.

### Variables de entorno

Todas en un único `.env` (no hay `.env.example`).

- **APP** — `APP_NAME`, `APP_ENV`, `DEBUG`
- **SUPABASE** — `SUPABASE_URL` + `SUPABASE_KEY` (**service_role**, nunca la anon; nunca exponerla a un frontend)
- **AUTH** — `JWT_SECRET_KEY` (obligatoria: sin ella nadie puede loguearse) + `JWT_ACCESS_TOKEN_EXPIRE_MINUTOS` (default 60)
- **ADMIN** — `ADMIN_API_KEY` (protege `/empresas`)
- **RABBITMQ** — `RABBITMQ_URL`, `RABBITMQ_EXCHANGE`, `RABBITMQ_DLX`, `RABBITMQ_DLQ`, `RABBITMQ_NOTIFICACIONES_QUEUE`, `RABBITMQ_NOTIFICACIONES_FANOUT`, `RABBITMQ_EVENTOS_FANOUT` (exchanges de difusión entre instancias)
- **NOTIFICACIONES** — `NOTIFICACIONES_MAX_INTENTOS` (default 5), `NOTIFICACIONES_REINTENTO_SEGUNDOS` (default 5), `NOTIFICACIONES_CANALES` (`websocket,log`)
- **TAREAS PROGRAMADAS** — `TAREAS_INTERVALO_SEGUNDOS` (60), `NO_SHOW_GRACIA_MINUTOS` (15), `RECORDATORIO_ANTICIPACION_MINUTOS` (60; 0 desactiva)
- **WEBSOCKET** — `WS_HEARTBEAT_INTERVAL`
- **RATE LIMITING** — `RATE_LIMIT_REQUESTS_POR_MINUTO` (300, por cuenta) y `RATE_LIMIT_AUTH_POR_MINUTO` (20, por IP en `POST /auth/token` y `/auth/registro`); `0` desactiva. Detrás de un proxy, `FORWARDED_ALLOW_IPS` para que se vea la IP real
- **CORS** — `CORS_ORIGINS`
- **PROCESOS** — `WEB_CONCURRENCY` (uvicorn lo lee solo; seguro porque los eventos y avisos se difunden por el broker)

`RABBITMQ_QUEUE` se eliminó: los nombres de las colas de negocio salen de `colas.rabbitmq_queue_name`, generados por trigger. En su lugar están `RABBITMQ_DLX` y `RABBITMQ_DLQ`, que sí se configuran porque son la infraestructura compartida.

---

## Estructura de archivos

El servicio completo vive dentro de `qhub-api/` (igual que un servicio en su propia carpeta, estilo del proyecto de referencia); en la raíz del repo quedan solo `docker-compose.yml` y la documentación. El código canónico vive **todo bajo `qhub-api/app/`** (Clean Architecture, DI con `dependency-injector`); la raíz del servicio tiene `main.py` como único módulo suelto.

```
Qhub/                              # raíz del repo
├── docker-compose.yml             # orquestación: build.context ./qhub-api, env_file ./qhub-api/.env
├── README.md · CLAUDE.md
└── qhub-api/                      # el servicio
    ├── main.py                    # Entry point mínimo: app = create_app()
    ├── dockerfile                 # Imagen python:3.12-slim, CMD uvicorn main:app
    ├── .dockerignore              # Excluye .venv/.git/.env, etc.
    ├── .env                       # credenciales (no se versiona)
    ├── requirements.txt · requirements.lock.txt
    ├── app/
    │   ├── config/                # base.py (EnvConfig) + config.py (Settings, get_settings)
    │   ├── domain/                # entidades, enums, reglas puras, interfaces/ (ports)
    │   ├── application/           # use_cases/, models, services/, errors
    │   ├── infrastructure/        # persistence/supabase (client, repos), messaging/rabbitmq (publishers, workers, topología),
    │   │                          #   security, delivery/log_channel, scheduling/sweep_worker, rate_limit, websocket/connection_manager
    │   ├── api/
    │   │   ├── core/              # app_factory, deps, middleware, security, rate_limit, heartbeat, websocket_auth, error_handlers
    │   │   ├── routers/           # auth, empresas, colas, turnos, notificaciones, health, websocket
    │   │   └── schemas/           # modelos Pydantic de request/response
    │   └── dependencies/          # Dependencies.py: el único grafo (DeclarativeContainer + build_container)
```

El `.env` lo resuelve `app/config/base.py` por ruta absoluta (`Path(__file__).resolve().parents[2] / ".env"`), así los valores son los mismos corras desde donde corras: tests, `uvicorn main:app` o el contenedor.

**Tareas de fondo** que arranca el lifespan (todas en el `RuntimeContainer`, se detienen en orden inverso):

| Worker | Módulo | Qué hace |
|---|---|---|
| `EventWorker` | `infrastructure/messaging/rabbitmq/event_worker.py` | Consume las colas dedicadas y entrega cada evento al `QueueEventDistributor` (difusión a todas las instancias) |
| `FanoutWorker` (eventos) | `infrastructure/messaging/rabbitmq/fanout_worker.py` | Recibe la difusión de eventos y los entrega a los sockets de **esta** instancia |
| `NotificationWorker` | `infrastructure/messaging/rabbitmq/notification_worker.py` | Entrega de avisos, con reintentos y DLQ |
| `FanoutWorker` (avisos) | `fanout_worker.py` | Recibe la difusión de avisos personales y los entrega a los sockets de esta instancia |
| `ScheduledSweepWorker` | `infrastructure/scheduling/sweep_worker.py` | No-show automático y recordatorios (`SweepUseCases`) |

No hay `usuarios_router.py`: no existe gestión de usuarios finales, ni como código apagado.

### Docker

Un solo servicio (`docker compose up --build`). Supabase y CloudAMQP son **externos** (no se levantan en el compose). La imagen parte de `python:3.12-slim`, fija `TZ=America/Guayaquil`, instala `requirements.txt` y corre `uvicorn main:app`. El `.env` **no se hornea** en la imagen: se inyecta en runtime vía `env_file`. El `healthcheck` del compose pega a `GET /` (responde `{"status":"ok",...}`).

---

## Verificación y limitaciones conocidas

No hay suite de tests en el repo (se eliminó a propósito el 2026-10-17). Antes de eliminarla, y de nuevo tras el último refactor, se validó todo contra Supabase y CloudAMQP reales: registro y login de los dos tipos de cuenta, límites 6/3, gestión de colas (crear, renombrar, editar horario, eliminar, reactivar), colas dedicadas en el broker, franjas y cupos, concurrencia (10 requests simultáneas sin números repetidos), aislamiento entre cuentas en todos los endpoints, notificaciones, WebSocket, barridos, paginación, freno por IP en `/auth/*`, y la entrega de eventos y avisos **entre 3 procesos reales** (también con el contenedor Docker como una de las instancias). **Sin tests, toda modificación que toque filtros por cuenta (`propietario_tipo` + `propietario_id`) hay que revisarla a mano**: es el error más grave posible.

Cosas que se aprendieron al probar y conviene no redescubrir:

- **Una transición de estado inválida responde 400** (no 409).
- **Los barridos** se verifican dentro de una transacción que se fuerza a deshacerse (`DO $$ ... raise exception ... $$`), nunca ejecutándolos sobre datos reales: son globales.
- **El DNS de WSL y el de Docker fallan de forma intermitente** (`No address associated with hostname`, `TLSV1_UNRECOGNIZED_NAME`), sobre todo en los primeros segundos de un contenedor. Es del entorno, no de la API: los workers reintentan y `GET /listo` responde `503` hasta que Supabase vuelve a responder.
- **La imagen de Docker instala `requirements.lock.txt`**, no `requirements.txt` (que solo lista las directas): así lleva exactamente las versiones probadas.

### Limitaciones conocidas

- **El freno de requests es por instancia** (memoria del proceso): con N instancias el tope efectivo es N × el configurado.
- **Techo de colas del broker:** ~140 colas de negocio activas en el plan free de CloudAMQP (150 colas en total).
- **La identidad de la persona (`X-Usuario-Id`) la informa quien integra:** quien tenga un token de la cuenta puede actuar como cualquier persona de esa cuenta, y `/ws/notificaciones` escucha los avisos de cualquier `usuario_id` de la cuenta. Es consecuencia de que la API no gestiona usuarios finales; el token debe quedar en el backend del integrador.
- **El token del WebSocket puede viajar por query string** (`?token=`) y quedar en logs de proxies; existe la alternativa de mandarlo como primer mensaje.

---

## Decisiones ya tomadas

- [x] **La IA sale de la API por completo** — se implementa en la aplicación (escritorio), que consume esta API. Se eliminaron `ia.py`, `ia_router.py`, `ia_config.json`, la tabla `colas_ia_config` y sus tests.
- [x] **Dos tipos de cuenta al mismo nivel** (empresa y usuario), con límites 6 y 3 colas activas respectivamente (bajados desde 10 y 5 para repartir mejor las 150 colas del broker), fijos en `limite_colas_por_tipo()`.
- [x] **Propiedad polimórfica** (`propietario_tipo` + `propietario_id`) en vez de `empresa_id`, con trigger `valida_propietario()` cubriendo la FK que no se puede declarar.
- [x] **Una sola tabla `api_keys`** para los dos tipos de cuenta, en vez de `empresa_api_keys` + `usuario_api_keys`: es el mismo concepto, y duplicar la tabla duplicaba el código que la consulta sin ganar nada.
- [x] **`empresas` separada de `control_empresas`** — entidad vs. personas que la administran (1:N).
- [x] **Sumar una cuenta a una empresa existente se autoriza con el propio token**, no con un rol ni un código de invitación: la API no gestiona roles, y quien integra no debería aprender conceptos nuevos.
- [x] **Una cola de RabbitMQ por cola de negocio**, con nombre generado por trigger, y **un DLQ compartido** (por el límite de 150 colas del plan free).
- [x] **Worker de consumo dinámico**, con la tabla `colas` como fuente de verdad y barrido cada 30s como red de seguridad.
- [x] **Login obligatorio** (`POST /auth/token`), único mecanismo, sin adaptador hacia JWT de terceros.
- [x] **Acceso a datos vía supabase-py (PostgREST)**, no SQLAlchemy. El esquema real vive en la base de Supabase.
- [x] **`DELETE /colas/{id}` es soft-delete** — preserva historial, libera un lugar del límite y **libera el nombre** (unicidad solo entre activas).
- [x] **`POST /turnos` vía `crear_turno_atomico()`**, que resuelve la franja, numera por día y valida propietario, estado, horario y cupos en la misma transacción.
- [x] **Franjas horarias con turnos en vivo y programados** — ver la sección "Franjas horarias" más arriba.
- [x] **Rate limiting por cuenta** (par `tipo:id`), no por IP.
- [x] **CORS**: `allow_credentials` se desactiva automáticamente con `CORS_ORIGINS=*` (combinación inválida por spec).
- [x] **Dead-letter**: los mensajes que no se pueden procesar se rechazan sin reencolar y terminan en el DLQ compartido.
- [x] **Las notificaciones se entregan por una cola de trabajo** (`qhub.notificaciones`), con reintentos, idempotencia por `clave_idempotencia` y DLQ. Reemplaza el `INSERT` inline que perdía el aviso en silencio si fallaba. Costo aceptado: `GET /notificaciones` es consistente eventualmente.
- [x] **Si el broker está caído, la notificación cae al `INSERT` directo** — se pierde la entrega externa, no el registro.
- [x] **No-show automático y recordatorios son barridos sobre Postgres, no mensajes diferidos** — el plugin de mensajes diferidos de RabbitMQ solo existe en los planes dedicados de CloudAMQP, y el workaround de TTL + DLX expira en orden de cola, que con reservas de horas y días mezcladas no sirve.
- [x] **Los barridos son exactly-once por construcción**: seleccionan y marcan en una sola sentencia SQL, así que varias instancias en paralelo no duplican avisos.
- [x] **El no-show automático solo toca `en_espera`** — un turno colgado en `atendiendo` no es un no-show: esa persona se presentó.
- [x] **El canal `log` es el único canal externo, a propósito** — la API no sabe cómo contactar a los clientes finales de cada negocio; en `Dependencies._select_channels` se engancha FCM/APNs/email.
- [x] **Validado contra infraestructura real** (Supabase + CloudAMQP): 2 empresas con 3 cuentas cada una + 1 cuenta de usuario, límites (entonces 10/5), colas dedicadas confirmadas en el broker, flujo completo de turnos, notificaciones, aislamiento entre las tres cuentas, y el recorrido completo evento → CloudAMQP → cola dedicada → worker → WebSocket. Repetido el 2026-10-17 con el esquema actual.
- [x] **Un solo grafo de dependencias** (`build_container`) para HTTP, WebSocket y workers: una conexión a Supabase y una a RabbitMQ por proceso. Se eliminó el puente "legacy" que armaba adaptadores por request y abría una conexión al broker por cada evento.
- [x] **Eventos de cola en dos saltos**: cola dedicada (buffer duradero, consumidores competidores) → exchange fanout → cola exclusiva por instancia → sockets locales. Es lo que permite varios procesos sin Redis. Sin broker, fallback local.
- [x] **El consumidor de una cola nueva se engancha al crearla** (`SubscribingQueueProvisioner`), no en el barrido de 30 s; **desactivar una cola borra su cola del broker** (si está vacía) y reactivarla la vuelve a crear.
- [x] **Los modelos de comandos viven en `domain/models.py`**, junto a los puertos que los usan: la dirección de dependencias queda realmente `application → domain`.
- [x] **Listados paginados con orden total** (`limite` ≤ 1000, `desde`): Supabase corta en silencio en 1000 filas.
- [x] **Freno por IP en `/auth/token` y `/auth/registro`** y login con tiempo constante frente a usuarios inexistentes.
- [x] **`GET /listo` (readiness) separado de `GET /` (liveness).**
- [x] **El esquema vive solo en Supabase**: sin `schema.sql`, sin tests ni scripts en el repo (decisión del 2026-10-17). Respaldar con `pg_dump --schema-only`.
- [x] **`anon` y `authenticated` sin permisos** sobre tablas y funciones (migración `cerrar_acceso_anon_authenticated`).
