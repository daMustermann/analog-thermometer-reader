# Analog Thermometer Reader (Reolink & Home Assistant)

This project uses Python and OpenCV to read temperature values from an analog thermometer captured by a Reolink 810A security camera. It processes snapshots, calculates the needle position, and transmits the data to Home Assistant via MQTT.

## Features

- Snapshot-Based Processing: Fetches high-resolution (1080p) images via HTTPS API.
- Computer Vision Pipeline: Automatic circle detection (Hough Circles), ROI normalization, centering, and rotation.
- Radial scanning to determine the needle angle.
- Storage Management: Saves cropped images, automatic history cleanup (last 100 captures).
- Home Assistant Integration: Automatic MQTT Discovery.

## Portainer Stack

### Option A: Git Repository
Siehe oben (Repository Build).

### Option B: Upload (ohne Git)
1. **Stacks** → **Add stack**
2. **Build method**: Upload
3. **Upload**: `docker-compose.yml` und `.env` auswählen
4. **Deploy stack**

**Wichtig:** Bei Upload muss das Image zuerst gebaut werden:
```bash
docker build -t heizung-reader .
```

Dann in Portainer als "Custom" template deployen oder `image: heizung-reader` statt `build: .` in compose verwenden.

## Docker (Recommended)

### Quick Start

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit .env with your settings
nano .env

# 3. Build and run
docker-compose up -d
```

### Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| SNAPSHOT_URL | Camera API endpoint | (see .env.example) |
| MQTT_HOST | MQTT broker IP | 192.168.1.180 |
| MQTT_PORT | MQTT broker port | 1883 |
| MQTT_USER | MQTT username | mqtt |
| MQTT_PASSWORD | MQTT password | mqtt |

### Volumes

- `./captures` → `/app/captures` (saved images)

### Logs

```bash
docker-compose logs -f
```

## Local Development

```bash
pip install -r requirements.txt
python reader.py
```

## Configuration (reader.py)

Edit these constants in `reader.py`:

- `ROI`: Coordinates of the thermometer in the 1920x1080 frame.
- `GAUGE_ROTATION`: Rotation to align "0" and "120" markers.
- `INTERVAL`: Capture interval in seconds (default: 300 = 5 minutes).

## How it Works

1. **Capture**: Every 5 minutes, the script pulls a JPG from the Reolink camera.
2. **Detection**: Looks for a circular shape within the defined ROI.
3. **Normalization**: Crops, rotates, and resizes the gauge to 400x400px.
4. **Radial Scan**: Samples pixel brightness along a radial path to find the darkest area (the needle).
5. **Mapping**: Converts angle to temperature based on TEMP_MIN and TEMP_MAX.
6. **Publication**: Sends value to Home Assistant via MQTT.
7. **Storage**: Saves cropped frame with timestamp to `captures/history/`.

## File Structure

```
.
├── reader.py           # Main execution script
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container definition
├── docker-compose.yml  # Docker Compose configuration
├── .env.example        # Environment template
├── captures/           # Saved images (created at runtime)
│   ├── latest.jpg
│   ├── latest_normalized.jpg
│   └── history/
```
