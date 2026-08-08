import os
import sys
import re
import base64
import uuid
import sqlite3
from datetime import datetime
from contextlib import contextmanager

from flask import Flask, request, jsonify, send_from_directory
import mysql.connector as sql
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import joblib
import xgboost as xgb
import pandas as pd
import requests

import disease_predict
import mandi_price

# ---------------------------------------------------------------------
# Config (all from environment variables — set these in Render's
# dashboard, never hardcode secrets in the repo)
# ---------------------------------------------------------------------
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "Neurobots")

# Aiven (and most managed MySQL hosts) require SSL. Store the CA cert
# base64-encoded in an env var so nothing sensitive is committed to git.
DB_SSL_CA_B64 = os.environ.get("DB_SSL_CA_B64")
DB_SSL_CA_PATH = "/tmp/db-ca.pem"
if DB_SSL_CA_B64:
    with open(DB_SSL_CA_PATH, "wb") as _f:
        _f.write(base64.b64decode(DB_SSL_CA_B64))

API_KEY = os.environ.get("SENSOR_API_KEY")  # if unset, key check is skipped (dev only)

LATITUDE = os.environ.get("FARM_LAT", "10.5276")
LONGITUDE = os.environ.get("FARM_LON", "76.2144")

crop = os.environ.get("DEFAULT_CROP", "Wheat")
soil = os.environ.get("DEFAULT_SOIL", "Black Soil")
seedling_stage = os.environ.get("DEFAULT_STAGE", "Germination")

SENSOR_ID_PATTERN = re.compile(r'^[A-Za-z0-9_]+$')

# In-memory caches
latest_data_by_sensor = {}
latest_predictions = {}     # sensor -> {"water": 0/1, "time": "..."}
weather_forecast = {}
prediction_probability = []

from sklearn.preprocessing import LabelEncoder


def load_or_create_encoders():
    path = "label_encoders.joblib"
    is_lfs = False
    if os.path.exists(path) and os.path.getsize(path) < 4096:
        with open(path, "r", errors="ignore") as f:
            if "git-lfs" in f.read(100):
                is_lfs = True

    if not is_lfs and os.path.exists(path):
        try:
            return joblib.load(path)
        except Exception:
            pass

    print("[Encoder] Constructing active LabelEncoders...")
    crop_enc = LabelEncoder()
    crop_enc.fit(["Wheat", "Rice", "Sugarcane", "Cotton", "Maize"])
    soil_enc = LabelEncoder()
    soil_enc.fit(["Black Soil", "Clay Soil", "Loam Soil", "Red Soil", "Sandy Soil"])
    stage_enc = LabelEncoder()
    stage_enc.fit(["Germination", "Vegetative", "Flowering", "Harvest"])

    encoders_dict = {
        "crop ID": crop_enc,
        "soil_type": soil_enc,
        "Seedling Stage": stage_enc
    }
    try:
        joblib.dump(encoders_dict, path)
    except Exception as e:
        print(f"[Encoder] Could not save encoders to disk: {e}")
    return encoders_dict


# ---------------------------------------------------------------------
# Load models once at startup
# ---------------------------------------------------------------------
irrigation_model = xgb.XGBClassifier()
irrigation_model.load_model("xgb_crop_model.json")
encoders = load_or_create_encoders()

disease_predict.load_all_models()

# ---------------------------------------------------------------------
# Database — MySQL primary with seamless SQLite fallback.
# ---------------------------------------------------------------------
_conn = None
_db_mode = None  # 'mysql' or 'sqlite'


def _connect():
    global _db_mode
    # Only try MySQL if explicitly configured or if DB_HOST is set to non-default
    if os.environ.get("DB_HOST") or os.environ.get("DB_USER"):
        try:
            conn = sql.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER,
                password=DB_PASSWORD, database=DB_NAME,
                ssl_ca=DB_SSL_CA_PATH if DB_SSL_CA_B64 else None,
                ssl_verify_cert=bool(DB_SSL_CA_B64),
                connect_timeout=3
            )
            _db_mode = "mysql"
            print("[Database] Connected to MySQL database.")
            return conn
        except Exception as e:
            print(f"[Database] MySQL connection failed ({e}). Falling back to SQLite.")

    _db_mode = "sqlite"
    print("[Database] Using SQLite local database (neurobots.db).")
    return sqlite3.connect("neurobots.db", check_same_thread=False)


