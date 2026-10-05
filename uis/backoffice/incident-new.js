// Formulario de registro de incidencias, con ayuda semántica mientras se escribe:
// incidencias parecidas, posibles duplicados y categoría sugerida.
const {
  ApiError,
  BRANCHES,
  CATEGORIES,
  DESCRIPTION_MAX_LENGTH,
  ORIGINS,
  STATUSES,
  TITLE_MAX_LENGTH,
  api,
  el,
  errorMessage,
  fieldErrorMessage,
  fillSelect,
  statusBadge,
  t,
} = TrackflowIncidents;

const FIELDS = ["origin", "branch", "category", "status", "title", "description"];
const ASSIST_MIN_LENGTH = 12;
const ASSIST_DELAY_MS = 600;

const form = document.querySelector("#incidentForm");
const originOptions = document.querySelector("#originOptions");
const branchField = document.querySelector("#branchField");
const branchInput = document.querySelector("#branchInput");
const branchHint = document.querySelector("#branchHint");
const categoryInput = document.querySelector("#categoryInput");
const categoryHint = document.querySelector("#categoryHint");
const statusInput = document.querySelector("#statusInput");
const titleInput = document.querySelector("#titleInput");
const descriptionInput = document.querySelector("#descriptionInput");
const formMessage = document.querySelector("#formMessage");
const submitButton = document.querySelector("#submitButton");
const submitSpinner = document.querySelector("#submitSpinner");
const submitText = document.querySelector("#submitText");
const assistState = document.querySelector("#assistState");
const assistContent = document.querySelector("#assistContent");

let isSubmitting = false;
let fieldErrors = {};
let lastMessage = null;
let assistTimer = null;
let assistRequestId = 0;
let assistResult = null;
// "idle" | "loading" | "ready"
let assistStatus = "idle";

function selectedOrigin() {
  const checked = form.querySelector('input[name="origin"]:checked');
  return checked ? checked.value : "";
}

function fieldControl(field) {
  return field === "origin" ? form.querySelector('input[name="origin"]') : form.elements[field];
}

// =========================================================
// CAMPOS
// =========================================================

function renderOriginOptions() {
  const current = selectedOrigin();
  originOptions.replaceChildren();

  ORIGINS.forEach((origin) => {
    const label = el(
      "label",
      "flex min-h-20 cursor-pointer flex-col justify-center rounded-xl border-2 border-cyan-200 bg-white px-4 py-3 transition hover:bg-cyan-50 has-[:checked]:border-cyan-700 has-[:checked]:bg-cyan-50 has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-cyan-200",
    );
    const radio = el("input", "sr-only");
    radio.type = "radio";
    radio.name = "origin";
    radio.value = origin;
    radio.checked = origin === current;
    label.append(
      radio,
      el("span", "text-lg font-bold text-slate-900", t(`origin.${origin}`)),
      el("span", "text-sm text-slate-600", t(`originHint.${origin}`)),
    );
    originOptions.append(label);
  });
}

// Cuando el origen es una sede, el campo de sede se destaca.
function renderBranchHighlight() {
  const highlighted = selectedOrigin() === "branch";
  branchField.dataset.highlighted = String(highlighted);
  branchField.className = highlighted
    ? "rounded-xl border-2 border-amber-400 bg-amber-50 p-4 ring-4 ring-amber-100 transition-all"
    : "rounded-xl border border-transparent p-0 transition-all";
  branchHint.textContent = t(highlighted ? "form.branchHighlight" : "form.branchHint");
  branchHint.className = highlighted ? "mt-2 text-sm font-bold text-amber-900" : "mt-2 text-sm text-slate-600";
}

function renderCategoryHint() {
  categoryHint.textContent = categoryInput.value ? t(`categoryHint.${categoryInput.value}`) : "";
}

function renderOptions() {
  renderOriginOptions();
  fillSelect(branchInput, BRANCHES, "branch", "common.select");
  fillSelect(categoryInput, CATEGORIES, "category", "common.select");
  fillSelect(statusInput, STATUSES, "status");
  renderBranchHighlight();
  renderCategoryHint();
}

// =========================================================
// ERRORES Y MENSAJES
// =========================================================

