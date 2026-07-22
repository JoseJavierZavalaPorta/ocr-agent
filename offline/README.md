# Despliegue offline (USB, sin red en destino)

Para cuando la PC que va a correr OCR Agent no tiene acceso a internet. En vez
de `install.sh` (que descarga ~35 GB en el momento), este flujo separa el
proceso en dos partes: armar el paquete en una máquina CON internet, e
instalar ese paquete en la PC destino SIN red.

## 1. Máquina puente (con internet)

Cualquier PC/VM con **Ubuntu 24.04 (noble) x86_64** y Docker funcionando.
No necesita GPU — construir imágenes y descargar modelos no usa GPU.

```bash
git clone https://github.com/JoseJavierZavalaPorta/ocr-agent.git
cd ocr-agent
./offline/build-bundle.sh /ruta/al/usb/ocr-agent-offline
```

Apunta directo a la ruta del USB/disco ya montado — el script descarga y
descomprime todo ahí mismo, no duplica ~45-55 GB en el disco local.

Tarda 30-90 min según la conexión. Al final tendrás:

```
ocr-agent-offline/
├── ocr-agent/              ← el repo completo, con volumes/models ya poblado
├── images/ocr-images.tar.gz
├── packages/docker/*.deb   ← Docker Engine + compose plugin
├── packages/rocm/*.deb     ← ROCm para GPU AMD (best-effort, puede quedar vacío)
└── MANIFEST.txt
```

## 2. PC destino (sin red)

Conecta el USB, y desde dentro de `ocr-agent-offline/ocr-agent`:

```bash
sudo ./offline/install-target.sh
```

Un solo comando, sin prompts. El script:

- Instala Docker Engine desde los `.deb` locales (si no está ya instalado).
- Detecta `/dev/kfd` (GPU AMD); si falta y hay paquetes ROCm en el bundle,
  los instala. Si sigue sin aparecer, sigue en modo CPU sin fallar.
- Carga las imágenes Docker (`docker load`).
- Levanta los servicios con o sin el override de GPU
  (`docker-compose.gpu.yml`) según lo detectado.
- Verifica que el backend responda en `/health`.

Después de esto, el uso diario es igual que en el README principal:
`./start.sh`, `./status.sh`, `./resume.sh`.

## Por qué dos imágenes de Ollama distintas importaban

`docker-compose.yml` ahora usa `ollama/ollama:rocm` (antes `:latest`, que
**no** trae soporte ROCm — con GPU AMD y `:latest` la inferencia caía a CPU en
silencio). El tag `:rocm` funciona igual sin GPU, así que un solo bundle sirve
para ambos casos. Los `devices: /dev/kfd, /dev/dri` que antes estaban fijos en
`docker-compose.yml` se movieron a `docker-compose.gpu.yml`, un override que
solo se aplica si `/dev/kfd` existe — así el mismo paquete no falla en una PC
sin GPU AMD.

## Actualizar el bundle más adelante

Si cambia el código o `requirements.txt`, hay que rehacer el bundle desde
cero (`build-bundle.sh` de nuevo) — no hay forma de "parchear" un USB offline
sin repetir el build y la descarga de modelos que hayan cambiado.