def _get_conn():
    global _conn, _db_mode
    if _db_mode == "sqlite":
        if _conn is None:
            _conn = _connect()
        return _conn

    if _conn is None or not getattr(_conn, "is_connected", lambda: False)():
        try:
            _conn = _connect()
        except Exception:
            _db_mode = "sqlite"
            _conn = sqlite3.connect("neurobots.db", check_same_thread=False)
    return _conn


@contextmanager
def get_cursor(buffered=False):
    """Yields a cursor on a live connection, reconnecting if needed,
    and commits on clean exit."""
    conn = _get_conn()
    if _db_mode == "sqlite":
        cursor = conn.cursor()
    else:
        cursor = conn.cursor(buffered=buffered)
    try:
        yield cursor
        conn.commit()
    finally:
        cursor.close()


def db_execute(cursor, query, params=()):
    """Helper to execute SQL handling dialect differences between MySQL and SQLite."""
    if _db_mode == "sqlite":
        query = query.replace("%s", "?")
        if "INSERT INTO SENSORS" in query and "ON DUPLICATE KEY UPDATE" in query:
            query = "INSERT OR REPLACE INTO SENSORS (Sensor_no, last_seen) VALUES (?, ?)"
        elif "ON DUPLICATE KEY UPDATE" in query:
            query = query.split("ON DUPLICATE KEY UPDATE")[0].strip()
    cursor.execute(query, params)


with get_cursor() as _setup_cursor:
    if _db_mode == "sqlite":
        _setup_cursor.execute(
            "CREATE TABLE IF NOT EXISTS SENSORS (Sensor_no TEXT PRIMARY KEY, last_seen TEXT);"
        )
    else:
        _setup_cursor.execute(
            "CREATE TABLE IF NOT EXISTS SENSORS (Sensor_no varchar(50) PRIMARY KEY, last_seen varchar(50));"
        )


# ---------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="")
scheduler = BackgroundScheduler()


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def _check_api_key(req):
    if API_KEY is None:
        return True  # no key configured -> skip check (fine for local dev only)
    return req.headers.get("X-API-Key") == API_KEY


@app.route("/sensor", methods=["POST"])
def receive_sensor():
    if not _check_api_key(request):
        return jsonify({"status": "error", "message": "Invalid or missing API key"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "Expected a JSON object body"}), 400

    current_sensor = payload.get("ESP_no")
    if not current_sensor or not SENSOR_ID_PATTERN.match(str(current_sensor)):
        return jsonify({"status": "error", "message": "Missing or invalid ESP_no"}), 400

    now_str = str(datetime.now())
    payload["time"] = now_str
    latest_data_by_sensor[current_sensor] = payload

    with get_cursor() as cursor:
        db_execute(cursor, """
            INSERT INTO SENSORS (Sensor_no, last_seen)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE last_seen = VALUES(last_seen)
        """, (current_sensor, now_str))

        db_execute(cursor,
            f'CREATE TABLE IF NOT EXISTS `{current_sensor}` '
            '(TIME_STAMP VARCHAR(50), TEMPERATURE DECIMAL(4,1), '
            'HUMIDITY DECIMAL(4,1), SOIL_MOISTURE DECIMAL(4,1), PRESSURE DECIMAL(6,2))'
        )

        db_execute(cursor,
            f'INSERT INTO `{current_sensor}` (TIME_STAMP, TEMPERATURE, HUMIDITY, SOIL_MOISTURE, PRESSURE) '
            'VALUES (%s, %s, %s, %s, %s)',
            (now_str, payload.get("temperature", 25.0), payload.get("humidity", 60.0), payload.get("soil moisture", payload.get("soil_moisture", 50.0)), payload.get("pressure", 1013.25))
        )

    # Immediately trigger watering prediction update for this sensor
    watering_prediction()

    return jsonify({"status": "ok", "prediction": latest_predictions.get(current_sensor, {})}), 200


