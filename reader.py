#!/usr/bin/env python3
"""
thermometer_reader_snapshot.py (Updated)

Liest den Wert deines analogen Thermometers (0–120 °C) über einen
HTTPS-Snapshot der Reolink 810A.

Updates:
- Interval changed to 5 minutes (300s).
- Saves only the ROI (cropped) to save disk space.
- Maintains a maximum of 100 images in history, deleting the oldest.
"""

import os, math, time, json, collections
import cv2, numpy as np
import paho.mqtt.publish as mqtt_publish
import requests, urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════ CONFIG ════════════════════════════════

import os

SNAPSHOT_URL = os.getenv(
    "SNAPSHOT_URL",
    "https://192.168.1.199/cgi-bin/api.cgi?cmd=Snap&channel=0.rs=abc123&user=admin&password=Gitarre123&width=1920&height=1080",
)

# ROI im 1920x1080-Referenzbild (y1, y2, x1, x2)
ROI_REFERENCE_SIZE = (1920, 1080)
ROI = (687, 829, 941, 1083)

# Normalisierung des Thermometer-Bilds
GAUGE_ROTATION = -23.0  # Grad, um das Thermometer gerade zu stellen
NORMALIZED_SIZE = 400  # px × px für das normalisierte Bild

# Skala: 0–120 °C über 240° Winkelbereich
TEMP_MIN = 0.0
TEMP_MAX = 120.0
ANGLE_AT_MIN = -120.0
ANGLE_AT_MAX = 120.0

# Zeiger-Erkennung / Glättung
ANGLE_SEARCH_MIN = -130.0
ANGLE_SEARCH_MAX = 130.0
ANGLE_STEP_DEG = 1.0
R_INNER_FRAC = 0.20
R_OUTER_FRAC = 0.85
R_SAMPLES = 30

MAX_JUMP_DEG = 40.0
SMOOTH_WINDOW = 5

# MQTT / Home Assistant
MQTT_HOST = os.getenv("MQTT_HOST", "192.168.1.180")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "mqtt")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "mqtt")

MQTT_TOPIC = "homeassistant/sensor/heizung_thermo/state"
MQTT_CFG = "homeassistant/sensor/heizung_thermo/config"

# Bilder speichern
SAVE_DIR = "captures"
SAVE_LATEST = "latest.jpg"
SAVE_NORM = "latest_normalized.jpg"
SAVE_HISTORY = True
HISTORY_DIR = "captures/history"
MAX_HISTORY_FILES = 100

INTERVAL = 300  # 5 Minuten (in Sekunden)

# ═══════════════════════════════════════════════════════════════════

os.makedirs(SAVE_DIR, exist_ok=True)
if SAVE_HISTORY:
    os.makedirs(HISTORY_DIR, exist_ok=True)

_prev_angle = None
_angle_hist = collections.deque(maxlen=SMOOTH_WINDOW)


def scale_roi(frame_shape):
    fh, fw = frame_shape[:2]
    ref_w, ref_h = ROI_REFERENCE_SIZE
    sy, sx = fh / ref_h, fw / ref_w
    y1, y2, x1, x2 = ROI
    return int(y1 * sy), int(y2 * sy), int(x1 * sx), int(x2 * sx)


def cleanup_history():
    """Löscht die ältesten Dateien, wenn mehr als MAX_HISTORY_FILES vorhanden sind."""
    if not SAVE_HISTORY:
        return

    files = [
        os.path.join(HISTORY_DIR, f)
        for f in os.listdir(HISTORY_DIR)
        if f.endswith(".jpg")
    ]
    if len(files) <= MAX_HISTORY_FILES:
        return

    # Sortieren nach Erstellungszeit (älteste zuerst)
    files.sort(key=os.path.getctime)

    to_delete = len(files) - MAX_HISTORY_FILES
    for i in range(to_delete):
        try:
            os.remove(files[i])
        except Exception as e:
            print(f"Fehler beim Löschen von {files[i]}: {e}")


