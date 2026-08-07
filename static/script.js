// ============ FARMORA - AI : APP SCRIPT ============

document.addEventListener('DOMContentLoaded', () => {

  /* ---------- NAVIGATION ---------- */
  const navLinks = document.querySelectorAll('.nav-link');
  const pages = document.querySelectorAll('.page');

  function goToPage(pageId) {
    pages.forEach(page => page.classList.toggle('active', page.id === pageId));
    navLinks.forEach(link => link.classList.toggle('active', link.dataset.page === pageId));
    history.replaceState(null, '', `#${pageId}`);
    if (pageId === 'home') {
      playHomeAnimation();
    } else {
      playPageAnimation(pageId);
    }
  }

  function playHomeAnimation() {
    const grid = document.querySelector('.home-grid');
    if (!grid) return;
    grid.classList.remove('play');
    void grid.offsetWidth; // force reflow
    grid.classList.add('play');
  }

  function playPageAnimation(pageId) {
    const page = document.getElementById(pageId);
    if (!page) return;
    const items = page.querySelectorAll('.reveal');
    items.forEach((el, i) => {
      el.classList.remove('reveal-play');
      el.style.animationDelay = (i * 0.07) + 's';
    });
    void page.offsetWidth;
    requestAnimationFrame(() => {
      items.forEach(el => el.classList.add('reveal-play'));
    });
  }

  navLinks.forEach(link => link.addEventListener('click', () => goToPage(link.dataset.page)));

  const initialPage = window.location.hash.replace('#', '');
  if (document.getElementById(initialPage)) {
    goToPage(initialPage);
  } else {
    playHomeAnimation();
  }

  const pageOrder = Array.from(pages).map(p => p.id);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const modalOverlay = document.getElementById('modalOverlay');
    if (modalOverlay && modalOverlay.classList.contains('open')) return;
    const activePage = document.querySelector('.page.active');
    if (!activePage) return;
    const current = activePage.id;
    let idx = pageOrder.indexOf(current);
    idx = e.key === 'ArrowRight' ? (idx + 1) % pageOrder.length : (idx - 1 + pageOrder.length) % pageOrder.length;
    goToPage(pageOrder[idx]);
  });

  /* ---------- MODAL ---------- */
  const modalOverlay = document.getElementById('modalOverlay');
  const modalContent = document.getElementById('modalContent');
  const modalClose = document.getElementById('modalClose');

  function openModal(html) {
    if (!modalContent || !modalOverlay) return;
    modalContent.innerHTML = html;
    modalOverlay.classList.add('open');
  }
  function closeModal() {
    if (!modalOverlay) return;
    modalOverlay.classList.remove('open');
  }
  if (modalClose) modalClose.addEventListener('click', closeModal);
  if (modalOverlay) modalOverlay.addEventListener('click', (e) => { if (e.target === modalOverlay) closeModal(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

  /* ---------- TOAST ---------- */
  const toastStack = document.getElementById('toastStack');
  function showToast(message) {
    if (!toastStack) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    toastStack.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  /* ---------- GET STARTED ---------- */
  const getStartedBtn = document.getElementById('getStartedBtn');
  if (getStartedBtn) getStartedBtn.addEventListener('click', () => {
    goToPage('sensors');
    showToast("Welcome! Here's your live field dashboard.");
  });

  /* ---------- WATCH DEMO ---------- */
  const watchDemoBtn = document.getElementById('watchDemoBtn');
  if (watchDemoBtn) watchDemoBtn.addEventListener('click', () => {
    openModal(`
      <div style="text-align:center; padding:10px;">
        <h3 style="margin-bottom:10px; color:#8CFF6B;">▶ Farmora AI Demo</h3>
        <p style="margin-bottom:15px; font-size:14px; color:#cbd5e1;">Watch our intelligent agricultural management walkthrough.</p>
        <a href="https://youtu.be/w_uo3FyGN3k?si=2C-eQBugHiC2i17i" target="_blank" class="btn btn-primary" style="display:inline-block; padding:10px 20px;">Open Demo Video ↗</a>
      </div>
    `);
  });

  /* ---------- SENSOR POLLING & WATERING PREDICTION ---------- */
  const sensorSelect = document.getElementById('sensorSelect');
  const soilMoistureVal = document.getElementById('soilMoistureVal');
  const soilTempVal = document.getElementById('soilTempVal');
  const airHumVal = document.getElementById('airHumVal');
  const wateringDecisionText = document.getElementById('wateringDecisionText');

  async function loadAvailableSensors() {
    if (!sensorSelect) return;
    try {
      const res = await fetch('/sensors');
      if (res.ok) {
        const data = await res.json();
        if (data.sensors && data.sensors.length) {
          const currentVal = sensorSelect.value;
          sensorSelect.innerHTML = data.sensors.map(id => `<option value="${id}">${id}</option>`).join('');
          if (data.sensors.includes(currentVal)) {
            sensorSelect.value = currentVal;
          }
        }
      }
    } catch (e) {
      console.warn('[Sensors List] Could not fetch sensors:', e);
    }
  }

  async function pollLatestSensorData() {
    const sensorId = sensorSelect ? sensorSelect.value : 'ESP_01';
    try {
      const res = await fetch(`/latest/${sensorId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.reading) {
          if (soilMoistureVal) soilMoistureVal.textContent = (data.reading['soil moisture'] || data.reading['soil_moisture'] || '--') + '%';
          if (soilTempVal) soilTempVal.textContent = (data.reading['temperature'] || '--') + '°C';
          if (airHumVal) airHumVal.textContent = (data.reading['humidity'] || '--') + '%';
        }
        if (data.prediction && wateringDecisionText) {
          if (data.prediction.water === 1) {
            wateringDecisionText.textContent = '💧 Irrigation Recommended: Turn Water Pump ON';
            wateringDecisionText.style.color = '#8CFF6B';
          } else {
            wateringDecisionText.textContent = '✅ Optimal Moisture: Irrigation Pump OFF';
            wateringDecisionText.style.color = '#38bdf8';
          }
        }
      }
    } catch (err) {
      console.warn('[Telemetry Polling] Error fetching latest sensor reading:', err);
    }
  }

  if (sensorSelect) {
    sensorSelect.addEventListener('change', pollLatestSensorData);
  }
  loadAvailableSensors();
  setInterval(loadAvailableSensors, 15000);
  setInterval(pollLatestSensorData, 5000);
  pollLatestSensorData();

  /* ---------- TELEMETRY SIMULATOR MODAL ---------- */
  const simulateModalBtn = document.getElementById('simulateModalBtn');
  if (simulateModalBtn) {
    simulateModalBtn.addEventListener('click', () => {
      openModal(`
        <div style="padding:15px;">
          <h3 style="color:#8CFF6B; margin-bottom:12px;">⚡ Simulate Field Telemetry</h3>
          <p style="font-size:13px; color:#94a3b8; margin-bottom:15px;">Inject custom sensor values to test XGBoost watering prediction.</p>
          <div style="display:flex; flex-direction:column; gap:10px; text-align:left;">
            <label style="font-size:12px; color:#cbd5e1;">Soil Moisture (%)
              <input type="number" id="simMoisture" value="25" min="0" max="100" style="width:100%; padding:8px; border-radius:6px; background:#1e293b; border:1px solid #334155; color:#fff; margin-top:4px;">
            </label>
            <label style="font-size:12px; color:#cbd5e1;">Temperature (°C)
              <input type="number" id="simTemp" value="30" style="width:100%; padding:8px; border-radius:6px; background:#1e293b; border:1px solid #334155; color:#fff; margin-top:4px;">
            </label>
            <label style="font-size:12px; color:#cbd5e1;">Air Humidity (%)
              <input type="number" id="simHum" value="60" style="width:100%; padding:8px; border-radius:6px; background:#1e293b; border:1px solid #334155; color:#fff; margin-top:4px;">
            </label>
            <button id="sendSimBtn" class="btn btn-primary" style="margin-top:10px; width:100%;">Submit Simulation</button>
          </div>
        </div>
      `);

      setTimeout(() => {
        const sendSimBtn = document.getElementById('sendSimBtn');
        if (sendSimBtn) {
          sendSimBtn.addEventListener('click', async () => {
            const m = parseFloat(document.getElementById('simMoisture').value) || 25;
            const t = parseFloat(document.getElementById('simTemp').value) || 30;
            const h = parseFloat(document.getElementById('simHum').value) || 60;
            const sensorId = sensorSelect ? sensorSelect.value : 'ESP_01';

            try {
              const res = await fetch('/simulate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ESP_no: sensorId, soil_moisture: m, temperature: t, humidity: h })
              });
              if (res.ok) {
                showToast(`Simulation sent: Moisture ${m}%`);
                closeModal();
                pollLatestSensorData();
              }
            } catch (e) {
              showToast('Simulation failed to connect.');
            }
          });
        }
      }, 100);
    });
  }

  /* ---------- MANDI MARKET PRICE LOOKUP ---------- */
  const mandiCropSelect = document.getElementById('mandiCropSelect') || document.getElementById('cropSelect');
  const stateSelect = document.getElementById('stateSelect');
  const districtSelect = document.getElementById('districtSelect');

  async function loadMandiPrices() {
    const crop = mandiCropSelect ? mandiCropSelect.value : 'rice';
    const state = stateSelect ? stateSelect.value : '';
    const district = districtSelect ? districtSelect.value : '';

    try {
      const res = await fetch(`/mandi-price?crop=${encodeURIComponent(crop)}&state=${encodeURIComponent(state)}&district=${encodeURIComponent(district)}`);
      if (res.ok) {
        const data = await res.json();
        const mandiPriceEl = document.getElementById('mandiPriceVal');
        const mandiNameEl = document.getElementById('mandiNameVal');
        const mandiTrendEl = document.getElementById('mandiTrendVal');
        if (mandiPriceEl) mandiPriceEl.textContent = `₹${data.price_per_quintal || '--'} / qtl`;
        if (mandiNameEl) mandiNameEl.textContent = `${data.mandi || 'Market Mandi'} (${data.state || ''})`;
        if (mandiTrendEl) mandiTrendEl.textContent = data.trend || '0.0%';
      }
    } catch (e) {
      console.warn('[Mandi Lookup] Error:', e);
    }
  }

  if (mandiCropSelect) mandiCropSelect.addEventListener('change', loadMandiPrices);
  if (stateSelect) stateSelect.addEventListener('change', loadMandiPrices);
  if (districtSelect) districtSelect.addEventListener('change', loadMandiPrices);
  loadMandiPrices();

  /* ---------- TENSORFLOW DISEASE SCANNER ---------- */
  const diseaseForm = document.getElementById('diseaseForm');
  const diseaseFileInput = document.getElementById('diseaseFileInput');
  const diseaseCropSelect = document.getElementById('diseaseCropSelect');
  const diseaseResultBox = document.getElementById('diseaseResultBox');

  if (diseaseForm) {
    diseaseForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!diseaseFileInput || !diseaseFileInput.files.length) {
        showToast('Please select a crop leaf image to scan.');
        return;
      }
      const formData = new FormData();
      formData.append('image', diseaseFileInput.files[0]);
      formData.append('crop', diseaseCropSelect ? diseaseCropSelect.value : 'rice');

      if (diseaseResultBox) {
        diseaseResultBox.innerHTML = '<p style="color:#8CFF6B;">🔍 Running TensorFlow Neural Network Inference...</p>';
      }

      try {
        const res = await fetch('/disease', { method: 'POST', body: formData });
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'ok' && data.top_prediction) {
            const pred = data.top_prediction;
            diseaseResultBox.innerHTML = `
              <div style="background:#1e293b; padding:15px; border-radius:10px; border:1px solid #334155; margin-top:10px;">
                <h4 style="color:#8CFF6B; font-size:16px; margin-bottom:8px;">Diagnosis: ${pred.name}</h4>
                <p style="font-size:13px; color:#cbd5e1; margin-bottom:5px;"><b>Confidence:</b> ${pred.confidence}%</p>
                <p style="font-size:13px; color:#cbd5e1; margin-bottom:5px;"><b>Severity:</b> <span style="color:${pred.severity === 'High' ? '#ef4444' : '#f59e0b'};">${pred.severity}</span> (Affected Area: ${pred.area || 'N/A'})</p>
                <p style="font-size:13px; color:#38bdf8; margin-top:8px;"><b>Recommended Treatment:</b> ${pred.action}</p>
              </div>
            `;
          } else {
            if (diseaseResultBox) diseaseResultBox.innerHTML = '<p style="color:#ef4444;">Could not analyze image. Try another leaf sample.</p>';
          }
        }
      } catch (err) {
        if (diseaseResultBox) diseaseResultBox.innerHTML = '<p style="color:#ef4444;">Server connection error during scan.</p>';
      }
    });
  }

});
