// HTMX and General UI Enhancements
document.addEventListener('DOMContentLoaded', function() {
  // Initialize tooltips if Bootstrap tooltips are being used
  const tooltipElements = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipElements.forEach(el => {
    if (window.bootstrap && window.bootstrap.Tooltip) {
      new window.bootstrap.Tooltip(el);
    }
  });

  // Handle HTMX errors gracefully
  document.addEventListener('htmx:responseError', function(evt) {
    console.error('HTMX request failed:', evt.detail);
    // Could show a toast notification here
    // Re-enable submit button if present
    try {
      const elt = evt.detail.elt || (evt.detail.request && evt.detail.request.elt);
      const form = elt ? elt.closest('form') : null;
      if (form) {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = submitBtn.getAttribute('data-original-text') || 'Apply Filters';
        }
      }
    } catch (e) {
      // ignore
    }
  });

  // Handle HTMX load
  document.addEventListener('htmx:load', function(evt) {
    // Reinitialize tooltips after HTMX content loads
    const newTooltips = evt.detail.xhr.response.querySelectorAll('[data-bs-toggle="tooltip"]');
    newTooltips.forEach(el => {
      if (window.bootstrap && window.bootstrap.Tooltip) {
        new window.bootstrap.Tooltip(el);
      }
    });
  });

  // Smooth scroll behavior
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const href = this.getAttribute('href');
      if (href !== '#' && document.querySelector(href)) {
        e.preventDefault();
        document.querySelector(href).scrollIntoView({
          behavior: 'smooth'
        });
      }
    });
  });

  // Add loading state to buttons on form submission
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function() {
      const submitBtn = this.querySelector('button[type="submit"]');
      if (submitBtn) {
        // Save original text for later restore
        if (!submitBtn.getAttribute('data-original-text')) {
          submitBtn.setAttribute('data-original-text', submitBtn.innerHTML);
        }
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>';
      }
    });
  });

  // Re-enable submit buttons after HTMX requests complete
  document.addEventListener('htmx:afterRequest', function(evt) {
    try {
      const elt = evt.detail.elt;
      const form = elt ? elt.closest('form') : null;
      if (form) {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = submitBtn.getAttribute('data-original-text') || 'Apply Filters';
        }
      }
    } catch (e) {
      // ignore
    }
  });
});

// Lazy load images with Intersection Observer
if ('IntersectionObserver' in window) {
  const imageObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const img = entry.target;
        img.src = img.dataset.src;
        img.classList.remove('lazy-image');
        imageObserver.unobserve(img);
      }
    });
  });

  document.querySelectorAll('img.lazy-image').forEach((img) => {
    imageObserver.observe(img);
  });
}

// Debounce function for search input
function debounce(func, delay) {
  let timeoutId;
  return function(...args) {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => func.apply(this, args), delay);
  };
}

// Export for use in other scripts
window.Utilities = {
  debounce: debounce
};