@app.route("/simulate", methods=["POST"])
def simulate_sensor():
    """UI helper to simulate incoming sensor telemetry."""
    payload = request.get_json(silent=True) or {}
    sensor_id = str(payload.get("ESP_no") or "SIM_01")
    temp = float(payload.get("temperature", 27.0))
    hum = float(payload.get("humidity", 65.0))
    moi = float(payload.get("soil_moisture", payload.get("soil moisture", 55.0)))

    now_str = str(datetime.now())
    rec_payload = {
        "ESP_no": sensor_id,
        "temperature": temp,
        "humidity": hum,
        "soil moisture": moi,
        "time": now_str
    }
    latest_data_by_sensor[sensor_id] = rec_payload

    with get_cursor() as cursor:
        db_execute(cursor, """
            INSERT INTO SENSORS (Sensor_no, last_seen)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE last_seen = VALUES(last_seen)
        """, (sensor_id, now_str))

        db_execute(cursor,
            f'CREATE TABLE IF NOT EXISTS `{sensor_id}` '
            '(TIME_STAMP VARCHAR(50), TEMPERATURE DECIMAL(4,1), '
            'HUMIDITY DECIMAL(4,1), SOIL_MOISTURE DECIMAL(4,1))'
        )
        db_execute(cursor,
            f'INSERT INTO `{sensor_id}` (TIME_STAMP, TEMPERATURE, HUMIDITY, SOIL_MOISTURE) '
            'VALUES (%s, %s, %s, %s)',
            (now_str, temp, hum, moi)
        )

    watering_prediction()

    return jsonify({"status": "ok", "reading": rec_payload, "prediction": latest_predictions.get(sensor_id, {})})


@app.route("/latest/<sensor_id>", methods=["GET"])
def latest(sensor_id):
    """UI polls this to show the current watering decision + raw reading for a sensor."""
    target_id = None
    for k in latest_data_by_sensor.keys():
        if k.lower() == str(sensor_id).lower():
            target_id = k
            break
    if not target_id:
        target_id = sensor_id

    return jsonify({
        "reading": latest_data_by_sensor.get(target_id, {}),
        "prediction": latest_predictions.get(target_id, {}),
    })


@app.route("/sensors", methods=["GET"])
def list_sensors():
    """UI can call this to populate a dropdown of known sensors."""
    sensors_set = set(latest_data_by_sensor.keys())
    try:
        with get_cursor(buffered=True) as cursor:
            db_execute(cursor, "SELECT Sensor_no FROM SENSORS")
            rows = cursor.fetchall()
            for r in rows:
                if r and r[0]:
                    sensors_set.add(r[0])
    except Exception as e:
        print(f"[Sensors DB List] Error: {e}")

    return jsonify({"sensors": sorted(list(sensors_set))})


@app.route("/disease", methods=["POST"])
def disease_endpoint():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image file uploaded"}), 400
    crop_param = request.form.get("crop")
    if not crop_param:
        return jsonify({
            "status": "error",
            "message": f"Missing 'crop' field. Available: {disease_predict.available_crops()}"
        }), 400

    tmp_path = f"/tmp/upload_{uuid.uuid4().hex}.jpg"
    request.files["image"].save(tmp_path)

    try:
        result = disease_predict.predict(tmp_path, crop_param)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return jsonify({"status": "ok", **result})


@app.route("/mandi-price", methods=["GET"])
def mandi_price_endpoint():
    crop_param = request.args.get("crop", crop)
    state = request.args.get("state")
    district = request.args.get("district")
    result = mandi_price.fetch_mandi_price(crop_param, state, district)
    return jsonify(result)


