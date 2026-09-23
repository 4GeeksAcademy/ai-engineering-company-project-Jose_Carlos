const API_BASE_URL = window.INCIDENTS_API_BASE_URL || "http://localhost:8000";
const ANALYZE_URL = `${API_BASE_URL}/analyze`;
const EXPORT_URL = `${API_BASE_URL}/api/incidents/results/export`;

const analysisForm = document.querySelector("#analysisForm");
const fileInput = document.querySelector("#csvFile");
const dropZone = document.querySelector("#dropZone");
const selectedFile = document.querySelector("#selectedFile");
const fileName = document.querySelector("#fileName");
const fileSize = document.querySelector("#fileSize");
const removeFileButton = document.querySelector("#removeFileButton");
const analyzeButton = document.querySelector("#analyzeButton");
const analyzeButtonText = document.querySelector("#analyzeButtonText");
const loadingSpinner = document.querySelector("#loadingSpinner");
const exportButton = document.querySelector("#exportButton");
const requestMessage = document.querySelector("#requestMessage");
const resultsSection = document.querySelector("#resultsSection");

let currentFile = null;
let isAnalyzing = false;

function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const kilobytes = bytes / 1024;
  return kilobytes < 1024
    ? `${kilobytes.toFixed(1)} KB`
    : `${(kilobytes / 1024).toFixed(1)} MB`;
}

function setSelectedFile(file) {
  currentFile = file;

  if (!file) {
    fileInput.value = "";
    selectedFile.classList.add("hidden");
    selectedFile.classList.remove("flex");
    fileName.textContent = "";
    fileSize.textContent = "";
    analyzeButton.disabled = true;
    return;
  }

  fileName.textContent = file.name;
  fileSize.textContent = formatFileSize(file.size);
  selectedFile.classList.remove("hidden");
  selectedFile.classList.add("flex");
  analyzeButton.disabled = isAnalyzing;
}

function showRequestMessage(type, message) {
  const isError = type === "error";
  requestMessage.textContent = message;
  requestMessage.className = `mt-4 rounded-xl border p-4 text-sm ${
    isError
      ? "border-red-200 bg-red-50 font-semibold text-red-800"
      : "border-cyan-200 bg-cyan-50 text-cyan-900"
  }`;
}

function hideRequestMessage() {
  requestMessage.classList.add("hidden");
  requestMessage.textContent = "";
}

function setAnalyzing(analyzing) {
  isAnalyzing = analyzing;
  fileInput.disabled = analyzing;
  removeFileButton.disabled = analyzing;
  analyzeButton.disabled = analyzing || !currentFile;
  analyzeButtonText.textContent = analyzing ? "Analizando..." : "Analizar archivo";
  loadingSpinner.classList.toggle("hidden", !analyzing);
}

function renderBreakdown(containerId, entries, emptyMessage) {
  const container = document.querySelector(containerId);
  container.replaceChildren();

  if (entries.length === 0) {
    const emptyState = document.createElement("p");
    emptyState.className = "py-4 text-sm text-slate-600";
    emptyState.textContent = emptyMessage;
    container.append(emptyState);
    return;
  }

  entries.forEach(([label, count]) => {
    const row = document.createElement("div");
    row.className = "flex items-center justify-between gap-4 py-3";

    const term = document.createElement("dt");
    term.className = "break-words text-sm font-medium text-slate-700";
    term.textContent = label;

    const value = document.createElement("dd");
    value.className = "rounded-full bg-cyan-100 px-3 py-1 text-sm font-bold text-cyan-800";
    value.textContent = String(count);

    row.append(term, value);
    container.append(row);
  });
}

