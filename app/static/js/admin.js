(() => {
  "use strict";

  const app = document.getElementById("admin-app");
  if (!app) return;

  const timeZone = app.dataset.timezone || "America/Argentina/Buenos_Aires";
  const canReschedule = app.dataset.canReschedule === "true";
  const canViewClient = app.dataset.clientDetail === "true";
  const defaultBarberId = app.dataset.barberId || "";
  const list = document.getElementById("queue-list");
  const filters = document.getElementById("queue-filters");
  const barberSelect = document.getElementById("admin-barber");
  const dateInput = document.getElementById("admin-date");
  const refreshButton = document.getElementById("queue-refresh");
  const updatedLabel = document.getElementById("queue-updated");
  const feedback = document.getElementById("queue-feedback");
  const toast = document.getElementById("admin-toast");
  const dialog = document.getElementById("payment-dialog");
  const paymentForm = document.getElementById("payment-form");
  const paymentContext = document.getElementById("payment-context");
  const paymentAmount = document.getElementById("payment-amount");
  const paymentMethod = document.getElementById("payment-method");
  const paymentKind = document.getElementById("payment-kind");
  const paymentError = document.getElementById("payment-error");
  const paymentSubmit = document.getElementById("payment-submit");
  const rescheduleDialog = document.getElementById("reschedule-dialog");
  const rescheduleForm = document.getElementById("reschedule-form");
  const rescheduleContext = document.getElementById("reschedule-context");
  const rescheduleBarber = document.getElementById("reschedule-barber");
  const rescheduleDate = document.getElementById("reschedule-date");
  const rescheduleSlot = document.getElementById("reschedule-slot");
  const rescheduleHint = document.getElementById("reschedule-hint");
  const rescheduleError = document.getElementById("reschedule-error");
  const rescheduleSubmit = document.getElementById("reschedule-submit");

  const statusLabels = {
    confirmed: "Confirmado",
    in_progress: "En curso",
    completed: "Completado",
    cancelled: "Cancelado",
    no_show: "No se presentó",
  };

  const statusToasts = {
    in_progress: "Turno iniciado.",
    completed: "Turno completado.",
    cancelled: "Turno cancelado.",
    no_show: "Turno marcado como no asistido.",
  };

  const state = {
    items: [],
    serial: 0,
    paymentItem: null,
    rescheduleItem: null,
    queueBarberId: null,
    slotSerial: 0,
  };

  let toastTimer = null;
  const moneyFormatter = new Intl.NumberFormat("es-AR", {
    maximumFractionDigits: 0,
  });

  function formatMoney(cents) {
    if (cents === null || cents === undefined) return "—";
    const sign = cents < 0 ? "-" : "";
    const absolute = Math.abs(Math.round(cents));
    const whole = Math.floor(absolute / 100);
    const remainder = absolute % 100;
    const decimals = remainder ? `,${String(remainder).padStart(2, "0")}` : "";
    return `${sign}$ ${moneyFormatter.format(whole)}${decimals}`;
  }

  function formatDuration(minutes) {
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
  }

  function formatTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("es-AR", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone,
    }).format(date);
  }

  function formatDateInput(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const parts = new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      timeZone,
    }).formatToParts(date);
    const value = (type) =>
      parts.find((part) => part.type === type)?.value || "";
    return `${value("year")}-${value("month")}-${value("day")}`;
  }

  function clockNow() {
    return new Intl.DateTimeFormat("es-AR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
      timeZone,
    }).format(new Date());
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => {
      const entities = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return entities[character];
    });
  }

  async function apiMessage(response) {
    try {
      const data = await response.json();
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((item) => (item.msg || "").replace(/^Value error,\s*/i, ""))
          .filter(Boolean)
          .join(" ");
      }
    } catch (_error) {
      // Fall through to the generic message.
    }
    return `No pudimos completar la operación (error ${response.status}).`;
  }

  async function apiFetch(url, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });

    if (response.status === 401) {
      window.location.replace("/admin/login");
      throw new Error("Sesión vencida.");
    }
    if (!response.ok) {
      throw new Error(await apiMessage(response));
    }
    return response.json();
  }

  function showToast(message, isError = false) {
    if (!toast) return;
    toast.textContent = message;
    toast.className = isError ? "toast toast--error" : "toast";
    toast.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toast.hidden = true;
    }, 4500);
  }

  function setFeedback(message) {
    if (!feedback) return;
    feedback.textContent = message || "";
    feedback.hidden = !message;
  }

  function renderMetrics(items) {
    const active = items.filter((item) =>
      ["confirmed", "in_progress"].includes(item.status)
    );
    const inProgress = items.filter((item) => item.status === "in_progress");
    const collected = items.reduce(
      (total, item) => total + (Number(item.paid_cents) || 0),
      0
    );
    const balance = items
      .filter((item) => !["cancelled", "no_show"].includes(item.status))
      .reduce((total, item) => total + (Number(item.balance_cents) || 0), 0);

    document.getElementById("metric-agenda").textContent = String(active.length);
    document.getElementById("metric-progress").textContent = String(inProgress.length);
    document.getElementById("metric-collected").textContent = formatMoney(collected);
    document.getElementById("metric-balance").textContent = formatMoney(balance);
  }

  function etaMarkup(item) {
    if (item.status === "confirmed") {
      if (!item.eta_start_at) {
        return '<span class="queue-eta">Turno confirmado</span>';
      }
      const late = Number(item.delay_minutes) > 0;
      const suffix = late ? ` · +${item.delay_minutes} min` : "";
      return `<span class="queue-eta ${late ? "queue-eta--late" : ""}">Llegada ${formatTime(
        item.eta_start_at
      )}${suffix}</span>`;
    }
    if (item.status === "in_progress") {
      return `<span class="queue-eta">En sillón desde ${formatTime(
        item.actual_start_at || item.eta_start_at
      )}</span>`;
    }
    if (item.status === "completed") {
      return `<span class="queue-eta">Finalizado ${formatTime(
        item.actual_end_at || item.eta_end_at
      )}</span>`;
    }
    return '<span class="queue-eta">Sin servicio</span>';
  }

  function paymentMarkup(item) {
    const paid = Number(item.paid_cents) || 0;
    const balance = Number(item.balance_cents) || 0;
    if (paid > 0 && balance > 0) {
      return `Abonado ${formatMoney(paid)} · saldo ${formatMoney(balance)}`;
    }
    if (paid > 0) return `Pagado ${formatMoney(paid)}`;
    return `Saldo ${formatMoney(balance)}`;
  }

  function actionsMarkup(item) {
    const id = Number(item.id);
    const canPay =
      Number(item.balance_cents) > 0 &&
      !["cancelled", "no_show"].includes(item.status);
    const isFuture =
      new Date(item.scheduled_start_at).getTime() > Date.now() + 60 * 1000;
    const buttons = [];

    if (item.status === "confirmed") {
      buttons.push(
        `<button type="button" class="btn btn--accent-outline btn--mini" data-action="start" data-id="${id}">Iniciar</button>`
      );
      if (isFuture) {
        buttons.push(
          `<button type="button" class="btn btn--quiet btn--mini" data-action="advance" data-id="${id}">Adelantar</button>`
        );
      }
      if (canPay) {
        buttons.push(
          `<button type="button" class="btn btn--quiet btn--mini" data-action="pay" data-id="${id}">Cobrar</button>`
        );
      }
      const moreActions = [
        canReschedule
          ? `<button type="button" data-action="reschedule" data-id="${id}">Reasignar turno</button>`
          : "",
        `<button type="button" data-action="cancel" data-id="${id}">Cancelar turno</button>`,
        `<button type="button" class="is-danger" data-action="no_show" data-id="${id}">No se presentó</button>`,
      ].join("");
      buttons.push(
        `<details class="action-more"><summary>Más</summary><div class="action-more-panel">${moreActions}</div></details>`
      );
    } else if (item.status === "in_progress") {
      buttons.push(
        `<button type="button" class="btn btn--accent-outline btn--mini" data-action="complete" data-id="${id}">Completar</button>`
      );
      if (canPay) {
        buttons.push(
          `<button type="button" class="btn btn--quiet btn--mini" data-action="pay" data-id="${id}">Cobrar</button>`
        );
      }
    } else if (item.status === "completed" && canPay) {
      buttons.push(
        `<button type="button" class="btn btn--quiet btn--mini" data-action="pay" data-id="${id}">Cobrar</button>`
      );
    }

    return `<div class="queue-actions">${buttons.join("")}</div>`;
  }

  function queueItemMarkup(item) {
    const client = item.client;
    const fullName = `${client.first_name} ${client.last_name}`;
    const id = Number(item.id);
    const tel = String(client.phone || "").replace(/[^\d+]/g, "");
    const delayChip =
      Number(item.delay_minutes) > 0 &&
      ["confirmed", "in_progress"].includes(item.status)
        ? `<span class="delay-chip">+${item.delay_minutes} min</span>`
        : "";
    const code = String(item.public_code || "").slice(0, 8).toUpperCase();
    const statusLabel = statusLabels[item.status] || item.status;
    const confirmChip =
      item.status === "confirmed" && !item.client_confirmed
        ? `<span class="confirm-chip">Sin confirmar</span>`
        : "";
    const dueClass = item.confirmation_due_soon ? " queue-item--due" : "";

    return `
      <article class="queue-item queue-item--${item.status}${dueClass}" data-appointment="${id}">
        <div class="queue-time">
          <strong>${formatTime(item.scheduled_start_at)}</strong>
          ${etaMarkup(item)}
        </div>
        <div class="queue-person">
          <div class="queue-person-head">
            <h3>${escapeHtml(fullName)}</h3>
            <span class="queue-badges">
              <span class="status-pill status-pill--${item.status}">${statusLabel}</span>
              ${delayChip}
              ${confirmChip}
            </span>
          </div>
          <p class="queue-service">
            ${escapeHtml(item.service.name)} · ${formatDuration(item.service.duration_minutes)}
            ${canViewClient ? `· <a href="/admin/clientes/${Number(client.id)}">Ver ficha</a>` : ""}
          </p>
          <div class="queue-meta">
            <span>#${escapeHtml(code)}</span>
            <span>${paymentMarkup(item)}</span>
            ${tel ? `<a class="phone-link" href="tel:${escapeHtml(tel)}">${escapeHtml(client.phone)}</a>` : ""}
          </div>
        </div>
        ${actionsMarkup(item)}
      </article>
    `;
  }

  function dueBannerMarkup(items) {
    const due = items.filter(
      (item) => item.confirmation_due_soon && item.status === "confirmed"
    );
    if (!due.length) return "";
    const times = due
      .map((item) => formatTime(item.scheduled_start_at))
      .join(" · ");
    return `
      <div class="queue-alert" role="alert">
        <strong>
          ${due.length === 1
            ? "Hay 1 turno sin confirmar que vence pronto"
            : `Hay ${due.length} turnos sin confirmar que vencen pronto`}
        </strong>
        <span>A las ${times}. Escribile al cliente o liberá el horario si no responde.</span>
      </div>
    `;
  }

  function renderQueue(items) {
    if (!items.length) {
      list.innerHTML = `
        <div class="queue-empty">
          <h3>Sin turnos para este día.</h3>
          <p>${
            canReschedule
              ? "La agenda de este barbero está libre. Podés cambiar de fecha o de profesional para revisar otra cola."
              : "Tu agenda está libre para esta fecha. Probá con otro día."
          }</p>
        </div>
      `;
      return;
    }
    list.innerHTML = dueBannerMarkup(items) + items.map(queueItemMarkup).join("");
  }

  function renderLoadError() {
    list.innerHTML = `
      <div class="queue-empty">
        <h3>No pudimos cargar la agenda.</h3>
        <p>Revisá la conexión y volvé a intentar con el botón Actualizar.</p>
      </div>
    `;
  }

  async function loadQueue({ silent = false } = {}) {
    const serial = ++state.serial;
    if (!silent) {
      refreshButton.disabled = true;
      refreshButton.textContent = "Actualizando…";
    }

    const params = new URLSearchParams({
      barber_id: barberSelect ? barberSelect.value : defaultBarberId,
      date: dateInput.value,
    });

    try {
      const data = await apiFetch(`/api/admin/queue?${params}`);
      if (serial !== state.serial) return;
      state.items = data.items;
      state.queueBarberId = Number(data.barber.id);
      renderMetrics(data.items);
      renderQueue(data.items);
      setFeedback("");
      updatedLabel.textContent = `Actualizado ${clockNow()} · se refresca cada 30 s`;
    } catch (error) {
      if (serial !== state.serial) return;
      if (error.message !== "Sesión vencida.") {
        setFeedback(error.message);
        if (!state.items.length) renderLoadError();
      }
    } finally {
      if (serial === state.serial) {
        refreshButton.disabled = false;
        refreshButton.textContent = "Actualizar";
      }
    }
  }

  function findItem(id) {
    return state.items.find((item) => Number(item.id) === id);
  }

  function itemName(item) {
    return `${item.client.first_name} ${item.client.last_name}`;
  }

  async function submitStatus(item, status, trigger) {
    trigger.disabled = true;
    try {
      await apiFetch(`/api/admin/appointments/${Number(item.id)}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      showToast(statusToasts[status] || "Turno actualizado.");
      await loadQueue({ silent: true });
    } catch (error) {
      if (error.message !== "Sesión vencida.") showToast(error.message, true);
    } finally {
      if (trigger.isConnected) trigger.disabled = false;
    }
  }

  async function advanceItem(item, trigger) {
    trigger.disabled = true;
    try {
      const result = await apiFetch(
        `/api/admin/appointments/${Number(item.id)}/advance`,
        { method: "POST" }
      );
      showToast(
        `Turno adelantado de ${formatTime(
          result.previous_start_at
        )} a ${formatTime(result.appointment.start_at)}.`
      );
      await loadQueue({ silent: true });
    } catch (error) {
      if (error.message !== "Sesión vencida.") showToast(error.message, true);
    } finally {
      if (trigger.isConnected) trigger.disabled = false;
    }
  }

  function openPayment(item) {
    if (!dialog) return;
    state.paymentItem = item;
    paymentContext.textContent = `${itemName(item)} · ${item.service.name} · saldo ${formatMoney(
      item.balance_cents
    )}`;
    paymentAmount.value = String(Number(item.balance_cents) / 100);
    paymentMethod.value = "cash";
    paymentKind.value = "balance";
    paymentError.hidden = true;
    paymentError.textContent = "";
    paymentSubmit.disabled = false;
    paymentSubmit.textContent = "Registrar pago";
    if (!dialog.open) dialog.showModal();
    window.setTimeout(() => {
      paymentAmount.focus();
      paymentAmount.select();
    }, 0);
  }

  function resetRescheduleSlots(message) {
    rescheduleSlot.replaceChildren(new Option(message, ""));
    rescheduleSlot.disabled = true;
    rescheduleSubmit.disabled = true;
  }

  async function loadRescheduleSlots() {
    const item = state.rescheduleItem;
    if (!item || !rescheduleDialog) return;

    const serial = ++state.slotSerial;
    const barberId = Number(rescheduleBarber.value);
    const day = rescheduleDate.value;
    rescheduleError.hidden = true;
    rescheduleError.textContent = "";
    rescheduleSubmit.textContent = "Reasignar turno";

    if (!barberId || !day) {
      resetRescheduleSlots("Elegí barbero y fecha");
      return;
    }

    resetRescheduleSlots("Buscando horarios…");

    try {
      const params = new URLSearchParams({
        barber_id: String(barberId),
        date: day,
      });
      const data = await apiFetch(
        `/api/admin/appointments/${Number(item.id)}/slots?${params}`
      );
      if (serial !== state.slotSerial) return;

      rescheduleSlot.replaceChildren(new Option("Elegí un horario", ""));
      data.slots.forEach((slot) => {
        rescheduleSlot.append(new Option(slot.label, slot.start_at));
      });
      rescheduleSlot.disabled = false;
      const hasSlots = data.slots.length > 0;
      rescheduleSubmit.disabled = !hasSlots;
      rescheduleHint.textContent = hasSlots
        ? "Los horarios mostrados ya descuentan los turnos del profesional."
        : "No hay horarios libres para ese profesional y fecha. Probá con otro día o barbero.";
    } catch (error) {
      if (serial !== state.slotSerial) return;
      if (error.message !== "Sesión vencida.") {
        rescheduleError.textContent = error.message;
        rescheduleError.hidden = false;
        rescheduleHint.textContent =
          "Revisá la fecha o probá con otro profesional.";
        resetRescheduleSlots("Sin horarios disponibles");
      }
    }
  }

  function openReschedule(item) {
    if (!rescheduleDialog) return;

    state.rescheduleItem = item;
    rescheduleContext.textContent = `${itemName(item)} · ${item.service.name} · actual ${formatTime(
      item.scheduled_start_at
    )}`;
    rescheduleBarber.value = String(state.queueBarberId || barberSelect.value);

    const currentDay = formatDateInput(item.scheduled_start_at);
    const min = rescheduleDate.min;
    const max = rescheduleDate.max;
    let targetDay = currentDay;
    if ((min && targetDay < min) || (max && targetDay > max)) {
      targetDay = min || currentDay;
    }
    rescheduleDate.value = targetDay;

    rescheduleError.hidden = true;
    rescheduleError.textContent = "";
    rescheduleSubmit.textContent = "Reasignar turno";
    rescheduleHint.textContent =
      "El servicio, el precio y los pagos del turno se mantienen al moverlo.";
    resetRescheduleSlots("Buscando horarios…");

    if (!rescheduleDialog.open) rescheduleDialog.showModal();
    loadRescheduleSlots();
  }

  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const item = findItem(Number(button.dataset.id));
    if (!item) return;
    const action = button.dataset.action;

    if (action === "pay") {
      openPayment(item);
      return;
    }
    if (action === "start") {
      submitStatus(item, "in_progress", button);
      return;
    }
    if (action === "complete") {
      submitStatus(item, "completed", button);
      return;
    }
    if (action === "advance") {
      advanceItem(item, button);
      return;
    }
    if (action === "reschedule") {
      openReschedule(item);
      return;
    }
    if (action === "cancel") {
      const confirmed = window.confirm(
        `¿Cancelar el turno de ${itemName(item)} a las ${formatTime(
          item.scheduled_start_at
        )}?`
      );
      if (confirmed) submitStatus(item, "cancelled", button);
      return;
    }
    if (action === "no_show") {
      const confirmed = window.confirm(
        `¿Marcar como no asistido el turno de ${itemName(item)}?`
      );
      if (confirmed) submitStatus(item, "no_show", button);
    }
  });

  if (paymentForm) {
    paymentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const item = state.paymentItem;
      if (!item) return;

      const amount = Number(paymentAmount.value);
      if (!Number.isFinite(amount) || amount <= 0) {
        paymentError.textContent = "Ingresá un monto mayor a cero.";
        paymentError.hidden = false;
        return;
      }
      const amountCents = Math.round(amount * 100);
      if (amountCents > Number(item.balance_cents)) {
        paymentError.textContent = `El monto supera el saldo pendiente (${formatMoney(
          item.balance_cents
        )}).`;
        paymentError.hidden = false;
        return;
      }

      paymentError.hidden = true;
      paymentSubmit.disabled = true;
      paymentSubmit.textContent = "Registrando…";

      try {
        await apiFetch(
          `/api/admin/appointments/${Number(item.id)}/payments`,
          {
            method: "POST",
            body: JSON.stringify({
              amount_cents: amountCents,
              method: paymentMethod.value,
              kind: paymentKind.value,
            }),
          }
        );
        dialog.close();
        state.paymentItem = null;
        showToast(`Pago de ${formatMoney(amountCents)} registrado.`);
        await loadQueue({ silent: true });
      } catch (error) {
        if (error.message !== "Sesión vencida.") {
          paymentError.textContent = error.message;
          paymentError.hidden = false;
          paymentSubmit.disabled = false;
          paymentSubmit.textContent = "Registrar pago";
        }
      }
    });
  }

  if (dialog) {
    dialog.querySelectorAll("[data-close-payment]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
      state.paymentItem = null;
      paymentError.hidden = true;
    });
  }

  if (rescheduleForm) {
    rescheduleForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const item = state.rescheduleItem;
      if (!item) return;

      const barberId = Number(rescheduleBarber.value);
      const startAt = rescheduleSlot.value;
      if (!barberId || !startAt) {
        rescheduleError.textContent = "Elegí un barbero, una fecha y un horario.";
        rescheduleError.hidden = false;
        return;
      }
      if (
        barberId === Number(state.queueBarberId) &&
        new Date(startAt).getTime() === new Date(item.scheduled_start_at).getTime()
      ) {
        rescheduleError.textContent =
          "Ese es el horario actual del turno. Elegí otro para reasignarlo.";
        rescheduleError.hidden = false;
        return;
      }

      rescheduleError.hidden = true;
      rescheduleError.textContent = "";
      rescheduleSubmit.disabled = true;
      rescheduleSubmit.textContent = "Reasignando…";

      try {
        const result = await apiFetch(
          `/api/admin/appointments/${Number(item.id)}/reschedule`,
          {
            method: "POST",
            body: JSON.stringify({ barber_id: barberId, start_at: startAt }),
          }
        );
        rescheduleDialog.close();
        state.rescheduleItem = null;
        showToast(
          `Turno de ${itemName(item)} reasignado a ${
            result.appointment.barber.name
          } · ${formatTime(result.appointment.start_at)}.`
        );
        await loadQueue({ silent: true });
      } catch (error) {
        if (error.message !== "Sesión vencida.") {
          if (error.message.includes("ya no está disponible")) {
            showToast(error.message, true);
            await loadRescheduleSlots();
            return;
          }
          rescheduleError.textContent = error.message;
          rescheduleError.hidden = false;
          rescheduleSubmit.disabled = false;
          rescheduleSubmit.textContent = "Reasignar turno";
        }
      }
    });
  }

  if (rescheduleDialog) {
    rescheduleDialog
      .querySelectorAll("[data-close-reschedule]")
      .forEach((button) => {
        button.addEventListener("click", () => rescheduleDialog.close());
      });
    rescheduleDialog.addEventListener("click", (event) => {
      if (event.target === rescheduleDialog) rescheduleDialog.close();
    });
    rescheduleDialog.addEventListener("close", () => {
      state.rescheduleItem = null;
      state.slotSerial += 1;
      rescheduleError.hidden = true;
      rescheduleSlot.disabled = true;
    });
    rescheduleBarber.addEventListener("change", () => loadRescheduleSlots());
    rescheduleDate.addEventListener("change", () => loadRescheduleSlots());
  }

  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadQueue();
  });
  if (barberSelect) {
    barberSelect.addEventListener("change", () => loadQueue());
  }
  dateInput.addEventListener("change", () => loadQueue());

  window.setInterval(() => {
    if (!document.hidden) loadQueue({ silent: true });
  }, 30000);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) loadQueue({ silent: true });
  });

  loadQueue();
})();
