# Pendientes de Qhub

La API está completa y verificada de punta a punta (Supabase y CloudAMQP reales, varias instancias, Docker). Lo que queda **no es código de la API**: son acciones tuyas sobre cuentas e infraestructura, y piezas que viven en otros proyectos.

---

## 1. Antes de subir a producción (acciones tuyas)

- [ ] **Rotar la `service_role` key de Supabase** y pegar la nueva en `SUPABASE_KEY` (Project Settings → API Keys). Quedó escrita en chats y da acceso total a los datos.
- [ ] **Rotar la contraseña/URL de CloudAMQP** y actualizar `RABBITMQ_URL`. También quedó expuesta.
- [ ] **Revocar el Personal Access Token `sbp_...`** de Supabase (supabase.com/dashboard/account/tokens) y **quitar el MCP de Supabase** de Claude Code (`claude mcp remove supabase -s local`): hoy tiene permiso de **escritura** sobre el proyecto de producción.
- [ ] **Respaldar el esquema de la base.** Ya no hay `schema.sql`: el esquema vive solo en Supabase. `pg_dump --schema-only "<connection string>" > respaldo-esquema.sql` (Project Settings → Database) y guardarlo **fuera** del proyecto, o activar los Backups del dashboard.
- [ ] **`git init` y un primer commit.** El proyecto no está en git: un borrado no tiene vuelta atrás (ya pasó con los tests, los scripts y el esquema).
- [ ] **Configuración de producción en el `.env`:** `APP_ENV=production`, `DEBUG=false`, `CORS_ORIGINS` con los orígenes reales (hoy `*`), `JWT_SECRET_KEY` y `ADMIN_API_KEY` de **≥ 32 caracteres** y distintas a las de desarrollo. Con `APP_ENV=production` la API avisa en el log lo que falte.
- [ ] **Poner la API detrás de HTTPS** (proxy o balanceador con TLS). La API no termina TLS. Con proxy: `FORWARDED_ALLOW_IPS=<ip del proxy>` para que el freno por IP vea la IP real del cliente, y `GET /listo` como chequeo de salud.
- [ ] **Desplegar con Docker en el servidor** (`docker compose up --build`) y comprobar `GET /listo`. Decidir `WEB_CONCURRENCY` según la máquina.

## 2. Decisiones de infraestructura

- [ ] **Plan de CloudAMQP.** El plan free permite 150 colas y cada cola de negocio ocupa una: caben ~140 colas activas (≈ 23 empresas completas de 6 colas). Antes de crecer más, subir de plan.
- [ ] **Tope de requests compartido (opcional).** Hoy el freno es por instancia: con N instancias el tope efectivo es N veces el configurado. Si se necesita exacto, hace falta un almacén compartido (Redis).

## 3. Fuera de esta API

- [ ] **Canal de entrega externo (push / email / SMS).** La API entrega avisos por WebSocket y deja el punto de enganche (`Dependencies._select_channels` + `NOTIFICACIONES_CANALES`), con reintentos y DLQ ya resueltos. Falta elegir el proveedor (FCM, APNs, email…) y escribir el canal cuando exista la app.
- [ ] **App (Flutter) y su backend de IA.** Estimación de espera, detección de picos y chatbot van en la app o en su propio backend, consumiendo esta API como cliente (leyendo el histórico crudo de `GET /turnos`, que ya está paginado).
- [ ] **Sitio de documentación pública.** Planteado, no empezado. La referencia de endpoints está en el README y, con el servidor corriendo, en `/docs`.
