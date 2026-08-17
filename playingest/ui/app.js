/* PlayIngest — lógica de UI */

const api = () => window.pywebview.api;

// ── Popup de erro ─────────────────────────────────────────────────────────────
const popupBackdrop = document.getElementById("popupBackdrop");
const popupTitle    = document.getElementById("popupTitle");
const popupMsg      = document.getElementById("popupMsg");
document.getElementById("popupOk").addEventListener("click", () => popupBackdrop.classList.remove("visible"));

function showError(title, msg) {
  popupTitle.textContent = title;
  popupMsg.textContent   = msg;
  popupBackdrop.classList.add("visible");
}

// ── Estado ────────────────────────────────────────────────────────────────────
let _connected = false;
let _authenticated = false;
let _files = [];       // [{path, name, ext, size, valid, error, status, progress}]
let _uploading = false;

// ── Elementos ─────────────────────────────────────────────────────────────────
const statusDot     = document.getElementById("statusDot");
const statusText    = document.getElementById("statusText");
const ipInput       = document.getElementById("ipInput");
const btnConnect    = document.getElementById("btnConnect");
const errConnect    = document.getElementById("errConnect");
const loginBackdrop = document.getElementById("loginBackdrop");
const inputUser     = document.getElementById("inputUser");
const inputPass     = document.getElementById("inputPass");
const btnLogin      = document.getElementById("btnLogin");
const errLogin      = document.getElementById("errLogin");
const cardUpload    = document.getElementById("cardUpload");
const subfolderSelect = document.getElementById("subfolderSelect");
const btnSelect     = document.getElementById("btnSelect");
const fileTableBody = document.getElementById("fileTableBody");
const btnSendAll    = document.getElementById("btnSendAll");
const footerInfo    = document.getElementById("footerInfo");

// ── Utilitários ───────────────────────────────────────────────────────────────
function formatSize(bytes) {
  if (bytes >= 1_073_741_824) return (bytes / 1_073_741_824).toFixed(1) + " GB";
  if (bytes >= 1_048_576)     return (bytes / 1_048_576).toFixed(1) + " MB";
  return (bytes / 1024).toFixed(0) + " KB";
}

function setStatus(state) {
  statusDot.className = "status-dot " + state;
  statusText.textContent = { connected: "Conectado", connecting: "Conectando…", error: "Erro de conexão", "": "Desconectado" }[state] ?? state;
}

function setConnected(ok) {
  _connected = ok;
  setStatus(ok ? "connected" : "error");
  if (ok) {
    loginBackdrop.classList.add("visible");
    inputUser.focus();
  }
}

function setAuthenticated(ok) {
  _authenticated = ok;
  cardUpload.classList.toggle("disabled", !ok);
  if (ok) loadSubfolders();
}

function updateSendButton() {
  const validCount = _files.filter(f => f.valid && f.status !== "done").length;
  btnSendAll.disabled = _uploading || validCount === 0 || !_authenticated;
  footerInfo.textContent = _files.length
    ? `${_files.filter(f => f.valid).length} válido(s) · ${_files.filter(f => !f.valid).length} inválido(s) · ${_files.filter(f => f.status === "done").length} enviado(s)`
    : "";
}

// ── Renderização da tabela ────────────────────────────────────────────────────
function renderTable() {
  if (_files.length === 0) {
    fileTableBody.innerHTML = '<tr><td colspan="5" class="empty-queue">Nenhum arquivo selecionado</td></tr>';
    return;
  }
  fileTableBody.innerHTML = _files.map((f, i) => {
    const valBadge = f.valid
      ? '<span class="badge badge-ok">OK</span>'
      : `<span class="badge badge-error" title="${f.error}">Inválido</span>`;

    let statusBadge;
    if      (f.status === "done")    statusBadge = '<span class="badge badge-done">Concluído</span>';
    else if (f.status === "error")   statusBadge = `<span class="badge badge-error" title="${f.error}">Erro</span>`;
    else if (f.status === "sending") statusBadge = '<span class="badge badge-sending">Enviando</span>';
    else                             statusBadge = '<span class="badge badge-pending">Aguardando</span>';

    const pct = f.progress ?? 0;
    const progress = f.valid
      ? `<div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${pct}%"></div></div>`
      : "—";

    return `<tr>
      <td class="col-name" title="${f.name}">${f.name}</td>
      <td class="col-size">${formatSize(f.size)}</td>
      <td>${valBadge}</td>
      <td>${progress}</td>
      <td>${statusBadge}</td>
    </tr>`;
  }).join("");
}

// ── Conectar ──────────────────────────────────────────────────────────────────
btnConnect.addEventListener("click", async () => {
  const ip = ipInput.value.trim();
  if (!ip) { errConnect.textContent = "Informe o IP do servidor."; return; }
  errConnect.textContent = "";
  btnConnect.disabled = true;
  setStatus("connecting");
  const res = await api().ping(ip);
  btnConnect.disabled = false;
  if (res.ok) {
    setConnected(true);
  } else {
    setStatus("error");
    errConnect.textContent = "Servidor não encontrado. Verifique o IP e se o PlayLine está rodando.";
  }
});

ipInput.addEventListener("keydown", e => { if (e.key === "Enter") btnConnect.click(); });

