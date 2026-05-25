// Tabs
const appTabs = document.querySelectorAll('.app-tab');
const appPanels = document.querySelectorAll('.app-panel');

appTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
        const target = tab.dataset.tab;

        appTabs.forEach((item) => item.classList.remove('active'));
        appPanels.forEach((panel) => panel.classList.remove('active'));

        tab.classList.add('active');
        const panel = document.getElementById(`panel-${target}`);
        if (panel) {
            panel.classList.add('active');
        }
    });
});

// Upload staging
const fileInput = document.getElementById('fileInput');
const dropZone = document.getElementById('dropZone');
const stagingArea = document.getElementById('stagingArea');
const stagingList = document.getElementById('stagingList');
const stagingCount = document.getElementById('stagingCount');
const stagingTotal = document.getElementById('stagingTotal');
const uploadBtn = document.getElementById('uploadBtn');
const clearAllBtn = document.getElementById('clearAllBtn');
const actualInput = document.getElementById('actualInput');
const uploadForm = document.getElementById('uploadForm');

let staged = [];

function formatSize(bytes) {
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    if (bytes < 1024 * 1024 * 1024) {
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fileExt(name) {
    const parts = name.split('.');
    return parts.length > 1 ? parts.pop().toUpperCase().slice(0, 4) : 'FILE';
}

function renderStaging() {
    stagingList.innerHTML = '';

    if (!staged.length) {
        stagingArea.style.display = 'none';
        return;
    }

    stagingArea.style.display = 'block';
    stagingCount.textContent = `${staged.length} ${staged.length === 1 ? 'file' : 'files'}`;
    const totalSize = staged.reduce((sum, file) => sum + file.size, 0);
    stagingTotal.textContent = `Total: ${formatSize(totalSize)}`;

    staged.forEach((file, index) => {
        const item = document.createElement('li');
        item.className = 'staging-item';
        item.innerHTML = `
            <div class="si-ext">${fileExt(file.name)}</div>
            <span class="si-name">${file.name}</span>
            <span class="si-size">${formatSize(file.size)}</span>
            <button class="si-remove" type="button" aria-label="Remove file">✕</button>
        `;

        item.querySelector('.si-remove').addEventListener('click', () => {
            staged.splice(index, 1);
            renderStaging();
        });

        stagingList.appendChild(item);
    });
}

function addFiles(files) {
    Array.from(files).forEach((file) => {
        const exists = staged.some((item) => item.name === file.name && item.size === file.size);
        if (!exists) {
            staged.push(file);
        }
    });
    renderStaging();
}

if (fileInput) {
    fileInput.addEventListener('change', (event) => {
        addFiles(event.target.files);
        fileInput.value = '';
    });
}

if (clearAllBtn) {
    clearAllBtn.addEventListener('click', () => {
        staged = [];
        renderStaging();
    });
}

if (uploadBtn) {
    uploadBtn.addEventListener('click', () => {
        if (!staged.length || !actualInput || !uploadForm) {
            return;
        }

        const dataTransfer = new DataTransfer();
        staged.forEach((file) => dataTransfer.items.add(file));
        actualInput.files = dataTransfer.files;
        uploadForm.submit();
    });
}

// Drag and drop
if (dropZone) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => event.preventDefault());
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragging'));
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragging'));
    });

    dropZone.addEventListener('drop', (event) => {
        addFiles(event.dataTransfer.files);
    });
}

// File search and sort
const searchInput = document.getElementById('searchInput');
const sortSelect = document.getElementById('sortSelect');
const fileList = document.getElementById('fileList');

function parseSize(sizeText) {
    const match = String(sizeText).trim().match(/^([\d.]+)\s*(B|KB|MB|GB)$/i);
    if (!match) {
        return 0;
    }

    const value = Number.parseFloat(match[1]);
    const unit = match[2].toUpperCase();
    const multipliers = {
        B: 1,
        KB: 1024,
        MB: 1024 * 1024,
        GB: 1024 * 1024 * 1024,
    };

    return value * (multipliers[unit] || 1);
}

