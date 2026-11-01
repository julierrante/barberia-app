(() => {
  const dialog = document.getElementById("owner-actions-dialog");
  if (!dialog) {
    return;
  }

  const cards = Array.from(document.querySelectorAll("[data-barber-card]"));
  const title = document.getElementById("owner-actions-title");
  const status = document.getElementById("owner-actions-status");
  const image = document.getElementById("owner-actions-image");
  const initial = document.getElementById("owner-actions-initial");
  const agendaLink = document.getElementById("owner-action-agenda");
  const editLink = document.getElementById("owner-action-edit");
  const publicLink = document.getElementById("owner-action-public");
  const approveForm = document.getElementById("owner-action-approve-form");
  const approveButton = document.getElementById("owner-action-approve");
  const hint = document.getElementById("owner-actions-hint");
  const deleteForm = document.getElementById("owner-action-delete-form");

  function openCard(card) {
    const name = card.dataset.name || "Barbero";
    const pending = card.dataset.pending === "true";
    const hasSchedules = card.dataset.hasSchedules === "true";

    title.textContent = name;
    status.textContent = pending ? "Pendiente" : "Activo";
    status.className = `status-pill status-pill--${pending ? "pending" : "confirmed"}`;

    if (card.dataset.photo) {
      image.src = card.dataset.photo;
      image.hidden = false;
      initial.hidden = true;
      initial.textContent = "";
    } else {
      image.removeAttribute("src");
      image.hidden = true;
      initial.textContent = card.dataset.initial || name.slice(0, 1);
      initial.hidden = false;
    }

    agendaLink.href = card.dataset.agendaUrl;
    editLink.href = card.dataset.editUrl;
    publicLink.href = card.dataset.publicUrl || "#";
    publicLink.hidden = !card.dataset.publicUrl;
    approveForm.action = card.dataset.approveUrl;
    approveForm.hidden = !pending;
    approveButton.disabled = !hasSchedules;
    hint.hidden = !(pending && !hasSchedules);
    deleteForm.action = card.dataset.deleteUrl;

    if (!dialog.open) {
      dialog.showModal();
    }
  }

  cards.forEach((card) => {
    card.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      openCard(card);
    });
  });

  dialog.querySelectorAll("[data-close-owner-actions]").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
})();
