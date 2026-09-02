# Gestión de Usuarios + Perfil — How To Use

Administra niveles, estado (activo/inactivo con invalidación de sesiones) y
el perfil propio de cada usuario (datos, contraseña, foto).

**Routers:** `routers/usuarios.py` (admin) y `routers/perfil.py` (self-service)
**Migración:** `d9c4e7f2a6b8` (`users.token_version`)

> **Requires auth** — `Authorization: Bearer <token>` en cada call.

---

## 1. Quick reference

### `/usuarios` — requiere nivel ≥ 2 (admin)

| Method | Endpoint | Qué hace |
|---|---|---|
| `GET` | `/usuarios` | Lista todos los usuarios (con `activo`, `nivel`, `token_version`) |
| `PATCH` | `/usuarios/{user_id}/nivel` | Promover/degradar. Body: `{"nivel": 0\|1\|2\|5}` |
| `PATCH` | `/usuarios/{user_id}/estado` | Activar/desactivar. Body: `{"activo": true\|false}` |

### `/perfil` — el propio usuario

| Method | Endpoint | Qué hace |
|---|---|---|
| `GET` | `/perfil` | Mi perfil (+ `foto_perfil_url`) |
| `PUT` | `/perfil` | Editar `name`, `telefono`, `cargo` |
| `PUT` | `/perfil/password` | `{"actual": "...", "nueva": "..."}` → invalida sesiones y devuelve token fresco |
| `POST` | `/perfil/imagen` | Subir/reemplazar foto de perfil (multipart `imagen`) |

---

## 2. Niveles y reglas RBAC

| Nivel | Significado |
|---|---|
| `0` | Técnico |
| `1` | Moderador |
| `2` | Admin — puede gestionar usuarios (este router) |
| `5` | Super admin — único que puede tocar nivel 5 |

Reglas de `PATCH /nivel`:
* No puedes cambiar **tu propio** nivel → `403`.
* No puedes asignar un nivel **mayor que el tuyo** → `403`.
* Solo un super (5) puede asignar nivel 5 o modificar a otro super → `403`.

```bash
curl -X PATCH "$BASE/usuarios/$USER_ID/nivel" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"nivel": 1}'
```

```json
{ "status": "success", "message": "Nivel actualizado a 1",
  "data": { "id": "…", "email": "juan@x.com", "nivel": 1, "activo": true, "...": "…" } }
```

Errores: `422` nivel inválido (≠ 0/1/2/5) · `404` usuario no existe · `403` reglas de arriba.

---

## 3. Activar / Desactivar (y cierre forzoso de sesiones)

```bash
curl -X PATCH "$BASE/usuarios/$USER_ID/estado" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"activo": false}'
```

**Qué pasa al desactivar** (`activo: false`):
1. `users.disabled = true`
2. `users.token_version += 1` → **TODOS sus JWT vigentes mueren al instante**
   (cada request con un token viejo → `401`). Es el "logout forzoso".
3. Login rechazado → `400 "Inactive user"`.

**Al reactivar** (`activo: true`): se levanta el bloqueo de login y las
sesiones anteriores también quedan invalidadas (época limpia de tokens) — el
usuario simplemente vuelve a iniciar sesión.

Reglas extra: no puedes desactivar **tu propia** cuenta (`403`); solo un super
desactiva a otro super (`403`).

> **Cómo funciona la invalidación:** el JWT lleva el claim `ver` con la
> `token_version` del usuario al momento del login. `get_current_user`
> compara `ver` contra `users.token_version`; si difieren → `401`. Los
> tokens emitidos antes de esta función cuentan como `ver = 0`.

---

## 4. Perfil (self-service)

### Ver / editar datos

```bash
curl "$BASE/perfil" -H "Authorization: Bearer $TOKEN"
curl -X PUT "$BASE/perfil" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"telefono": "+58 412-1234567", "cargo": "Técnico Senior"}'
```

> `nivel`, `email` y `cedula` NO son editables desde `/perfil` (solo un
> admin puede cambiar `nivel` vía `/usuarios`).

### Cambiar contraseña

```bash
curl -X PUT "$BASE/perfil/password" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"actual": "vieja123", "nueva": "nueva456"}'
```

* Contraseña actual incorrecta → `400`.
* `nueva` mínimo 6 caracteres.
* Todas las demás sesiones quedan invalidadas (bump de `token_version`);
  la respuesta incluye un **access_token fresco** para que el dispositivo
  actual siga logueado:

```json
{ "access_token": "eyJ…", "token_type": "bearer", "user": { … } }
```

### Foto de perfil

```bash
curl -X POST "$BASE/perfil/imagen" \
  -H "Authorization: Bearer $TOKEN" \
  -F "imagen=@foto.jpg"
```

* jpg / png / webp, máx 5 MB (configurable con `MAX_UPLOAD_BYTES`).
* Se guarda en `storage/perfil/{user_id}/`; la foto anterior se borra.
* Respuesta:

```json
{ "status": "success", "message": "Foto de perfil actualizada",
  "data": { "foto_perfil": "perfil/…/abc.jpg",
            "foto_perfil_url": "https://APP/storage/perfil/…/abc.jpg",
            "user": { … } } }
```

`GET /perfil` siempre incluye `foto_perfil_url` derivada de `APP_URL`.

---

## 5. Flujo típico de administración

```text
1. GET  /usuarios                         → detectar usuario a gestionar
2. PATCH /usuarios/{id}/nivel  {"nivel":2} → promover a admin
3. PATCH /usuarios/{id}/estado {"activo":false} → desactivar (logout forzoso)
4. PATCH /usuarios/{id}/estado {"activo":true}  → reactivar
```