function renderInvalidRecords(records) {
  const status = document.querySelector("#invalidRecordsStatus");
  const list = document.querySelector("#invalidRecordsList");
  list.replaceChildren();

  if (records.length === 0) {
    status.className = "mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900";
    status.textContent = "No se encontraron registros inválidos en el archivo.";
    return;
  }

  status.className = "mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold text-amber-900";
  status.textContent = `Se encontraron ${records.length} registros con errores. Revisa el detalle antes de continuar.`;

  records.forEach((record) => {
    const article = document.createElement("article");
    article.className = "rounded-xl border border-amber-200 bg-white p-4";

    const title = document.createElement("h4");
    title.className = "font-bold text-slate-900";
    title.textContent = `Incidente: ${String(record.incident_id ?? "UNKNOWN")}`;

    const errorList = document.createElement("ul");
    errorList.className = "mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700";

    const errors = Array.isArray(record.errors) ? record.errors : [];
    errors.forEach((error) => {
      const item = document.createElement("li");
      item.textContent = String(error);
      errorList.append(item);
    });

    article.append(title, errorList);
    list.append(article);
  });
}

function renderResults(results) {
  const valid = Number(results.valid) || 0;
  const invalid = Number(results.invalid) || 0;
  const satisfaction = Number(results.media_satisfaccion);
  const categories = results.categories && typeof results.categories === "object"
    ? Object.entries(results.categories)
    : [];
  const statuses = results.statuses && typeof results.statuses === "object"
    ? Object.entries(results.statuses)
    : [];
  const invalidRecords = Array.isArray(results.errores) ? results.errores : [];

  document.querySelector("#validCount").textContent = String(valid);
  document.querySelector("#invalidCount").textContent = String(invalid);
  document.querySelector("#satisfactionAverage").textContent = Number.isFinite(satisfaction)
    ? satisfaction.toFixed(2)
    : "0.00";
  document.querySelector("#resultsFileName").textContent = currentFile
    ? `Archivo: ${currentFile.name}`
    : "";

  renderBreakdown("#categoriesList", categories, "No hay categorías contabilizadas.");
  renderBreakdown("#statusesList", statuses, "No hay estados contabilizados.");
  renderInvalidRecords(invalidRecords);

  resultsSection.classList.remove("hidden");
  exportButton.disabled = false;
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function getErrorMessage(response) {
  try {
    const body = await response.json();
    return body.detail || body.message || `El servidor respondió con el estado ${response.status}.`;
  } catch {
    return `El servidor respondió con el estado ${response.status}.`;
  }
}

fileInput.addEventListener("change", () => {
  setSelectedFile(fileInput.files[0] || null);
  hideRequestMessage();
});

removeFileButton.addEventListener("click", () => {
  setSelectedFile(null);
  hideRequestMessage();
  fileInput.focus();
});

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (!isAnalyzing) {
      dropZone.classList.add("border-cyan-600", "bg-cyan-100");
    }
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("border-cyan-600", "bg-cyan-100");
  });
});

dropZone.addEventListener("drop", (event) => {
  if (isAnalyzing) {
    return;
  }

  const [file] = event.dataTransfer.files;
  if (file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    setSelectedFile(file);
    hideRequestMessage();
  }
});

analysisForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!currentFile || isAnalyzing) {
    showRequestMessage("error", "Selecciona un archivo CSV antes de iniciar el análisis.");
    return;
  }

  hideRequestMessage();
  setAnalyzing(true);
  const formData = new FormData();
  formData.append("file", currentFile);

  try {
    const response = await fetch(ANALYZE_URL, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const results = await response.json();
    renderResults(results);
    showRequestMessage(
      "success",
      results.invalid > 0
        ? "Análisis completado. Se encontraron registros que requieren revisión."
        : "Análisis completado correctamente, sin registros inválidos.",
    );
  } catch (error) {
    const message = error instanceof TypeError
      ? "No se pudo conectar con la API. Comprueba que el servidor esté disponible y permita peticiones desde este origen."
      : error.message;
    showRequestMessage("error", `No se pudo completar el análisis. ${message}`);
  } finally {
    setAnalyzing(false);
  }
});

exportButton.addEventListener("click", () => {
  if (!exportButton.disabled) {
    window.location.assign(EXPORT_URL);
  }
});
