(() => {
  "use strict";

  const root = document.getElementById("confirmation-data");
  if (!root) return;

  const code = root.dataset.code;
  const timeZone = root.dataset.timezone || "America/Argentina/Buenos_Aires";
  const badge = document.getElementById("status-badge");
  const title = document.getElementById("confirmation-title");
  const lead = document.getElementById("confirmation-lead");
  const cancelForm = document.getElementById("cancel-form");
  const cancelPanel = document.querySelector(".cancel-panel");
  const cancelSuccess = document.getElementById("cancel-success");
  const cancelError = document.getElementById("cancel-error");
  const cancelSubmit = document.getElementById("cancel-submit");
  const cancelPhone = document.getElementById("cancel-phone");
  const ratingPanel = document.getElementById("rating-panel");
  const ratingForm = document.getElementById("rating-form");
  const ratingStars = document.getElementById("rating-stars");
  const ratingComment = document.getElementById("rating-comment");
  const ratingError = document.getElementById("rating-error");
  const ratingSubmit = document.getElementById("rating-submit");
  const ratingSummary = document.getElementById("rating-summary");
  const ratingSummaryStars = document.getElementById("rating-summary-stars");
  const ratingSummaryScore = document.getElementById("rating-summary-score");
  const ratingSummaryComment = document.getElementById("rating-summary-comment");
  const copyAliasButton = document.getElementById("copy-alias");
  const copyAliasStatus = document.getElementById("copy-alias-status");
  const attendancePanel = document.getElementById("attendance-panel");
  const attendanceButton = document.getElementById("attendance-confirm");
  const attendanceError = document.getElementById("attendance-error");
  const activeStatuses = ["confirmed", "in_progress"];

  const copy = {
    confirmed: {
      label: "Confirmado",
      title: "Tu turno está<br><em>confirmado</em>.",
      lead: "Guardá este comprobante. El día del turno vas a poder ver acá la llegada estimada actualizada.",
    },
    in_progress: {
      label: "En curso",
      title: "Tu turno está<br><em>en marcha</em>.",
      lead: "El barbero ya empezó el servicio.",
    },
    completed: {
      label: "Completado",
      title: "Servicio<br><em>completado</em>.",
      lead: "Gracias por pasar. Este turno ya quedó en tu historial.",
    },
    cancelled: {
      label: "Cancelado",
      title: "Turno<br><em>cancelado</em>.",
      lead: "El horario fue liberado. Podés reservar uno nuevo cuando quieras.",
    },
    no_show: {
      label: "No se presentó",
      title: "Turno<br><em>no asistido</em>.",
      lead: "Este turno figura como no asistido.",
    },
  };

  let currentStatus =
    root.dataset.status && copy[root.dataset.status] ? root.dataset.status : "confirmed";
  let pollTimer = null;
  let selectedScore = 0;

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

  function setBadge(status) {
    const info = copy[status];
    if (!info) return;
    badge.className = `status-badge status-badge--${status}`;
    badge.innerHTML = `<span class="status-dot" aria-hidden="true"></span>${info.label}`;
  }

  function setCopy(status) {
    const info = copy[status];
    if (!info) return;
    title.innerHTML = info.title;
    lead.textContent = info.lead;
  }

  function updateEta(data) {
    const box = document.getElementById("live-eta");
    if (!activeStatuses.includes(data.status)) {
      if (box) box.remove();
      return;
    }
    if (!box) return;

    const value = document.getElementById("eta-value");
    const chip = document.getElementById("delay-chip");
    const note = document.getElementById("eta-note");
    const delay = Number(data.delay_minutes) || 0;

    if (value) value.textContent = formatTime(data.eta_start_at);
    if (chip) {
      chip.textContent = delay > 0 ? `+${delay} min` : "En horario";
      chip.classList.toggle("delay-chip--ok", delay === 0);
    }
    if (note) {
      note.textContent =
        data.status === "in_progress"
          ? "Estimación según el avance del servicio actual."
          : "Se actualiza con la cola real del barbero el día del turno.";
    }
  }

  function showCancellationReason(reason) {
    if (!reason) return;
    let element = document.querySelector(".cancellation-reason");
    if (!element) {
      element = document.createElement("p");
      element.className = "cancellation-reason";
      root.querySelector(".ticket-main")?.append(element);
    }
    element.textContent = reason;
  }

  function applyData(data) {
    const status = copy[data.status] ? data.status : currentStatus;
    if (
      attendancePanel &&
      data.client_confirmed_at &&
      attendancePanel.dataset.confirmed !== "true"
    ) {
      showAttendanceConfirmed();
    }
    if (status !== currentStatus) {
      currentStatus = status;
      setBadge(status);
      setCopy(status);
      if (status !== "confirmed" && cancelPanel) {
        cancelPanel.hidden = true;
      }
      if (status === "cancelled") {
        showCancellationReason(data.cancel_reason);
      }
    }
    if (ratingPanel && status === "completed") {
      ratingPanel.hidden = false;
    }
    updateEta(data);
    if (!activeStatuses.includes(currentStatus)) {
      stopPolling();
    }
  }

  function paintStars(score) {
    ratingStars
      ?.querySelectorAll(".rating-star")
      .forEach((label) => {
        label.classList.toggle(
          "is-active",
          Number(label.dataset.score) <= score
        );
      });
  }

  function showRatingSummary(rating) {
    if (!ratingSummary) return;
    const score = Number(rating.score) || 0;
    if (ratingSummaryStars) {
      ratingSummaryStars.textContent = `${"★".repeat(score)}${"☆".repeat(5 - score)}`;
    }
    if (ratingSummaryScore) {
      ratingSummaryScore.textContent = `${score} de 5`;
    }
    if (ratingSummaryComment) {
      ratingSummaryComment.textContent = rating.comment || "";
    }
    ratingSummary.hidden = false;
    if (ratingForm) ratingForm.hidden = true;
    if (ratingPanel) ratingPanel.dataset.hasRating = "true";
  }

  if (ratingStars) {
    ratingStars.querySelectorAll('input[name="score"]').forEach((input) => {
      input.addEventListener("change", () => {
        selectedScore = Number(input.value);
        paintStars(selectedScore);
        if (ratingError) ratingError.hidden = true;
      });
    });
  }

  if (ratingForm && ratingPanel) {
    ratingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (ratingError) {
        ratingError.hidden = true;
        ratingError.textContent = "";
      }
      if (!selectedScore) {
        if (ratingError) {
          ratingError.textContent = "Elegí una puntuación de 1 a 5 estrellas.";
          ratingError.hidden = false;
        }
        return;
      }
      if (ratingSubmit) {
        ratingSubmit.disabled = true;
        ratingSubmit.textContent = "Enviando…";
      }

      try {
        const response = await fetch(ratingPanel.dataset.endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            score: selectedScore,
            comment: ratingComment?.value.trim() || null,
          }),
        });

        if (!response.ok) {
          throw new Error(await apiMessage(response));
        }

        showRatingSummary(await response.json());
      } catch (error) {
        if (ratingError) {
          ratingError.textContent =
            error.message || "No pudimos enviar tu calificación.";
          ratingError.hidden = false;
        }
        if (ratingSubmit) {
          ratingSubmit.disabled = false;
          ratingSubmit.textContent = "Enviar calificación";
        }
      }
    });
  }

  if (copyAliasButton) {
    copyAliasButton.addEventListener("click", async () => {
      const alias = document.getElementById("tip-alias-value")?.textContent.trim();
      if (!alias) return;
      try {
        await navigator.clipboard.writeText(alias);
      } catch (_error) {
        const helper = document.createElement("textarea");
        helper.value = alias;
        helper.setAttribute("readonly", "");
        helper.style.position = "fixed";
        helper.style.opacity = "0";
        document.body.append(helper);
        helper.select();
        document.execCommand("copy");
        helper.remove();
      }
      if (copyAliasStatus) {
        copyAliasStatus.hidden = false;
        window.setTimeout(() => {
          copyAliasStatus.hidden = true;
        }, 2500);
      }
    });
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function refresh() {
    if (document.hidden || !activeStatuses.includes(currentStatus)) return;
    try {
      const response = await fetch(`/api/appointments/${encodeURIComponent(code)}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) {
        if (response.status === 404) stopPolling();
        return;
      }
      applyData(await response.json());
    } catch (_error) {
      // Keep the last known state when the network is unavailable.
    }
  }

  function showAttendanceConfirmed() {
    if (!attendancePanel) return;
    attendancePanel.dataset.confirmed = "true";
    attendancePanel.innerHTML = `
      <p class="attendance-note attendance-note--ok">
        <span aria-hidden="true">✓</span>
        Asistencia confirmada. ¡Nos vemos el día del turno!
      </p>
    `;
  }

  if (attendanceButton && attendancePanel) {
    attendanceButton.addEventListener("click", async () => {
      if (attendanceError) {
        attendanceError.hidden = true;
        attendanceError.textContent = "";
      }
      attendanceButton.disabled = true;
      attendanceButton.textContent = "Confirmando…";

      try {
        const response = await fetch(attendancePanel.dataset.endpoint, {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error(await apiMessage(response));
        }
        showAttendanceConfirmed();
      } catch (error) {
        if (attendanceError) {
          attendanceError.textContent =
            error.message || "No pudimos registrar tu confirmación. Intentá de nuevo.";
          attendanceError.hidden = false;
        }
        attendanceButton.disabled = false;
        attendanceButton.textContent = "Confirmar asistencia";
      }
    });
  }

  if (cancelForm) {
    try {
      const savedPhone = sessionStorage.getItem(`barberia:phone:${code}`);
      if (savedPhone && cancelPhone) cancelPhone.value = savedPhone;
    } catch (_error) {
      // Session storage can be unavailable in private browsing.
    }

    cancelForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      cancelError.hidden = true;
      cancelError.textContent = "";
      cancelSubmit.disabled = true;
      cancelSubmit.textContent = "Cancelando…";

      try {
        const response = await fetch(
          `/api/appointments/${encodeURIComponent(code)}/cancel`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify({ phone: cancelPhone.value.trim() }),
          }
        );

        if (!response.ok) {
          throw new Error(await apiMessage(response));
        }

        const data = await response.json();
        applyData(data);
        cancelForm.hidden = true;
        if (cancelError) cancelError.hidden = true;
        if (cancelSuccess) cancelSuccess.hidden = false;
      } catch (error) {
        cancelError.textContent =
          error.message || "No pudimos cancelar el turno. Intentá de nuevo.";
        cancelError.hidden = false;
        cancelSubmit.disabled = false;
        cancelSubmit.textContent = "Cancelar turno";
      }
    });
  }

  if (activeStatuses.includes(currentStatus)) {
    pollTimer = window.setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) refresh();
    });
  }
})();
