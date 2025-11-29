const SUPPORTED_LANGUAGES = ['en', 'ru', 'es', 'az', 'tr'];
const DEFAULT_LANGUAGE = 'en';
const translations = {};
const localeLoadPromises = {};
let currentLanguage = 'ru';

function normalizeLanguage(lang) {
    if (lang && SUPPORTED_LANGUAGES.includes(lang)) {
        return lang;
    }
    return DEFAULT_LANGUAGE;
}

async function loadLocale(lang) {
    const normalized = normalizeLanguage(lang);
    if (translations[normalized]) {
        return translations[normalized];
    }
    if (!localeLoadPromises[normalized]) {
        localeLoadPromises[normalized] = fetch(`/static/i18n/${normalized}.json`)
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Failed to load locale ${normalized}`);
                }
                return response.json();
            })
            .then((data) => {
                translations[normalized] = data;
                return data;
            })
            .catch((error) => {
                console.error(`Ошибка загрузки перевода для ${normalized}:`, error);
                throw error;
            })
            .finally(() => {
                delete localeLoadPromises[normalized];
            });
    }
    return localeLoadPromises[normalized];
}

async function ensureLocale(lang) {
    const normalized = normalizeLanguage(lang);
    try {
        return await loadLocale(normalized);
    } catch (error) {
        if (normalized !== DEFAULT_LANGUAGE) {
            return ensureLocale(DEFAULT_LANGUAGE);
        }
        return translations[DEFAULT_LANGUAGE] || {};
    }
}


async function applyTranslations(lang) {
    const normalized = normalizeLanguage(lang);
    await ensureLocale(normalized);
    if (normalized !== DEFAULT_LANGUAGE && !translations[DEFAULT_LANGUAGE]) {
        await ensureLocale(DEFAULT_LANGUAGE);
    }

    currentLanguage = normalized;
    try {
        localStorage.setItem('preferredLanguage', normalized);
    } catch (_) {
        // Ignore storage errors (e.g., private mode)
    }
    document.documentElement.lang = normalized;
    document.documentElement.dir = normalized === 'ar' ? 'rtl' : 'ltr';

    document.title = getTranslation('pageTitle', normalized);

    const metaDescElement = document.querySelector('meta[data-translate-meta-description]');
    if (metaDescElement) {
        metaDescElement.content = getTranslation('metaDescriptionContent', normalized);
    }

    document.querySelectorAll('[data-translate-key]').forEach(element => {
        const key = element.getAttribute('data-translate-key');
        if (key === 'footerCopyrightText') {
            const yearSpan = `<span id="year">${new Date().getFullYear()}</span>`;
            element.innerHTML = getTranslation(key, normalized).replace('<span id="year"></span>', yearSpan);
        } else {
            element.innerHTML = getTranslation(key, normalized);
        }
    });

    document.querySelectorAll('[data-translate-placeholder]').forEach(element => {
        const key = element.getAttribute('data-translate-placeholder');
        element.placeholder = getTranslation(key, normalized);
    });

    const langSelector = document.getElementById('languageSelector');
    if (langSelector) {
        langSelector.value = normalized;
        langSelector.setAttribute('aria-label', getTranslation('languageLabel', normalized));
    }

    const backgroundSelectorEl = document.getElementById('backgroundSelector');
    if (backgroundSelectorEl) {
        backgroundSelectorEl.setAttribute('aria-label', getTranslation('backgroundLabel', normalized));
    }

    window.reactbitsCurrentLanguage = normalized;
    window.dispatchEvent(new CustomEvent('reactbits-language-change', { detail: normalized }));
    // update route-aware converter button label if present
    try { updateConverterButtonForRoute(); } catch (e) {}
}

function getTranslation(key, lang = currentLanguage, replacements = {}) {
    const normalized = normalizeLanguage(lang);
    const activeBundle = translations[normalized] || {};
    const fallbackBundle = translations[DEFAULT_LANGUAGE] || {};
    let text = activeBundle[key] || fallbackBundle[key] || key;
    for (const placeholder in replacements) {
        text = text.replace(`{${placeholder}}`, replacements[placeholder]);
    }
    return text;
}

document.addEventListener('DOMContentLoaded', async () => {
            const yearSpan = document.getElementById('year');
            if (yearSpan) {
                yearSpan.textContent = new Date().getFullYear();
            }

            const downloadForm = document.getElementById('downloadForm');
            const statusArea = document.getElementById('statusArea');
            const telegramLinkContainer = document.getElementById('telegramLinkContainer');
            const youtubeUrlInput = document.getElementById('youtube_url');
            const formatChoiceSelect = document.getElementById('format_choice');
            const languageSelector = document.getElementById('languageSelector');

            const infoButton = document.getElementById('infoButton');
            const infoSectionOverlay = document.getElementById('infoSectionOverlay');
            const closeInfoButton = document.getElementById('closeInfoButton');

            const copyrightButton = document.getElementById('copyrightButton');
            const copyrightSectionOverlay = document.getElementById('copyrightSectionOverlay');
            const closeCopyrightButton = document.getElementById('closeCopyrightButton');
            const shareButton = document.getElementById('shareButton');
            const shareSectionOverlay = document.getElementById('shareSectionOverlay');
            const closeShareButton = document.getElementById('closeShareButton');
            const nativeShareButton = document.getElementById('nativeShareButton');

            const updatesButton = document.getElementById('updatesButton');
            const githubButton = document.getElementById('githubButton');
            const converterButton = document.getElementById('converterButton');
            const backgroundSelector = document.getElementById('backgroundSelector');
            const backgroundModes = ['night', 'faulty-terminal', 'dot-grid', 'aurora', 'dither'];
            const navContainer = document.querySelector('.top-nav-container');
            const navToggleButton = document.getElementById('navToggleButton');

            if (navContainer && navToggleButton) {
                let navCollapsed = window.innerWidth <= 768;
                const setNavCollapsed = (collapsed) => {
                    navCollapsed = collapsed;
                    navContainer.classList.toggle('nav-collapsed', collapsed);
                    navToggleButton.setAttribute('aria-expanded', (!collapsed).toString());
                    navToggleButton.setAttribute('aria-label', collapsed ? 'Expand navigation' : 'Collapse navigation');
                };
                navToggleButton.addEventListener('click', () => setNavCollapsed(!navCollapsed));
                window.addEventListener('resize', () => {
                    if (window.innerWidth <= 768 && !navCollapsed) {
                        setNavCollapsed(true);
                    }
                });
                setNavCollapsed(navCollapsed);
            }

            function applyBackgroundChoice(mode) {
                const normalized = backgroundModes.includes(mode) ? mode : 'night';
                backgroundModes.forEach(bg => document.body.classList.remove(`bg-mode-${bg}`));
                document.body.classList.add(`bg-mode-${normalized}`);
                if (backgroundSelector) {
                    backgroundSelector.value = normalized;
                }
                try {
                    localStorage.setItem('preferredBackground', normalized);
                } catch (_) {
                    // Ignore storage errors
                }
            }

            let storedBackground = 'night';
            try {
                const savedBackground = localStorage.getItem('preferredBackground');
                if (savedBackground) {
                    storedBackground = savedBackground;
                }
            } catch (_) {
                storedBackground = 'night';
            }
            applyBackgroundChoice(storedBackground);

            if (backgroundSelector) {
                backgroundSelector.addEventListener('change', (event) => {
                    applyBackgroundChoice(event.target.value);
                });
            }

            function setupOverlay(button, overlay, closeButton) {
                if (button && overlay && closeButton) {
                    button.addEventListener('click', () => {
                        overlay.classList.add('visible');
                        document.body.classList.add('overflow-hidden');
                    });
                    closeButton.addEventListener('click', () => {
                        overlay.classList.remove('visible');
                        document.body.classList.remove('overflow-hidden');
                    });
                    overlay.addEventListener('click', (event) => {
                        if (event.target === overlay) {
                            overlay.classList.remove('visible');
                            document.body.classList.remove('overflow-hidden');
                        }
                    });
                } else {
                    console.error(`One or more elements for ${overlay ? overlay.id : 'an overlay'} functionality are missing:`,
                        {button, overlay, closeButton });
                }
            }

            setupOverlay(infoButton, infoSectionOverlay, closeInfoButton);
            setupOverlay(copyrightButton, copyrightSectionOverlay, closeCopyrightButton);
            setupOverlay(shareButton, shareSectionOverlay, closeShareButton);

            const shareUrl = window.location.origin || window.location.href;
            if (nativeShareButton) {
                nativeShareButton.addEventListener('click', async () => {
                    const shareData = {
                        title: getTranslation('shareNativeTitle'),
                        text: getTranslation('shareNativeText'),
                        url: shareUrl
                    };
                    try {
                        if (navigator.share) {
                            await navigator.share(shareData);
                        } else if (navigator.clipboard && navigator.clipboard.writeText) {
                            await navigator.clipboard.writeText(shareData.url);
                            alert(getTranslation('shareClipboardFallback'));
                        } else {
                            alert(getTranslation('shareUnsupported'));
                        }
                    } catch (error) {
                        console.error('Native share failed:', error);
                        alert(getTranslation('shareFailed'));
                    }
                });
            }

            if (updatesButton) {
                updatesButton.addEventListener('click', () => {
                    window.location.href = '/miniblog';
                });
            }

            if (githubButton) {
                githubButton.addEventListener('click', () => {
                    window.open('https://github.com/thebitsamuraii23/MusicJacker-Site', '_blank');
                });
            }

            function updateConverterButtonForRoute() {
                if (!converterButton) return;
                const onConverter = window.location.pathname === '/converter' || window.location.pathname.startsWith('/converter');
                if (onConverter) {
                    converterButton.setAttribute('data-translate-key', 'navMusicJackerButton');
                    converterButton.onclick = () => { window.location.href = '/'; };
                    try { converterButton.innerHTML = getTranslation('navMusicJackerButton'); } catch (e) {}
                } else {
                    converterButton.setAttribute('data-translate-key', 'navConverterButton');
                    converterButton.onclick = () => { window.location.href = '/converter'; };
                    try { converterButton.innerHTML = getTranslation('navConverterButton'); } catch (e) {}
                }
            }
            if (converterButton) updateConverterButtonForRoute();


            let storedPreferredLanguage = null;
            try {
                storedPreferredLanguage = localStorage.getItem('preferredLanguage');
            } catch (_) {
                storedPreferredLanguage = null;
            }
            const browserLang = (navigator.language || DEFAULT_LANGUAGE).split('-')[0];
            const initialLang = (() => {
                if (storedPreferredLanguage && SUPPORTED_LANGUAGES.includes(storedPreferredLanguage)) {
                    return storedPreferredLanguage;
                }
                if (SUPPORTED_LANGUAGES.includes(browserLang)) {
                    return browserLang;
                }
                return currentLanguage || DEFAULT_LANGUAGE;
            })();

            if (languageSelector) {
                languageSelector.addEventListener('change', (event) => {
                    applyTranslations(event.target.value).catch((error) => {
                        console.error('Не удалось переключить язык:', error);
                    });
                });
                languageSelector.value = normalizeLanguage(initialLang);
            }

            await applyTranslations(initialLang);

            if (downloadForm) {
                downloadForm.addEventListener('submit', async function(event) {
                    event.preventDefault();
                    const url = youtubeUrlInput.value.trim();
                    const format = formatChoiceSelect.value;

                    if (telegramLinkContainer) telegramLinkContainer.classList.add('hidden');

                    if (!url) {
                        statusArea.innerHTML = `<p class="text-red-400 p-3 bg-red-900/30 rounded-md status-message-item">${getTranslation('statusErrorUrl')}</p>`;
                        return;
                    }
                     try {
                        new URL(url);
                    } catch (_) {
                        statusArea.innerHTML = `<p class="text-red-400 p-3 bg-red-900/30 rounded-md status-message-item">${getTranslation('statusErrorUrl')}</p>`;
                        return;
                    }

                    statusArea.innerHTML = `
                        <div class="flex flex-col justify-center items-center space-y-2 text-sky-400 p-3 status-message-item">
                            <div class="loader ease-linear rounded-full border-4 border-t-4 border-slate-600 h-8 w-8 mb-2"></div>
                            <span>${getTranslation('statusProcessing')}</span>
                        </div>`;

                    const submitButtonEl = document.getElementById('submitButton');
                    if(submitButtonEl) {
                        submitButtonEl.disabled = true;
                        submitButtonEl.classList.add('opacity-50', 'cursor-not-allowed');
                        submitButtonEl.classList.remove('hover:bg-sky-400', 'submit-button:hover');
                    }

                    try {
                        const response = await fetch('/api/download_audio', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ url: url, format: format }),
                        });

                        const contentType = response.headers.get("content-type");
                        if (!contentType || !contentType.includes("application/json")) {
                            const errorText = await response.text();
                            throw new Error(`Server returned an unexpected response: ${response.status} ${response.statusText}. ${errorText.substring(0,100)}`);
                        }
                        const data = await response.json();

                        if (response.ok && data.status === 'success' && data.files && data.files.length > 0) {
                            let filesListHtml = data.files.map((fileInfo, index) => `
                                <li id="file-item-${index}" class="bg-slate-700/60 p-3.5 rounded-lg shadow status-message-item flex justify-between items-center gap-3" style="animation-delay: ${index * 0.12}s">
                                    <div class="flex flex-col min-w-0">
                                        <span class="text-slate-300 block truncate" title="${fileInfo.title || ''}">${fileInfo.title || 'Untitled'} (${fileInfo.filename ? fileInfo.filename.split('.').pop().toUpperCase() : format.toUpperCase()})</span>
                                        ${fileInfo.artist ? `<span class="text-slate-400 text-xs truncate" title="${fileInfo.artist}">${fileInfo.artist}</span>` : ''}
                                    </div>
                                    <span id="file-status-${index}" class="file-download-status">${getTranslation('fileStatusPending')}</span>
                                </li>
                            `).join('');

                            statusArea.innerHTML = `
                                <div class="status-message-item">
                                    <p class="text-green-400 mb-3 text-lg">${getTranslation('statusSuccessHeader')}</p>
                                    <ul id="downloadQueueList" class="space-y-2.5 text-left max-h-60 overflow-y-auto pr-2">${filesListHtml}</ul>
                                    <p class="text-xs text-slate-500 mt-4">${getTranslation('statusPostDownloadHint')}</p>
                                </div>
                            `;
                            if (telegramLinkContainer) telegramLinkContainer.classList.remove('hidden');

                            (async () => {
                                for (let i = 0; i < data.files.length; i++) {
                                    const fileInfo = data.files[i];
                                    const fileStatusSpan = document.getElementById(`file-status-${i}`);

                                    if (fileStatusSpan) {
                                        fileStatusSpan.textContent = getTranslation('fileStatusDownloading');
                                        fileStatusSpan.className = 'file-download-status downloading';
                                    }

                                    const link = document.createElement('a');
                                    link.href = fileInfo.download_url;
                                    link.download = fileInfo.filename;
                                    document.body.appendChild(link);
                                    link.click();

                                    await new Promise(resolve => setTimeout(resolve, 5000));
                                    document.body.removeChild(link);

                                    if (fileStatusSpan) {
                                        fileStatusSpan.textContent = getTranslation('fileStatusStarted');
                                        fileStatusSpan.className = 'file-download-status completed';
                                    }

                                    if (i < data.files.length - 1) {
                                        await new Promise(resolve => setTimeout(resolve, 750));
                                    }
                                }
                            })();

                        } else {
                            if (data.message && (data.message.includes("Контент длиннее 10 минут") || data.message.includes("Плейлист содержит контент длиннее 10 минут"))) {
                                statusArea.innerHTML = `<p class="text-red-400 p-3 bg-red-900/30 rounded-md status-message-item">${data.message}</p>`;
                            } else {
                                statusArea.innerHTML = `<p class="text-red-400 p-3 bg-red-900/30 rounded-md status-message-item">${getTranslation('statusErrorGeneric', currentLanguage, {MESSAGE: (data.message || 'Could not download file.')})}</p>`;
                            }
                        }
                    } catch (error) {
                        console.error('Fetch error:', error);
                        statusArea.innerHTML = `<p class="text-red-400 p-3 bg-red-900/30 rounded-md status-message-item">${getTranslation('statusNetworkError')} (${error.message})}</p>`;
                    } finally {
                        if(submitButtonEl) {
                            submitButtonEl.disabled = false;
                            submitButtonEl.classList.remove('opacity-50', 'cursor-not-allowed');
                            submitButtonEl.classList.add('hover:bg-sky-400');
                        }
                    }
                });
            } else {
                console.error("Download form not found!");
            }

            console.log("Initial setup complete. Downloader should be visible.");
        });