# ---------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------
def store_latest_readings():
    if not latest_data_by_sensor:
        return

    try:
        with get_cursor() as cursor:
            for sensor, data in latest_data_by_sensor.items():
                temp = data.get("temperature")
                humidity = data.get("humidity")
                soil_moisture = data.get("soil moisture", data.get("soil_moisture"))
                time_stamp = data.get("time")

                if None in (temp, humidity, soil_moisture, time_stamp):
                    continue

                pressure = data.get("pressure", 1013.25)
                db_execute(cursor,
                    f'CREATE TABLE IF NOT EXISTS `{sensor}` '
                    '(TIME_STAMP VARCHAR(50), TEMPERATURE DECIMAL(4,1), '
                    'HUMIDITY DECIMAL(4,1), SOIL_MOISTURE DECIMAL(4,1), PRESSURE DECIMAL(6,2))'
                )
                db_execute(cursor,
                    f'INSERT INTO `{sensor}` (TIME_STAMP, TEMPERATURE, HUMIDITY, SOIL_MOISTURE, PRESSURE) '
                    'VALUES (%s, %s, %s, %s, %s)',
                    (time_stamp, temp, humidity, soil_moisture, pressure)
                )
    except Exception as e:
        print(f"[Store Readings] Error: {e}")


def fetch_weather():
    global weather_forecast, prediction_probability

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&hourly=temperature_2m,precipitation_probability,precipitation"
        "&forecast_hours=10"
    )
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            hourly = data.get("hourly")
            if hourly and "precipitation_probability" in hourly and "time" in hourly:
                weather_forecast = {}
                prediction_probability = []
                for i in range(min(10, len(hourly["time"]))):
                    t = hourly["time"][i]
                    p = hourly["precipitation_probability"][i]
                    weather_forecast[t] = p
                    prediction_probability.append(p)
                return
    except Exception as e:
        print(f"Weather fetch fallback active ({e}).")

    # Fallback forecast data if network is unavailable
    prediction_probability = [15, 20, 25, 10, 5, 0, 0, 10, 15, 20]


def watering_prediction():
    if not prediction_probability:
        prediction_probability.extend([15, 20, 25, 10, 5, 0, 0, 10, 15, 20])

    try:
        with get_cursor(buffered=True) as cursor:
            db_execute(cursor, "SELECT Sensor_no FROM SENSORS")
            sensor_list = cursor.fetchall()

            for row in sensor_list:
                sensor_name = row[0]
                try:
                    db_execute(cursor, f"SELECT * FROM `{sensor_name}` ORDER BY TIME_STAMP DESC LIMIT 1")
                    data = cursor.fetchone()
                except Exception:
                    continue
                if data is None:
                    continue

                temp = float(data[1])
                humidity = float(data[2])
                soil_moisture = float(data[3])

                # Transform categorical variables using label encoders
                crop_enc = encoders["crop ID"].transform([crop])[0] if crop in encoders["crop ID"].classes_ else 0
                soil_enc = encoders["soil_type"].transform([soil])[0] if soil in encoders["soil_type"].classes_ else 0
                stage_enc = encoders["Seedling Stage"].transform([seedling_stage])[0] if seedling_stage in encoders["Seedling Stage"].classes_ else 0

                sample = pd.DataFrame([{
                    "crop ID": crop_enc,
                    "soil_type": soil_enc,
                    "Seedling Stage": stage_enc,
                    "MOI": soil_moisture,
                    "temp": temp,
                    "humidity": humidity,
                }])

                prediction = irrigation_model.predict(sample)[0]
                final_outcome = 0

                if prediction == 1:
                    final_outcome = 1
                    for i in range(min(9, len(prediction_probability))):
                        p = prediction_probability[i]
                        if i <= 2 and p > 60 and soil_moisture > 60:
                            final_outcome = 0
                        elif 2 < i <= 4 and p > 70 and soil_moisture > 70:
                            final_outcome = 0
                        elif 4 < i <= 7 and p > 80 and soil_moisture > 80:
                            final_outcome = 0
                        elif 7 < i <= 10 and p > 90 and soil_moisture > 90:
                            final_outcome = 0

                latest_predictions[sensor_name] = {
                    "water": int(final_outcome),
                    "time": str(datetime.now()),
                }
    except Exception as e:
        print(f"[Watering Prediction] Error: {e}")


def wrapper_job():
    store_latest_readings()
    watering_prediction()


# ---------------------------------------------------------------------
# Startup — runs at import time so it fires under gunicorn too
# ---------------------------------------------------------------------
fetch_weather()
watering_prediction()
scheduler.add_job(func=fetch_weather, trigger="interval", seconds=600)
scheduler.add_job(func=wrapper_job, trigger="interval", seconds=10)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Farmora AI Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port)
