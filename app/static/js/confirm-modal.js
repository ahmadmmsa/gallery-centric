window.showConfirmModal = function ({
    title = "Confirm Action",
    message = "Are you sure you want to continue?",
    confirmText = "Confirm",
    confirmClass = "btn-danger"
} = {}) {
    return new Promise((resolve) => {
        const modalEl = document.getElementById("confirmModal");
        if (!modalEl) {
            console.error("Confirmation modal element #confirmModal not found in the DOM.");
            resolve(false);
            return;
        }
        
        // Storing active element for focus recovery
        const previousActiveElement = document.activeElement;

        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);

        const titleEl = document.getElementById("confirmModalLabel");
        const messageEl = document.getElementById("confirmModalMessage");
        const confirmBtn = document.getElementById("confirmModalOk");
        const iconEl = document.getElementById("confirmModalIcon");

        // Set text contents
        titleEl.textContent = title;
        messageEl.textContent = message;
        confirmBtn.textContent = confirmText;

        // Reset and assign classes to confirmation button
        confirmBtn.className = `btn ${confirmClass} px-4`;

        // Update icon based on confirmation context
        if (iconEl) {
            iconEl.className = "bi fs-4"; // Clear previous icon classes
            if (confirmClass.includes("btn-danger")) {
                iconEl.classList.add("bi-exclamation-triangle-fill", "text-danger");
            } else if (confirmClass.includes("btn-warning")) {
                iconEl.classList.add("bi-exclamation-circle-fill", "text-warning");
            } else if (confirmClass.includes("btn-success")) {
                iconEl.classList.add("bi-check-circle-fill", "text-success");
            } else {
                iconEl.classList.add("bi-info-circle-fill", "text-primary");
            }
        }

        let resolved = false;

        const cleanup = () => {
            confirmBtn.removeEventListener("click", onConfirm);
            modalEl.removeEventListener("hidden.bs.modal", onHidden);
            if (previousActiveElement && typeof previousActiveElement.focus === "function") {
                previousActiveElement.focus();
            }
        };

        const onConfirm = () => {
            resolved = true;
            cleanup();
            modal.hide();
            resolve(true);
        };

        const onHidden = () => {
            cleanup();
            if (!resolved) {
                resolve(false);
            }
        };

        confirmBtn.addEventListener("click", onConfirm, { once: true });
        modalEl.addEventListener("hidden.bs.modal", onHidden, { once: true });

        modal.show();
    });
};

// Global interceptor for HTMX hx-confirm actions
document.addEventListener("DOMContentLoaded", () => {
    document.body.addEventListener("htmx:confirm", function (evt) {
        // Stop browser default confirmation if hx-confirm is set
        if (!evt.detail.target.hasAttribute("hx-confirm")) return;

        evt.preventDefault();

        const target = evt.detail.target;
        const title = target.getAttribute("data-confirm-title") || "Confirm Action";
        const message = evt.detail.question; // Extract hx-confirm question string
        const confirmText = target.getAttribute("data-confirm-text") || "Confirm";
        const confirmClass = target.getAttribute("data-confirm-class") || "btn-danger";

        window.showConfirmModal({
            title: title,
            message: message,
            confirmText: confirmText,
            confirmClass: confirmClass
        }).then((confirmed) => {
            if (confirmed) {
                // Execute HTMX request skipping confirm event triggering again
                evt.detail.issueRequest(true);
            }
        });
    });
});
