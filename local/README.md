# Plan B: correr las revisiones desde tu Mac

GitHub Actions usa direcciones IP de centro de datos, y los anti-bots de algunas
farmacias (Imperva en Farmacias del Ahorro, Akamai en San Pablo) las reconocen y
pueden bloquearlas. Si eso pasa seguido, corre las revisiones desde tu Mac: tu
conexión de casa es una IP normal y no levanta sospechas.

La desventaja es que **solo corre si la Mac está prendida**. `launchd` ejecuta la
tarea en cuanto la despiertas si la hora programada pasó mientras estaba dormida.

## 1. Credenciales del correo

```bash
cp local/env.ejemplo local/.env    # y edítalo con tus datos
```

`local/.env` está en `.gitignore`: no se sube al repo.

## 2. Programar las 3 revisiones al día

```bash
chmod +x local/correr.sh
cp local/com.forozco.mounjaro-tracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.forozco.mounjaro-tracker.plist
```

Para comprobar que quedó y forzar una corrida ahora mismo:

```bash
launchctl list | grep mounjaro
launchctl start com.forozco.mounjaro-tracker
tail -f local/logs/$(date +%Y-%m-%d).log
```

Para quitarlo:

```bash
launchctl unload ~/Library/LaunchAgents/com.forozco.mounjaro-tracker.plist
```

## 3. Si quieres que el dashboard en línea siga actualizándose

Pon `SUBIR_A_GIT=1` en `local/.env`. Después de cada revisión hará commit y push
del historial, y GitHub Pages se actualiza solo.

Cuando corras desde la Mac, conviene apagar el horario de GitHub Actions para no
duplicar revisiones: comenta el bloque `schedule:` en
`.github/workflows/tracker.yml` (el botón de "Run workflow" seguirá disponible).