def get_frame():
    r = requests.get(SNAPSHOT_URL, timeout=10, verify=False)
    r.raise_for_status()
    data = np.frombuffer(r.content, dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("Snapshot konnte nicht decodiert werden")
    return frame


def extract_normalized_gauge(gray_roi):
    blur = cv2.GaussianBlur(gray_roi, (9, 9), 2)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=30,
        param1=50,
        param2=30,
        minRadius=25,
        maxRadius=120,
    )
    if circles is None:
        raise RuntimeError("Kein Thermometer-Kreis erkannt")
    cx_r, cy_r, r = np.round(circles[0][0]).astype(int)

    pad = 5
    bx0 = max(cx_r - r - pad, 0)
    by0 = max(cy_r - r - pad, 0)
    bx1 = min(cx_r + r + pad, gray_roi.shape[1])
    by1 = min(cy_r + r + pad, gray_roi.shape[0])
    crop = gray_roi[by0:by1, bx0:bx1]

    big = cv2.resize(
        crop, (NORMALIZED_SIZE, NORMALIZED_SIZE), interpolation=cv2.INTER_CUBIC
    )

    if GAUGE_ROTATION != 0.0:
        center = (NORMALIZED_SIZE // 2, NORMALIZED_SIZE // 2)
        M = cv2.getRotationMatrix2D(center, GAUGE_ROTATION, 1.0)
        big = cv2.warpAffine(
            big,
            M,
            (NORMALIZED_SIZE, NORMALIZED_SIZE),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=128,
        )

    return big, cx_r, cy_r, r


def radial_needle_angle(norm_img):
    h, w = norm_img.shape
    cx, cy = w // 2, h // 2
    r = int(min(h, w) * 0.45)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    img = clahe.apply(norm_img)

    angles = np.arange(
        ANGLE_SEARCH_MIN, ANGLE_SEARCH_MAX + ANGLE_STEP_DEG, ANGLE_STEP_DEG
    )
    scores = []

    for a in angles:
        rad = math.radians(a)
        vals = []
        for frac in np.linspace(R_INNER_FRAC, R_OUTER_FRAC, R_SAMPLES):
            x = cx + r * frac * math.sin(rad)
            y = cy - r * frac * math.cos(rad)
            if 0 <= x < w - 1 and 0 <= y < h - 1:
                x0, y0 = int(x), int(y)
                dx, dy = x - x0, y - y0
                v = (
                    img[y0, x0] * (1 - dx) * (1 - dy)
                    + img[y0, x0 + 1] * dx * (1 - dy)
                    + img[y0 + 1, x0] * (1 - dx) * dy
                    + img[y0 + 1, x0 + 1] * dx * dy
                )
                vals.append(v)
        if vals:
            scores.append(sum(vals) / len(vals))
        else:
            scores.append(255.0)

    scores = np.array(scores, dtype=np.float32)
    idx = int(np.argmin(scores))
    return float(angles[idx])


def smooth_angle(raw_angle):
    global _prev_angle, _angle_hist
    if _prev_angle is not None and abs(raw_angle - _prev_angle) > MAX_JUMP_DEG:
        return _prev_angle
    _angle_hist.append(raw_angle)
    smoothed = sum(_angle_hist) / len(_angle_hist)
    _prev_angle = smoothed
    return smoothed


def detect_gauge(frame):
    y1, y2, x1, x2 = scale_roi(frame.shape)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = gray[y1:y2, x1:x2]

    norm, cx_r, cy_r, r = extract_normalized_gauge(roi)
    raw_angle = radial_needle_angle(norm)
    angle = smooth_angle(raw_angle)

    cx_abs = x1 + cx_r
    cy_abs = y1 + cy_r

    rad = math.radians(angle)
    needle_len = int(r * 0.8)
    tip_abs = (
        int(cx_abs + needle_len * math.sin(rad)),
        int(cy_abs - needle_len * math.cos(rad)),
    )

    return angle, cx_abs, cy_abs, r, y1, y2, x1, x2, tip_abs, norm


def angle_to_temperature(angle: float) -> float:
    ratio = (angle - ANGLE_AT_MIN) / (ANGLE_AT_MAX - ANGLE_AT_MIN)
    ratio = max(0.0, min(1.0, ratio))
    return round(TEMP_MIN + ratio * (TEMP_MAX - TEMP_MIN), 1)


def annotate_and_save(frame, norm, angle, temperature, cx, cy, r, roi_coords, tip):
    y1, y2, x1, x2 = roi_coords

    # Text-Overlay vorbereiten
    ts = time.strftime("%d.%m.%Y %H:%M:%S")
    label = f"{temperature:.1f} C  |  {angle:.1f} deg  |  {ts}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)

    # ROI-Annotationen auf dem Original zeichnen
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
    cv2.circle(frame, (cx, cy), r, (0, 255, 0), 2)
    cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)

    # Label Box zeichnen
    cv2.rectangle(frame, (x1, y1 - th - 20), (x1 + tw + 10, y1), (0, 0, 0), -1)
    cv2.putText(
        frame, label, (x1 + 5, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2
    )

    # --- CROPPING FOR STORAGE EFFICIENCY ---
    # Crop-Bereich definieren: ROI + Padding für das Label
    padding = 50
    crop_y1 = max(0, y1 - th - padding)
    crop_y2 = min(frame.shape[0], y2 + padding)
    crop_x1 = max(0, x1 - padding)
    crop_x2 = min(frame.shape[1], x2 + padding)

    cropped_out = frame[crop_y1:crop_y2, crop_x1:crop_x2]

    # Speichern des neuesten Bildes (gecropped)
    cv2.imwrite(os.path.join(SAVE_DIR, SAVE_LATEST), cropped_out)
    cv2.imwrite(os.path.join(SAVE_DIR, SAVE_NORM), norm)

    # In die Historie speichern
    if SAVE_HISTORY:
        fname = time.strftime("%Y%m%d_%H%M%S") + f"_{temperature:.1f}C.jpg"
        cv2.imwrite(os.path.join(HISTORY_DIR, fname), cropped_out)
        cleanup_history()


def publish_ha_discovery():
    config = {
        "name": "Heizungsthermometer",
        "state_topic": MQTT_TOPIC,
        "unit_of_measurement": "°C",
        "device_class": "temperature",
        "unique_id": "heizung_thermo_cam",
        "icon": "mdi:thermometer",
    }
    mqtt_publish.single(
        MQTT_CFG,
        json.dumps(config),
        hostname=MQTT_HOST,
        port=MQTT_PORT,
        retain=True,
        auth={"username": MQTT_USER, "password": MQTT_PASSWORD},
    )


def run():
    publish_ha_discovery()
    print(f"Gestartet — Bilder: {SAVE_DIR}/  |  Intervall: {INTERVAL}s")
    while True:
        try:
            frame = get_frame()
            angle, cx, cy, r, y1, y2, x1, x2, tip, norm = detect_gauge(frame)
            temperature = angle_to_temperature(angle)

            annotate_and_save(
                frame, norm, angle, temperature, cx, cy, r, (y1, y2, x1, x2), tip
            )

            mqtt_publish.single(
                MQTT_TOPIC,
                str(temperature),
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                retain=True,
                auth={"username": MQTT_USER, "password": MQTT_PASSWORD},
            )

            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"angle: {angle:.1f}°  →  {temperature:.1f} °C  ✓ (Saved Cropped)"
            )

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}]  FEHLER: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    run()
