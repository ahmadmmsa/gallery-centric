// Reader Page Functionality
document.addEventListener('DOMContentLoaded', function () {
  const reader = {
    pages: Array.from(document.querySelectorAll('.reader-page')),
    currentPageIndex: 0,
    totalPages: 0,
    mode: 'slideshow', // 'slideshow' or 'infinite-scroll'
    isFullscreen: false,

    progressBar: document.getElementById('progress-bar'),
    currentPageDisplay: document.getElementById('current-page'),
    totalPagesDisplay: document.getElementById('total-pages'),
    modeSelector: document.getElementById('gallery-mode'),

    init() {
      this.totalPages = this.pages.length;
      if (this.totalPages === 0) return;

      if (this.totalPagesDisplay) {
        this.totalPagesDisplay.textContent = this.totalPages;
      }

      // Check query parameter or hash for starting page
      const urlParams = new URLSearchParams(window.location.search);
      let startPage = parseInt(urlParams.get('page')) || parseInt(window.location.hash.replace('#page-', ''));
      if (startPage && startPage >= 1 && startPage <= this.totalPages) {
        this.currentPageIndex = startPage - 1;
      }

      this.setupEventListeners();

      // Default to what's in the select (or slideshow)
      if (this.modeSelector) {
        this.setMode(this.modeSelector.value);
      } else {
        this.setMode('slideshow');
      }
    },

    setupEventListeners() {
      // Mode selector
      if (this.modeSelector) {
        this.modeSelector.addEventListener('change', (e) => {
          this.setMode(e.target.value);
        });
      }

      // Keyboard navigation
      document.addEventListener('keydown', (e) => this.handleKeyPress(e));

      // Click navigation
      document.addEventListener('click', (e) => this.handleImageClick(e));

      // Page Input navigation
      if (this.currentPageDisplay && this.currentPageDisplay.tagName === 'INPUT') {
        this.currentPageDisplay.addEventListener('change', (e) => {
          let page = parseInt(e.target.value);
          if (isNaN(page)) return;
          if (page < 1) page = 1;
          if (page > this.totalPages) page = this.totalPages;
          e.target.value = page; // update display if clamped
          this.navigateToPage(page - 1);
        });
      }

      // Action buttons
      const navFirst = document.getElementById('nav-first');
      const navPrev = document.getElementById('nav-prev');
      const navNext = document.getElementById('nav-next');
      const navLast = document.getElementById('nav-last');

      if (navFirst) navFirst.addEventListener('click', (e) => { e.preventDefault(); this.navigateToPage(0); });
      if (navPrev) navPrev.addEventListener('click', (e) => { e.preventDefault(); this.navigateToPage(this.currentPageIndex - 1); });
      if (navNext) navNext.addEventListener('click', (e) => { e.preventDefault(); this.navigateToPage(this.currentPageIndex + 1); });
      if (navLast) navLast.addEventListener('click', (e) => { e.preventDefault(); this.navigateToPage(this.totalPages - 1); });

      // Native fullscreen sync
      document.addEventListener('fullscreenchange', () => {
        if (!document.fullscreenElement && this.isFullscreen) {
          const page = this.pages[this.currentPageIndex];
          if (page) page.classList.remove('fullscreen');
          this.isFullscreen = false;
          document.body.style.overflow = ''; // Restore scrollbar
          if (this.mode === 'infinite-scroll') {
            setTimeout(() => page.scrollIntoView({ block: 'center' }), 50);
          }
        }
      });

      // Intersection Observer for Infinite Scroll
      this.observer = new IntersectionObserver((entries) => {
        if (this.mode !== 'infinite-scroll') return;
        if (this.isFullscreen) return; // Don't track scrolling while in full-screen

        let mostVisible = null;
        let maxRatio = 0;

        entries.forEach(entry => {
          if (entry.isIntersecting && entry.intersectionRatio > maxRatio) {
            maxRatio = entry.intersectionRatio;
            mostVisible = entry.target;
          }
        });

        if (mostVisible) {
          const idx = this.pages.indexOf(mostVisible);
          if (idx !== -1 && idx !== this.currentPageIndex) {
            this.currentPageIndex = idx;
            this.updateProgress();
            this.preloadNextImages(idx);
          }
        }
      }, {
        root: null,
        rootMargin: '0px',
        threshold: [0.1, 0.5, 0.9]
      });

      this.pages.forEach(page => this.observer.observe(page));
    },

    setMode(newMode) {
      this.mode = newMode;
      // Exit fullscreen when changing modes
      if (this.isFullscreen) {
        this.pages.forEach(p => p.classList.remove('fullscreen'));
        this.isFullscreen = false;
        document.body.style.overflow = ''; // Restore scrollbar
      }

      if (this.mode === 'slideshow') {
        // Hide all except current
        this.pages.forEach((page, idx) => {
          if (idx === this.currentPageIndex) {
            page.classList.remove('d-none');
            page.classList.add('active', 'd-block');
          } else {
            page.classList.remove('active', 'd-block');
            page.classList.add('d-none');
          }
        });
        // Scroll to top
        window.scrollTo(0, 0);
      } else if (this.mode === 'infinite-scroll') {
        // Show all
        this.pages.forEach(page => {
          page.classList.remove('d-none', 'active');
        });
        // Scroll to current page
        setTimeout(() => {
          this.pages[this.currentPageIndex].scrollIntoView();
        }, 50);
      }
      this.updateProgress();
      this.preloadNextImages(this.currentPageIndex);
    },

    handleKeyPress(e) {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      if (e.key === 'Escape') {
        if (this.isFullscreen) {
          this.toggleFullscreen(this.currentPageIndex);
        }
        return;
      }

      if (this.mode === 'slideshow') {
        if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowRight') {
          e.preventDefault();
          this.navigateToPage(this.currentPageIndex + 1);
        } else if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowLeft') {
          e.preventDefault();
          this.navigateToPage(this.currentPageIndex - 1);
        }
      } else if (this.mode === 'infinite-scroll') {
        if (this.isFullscreen) {
          if (e.key === 'j' || e.key === 'J' || e.key === 'ArrowDown') {
            e.preventDefault();
            this.navigateToPage(this.currentPageIndex + 1);
          } else if (e.key === 'k' || e.key === 'K' || e.key === 'ArrowUp') {
            e.preventDefault();
            this.navigateToPage(this.currentPageIndex - 1);
          }
        }
      }
    },

    handleImageClick(e) {
      if (e.target.classList.contains('reader-image')) {
        const pageElement = e.target.closest('.reader-page');
        const idx = this.pages.indexOf(pageElement);
        if (idx !== -1) {
          this.toggleFullscreen(idx);
        }
      }
    },

    toggleFullscreen(index) {
      const page = this.pages[index];
      if (!page) return;

      if (this.isFullscreen) {
        page.classList.remove('fullscreen');
        this.isFullscreen = false;
        document.body.style.overflow = ''; // Restore scrollbar

        if (document.fullscreenElement) {
          document.exitFullscreen().catch(err => console.log(err));
        }

        // If exiting fullscreen in infinite scroll, scroll to it
        if (this.mode === 'infinite-scroll') {
          setTimeout(() => page.scrollIntoView({ block: 'center' }), 50);
        }
      } else {
        // Remove fullscreen from any others
        this.pages.forEach(p => p.classList.remove('fullscreen'));

        page.classList.add('fullscreen');
        this.isFullscreen = true;
        this.currentPageIndex = index;
        this.updateProgress();
        document.body.style.overflow = 'hidden'; // Hide scrollbar

        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen().catch(err => console.log(err));
        }
      }
    },

    navigateToPage(index) {
      // Boundary check
      if (index >= 0 && index < this.totalPages) {
        const previousIndex = this.currentPageIndex;
        this.currentPageIndex = index;

        if (this.mode === 'slideshow') {
          this.pages[previousIndex].classList.remove('active', 'd-block');
          this.pages[previousIndex].classList.add('d-none');

          this.pages[this.currentPageIndex].classList.remove('d-none');
          this.pages[this.currentPageIndex].classList.add('active', 'd-block');

          // If we were in fullscreen, maintain fullscreen on new page
          if (this.isFullscreen) {
            this.pages[previousIndex].classList.remove('fullscreen');
            this.pages[this.currentPageIndex].classList.add('fullscreen');
          }
        } else if (this.mode === 'infinite-scroll') {
          if (this.isFullscreen) {
            this.pages[previousIndex].classList.remove('fullscreen');
            this.pages[this.currentPageIndex].classList.add('fullscreen');
          } else {
            this.pages[this.currentPageIndex].scrollIntoView({ behavior: 'smooth' });
          }
        }

        this.updateProgress();
        this.preloadNextImages(this.currentPageIndex);
      }
    },

    updateProgress() {
      const progress = ((this.currentPageIndex + 1) / this.totalPages) * 100;
      if (this.progressBar) {
        this.progressBar.style.width = progress + '%';
      }
      if (this.currentPageDisplay) {
        if (this.currentPageDisplay.tagName === 'INPUT') {
          this.currentPageDisplay.value = this.currentPageIndex + 1;
        } else {
          this.currentPageDisplay.textContent = this.currentPageIndex + 1;
        }
      }
    },

    preloadNextImages(currentIndex) {
      for (let i = 1; i <= 2; i++) {
        const nextIndex = currentIndex + i;
        if (nextIndex < this.totalPages) {
          const img = this.pages[nextIndex].querySelector('img');
          if (img && img.src) {
            const preloadImg = new Image();
            preloadImg.src = img.src;
          }
        }
      }
    }
  };

  reader.init();
});