// Pinta cada error junto a su campo. `fieldErrors` es {campo: {field, code}}.
function renderFieldErrors() {
  FIELDS.forEach((field) => {
    const message = form.querySelector(`[data-error-for="${field}"]`);
    const error = fieldErrors[field];
    message.textContent = error ? fieldErrorMessage(error) : "";
    message.classList.toggle("hidden", !error);

    const control = form.elements[field];
    if (control && control.classList) {
      control.classList.toggle("border-red-500", Boolean(error));
      control.setAttribute("aria-invalid", String(Boolean(error)));
    }
  });
}

function showMessage(type, text, link) {
  formMessage.replaceChildren(document.createTextNode(text));
  if (link) {
    const anchor = el("a", "ml-2 font-bold underline", link.text);
    anchor.href = link.href;
    formMessage.append(anchor);
  }
  formMessage.className = `mb-4 rounded-xl border p-4 text-base ${
    type === "error"
      ? "border-red-200 bg-red-50 font-semibold text-red-800"
      : "border-green-200 bg-green-50 font-semibold text-green-900"
  }`;
}

function hideMessage() {
  lastMessage = null;
  formMessage.classList.add("hidden");
  formMessage.replaceChildren();
}

function setSubmitting(submitting) {
  isSubmitting = submitting;
  submitButton.disabled = submitting;
  submitSpinner.classList.toggle("hidden", !submitting);
  submitText.textContent = t(submitting ? "form.submitting" : "form.submit");
}

function readForm() {
  return {
    title: titleInput.value.trim(),
    description: descriptionInput.value.trim(),
    category: categoryInput.value,
    status: statusInput.value,
    origin: selectedOrigin(),
    branch: branchInput.value,
  };
}

// Validación en cliente, antes de enviar. Devuelve {campo: {field, code}}.
function validate(data) {
  const errors = {};
  FIELDS.forEach((field) => {
    if (!data[field]) errors[field] = { field, code: "required" };
  });
  if (data.title.length > TITLE_MAX_LENGTH) errors.title = { field: "title", code: "too_long" };
  if (data.description.length > DESCRIPTION_MAX_LENGTH) {
    errors.description = { field: "description", code: "too_long" };
  }
  return errors;
}

function focusFirstError() {
  const first = FIELDS.find((field) => fieldErrors[field]);
  if (first) fieldControl(first).focus();
}

// =========================================================
// AYUDA SEMÁNTICA
// =========================================================

function renderAssist() {
  const similar = assistResult ? assistResult.similar : [];
  const hasContent = assistStatus === "ready" && similar.length > 0;
  assistContent.classList.toggle("hidden", !hasContent);
  assistContent.replaceChildren();

  if (assistStatus === "loading") {
    assistState.textContent = t("assist.loading");
    return;
  }
  if (!hasContent) {
    assistState.textContent = t(assistStatus === "ready" ? "assist.empty" : "assist.intro");
    return;
  }
  assistState.textContent = "";

  if (similar.some((item) => item.possible_duplicate)) {
    assistContent.append(
      el(
        "p",
        "rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-900",
        t("assist.duplicateWarning"),
      ),
    );
  }

  const suggestion = assistResult.suggested_category;
  if (suggestion && suggestion.value !== categoryInput.value) {
    const box = el("div", "rounded-xl border border-cyan-200 bg-cyan-50 p-3");
    box.append(el("p", "text-xs font-bold uppercase tracking-wide text-cyan-800", t("assist.suggested")));
    const button = el(
      "button",
      "mt-2 min-h-12 w-full rounded-lg bg-cyan-700 px-4 py-2 text-base font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200",
      t("assist.useCategory", { category: t(`category.${suggestion.value}`) }),
    );
    button.type = "button";
    button.addEventListener("click", () => {
      categoryInput.value = suggestion.value;
      delete fieldErrors.category;
      renderFieldErrors();
      renderCategoryHint();
      renderAssist();
    });
    box.append(
      button,
      el("p", "mt-2 text-xs text-slate-600", t("assist.confidence", { n: Math.round(suggestion.confidence * 100) })),
    );
    assistContent.append(box);
  }

  const section = el("div");
  section.append(el("p", "text-xs font-bold uppercase tracking-wide text-slate-500", t("assist.similar")));
  const list = el("ul", "mt-2 space-y-3");
  similar.forEach((item) => {
    const entry = el("li", "rounded-xl border border-cyan-100 p-3");
    entry.append(el("p", "text-sm font-semibold text-slate-900", `#${item.id} · ${item.title}`));
    const meta = el("p", "mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600");
    meta.append(statusBadge(item.status), document.createTextNode(t(`branch.${item.branch}`)));
    if (item.possible_duplicate) {
      meta.append(
        el("span", "rounded-full bg-amber-100 px-2 py-0.5 font-bold text-amber-900", t("assist.duplicate")),
      );
    }
    entry.append(meta);
    list.append(entry);
  });
  section.append(list);
  assistContent.append(section);
}

