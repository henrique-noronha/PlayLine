(() => {
  const modal        = document.getElementById("capture-modal");
  const btnOpen      = document.getElementById("btn-capture-open");
  const btnClose     = document.getElementById("capture-modal-close");
  const btnCancel    = document.getElementById("btn-capture-cancel");
  const btnAdd       = document.getElementById("btn-capture-add");
  const deviceList   = document.getElementById("capture-device-list");
  const previewWrap  = document.getElementById("capture-modal-preview-wrap");
  const previewVideo = document.getElementById("capture-modal-video");

  let selectedDevice = null;
  let _stream = null;

  function stopStream() {
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    previewVideo.srcObject = null;
    previewWrap.style.display = "none";
  }

  function openModal() {
    selectedDevice = null;
    btnAdd.disabled = true;
    previewWrap.style.display = "none";
    modal.style.display = "flex";
    loadDevices();
  }

  function closeModal() {
    stopStream();
    modal.style.display = "none";
    selectedDevice = null;
    btnAdd.disabled = true;
  }

  async function startPreview(deviceName) {
    stopStream();
    previewWrap.style.display = "block";
    try {
      const devices   = await navigator.mediaDevices.enumerateDevices();
      const videoDevs = devices.filter(d => d.kind === "videoinput" && d.label);
      const match = videoDevs.find(d =>
        d.label.toLowerCase().includes(deviceName.toLowerCase()) ||
        deviceName.toLowerCase().includes(d.label.toLowerCase())
      );
      const constraints = match
        ? { video: { deviceId: { exact: match.deviceId } } }
        : { video: true };
      _stream = await navigator.mediaDevices.getUserMedia(constraints);
      previewVideo.srcObject = _stream;
    } catch (_e) {
      previewWrap.style.display = "none";
      _stream = null;
    }
  }

  async function loadDevices() {
    deviceList.innerHTML = '<span class="yt-status yt-status-loading">Carregando dispositivos…</span>';
    try {
      const res  = await fetch("/api/capture-devices");
      const data = await res.json();
      renderDevices(data.devices || []);
    } catch {
      deviceList.innerHTML = '<span class="yt-status yt-status-error">Erro ao listar dispositivos.</span>';
    }
  }

  function renderDevices(devices) {
    if (!devices.length) {
      deviceList.innerHTML = '<span class="yt-status yt-status-error">Nenhum dispositivo encontrado.</span>';
      return;
    }
    deviceList.innerHTML = "";
    devices.forEach(name => {
      const item = document.createElement("div");
      item.className = "capture-device-item";
      item.innerHTML = `<span class="capture-device-icon">📷</span><span>${name}</span>`;
      item.addEventListener("click", () => {
        document.querySelectorAll(".capture-device-item").forEach(el => el.classList.remove("selected"));
        item.classList.add("selected");
        selectedDevice = name;
        btnAdd.disabled = false;
        if (navigator.mediaDevices?.getUserMedia) startPreview(name);
      });
      deviceList.appendChild(item);
    });
  }

  function addToSchedule() {
    if (!selectedDevice) return;
    const newItem = {
      id:       "item-" + Date.now(),
      type:     "capture",
      live:     true,
      title:    selectedDevice,
      path:     "av://dshow:video=" + selectedDevice,
      duration: 0,
    };
    state.schedule.push(newItem);
    renderSchedule();
    syncOrderToServer();
    closeModal();
  }

  btnOpen.addEventListener("click",   openModal);
  btnClose.addEventListener("click",  closeModal);
  btnCancel.addEventListener("click", closeModal);
  btnAdd.addEventListener("click",    addToSchedule);
  modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });
})();
