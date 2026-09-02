# HOW TO — Storage Persistente en Coolify (no perder imágenes en cada deploy)

## El problema

El servidor corre en **Coolify** como contenedor Docker. Cada deploy
reemplaza el contenedor → **todo lo escrito en su filesystem se pierde**
(imágenes de tareas, comentarios, visitas, fotos de perfil…). La BD
(Postgres) está en otro contenedor/volumen y sobrevive, así que quedan
filas `imagenes` apuntando a archivos que ya no existen.

Dónde guarda archivos la app:

| Variable | Default | Uso |
|---|---|---|
| `STORAGE_DIR` | `./storage` | Raíz de todos los uploads (`storage_helpers.py`) |
| `APP_URL` | `http://localhost:8000` | Prefijo de las URLs públicas (`/storage/…`) |
| `MAX_UPLOAD_BYTES` | `5242880` (5 MB) | Límite por archivo |

Estructura: `storage/{tareas|comentarios|visitas|perfil}/{parent_id}/{random}.{ext}`
servida estáticamente en `/storage/...` (mount en `main.py`).

---

## La solución: Persistent Storage de Coolify

Coolify permite montar **volúmenes docker persistentes** que sobreviven
deploys y recreaciones del contenedor.

### Paso a paso (UI de Coolify)

1. Abre tu aplicación → pestaña **"Persistent Storage"** (o *Storage*).
2. **Add Storage**:
   * **Type**: `Volume` (recomendado; Coolify lo gestiona y sobrevive a todo)
     * Nombre: `sbk-storage`
     * **Mount path**: `/app/storage`  ← dentro del contenedor
   * (Alternativa `Bind Mount` con path del host: solo si prefieres
     gestionar el directorio tú mismo, ej. `/srv/sbk/storage:/app/storage`.)
3. Guarda y **redeploy** la aplicación.
4. En **Environment variables** (o el `.env` que use la app), fija:

   ```env
   STORAGE_DIR=/app/storage
   APP_URL=https://tu-dominio.coolify.app
   ```

5. Verifica tras el deploy:

   ```bash
   curl https://tu-dominio.coolify.app/up        # {"status":"ok"}
   # sube una imagen de prueba y confirma que la URL responde:
   curl -I https://tu-dominio.coolify.app/storage/<subdir>/<id>/<file>.png
   ```

> `main.py` hace `STORAGE_DIR.mkdir(parents=True, exist_ok=True)` al
> arrancar, así que el volumen vacío se prepara solo.

### ¿Por qué `/app/storage`?

El Dockerfile copia la app a `/app` y el default de `STORAGE_DIR` es
`./storage` (relativo al WORKDIR `/app`), o sea **ya** apunta a
`/app/storage`. Montar el volumen exactamente ahí hace que el default
funcione incluso sin la env var — igual recomiendo fijarla para ser
explícito.

---

## Checklist completa en Coolify

- [ ] Volume `sbk-storage` montado en `/app/storage`
- [ ] `STORAGE_DIR=/app/storage` en environment
- [ ] `APP_URL` = URL pública real (las URLs de imágenes se derivan de ella)
- [ ] Redeploy y prueba de upload + acceso público
- [ ] (Opcional pero recomendado) Migraciones: `alembic upgrade head` en el
      arranque del deploy — hoy el lifespan crea tablas faltantes
      (`create_db_and_tables`), pero los cambios de columnas requieren
      Alembic manual:

      ```bash
      docker exec -it <container> alembic upgrade head
      ```

---

## Backups del volumen

El volumen vive en el host de Coolify. Opciones:

**1. rsync periódico (cron del host):**
```bash
rsync -a root@coolify-host:/data/coolify/volumes/sbk-storage/ /backup/sbk-storage/
```

**2. tar dentro de un contenedor temporal:**
```bash
docker run --rm -v sbk-storage:/data -v $(pwd):/backup alpine \
  tar czf /backup/sbk-storage-$(date +%F).tgz -C /data .
```

**3. Copia a S3-compatible (si tienes):** rclone/restic contra el volumen.

> Las filas de `imagenes` guardan el **path relativo** (`tareas/…/x.png`),
> nunca la URL completa — restaurar el volumen en la misma ruta basta para
> que todo vuelva a funcionar, aunque cambie `APP_URL`.

---

## Migrar imágenes existentes (si ya perdiste archivos en un deploy)

Si la BD tiene rutas de archivos que el contenedor ya no tiene, esos
archivos **no son recuperables** (el filesystem viejo murió con el
contenedor). Limpieza de filas huérfanas:

```sql
-- detectar huérfanas
SELECT imageable_type, count(*) FROM imagenes i
WHERE NOT EXISTS (
  SELECT 1 WHERE '/app/storage/' || i.path IS NOT NULL  -- comprobación manual del FS
)
GROUP BY 1;
```

(No hay forma SQL de verificar el FS; recorre las rutas desde un script y
borra las filas cuyo archivo no exista.)

---

## Resumen en una línea

**Volume de Coolify montado en `/app/storage` + `STORAGE_DIR=/app/storage`**
→ los uploads viven fuera del contenedor y sobreviven a todos los deploys.