function applyFileFilterSort() {
    if (!fileList) {
        return;
    }

    const q = (searchInput?.value || '').trim().toLowerCase();
    const items = Array.from(fileList.querySelectorAll('.file-item'));

    items.forEach((item) => {
        const name = (item.dataset.name || '').toLowerCase();
        item.style.display = name.includes(q) ? '' : 'none';
    });

    if (!sortSelect || items.length === 0) {
        return;
    }

    const mode = sortSelect.value;
    const sorted = items.slice().sort((a, b) => {
        const nameA = (a.dataset.name || '').toLowerCase();
        const nameB = (b.dataset.name || '').toLowerCase();
        const sizeA = parseSize(a.dataset.size || '0 B');
        const sizeB = parseSize(b.dataset.size || '0 B');
        const timeA = Number.parseFloat(a.dataset.mtime || '0');
        const timeB = Number.parseFloat(b.dataset.mtime || '0');

        switch (mode) {
            case 'Oldest first':
                return timeA - timeB;
            case 'Largest first':
                return sizeB - sizeA;
            case 'Name A–Z':
                return nameA.localeCompare(nameB);
            case 'Newest first':
            default:
                return timeB - timeA;
        }
    });

    sorted.forEach((item) => fileList.appendChild(item));
}

if (searchInput) {
    searchInput.addEventListener('input', applyFileFilterSort);
}

if (sortSelect) {
    sortSelect.addEventListener('change', applyFileFilterSort);
    applyFileFilterSort();
}

// Copy links
function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }

    return new Promise((resolve, reject) => {
        const helper = document.createElement('textarea');
        helper.value = text;
        helper.setAttribute('readonly', '');
        helper.style.position = 'fixed';
        helper.style.left = '-9999px';
        helper.style.top = '0';
        document.body.appendChild(helper);
        helper.select();

        const copied = document.execCommand('copy');
        document.body.removeChild(helper);

        if (copied) {
            resolve();
        } else {
            reject(new Error('copy failed'));
        }
    });
}

document.querySelectorAll('.copy-btn').forEach((button) => {
    button.addEventListener('click', async () => {
        const url = button.dataset.copyUrl || '';
        if (!url) {
            showToast('Could not copy link.');
            return;
        }

        try {
            await copyTextToClipboard(url);
            showToast('Link copied to clipboard.');
        } catch (error) {
            showToast('Could not copy link.');
        }
    });
});

// Toast
function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) {
        return;
    }

    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(window.__toastTimer);
    window.__toastTimer = window.setTimeout(() => {
        toast.classList.remove('show');
    }, 2400);
}

// Lenis smooth scroll
if (typeof Lenis !== 'undefined') {
    const lenis = new Lenis({
        duration: 1.15,
        easing: (t) => 1 - Math.pow(1 - t, 3),
        smoothWheel: true,
        smoothTouch: false,
    });

    function raf(time) {
        lenis.raf(time);
        requestAnimationFrame(raf);
    }

    requestAnimationFrame(raf);
}

// Scroll reveal
const revealTargets = document.querySelectorAll(
    '.hero-badge, .hero-title, .hero-sub, .hero-cta-row, .hero-stats, .hero-visual, .feature-card, .step, .plan-card, .app-shell, .site-footer'
);

revealTargets.forEach((element) => element.classList.add('reveal'));

const revealObserver = new IntersectionObserver(
    (entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                revealObserver.unobserve(entry.target);
            }
        });
    },
    { threshold: 0.16 }
);

revealTargets.forEach((element) => revealObserver.observe(element));

// Mobile nav
const hamburger = document.getElementById('navToggle');
const topnav = document.querySelector('.topnav');

if (hamburger && topnav) {
    hamburger.addEventListener('click', () => {
        topnav.classList.toggle('menu-open');
    });
}
