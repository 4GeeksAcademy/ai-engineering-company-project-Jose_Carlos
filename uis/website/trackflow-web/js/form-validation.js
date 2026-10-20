// Validación de formularios compartida por index.html y application.html (antes cada página
// tenía su propia copia). Cada campo tiene debajo un <p data-error-for="id-del-campo">.

window.TrackflowForms = (() => {
  const errorFor = (input) => document.querySelector(`[data-error-for="${input.id}"]`);

  const markInvalid = (input, message) => {
    const error = errorFor(input);
    input.classList.add('border-red-500', 'ring-red-200');
    input.classList.remove('border-cyan-200');
    if (error) {
      error.textContent = message;
      error.classList.remove('hidden');
    }
  };

  const clearInvalid = (input) => {
    const error = errorFor(input);
    input.classList.remove('border-red-500', 'ring-red-200');
    input.classList.add('border-cyan-200');
    if (error) error.classList.add('hidden');
  };

  const isEmailValid = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

  return { markInvalid, clearInvalid, isEmailValid };
})();
