/* PlayLine — Card de Live do YouTube */

(function () {
  const modal   = document.getElementById("yt-modal");
  const input   = document.getElementById("yt-url-input");
  const btn     = document.getElementById("btn-yt-add");
  const status  = document.getElementById("yt-status");
  const btnOpen = document.getElementById("btn-yt-open");

  function openModal() {
    input.value = "";
    setStatus("", "");
    btn.disabled = false;
    btn.textContent = "Adicionar ao roteiro";
    modal.style.display = "flex";
    setTimeout(() => input.focus(), 50);
  }

  function closeModal() {
    modal.style.display = "none";
  }

  function setStatus(msg, type) {
    status.textContent = msg;
    status.className = "yt-status" + (type ? " yt-status-" + type : "");
  }

  async function addLive() {
    const url = input.value.trim();
    if (!url) return;

    btn.disabled = true;
    btn.textContent = "Verificando…";
    setStatus("Obtendo informações…", "loading");

    try {
      const res = await fetch("/api/youtube/info?url=" + encodeURIComponent(url));
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Erro ao verificar URL");
      }
      const info = await res.json();

      const newItem = {
        id:       "item-" + Date.now(),
        type:     "youtube_live",
        live:     info.is_live,
        title:    info.title || "Vídeo do YouTube",
        path:     url,
        duration: info.is_live ? 0 : (info.duration || 0),
      };

      state.schedule.push(newItem);
      renderSchedule();
      syncOrderToServer();

      setStatus("“" + info.title + "” adicionado ao roteiro", "success");
      setTimeout(closeModal, 1800);
    } catch (err) {
      setStatus(err.message, "error");
      btn.disabled = false;
      btn.textContent = "Adicionar ao roteiro";
    }
  }

  // Abrir modal
  btnOpen.addEventListener("click", openModal);

  // Fechar modal
  document.getElementById("yt-modal-close").addEventListener("click", closeModal);
  document.getElementById("btn-yt-cancel").addEventListener("click", closeModal);
  modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

  // Submeter
  btn.addEventListener("click", addLive);
  input.addEventListener("keydown", e => { if (e.key === "Enter") addLive(); });

  // Fechar com Escape
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && modal.style.display !== "none") closeModal();
  });

  // Exposto pro quadrante fixo de entrada (input_quadrant.js) reaproveitar o mesmo modal
  window.openYtModal = openModal;
})();