function resetAssist() {
  window.clearTimeout(assistTimer);
  assistRequestId += 1;
  assistResult = null;
  assistStatus = "idle";
  renderAssist();
}

async function loadAssist() {
  const draft = { title: titleInput.value.trim(), description: descriptionInput.value.trim() };
  if (draft.title.length + draft.description.length < ASSIST_MIN_LENGTH) {
    resetAssist();
    return;
  }

  const requestId = ++assistRequestId;
  assistStatus = "loading";
  renderAssist();
  try {
    const result = await api.suggest(draft);
    if (requestId !== assistRequestId) return;
    assistResult = result;
    assistStatus = "ready";
  } catch (error) {
    if (error instanceof TrackflowAuth.SessionExpiredError || requestId !== assistRequestId) return;
    // Es solo una ayuda: si falla, el formulario sigue funcionando sin ella.
    assistResult = null;
    assistStatus = "idle";
  }
  renderAssist();
}

function scheduleAssist() {
  window.clearTimeout(assistTimer);
  assistTimer = window.setTimeout(loadAssist, ASSIST_DELAY_MS);
}

// =========================================================
// EVENTOS
// =========================================================

form.addEventListener("change", (event) => {
  const field = event.target.name;
  if (fieldErrors[field]) {
    delete fieldErrors[field];
    renderFieldErrors();
  }
  if (field === "origin") renderBranchHighlight();
  if (field === "category") {
    renderCategoryHint();
    renderAssist();
  }
});

[titleInput, descriptionInput].forEach((input) => {
  input.addEventListener("input", () => {
    if (fieldErrors[input.name]) {
      delete fieldErrors[input.name];
      renderFieldErrors();
    }
    scheduleAssist();
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting) return;
  hideMessage();

  const data = readForm();
  fieldErrors = validate(data);
  renderFieldErrors();
  if (Object.keys(fieldErrors).length > 0) {
    lastMessage = { type: "error", key: "form.reviewErrors" };
    showMessage("error", t("form.reviewErrors"));
    focusFirstError();
    return;
  }

  setSubmitting(true);
  try {
    const created = await api.create(data);
    form.reset();
    renderOptions();
    resetAssist();
    lastMessage = { type: "success", key: "form.success", params: { id: created.id } };
    showMessage("success", t("form.success", { id: created.id }), {
      text: t("form.successLink"),
      href: "incidents.html",
    });
  } catch (error) {
    if (error instanceof TrackflowAuth.SessionExpiredError) return;

    // Los errores que identifican un campo del formulario se muestran junto a él.
    const known = error instanceof ApiError ? error.errors.filter((item) => FIELDS.includes(item.field)) : [];
    if (known.length > 0) {
      known.forEach((item) => {
        fieldErrors[item.field] = item;
      });
      renderFieldErrors();
      lastMessage = { type: "error", key: "form.reviewErrors" };
      showMessage("error", t("form.reviewErrors"));
      focusFirstError();
    } else {
      showMessage("error", errorMessage(error));
    }
  } finally {
    setSubmitting(false);
  }
});

// Al cambiar de idioma se vuelve a pintar todo lo generado por JavaScript.
document.addEventListener("trackflow:langchange", () => {
  renderOptions();
  renderFieldErrors();
  renderAssist();
  submitText.textContent = t(isSubmitting ? "form.submitting" : "form.submit");
  if (lastMessage) {
    const link = lastMessage.type === "success" ? { text: t("form.successLink"), href: "incidents.html" } : null;
    showMessage(lastMessage.type, t(lastMessage.key, lastMessage.params), link);
  }
});

renderOptions();
renderAssist();
