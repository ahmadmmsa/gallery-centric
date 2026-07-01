document.addEventListener('DOMContentLoaded', () => {
    // CSRF token (double-submit cookie) for non-HTMX fetch/XHR requests.
    const CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    // -------------------------------------------------------------
    // 1. SortableJS Page Reordering
    // -------------------------------------------------------------
    const gridEl = document.getElementById('pagesSortableGrid');
    if (gridEl) {
        new Sortable(gridEl, {
            animation: 200,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            handle: '.drag-overlay',
            onEnd: async function (evt) {
                const pageId = evt.item.dataset.id;
                const newPageNumber = evt.newIndex + 1; // Sortable indices are 0-based, pages are 1-based

                // 1. Instantly update UI numbers for all elements locally
                updatePageLabels();

                // 2. Transmit reorder payload to the backend
                try {
                    const response = await fetch(`/admin/galleries/${GALLERY_ID}/pages/reorder`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRF-Token': CSRF_TOKEN
                        },
                        body: JSON.stringify({
                            page_id: parseInt(pageId),
                            new_page_number: newPageNumber
                        })
                    });
                    const data = await response.json();
                    if (data.status !== 'success') {
                        showGlobalToast('Reordering failed. Refreshing page...', 'danger');
                        window.location.reload();
                    }
                } catch (error) {
                    console.error('Error shifting pages order:', error);
                    showGlobalToast('Network error during reordering. Refreshing...', 'danger');
                    window.location.reload();
                }
            }
        });
    }

    // Renumbers the label and footer text for all page items in the DOM
    function updatePageLabels() {
        const items = document.querySelectorAll('#pagesSortableGrid .page-item');
        items.forEach((item, index) => {
            const newIndex = index + 1;
            // Update labels
            const numberLabel = item.querySelector('.page-number-label');
            if (numberLabel) numberLabel.textContent = '#' + newIndex;
            
            const textLabel = item.querySelector('.card-footer span');
            if (textLabel) textLabel.textContent = 'Page ' + newIndex;
        });

        // Update top counter badge
        const badge = document.getElementById('pageCountBadge');
        if (badge) badge.textContent = items.length + ' Pages';
    }

    // -------------------------------------------------------------
    // 2. AJAX Page Deletion
    // -------------------------------------------------------------
    if (gridEl) {
        gridEl.addEventListener('click', async (e) => {
            const btn = e.target.closest('.delete-btn');
            if (!btn) return;

            const pageId = btn.dataset.id;
            const confirmed = await window.showConfirmModal({
                title: 'Delete Page',
                message: 'Are you sure you want to delete this page? The image file will be removed permanently.',
                confirmText: 'Delete',
                confirmClass: 'btn-danger'
            });
            if (!confirmed) {
                return;
            }

            try {
                const response = await fetch(`/admin/pages/${pageId}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRF-Token': CSRF_TOKEN }
                });
                const data = await response.json();
                
                if (data.status === 'success') {
                    const itemEl = document.getElementById(`page-${pageId}`);
                    if (itemEl) {
                        // Apply premium fade out scale-down transition
                        itemEl.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                        itemEl.style.opacity = '0';
                        itemEl.style.transform = 'scale(0.8)';
                        
                        setTimeout(() => {
                            itemEl.remove();
                            updatePageLabels();
                            
                            // Check if grid is now empty
                            const items = document.querySelectorAll('#pagesSortableGrid .page-item');
                            if (items.length === 0) {
                                document.getElementById('emptyPagesState').classList.remove('d-none');
                            }
                        }, 300);
                    }
                } else {
                    alert('Delete failed: ' + (data.detail || 'unknown error'));
                }
            } catch (err) {
                console.error('Deletion error:', err);
                alert('Network error when deleting page.');
            }
        });
    }

    // -------------------------------------------------------------
    // 3. ZIP File Selection & Dnd
    // -------------------------------------------------------------
    const zipDropZone = document.getElementById('zipDropZone');
    const zipFileInput = document.getElementById('zipFileInput');
    const zipFileName = document.getElementById('zipFileName');
    const zipFileSize = document.getElementById('zipFileSize');
    const zipFileInfo = document.getElementById('zipFileInfo');
    const zipSubmitBtn = document.getElementById('zipSubmitBtn');
    const zipUploadForm = document.getElementById('zipUploadForm');

    if (zipDropZone) {
        // Trigger file picker
        zipDropZone.addEventListener('click', () => zipFileInput.click());

        // Drag highlights
        ['dragenter', 'dragover'].forEach(eventName => {
            zipDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                zipDropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            zipDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                zipDropZone.classList.remove('dragover');
            }, false);
        });

        // Drop file
        zipDropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length) {
                zipFileInput.files = files;
                handleZipFileSelection(files[0]);
            }
        });

        // Pick file
        zipFileInput.addEventListener('change', () => {
            if (zipFileInput.files.length) {
                handleZipFileSelection(zipFileInput.files[0]);
            }
        });
    }

    function handleZipFileSelection(file) {
        if (!file.name.endsWith('.zip')) {
            alert('Invalid file format. Please select a valid ZIP archive.');
            zipFileInput.value = '';
            zipFileInfo.classList.add('d-none');
            zipSubmitBtn.classList.add('d-none');
            return;
        }

        zipFileName.textContent = file.name;
        zipFileSize.textContent = (file.size / (1024 * 1024)).toFixed(2) + ' MB';
        zipFileInfo.classList.remove('d-none');
        zipSubmitBtn.classList.remove('d-none');
    }

    // AJAX Form submission for ZIP
    if (zipUploadForm) {
        zipUploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const file = zipFileInput.files[0];
            if (!file) return;

            zipSubmitBtn.disabled = true;
            zipSubmitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Extracting & Processing ZIP...';

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await fetch(`/admin/galleries/${GALLERY_ID}/upload-zip`, {
                    method: 'POST',
                    headers: { 'X-CSRF-Token': CSRF_TOKEN },
                    body: formData
                });
                
                if (response.ok) {
                    zipSubmitBtn.classList.replace('btn-primary', 'btn-success');
                    zipSubmitBtn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Bulk Import Success!';
                    setTimeout(() => {
                        window.location.reload();
                    }, 1000);
                } else {
                    const err = await response.json();
                    alert('ZIP Processing Failed: ' + (err.detail || 'Unknown error'));
                    zipSubmitBtn.disabled = false;
                    zipSubmitBtn.innerHTML = '<i class="bi bi-upload me-2"></i>Process ZIP File';
                }
            } catch (err) {
                console.error('ZIP upload error:', err);
                alert('ZIP transmission network error.');
                zipSubmitBtn.disabled = false;
                zipSubmitBtn.innerHTML = '<i class="bi bi-upload me-2"></i>Process ZIP File';
            }
        });
    }

    // -------------------------------------------------------------
    // 4. Multi-Image Selection, Dnd & Progressive Upload Queue
    // -------------------------------------------------------------
    const imageDropZone = document.getElementById('imageDropZone');
    const imageFileInput = document.getElementById('imageFileInput');
    const statusCard = document.getElementById('uploadStatusCard');
    const queueContainer = document.getElementById('uploadQueueContainer');
    const queueStatus = document.getElementById('queueStatus');

    if (imageDropZone) {
        imageDropZone.addEventListener('click', () => imageFileInput.click());

        ['dragenter', 'dragover'].forEach(eventName => {
            imageDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                imageDropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            imageDropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                imageDropZone.classList.remove('dragover');
            }, false);
        });

        imageDropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length) {
                processSelectedImages(Array.from(files));
            }
        });

        imageFileInput.addEventListener('change', () => {
            if (imageFileInput.files.length) {
                processSelectedImages(Array.from(imageFileInput.files));
            }
        });
    }

    let activeQueue = [];
    let completedCount = 0;
    let totalQueueCount = 0;
    let isUploading = false;

    function processSelectedImages(files) {
        // Filter only images
        const imageFiles = files.filter(f => f.type.startsWith('image/'));
        if (!imageFiles.length) {
            alert('No valid image files found.');
            return;
        }

        statusCard.classList.remove('d-none');
        
        imageFiles.forEach(file => {
            const fileId = 'upload-' + Math.random().toString(36).substr(2, 9);
            totalQueueCount++;
            
            // Add element to UI queue
            const row = document.createElement('div');
            row.className = 'upload-progress-card p-2 mb-2 rounded';
            row.id = fileId;
            row.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="small text-truncate" style="max-width: 70%;">${file.name}</span>
                    <span class="badge bg-secondary small-status">Waiting</span>
                </div>
                <div class="progress" style="height: 4px;">
                    <div class="progress-bar bg-primary" role="progressbar" style="width: 0%"></div>
                </div>
            `;
            queueContainer.appendChild(row);
            
            // Scroll container to bottom
            queueContainer.scrollTop = queueContainer.scrollHeight;

            activeQueue.push({ fileId, file });
        });

        updateQueueHeader();

        if (!isUploading) {
            startNextUpload();
        }
    }

    function updateQueueHeader() {
        if (queueStatus) {
            queueStatus.textContent = `${completedCount} / ${totalQueueCount} Done`;
        }
    }

    async function startNextUpload() {
        if (activeQueue.length === 0) {
            isUploading = false;
            showGlobalToast('All files uploaded successfully!', 'success');
            setTimeout(() => {
                window.location.reload();
            }, 1000);
            return;
        }

        isUploading = true;
        const task = activeQueue.shift();
        const row = document.getElementById(task.fileId);
        const bar = row.querySelector('.progress-bar');
        const badge = row.querySelector('.small-status');

        badge.textContent = 'Uploading';
        badge.className = 'badge bg-warning small-status';

        const formData = new FormData();
        formData.append('file', task.file);

        try {
            // Asynchronous XHR to track progress
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `/admin/galleries/${GALLERY_ID}/upload-image`, true);
            xhr.setRequestHeader('X-CSRF-Token', CSRF_TOKEN);

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    bar.style.width = percent + '%';
                    if (percent >= 100) {
                        badge.textContent = 'Processing';
                        badge.className = 'badge bg-info small-status';
                    }
                }
            });

            xhr.addEventListener('readystatechange', () => {
                if (xhr.readyState === XMLHttpRequest.DONE) {
                    if (xhr.status === 200 || xhr.status === 201 || xhr.status === 302) {
                        bar.className = 'progress-bar bg-success';
                        bar.style.width = '100%';
                        badge.textContent = 'Success';
                        badge.className = 'badge bg-success small-status';
                        
                        completedCount++;
                        updateQueueHeader();
                        startNextUpload();
                    } else {
                        bar.className = 'progress-bar bg-danger';
                        bar.style.width = '100%';
                        badge.textContent = 'Error';
                        badge.className = 'badge bg-danger small-status';
                        
                        startNextUpload();
                    }
                }
            });

            xhr.send(formData);

        } catch (err) {
            console.error('Queue upload failure:', err);
            bar.className = 'progress-bar bg-danger';
            badge.textContent = 'Failed';
            badge.className = 'badge bg-danger small-status';
            startNextUpload();
        }
    }

    // -------------------------------------------------------------
    // 5. Multiple Page Selection & Deletion
    // -------------------------------------------------------------
    const deleteSelectedBtn = document.getElementById('deleteSelectedBtn');
    const selectedCountSpan = document.getElementById('selectedCount');

    function updateSelectedState() {
        const selectedCheckboxes = document.querySelectorAll('.page-select-cb:checked');
        const count = selectedCheckboxes.length;
        
        if (count > 0) {
            if (deleteSelectedBtn) deleteSelectedBtn.disabled = false;
            if (selectedCountSpan) selectedCountSpan.textContent = count;
        } else {
            if (deleteSelectedBtn) deleteSelectedBtn.disabled = true;
            if (selectedCountSpan) selectedCountSpan.textContent = '0';
        }
    }

    if (gridEl) {
        // Handle click on card or checkbox
        gridEl.addEventListener('click', (e) => {
            // Ignore if clicking on delete single button
            if (e.target.closest('.delete-btn')) {
                return;
            }

            const card = e.target.closest('.page-card');
            if (!card) return;

            const cb = card.querySelector('.page-select-cb');
            if (!cb) return;

            // If click was not directly on the checkbox, toggle it
            if (!e.target.classList.contains('page-select-cb')) {
                cb.checked = !cb.checked;
            }

            if (cb.checked) {
                card.classList.add('selected');
            } else {
                card.classList.remove('selected');
            }

            updateSelectedState();
        });

        // Delete multiple
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', async () => {
                const selectedCheckboxes = document.querySelectorAll('.page-select-cb:checked');
                if (selectedCheckboxes.length === 0) return;

                const confirmed = await window.showConfirmModal({
                    title: 'Delete Multiple Pages',
                    message: `Are you sure you want to delete ${selectedCheckboxes.length} selected pages? This cannot be undone.`,
                    confirmText: 'Delete All',
                    confirmClass: 'btn-danger'
                });

                if (!confirmed) return;

                deleteSelectedBtn.disabled = true;
                deleteSelectedBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Deleting...';

                let successCount = 0;
                let errorCount = 0;

                const deletePromises = Array.from(selectedCheckboxes).map(cb => {
                    const pageId = cb.value;
                    return fetch(`/admin/pages/${pageId}`, { method: 'DELETE', headers: { 'X-CSRF-Token': CSRF_TOKEN } })
                        .then(res => res.json())
                        .then(data => {
                            if (data.status === 'success') {
                                successCount++;
                                const itemEl = document.getElementById(`page-${pageId}`);
                                if (itemEl) itemEl.remove();
                            } else {
                                errorCount++;
                            }
                        })
                        .catch(() => errorCount++);
                });

                await Promise.allSettled(deletePromises);

                updatePageLabels();
                updateSelectedState();
                
                const items = document.querySelectorAll('#pagesSortableGrid .page-item');
                if (items.length === 0) {
                    const emptyState = document.getElementById('emptyPagesState');
                    if (emptyState) emptyState.classList.remove('d-none');
                }

                if (errorCount > 0) {
                    showGlobalToast(`Deleted ${successCount} pages, but ${errorCount} failed.`, 'warning');
                } else {
                    showGlobalToast(`Successfully deleted ${successCount} pages.`, 'success');
                }

                deleteSelectedBtn.disabled = false;
                deleteSelectedBtn.innerHTML = '<i class="bi bi-trash"></i> Delete Selected (<span id="selectedCount">0</span>)';
            });
        }
    }

    // -------------------------------------------------------------
    // Helper alerts
    // -------------------------------------------------------------
    function showGlobalToast(message, type = 'primary') {
        const toast = document.createElement('div');
        toast.className = `position-fixed bottom-0 end-0 m-3 alert alert-${type} shadow`;
        toast.style.zIndex = '9999';
        toast.innerHTML = `<i class="bi bi-info-circle-fill me-2"></i> ${message}`;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
});