// ── Login ─────────────────────────────────────────────────────────────────────
async function doLogin() {
  const user = inputUser.value.trim();
  const pass = inputPass.value;
  if (!user || !pass) { errLogin.textContent = "Preencha usuário e senha."; return; }
  errLogin.textContent = "";
  btnLogin.disabled = true;
  const res = await api().login(user, pass);
  btnLogin.disabled = false;
  if (res.ok) {
    loginBackdrop.classList.remove("visible");
    inputPass.value = "";
    setAuthenticated(true);
  } else {
    errLogin.textContent = res.error || "Credenciais inválidas.";
    inputPass.value = "";
    inputPass.focus();
  }
}

btnLogin.addEventListener("click", doLogin);
inputPass.addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
inputUser.addEventListener("keydown", e => { if (e.key === "Enter") inputPass.focus(); });

// ── Subpastas ─────────────────────────────────────────────────────────────────
async function loadSubfolders() {
  const res = await api().get_subfolders();
  subfolderSelect.innerHTML = '<option value="">(raiz da Biblioteca)</option>';
  if (res.ok && res.subfolders.length) {
    res.subfolders.forEach(sub => {
      const opt = document.createElement("option");
      opt.value = sub;
      opt.textContent = sub;
      subfolderSelect.appendChild(opt);
    });
  }
}

// ── Selecionar arquivos ───────────────────────────────────────────────────────
const SUPPORTED_EXTS = new Set([".mp4",".mkv",".mov",".avi",".ts",".mxf",".mpg",".mpeg",".wmv",".flv",".webm"]);
const fileInput = document.getElementById("fileInput");

btnSelect.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", (e) => {
  const existing = new Set(_files.map(f => f.path));
  const novos = Array.from(e.target.files)
    .map(f => {
      const ext = f.name.substring(f.name.lastIndexOf(".")).toLowerCase();
      const size = f.size;
      const valid = SUPPORTED_EXTS.has(ext) && size > 0;
      return {
        fileObj: f,               // referência ao File real para o XHR
        path: f.name,
        name: f.name,
        ext,
        size,
        valid,
        error: valid ? "" : (SUPPORTED_EXTS.has(ext) ? "Arquivo vazio" : "Extensão não suportada"),
        status: "pending",
        progress: 0,
      };
    })
    .filter(f => !existing.has(f.path));
  _files = [..._files, ...novos];
  e.target.value = "";  // permite re-selecionar os mesmos arquivos
  renderTable();
  updateSendButton();
});

// ── Upload via XHR (progresso real, sem depender de f.path) ──────────────────
let _serverInfo = null;

async function ensureServerInfo() {
  if (!_serverInfo) _serverInfo = await api().get_server_info();
  return _serverInfo;
}

function uploadXHR(fileObj, subfolder, baseUrl, token, onProgress) {
  return new Promise((resolve) => {
    const form = new FormData();
    form.append("file", fileObj);

    const url = `${baseUrl}/api/upload?subfolder=${encodeURIComponent(subfolder)}&session_token=${encodeURIComponent(token)}`;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round(e.loaded / e.total * 100));
    };
    xhr.onload = () => {
      onProgress?.(100);
      if (xhr.status === 200) {
        resolve({ ok: true });
      } else {
        try { resolve({ ok: false, error: JSON.parse(xhr.responseText).detail || `HTTP ${xhr.status}` }); }
        catch { resolve({ ok: false, error: `HTTP ${xhr.status}` }); }
      }
    };
    xhr.onerror = () => resolve({ ok: false, error: "Erro de conexão" });
    xhr.send(form);
  });
}

// ── Enviar todos ──────────────────────────────────────────────────────────────
btnSendAll.addEventListener("click", async () => {
  if (_uploading) return;
  _uploading = true;
  btnSendAll.disabled = true;
  btnSelect.disabled = true;

  const info = await ensureServerInfo();
  if (!info.base_url || !info.token) {
    showError("Sessão expirada", "A sessão com o servidor foi perdida. Reconecte e faça login novamente.");
    _uploading = false;
    btnSendAll.disabled = false;
    btnSelect.disabled = false;
    return;
  }
  const subfolder = subfolderSelect.value;
  const queue = _files.filter(f => f.valid && f.status !== "done");

  for (const file of queue) {
    file.status = "sending";
    file.progress = 0;
    renderTable();

    const res = await uploadXHR(file.fileObj, subfolder, info.base_url, info.token, (pct) => {
      file.progress = pct;
      renderTable();
    });
    if (res.ok) {
      file.progress = 100;
      file.status = "done";
    } else {
      file.progress = 0;
      file.status = "error";
      file.error = res.error || "Erro desconhecido";
      showError("Falha no envio — " + file.name, errorHint(res.error));
    }
    renderTable();
  }

  _uploading = false;
  btnSelect.disabled = false;
  updateSendButton();
});

function errorHint(msg) {
  if (!msg) return "Erro desconhecido. Verifique o log PlayIngest.log.";
  if (/disco cheio|507|sem espaço/i.test(msg))
    return msg + "\n\nVerifique o espaço disponível no servidor.";
  if (/antivírus|acesso negado|403|permiss/i.test(msg))
    return msg + "\n\nUm antivírus ou política de segurança pode estar bloqueando a gravação. Verifique as exceções do antivírus para a pasta Biblioteca.";
  if (/conexão|network|ECONNREFUSED|ETIMEDOUT/i.test(msg))
    return msg + "\n\nVerifique se o servidor PlayLine está rodando e se a rede está disponível.";
  if (/firewall/i.test(msg))
    return msg + "\n\nO firewall do servidor pode estar bloqueando a porta 18000.";
  return msg;
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener("pywebviewready", async () => {
  const lastIp = await api().get_last_ip();
  if (lastIp) ipInput.value = lastIp;
  ipInput.focus();
});
