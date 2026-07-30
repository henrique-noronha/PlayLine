(function () {
  const overlay = document.getElementById('close-dialog-overlay');
  const btnInterface = document.getElementById('close-dlg-interface');
  const btnAll = document.getElementById('close-dlg-all');
  const btnCancel = document.getElementById('close-dlg-cancel');

  window._showCloseDialog = function () {
    overlay.style.display = 'flex';
  };

  function _hide() {
    overlay.style.display = 'none';
  }

  // Fechar somente a interface — daemon e servidor continuam rodando
  btnInterface.addEventListener('click', function () {
    _hide();
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.close_interface_only();
    }
  });

  // Fechar interface e player — confirmação extra antes de encerrar
  btnAll.addEventListener('click', function () {
    _hide();
    // Renomeia o botão de confirmação para "Fechar" e usa o modal existente
    const okBtn = document.getElementById('confirm-modal-ok');
    if (okBtn) okBtn.textContent = 'Fechar';
    showConfirm(
      'Tem certeza? Isso encerrará a transmissão e fechará o player.',
      function () {
        if (window.pywebview && window.pywebview.api) {
          window.pywebview.api.close_all();
        }
      }
    );
    // Ao cancelar a confirmação, reabre o close dialog
    const cancelBtn = document.getElementById('confirm-modal-cancel');
    if (cancelBtn) {
      const _origCancel = cancelBtn.onclick;
      cancelBtn.onclick = function () {
        if (_origCancel) _origCancel();
        overlay.style.display = 'flex';
        if (okBtn) okBtn.textContent = 'Confirmar'; // restaura para outros usos
      };
    }
  });

  btnCancel.addEventListener('click', _hide);

  // Fechar ao clicar no fundo
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) _hide();
  });
})();
