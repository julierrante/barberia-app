(() => {
  "use strict";

  const form = document.getElementById("booking-form");
  if (!form) return;

  const timeZone = form.dataset.timezone || "America/Argentina/Buenos_Aires";
  const dateInput = document.getElementById("booking-date");
  const slotPanel = document.getElementById("slot-panel");
  const serviceOptions = Array.from(document.querySelectorAll(".service-option"));
  const barberCards = Array.from(document.querySelectorAll(".barber-card"));
  const paymentInputs = Array.from(
    document.querySelectorAll('input[name="payment_option"]')
  );
  const depositInput = document.querySelector('input[value="deposit"]');
  const fullInput = document.querySelector('input[value="full"]');
  const laterInput = document.querySelector('input[value="later"]');
  const depositCard = document.getElementById("payment-deposit-card");
  const fullCard = document.getElementById("payment-full-card");
  const depositAmount = document.querySelector("[data-payment-deposit]");
  const fullAmount = document.querySelector("[data-payment-full]");
  const errorBox = document.getElementById("booking-error");
  const submitButton = document.getElementById("booking-submit");
  const hint = document.getElementById("summary-hint");
  const firstNameInput = document.getElementById("client-first-name");
  const lastNameInput = document.getElementById("client-last-name");
  const phoneInput = document.getElementById("client-phone");
  const emailInput = document.getElementById("client-email");

  const summary = {
    service: document.querySelector("[data-summary-service]"),
    barber: document.querySelector("[data-summary-barber]"),
    date: document.querySelector("[data-summary-date]"),
    time: document.querySelector("[data-summary-time]"),
    duration: document.querySelector("[data-summary-duration]"),
    price: document.querySelector("[data-summary-price]"),
    payment: document.querySelector("[data-summary-payment]"),
  };

  const state = {
    service: null,
    barber: null,
    slot: null,
    serial: 0,
  };

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

  function formatDateLabel(isoDate) {
    if (!isoDate) return "—";
    const date = new Date(`${isoDate}T12:00:00`);
    if (Number.isNaN(date.getTime())) return "—";
    const text = new Intl.DateTimeFormat("es-AR", {
      weekday: "long",
      day: "numeric",
      month: "long",
      timeZone,
    }).format(date);
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function setError(message) {
    errorBox.textContent = message || "";
    errorBox.hidden = !message;
  }

  function selectCard(node, selected) {
    node.classList.toggle("is-selected", selected);
    const button = node.matches("button")
      ? node
      : node.querySelector("[data-barber-select]");
    if (button) button.setAttribute("aria-pressed", String(selected));
  }

  function resetSlot() {
    state.slot = null;
    slotPanel.querySelectorAll(".slot-button.is-selected").forEach((button) => {
      button.classList.remove("is-selected");
      button.setAttribute("aria-pressed", "false");
    });
  }

  function clientIsValid() {
    const digits = phoneInput.value.replace(/\D/g, "");
    return (
      firstNameInput.value.trim().length >= 2 &&
      lastNameInput.value.trim().length >= 2 &&
      digits.length >= 6
    );
  }

  function syncPaymentCards() {
    const service = state.service;
    if (!service) {
      depositInput.disabled = true;
      fullInput.disabled = true;
      depositCard.classList.add("is-disabled");
      fullCard.classList.add("is-disabled");
      depositAmount.textContent = "Elegí un servicio";
      fullAmount.textContent = "Elegí un servicio";
    } else {
      depositInput.disabled = service.deposit <= 0;
      fullInput.disabled = false;
      depositCard.classList.toggle("is-disabled", service.deposit <= 0);
      fullCard.classList.remove("is-disabled");
      depositAmount.textContent =
        service.deposit > 0 ? `${formatMoney(service.deposit)} online` : "Sin seña";
      fullAmount.textContent = `${formatMoney(service.price)} online`;
    }

    const checked = paymentInputs.find((input) => input.checked);
    if (checked && checked.disabled) {
      laterInput.checked = true;
    }
  }

  function paymentMessage() {
    const service = state.service;
    if (!service) return "Pagás en el local.";
    const option = paymentInputs.find((input) => input.checked)?.value || "later";
    if (option === "deposit") {
      return `Seña online: ${formatMoney(service.deposit)} · saldo ${formatMoney(
        service.price - service.deposit
      )}.`;
    }
    if (option === "full") {
      return `Pago total online: ${formatMoney(service.price)}.`;
    }
    return `Pagás ${formatMoney(service.price)} en el local.`;
  }

  function updateSummary() {
    summary.service.textContent = state.service ? state.service.name : "—";
    summary.barber.textContent = state.barber ? state.barber.name : "—";
    summary.date.textContent = dateInput.value ? formatDateLabel(dateInput.value) : "—";
    summary.time.textContent = state.slot ? state.slot.label : "—";
    summary.duration.textContent = state.service
      ? formatDuration(state.service.duration)
      : "—";
    summary.price.textContent = state.service
      ? formatMoney(state.service.price)
      : "—";
    summary.payment.textContent = paymentMessage();

    const missing = [];
    if (!state.service) missing.push("servicio");
    if (!state.barber) missing.push("barbero");
    if (!state.slot) missing.push("horario");
    if (!clientIsValid()) missing.push("datos");

    submitButton.disabled = missing.length > 0;
    if (!missing.length) {
      hint.textContent = "Todo listo para confirmar tu turno.";
    } else if (missing.length === 1) {
      hint.textContent = `Falta elegir ${missing[0]}.`;
    } else {
      hint.textContent = "Completá los 4 pasos para confirmar.";
    }
  }

  function placeholder(message) {
    slotPanel.replaceChildren();
    slotPanel.removeAttribute("aria-busy");
    const wrapper = document.createElement("div");
    wrapper.className = "slot-placeholder";
    const mark = document.createElement("span");
    mark.className = "placeholder-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "—";
    const text = document.createElement("p");
    text.textContent = message;
    wrapper.append(mark, text);
    slotPanel.append(wrapper);
  }

  function renderLoading() {
    slotPanel.replaceChildren();
    slotPanel.setAttribute("aria-busy", "true");
    const skeleton = document.createElement("div");
    skeleton.className = "slot-loading";
    skeleton.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 8; index += 1) {
      skeleton.append(document.createElement("span"));
    }
    slotPanel.append(skeleton);
  }

  function renderError(message) {
    slotPanel.replaceChildren();
    slotPanel.removeAttribute("aria-busy");
    const wrapper = document.createElement("div");
    wrapper.className = "slot-empty";
    const mark = document.createElement("span");
    mark.className = "placeholder-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "—";
    const text = document.createElement("p");
    text.textContent = message;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn btn--ghost btn--small";
    retry.textContent = "Reintentar";
    retry.addEventListener("click", () => refreshSlots());
    wrapper.append(mark, text, retry);
    slotPanel.append(wrapper);
  }

  function groupSlots(slots) {
    const groups = new Map();
    slots.forEach((slot) => {
      const hour = Number.parseInt(slot.label.slice(0, 2), 10);
      const heading = hour < 12 ? "Mañana" : hour < 19 ? "Tarde" : "Noche";
      if (!groups.has(heading)) groups.set(heading, []);
      groups.get(heading).push(slot);
    });
    return groups;
  }

  function chooseSlot(button, slot) {
    state.slot = slot;
    slotPanel.querySelectorAll(".slot-button").forEach((node) => {
      const active = node === button;
      node.classList.toggle("is-selected", active);
      node.setAttribute("aria-pressed", String(active));
    });
    setError("");
    updateSummary();
  }

  function renderLegend() {
    const legend = document.createElement("div");
    legend.className = "slot-legend";
    [
      ["available", "Libre"],
      ["occupied", "Ocupado"],
      ["past", "No disponible"],
    ].forEach(([status, text]) => {
      const item = document.createElement("span");
      item.className = `slot-legend-item slot-legend-item--${status}`;
      item.textContent = text;
      legend.append(item);
    });
    return legend;
  }

  function renderSlots(data) {
    slotPanel.replaceChildren();
    slotPanel.removeAttribute("aria-busy");

    const calendar =
      Array.isArray(data.calendar) && data.calendar.length
        ? data.calendar
        : (data.slots || []).map((slot) => ({ ...slot, status: "available" }));

    if (!calendar.length) {
      const wrapper = document.createElement("div");
      wrapper.className = "slot-empty";
      const mark = document.createElement("span");
      mark.className = "placeholder-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "—";
      const text = document.createElement("p");
      text.textContent =
        "No hay horarios para este día con ese barbero. Probá otra fecha u otro profesional.";
      wrapper.append(mark, text);

      const searchButton = document.createElement("button");
      searchButton.type = "button";
      searchButton.className = "btn btn--ghost btn--small";
      searchButton.textContent = "Buscar el próximo día con lugar";
      searchButton.addEventListener("click", () => findNextDay(searchButton));
      wrapper.append(searchButton);

      slotPanel.append(wrapper);
      return;
    }

    slotPanel.append(renderLegend());

    groupSlots(calendar).forEach((slots, heading) => {
      const group = document.createElement("section");
      group.className = "slot-group";
      const head = document.createElement("div");
      head.className = "slot-group-head";
      head.textContent = heading;
      const grid = document.createElement("div");
      grid.className = "slot-grid";

      slots.forEach((slot) => {
        const status = slot.status || "available";
        const button = document.createElement("button");
        button.type = "button";
        button.className = `slot-button slot-button--${status}`;
        button.textContent = slot.label;

        if (status === "available") {
          button.setAttribute("aria-pressed", "false");
          button.addEventListener("click", () => chooseSlot(button, slot));
        } else {
          button.disabled = true;
          button.title =
            status === "occupied" ? "Horario ya ocupado" : "Horario no disponible";
          button.setAttribute("aria-disabled", "true");
        }

        grid.append(button);
      });

      group.append(head, grid);
      slotPanel.append(group);
    });

    if (!data.slots.length) {
      const hint = document.createElement("div");
      hint.className = "slot-empty slot-empty--compact";
      const text = document.createElement("p");
      text.textContent =
        "Ya no quedan horarios libres este día. Los horarios en rojo están ocupados.";
      const searchButton = document.createElement("button");
      searchButton.type = "button";
      searchButton.className = "btn btn--ghost btn--small";
      searchButton.textContent = "Buscar el próximo día con lugar";
      searchButton.addEventListener("click", () => findNextDay(searchButton));
      hint.append(text, searchButton);
      slotPanel.append(hint);
    }
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

  async function fetchAvailability(day) {
    const params = new URLSearchParams({
      barber_id: String(state.barber.id),
      service_id: String(state.service.id),
      date: day,
    });
    const response = await fetch(`/api/availability?${params}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(await apiMessage(response));
    }
    return response.json();
  }

  async function refreshSlots() {
    const serial = ++state.serial;
    resetSlot();
    updateSummary();

    if (!state.service || !state.barber || !dateInput.value) {
      if (!state.service && !state.barber) {
        placeholder("Elegí un servicio y un barbero para ver los horarios disponibles.");
      } else if (!state.service) {
        placeholder("Elegí un servicio para ver los horarios disponibles.");
      } else if (!state.barber) {
        placeholder("Ahora elegí un barbero para ver su disponibilidad.");
      } else {
        placeholder("Elegí una fecha para consultar los horarios.");
      }
      return;
    }

    renderLoading();
    try {
      const data = await fetchAvailability(dateInput.value);
      if (serial !== state.serial) return;
      renderSlots(data);
    } catch (error) {
      if (serial !== state.serial) return;
      renderError(error.message || "No pudimos cargar la disponibilidad.");
    }
  }

  async function findNextDay(button) {
    if (!state.service || !state.barber || !dateInput.value) return;
    const serial = ++state.serial;
    const maxDate = dateInput.max ? new Date(`${dateInput.max}T12:00:00`) : null;
    const start = new Date(`${dateInput.value}T12:00:00`);

    button.disabled = true;
    button.textContent = "Buscando…";
    slotPanel.setAttribute("aria-busy", "true");

    for (let offset = 1; offset <= 14; offset += 1) {
      const candidate = new Date(start);
      candidate.setDate(start.getDate() + offset);
      if (maxDate && candidate > maxDate) break;
      const iso = [
        candidate.getFullYear(),
        String(candidate.getMonth() + 1).padStart(2, "0"),
        String(candidate.getDate()).padStart(2, "0"),
      ].join("-");

      try {
        const data = await fetchAvailability(iso);
        if (serial !== state.serial) return;
        if (data.slots.length) {
          dateInput.value = iso;
          state.slot = null;
          renderSlots(data);
          updateSummary();
          return;
        }
      } catch (error) {
        if (serial !== state.serial) return;
        renderError(error.message || "No pudimos buscar disponibilidad.");
        return;
      }
    }

    if (serial !== state.serial) return;
    slotPanel.replaceChildren();
    slotPanel.removeAttribute("aria-busy");
    const wrapper = document.createElement("div");
    wrapper.className = "slot-empty";
    const mark = document.createElement("span");
    mark.className = "placeholder-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "—";
    const text = document.createElement("p");
    text.textContent =
      "No encontramos horarios libres en los próximos 14 días. Probá con otro barbero o elegí otra fecha.";
    wrapper.append(mark, text);
    slotPanel.append(wrapper);
  }

  serviceOptions.forEach((button) => {
    button.addEventListener("click", () => {
      const id = Number(button.dataset.serviceId);
      if (state.service && state.service.id === id) return;
      state.service = {
        id,
        name: button.dataset.name,
        price: Number(button.dataset.price),
        deposit: Number(button.dataset.deposit),
        duration: Number(button.dataset.duration),
      };
      serviceOptions.forEach((option) => selectCard(option, option === button));
      syncPaymentCards();
      setError("");
      refreshSlots();
    });
  });

  function chooseBarber(card) {
    const id = Number(card.dataset.barberId);
    if (state.barber && state.barber.id === id) return;
    state.barber = {
      id,
      slug: card.dataset.slug,
      name: card.querySelector(".barber-name")?.textContent.trim() || "Barbero",
    };
    barberCards.forEach((item) => selectCard(item, item === card));
    setError("");
    refreshSlots();
  }

  barberCards.forEach((card) => {
    card
      .querySelector("[data-barber-select]")
      ?.addEventListener("click", () => chooseBarber(card));
  });

  dateInput.addEventListener("change", () => {
    setError("");
    refreshSlots();
  });

  paymentInputs.forEach((input) => {
    input.addEventListener("change", () => {
      setError("");
      updateSummary();
    });
  });

  [firstNameInput, lastNameInput, phoneInput, emailInput].forEach((input) => {
    input.addEventListener("input", updateSummary);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");

    if (!state.service || !state.barber || !state.slot) {
      setError("Elegí un servicio, un barbero y un horario antes de confirmar.");
      return;
    }
    if (!form.reportValidity()) {
      setError("Revisá los datos marcados en el formulario.");
      return;
    }

    const payload = {
      barber_id: state.barber.id,
      service_id: state.service.id,
      start_at: state.slot.start_at,
      payment_option:
        paymentInputs.find((input) => input.checked)?.value || "later",
      client: {
        first_name: firstNameInput.value.trim(),
        last_name: lastNameInput.value.trim(),
        phone: phoneInput.value.trim(),
        email: emailInput.value.trim() || null,
      },
    };

    submitButton.disabled = true;
    submitButton.textContent = "Confirmando…";

    try {
      const response = await fetch("/api/appointments", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const message = await apiMessage(response);
        if (response.status === 409) {
          refreshSlots();
        }
        throw new Error(message);
      }

      const appointment = await response.json();
      try {
        sessionStorage.setItem(
          `barberia:phone:${appointment.public_code}`,
          payload.client.phone
        );
      } catch (_error) {
        // Session storage can be unavailable in private browsing.
      }
      window.location.assign(`/reserva/${appointment.public_code}`);
    } catch (error) {
      setError(error.message || "No pudimos confirmar el turno. Intentá de nuevo.");
      submitButton.textContent = "Confirmar turno";
      updateSummary();
    }
  });

  syncPaymentCards();
  updateSummary();

  const presetSlug = new URLSearchParams(window.location.search).get("barbero");
  if (presetSlug) {
    const presetCard = barberCards.find(
      (card) => card.dataset.slug === presetSlug
    );
    if (presetCard) chooseBarber(presetCard);
  }
})();
