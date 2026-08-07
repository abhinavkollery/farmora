# Farmora AI — Smart Agriculture Platform

Farmora AI is an intelligent agricultural monitoring and management system powered by Flask, XGBoost, and TensorFlow.

---

## 📁 Repository Structure

```
farmorai/
├── main.py                      # Flask REST API, background scheduler & telemetry handlers
├── disease_predict.py           # TensorFlow crop disease detection & recommendation engine
├── mandi_price.py               # Agmarknet market benchmark price service
├── requirements.txt             # Python dependencies
├── Procfile                     # Web process start declaration
├── render.yaml                  # Render Infrastructure-as-Code Blueprint
├── runtime.txt                  # Python runtime specification (python-3.10.12)
├── .gitignore
├── static/
│   ├── index.html               # Farmora AI Dashboard UI
│   └── script.js                # Frontend API client
├── xgb_crop_model.json          # Trained XGBoost irrigation model
├── label_encoders.joblib        # Categorical encoders
└── models/
    ├── rice/
    │   ├── Rice.h5              # Rice disease Keras CNN model
    │   └── class_indices.json   # Class label mapping
    └── sugarcane/
        ├── Sugarcane.h5         # Sugarcane disease Keras CNN model
        └── class_indices.json   # Class label mapping
```

---

## 🚀 Deployment on Render

Render supports zero-config deployment using Gunicorn and Render Blueprints.

### Option A: Deploy via Render Blueprint (Recommended)
1. Push this repository to **GitHub**.
2. Log in to [Render](https://dashboard.render.com).
3. Click **New +** -> **Blueprint**.
4. Connect your GitHub repository.
5. Render will automatically detect `render.yaml` and configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn main:app`
   - **Python Version**: `3.10.12`
6. Click **Apply**. Render will build and deploy your application.

---

### Option B: Manual Web Service Creation on Render
1. Log in to [Render](https://dashboard.render.com).
2. Click **New +** -> **Web Service**.
3. Connect your repository.
4. Set the following fields:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn main:app`
5. (Optional) Configure Environment Variables:
   - `PYTHON_VERSION`: `3.10.12`
   - `MODEL_DIR`: `models`
6. Click **Create Web Service**.

---

## 🔒 Database Configuration Options

Farmora AI features **dual-database support**:

- **Automatic SQLite Fallback (Default)**: If no MySQL credentials are provided, Farmora AI automatically initializes and uses a local SQLite database (`neurobots.db`). No configuration is required.
- **External MySQL (Optional)**: To use an external MySQL database (e.g., Aiven or Railway MySQL), set the following environment variables in Render:
  - `DB_HOST`: Hostname of MySQL database
  - `DB_USER`: Database username
  - `DB_PASSWORD`: Database password (mark as Secret)
  - `DB_NAME`: Database name
  - `DB_PORT`: Database port (default: 3306)

---

## 🧪 Local Execution & Verification

To run locally using the virtual environment:
```bash
./venv/bin/python main.py
```
Or run via Gunicorn:
```bash
./venv/bin/gunicorn main:app
```
Access the dashboard at `http://localhost:5000`.
