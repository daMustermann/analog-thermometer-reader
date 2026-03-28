# Analog Thermometer Reader

Read analog thermometer values from any camera and publish to Home Assistant via MQTT.

## Features

- Works with any camera that provides HTTP/HTTPS snapshot endpoints
- Automatic circle detection and needle angle calculation
- Configurable temperature range and angle mapping
- Automatic history cleanup (last 100 captures)
- Home Assistant Integration via MQTT

## Supported Cameras

This script works with any camera that provides a snapshot URL. Common examples:

- **Reolink**: `https://<IP>/cgi-bin/api.cgi?cmd=Snap&channel=0&user=<USER>&password=<PASS>`
- **Axis**: `http://<IP>/axis-cgi/jpg/image.cgi`
- **Generic MJPEG**: Any URL returning a JPEG image

## Quick Start (Docker)

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit .env with your settings
nano .env

# 3. Build and run
docker-compose up -d
```

## Configuration (.env)

| Variable | Description | Required |
|----------|-------------|----------|
| SNAPSHOT_URL | Camera snapshot URL | Yes |
| MQTT_HOST | MQTT broker IP | Yes |
| MQTT_PORT | MQTT broker port | No (default: 1883) |
| MQTT_USER | MQTT username | No |
| MQTT_PASSWORD | MQTT password | No |

## Finding Your Camera Snapshot URL

### Reolink
```
https://<CAMERA_IP>/cgi-bin/api.cgi?cmd=Snap&channel=0&user=<USERNAME>&password=<PASSWORD>
```

### Generic IP Cameras
Most IP cameras support one of these endpoints:
- `/snap.jpeg`
- `/jpg/image.jpg`
- `/cgi-bin/jpg/image.cgi`
- `/onvif/snapshot`

### Testing Your URL
```bash
# Test from command line
curl -k -o test.jpg "YOUR_SNAPSHOT_URL"

# Or in browser - you should see the image
```

## Finding ROI Coordinates

The **ROI (Region of Interest)** defines where the thermometer is located in the camera image.

### Using the ROI Finder Script

1. Run the built-in ROI finder:
```bash
python -c "
import cv2
import requests
import os
import numpy as np

url = os.getenv('SNAPSHOT_URL', 'YOUR_URL_HERE')
print('Fetching image...')
r = requests.get(url, verify=False)
frame = cv2.imdecode(np.frombuffer(r.content, dtype=np.uint8), cv2.IMREAD_COLOR)

roi = cv2.selectROI('Select thermometer region (press SPACE or ENTER)', frame)
cv2.destroyAllWindows()
print(f'ROI: {roi}')  # Format: (x, y, width, height)
print(f'Use as ROI = ({roi[1]}, {roi[1]+roi[3]}, {roi[0]}, {roi[0]+roi[2]})')
"
```

2. Click and drag to select the thermometer area
3. Press SPACE or ENTER to confirm
4. Copy the output coordinates to `reader.py`

### Manual ROI Format

The script expects: `(y1, y2, x1, x2)` - top, bottom, left, right coordinates.

If you get `(x, y, w, h)` from a tool, convert like:
```python
y1, y2 = y, y + h
x1, x2 = x, x + w
```

## Calibration

After setting ROI, calibrate these values in `reader.py`:

| Parameter | Description |
|-----------|-------------|
| `TEMP_MIN` / `TEMP_MAX` | Temperature range of your thermometer (e.g., 0-120) |
| `ANGLE_AT_MIN` / `ANGLE_AT_MAX` | Angle at min/max temperature |
| `GAUGE_ROTATION` | Rotation to straighten the gauge |

### How to Find the Right Angles

1. Set `GAUGE_ROTATION = 0` initially
2. Run the script and check `latest_normalized.jpg`
3. Adjust `GAUGE_ROTATION` until the "0" mark is at the bottom and "max" at the top
4. Adjust `ANGLE_AT_MIN` and `ANGLE_AT_MAX` to match your thermometer scale

Typical values for a 240° gauge (common for 0-120°C):
- `ANGLE_AT_MIN = -120`
- `ANGLE_AT_MAX = 120`

## Portainer Deployment

### Option A: Git Repository
1. **Stacks** → **Add stack**
2. **Build method**: Repository
3. Repository URL: `https://github.com/daMustermann/analog-thermometer-reader`
4. Add environment variables
5. **Deploy stack**

### Option B: Upload
1. **Stacks** → **Add stack**
2. **Build method**: Upload
3. Upload `docker-compose.yml` and `.env`
4. **Deploy stack**

## Local Development

```bash
pip install -r requirements.txt
python reader.py
```

## How it Works

1. **Capture**: Fetches a JPEG snapshot from your camera
2. **ROI Extraction**: Crops the thermometer region
3. **Circle Detection**: Finds the gauge circle using Hough Transform
4. **Normalization**: Rotates and resizes to standard 400x400px
5. **Radial Scan**: Samples brightness along radial lines to find the needle
6. **Angle Mapping**: Converts angle to temperature
7. **Publish**: Sends to MQTT broker
8. **Storage**: Saves cropped image with timestamp

## File Structure

```
.
├── reader.py           # Main script
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container definition
├── docker-compose.yml  # Docker Compose config
├── .env.example       # Environment template
├── captures/           # Saved images
│   ├── latest.jpg
│   ├── latest_normalized.jpg
│   └── history/
```

## Troubleshooting

### Viewing Logs

**In Portainer:**
1. Go to your stack → **Containers**
2. Click on the container name
3. Click **Logs** tab
4. Enable **Show timestamps** and **Tail mode**

**Via command line:**
```bash
docker logs heizung-reader
docker logs -f heizung-reader  # follow mode
```

### No logs appearing

If no logs appear, the container might be running but not producing output yet. Check:
- Container status should show "Running"
- Wait a few seconds (first capture happens every 5 minutes)

### No circle detected:
- Check ROI coordinates are correct
- Adjust `GAUGE_ROTATION` to make the gauge more circular

**Wrong temperature:**
- Adjust `TEMP_MIN` / `TEMP_MAX` to match your thermometer
- Fine-tune `ANGLE_AT_MIN` / `ANGLE_AT_MAX`

**SSL certificate errors:**
- Add `-k` flag to curl or set `verify=False` in requests

**Image not loading:**
- Test your snapshot URL in a browser first
- Check firewall settings
