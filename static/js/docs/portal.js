/**
 * Documentation portal (documentation/2.8 Documentation Page Delivery.md):
 * partial page loads, the sidebar (expanded sections, active page, filter),
 * the "On this page" contents and the PDF export dialog.
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'docsSidebarExpanded';
    // A heading becomes the current section once its top passes this line,
    // which lies below the sticky navbar and the headings' scroll margin.
    var CURRENT_SECTION_OFFSET = 96;
    // The page's own headings (h2, h3) listed in "On this page".
    var TOC_HEADINGS = 'h2[id], h3[id]';
    var TOC_MIN_SECTIONS = 2;

    function normalize(text) {
        return String(text || '').replace(/\s+/g, ' ').trim().toLowerCase();
    }

    function readExpanded() {
        try {
            var keys = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
            return Array.isArray(keys) ? keys : [];
        } catch (e) {
            return [];
        }
    }

    function writeExpanded(keys) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
        } catch (e) {
            // Without storage the sidebar simply forgets its sections.
        }
    }

    function setSectionOpen(section, open) {
        var subitems = section.querySelector('.docs-subitems');
        var toggle = section.querySelector('.docs-toggle');
        if (subitems) subitems.classList.toggle('show', open);
        if (toggle) toggle.setAttribute('aria-expanded', String(open));
    }

    function isSectionOpen(section) {
        var subitems = section.querySelector('.docs-subitems');
        return !!subitems && subitems.classList.contains('show');
    }

    /**
     * Sidebar: remembered sections, the active page and the filter.
     * While the filter has text it decides which pages show; clearing it
     * restores the remembered sections.
     */
    function createSidebar(options) {
        var sidebar = options.sidebar;
        var input = options.input;
        var empty = options.empty;
        var query = '';

        function matches(element) {
            return normalize(element.textContent).indexOf(query) !== -1;
        }

        function render() {
            var expanded = readExpanded();
            var visibleSections = 0;
            sidebar.querySelectorAll('.docs-collection').forEach(function (collection) {
                var visibleInCollection = 0;
                collection.querySelectorAll('.docs-section').forEach(function (section) {
                    var header = section.querySelector('.docs-section-header');
                    var items = Array.prototype.slice.call(section.querySelectorAll('.docs-subitems .docs-nav-link'));
                    var matchingItems = query ? items.filter(matches) : [];
                    var visible = !query || matches(header) || matchingItems.length > 0;
                    // A section found by its own title keeps all its pages, collapsed.
                    items.forEach(function (item) {
                        item.hidden = matchingItems.length > 0 && matchingItems.indexOf(item) === -1;
                    });
                    section.hidden = !visible;
                    setSectionOpen(section, query
                        ? matchingItems.length > 0
                        : expanded.indexOf(section.dataset.section) !== -1);
                    if (visible) visibleInCollection += 1;
                });
                collection.hidden = visibleInCollection === 0;
                visibleSections += visibleInCollection;
            });
            // An audience heading goes with the collections below it.
            sidebar.querySelectorAll('.docs-audience-heading').forEach(function (heading) {
                var audience = heading.dataset.audience;
                heading.hidden = !Array.prototype.some.call(
                    sidebar.querySelectorAll('.docs-collection[data-audience]'),
                    function (collection) { return collection.dataset.audience === audience && !collection.hidden; }
                );
            });
            if (empty) empty.hidden = visibleSections > 0;
        }

        function remember(key, open) {
            var expanded = readExpanded().filter(function (value) { return value !== key; });
            if (open) expanded.push(key);
            writeExpanded(expanded);
        }

        function markActive(slug, sectionKey) {
            sidebar.querySelectorAll('.docs-nav-link').forEach(function (link) {
                var active = !!slug && link.dataset.docSlug === slug;
                link.classList.toggle('active', active);
                if (active) {
                    link.setAttribute('aria-current', 'page');
                } else {
                    link.removeAttribute('aria-current');
                }
            });
            sidebar.querySelectorAll('.docs-section').forEach(function (section) {
                var header = section.querySelector('.docs-section-header');
                var rootLink = header.querySelector('.docs-nav-link');
                header.classList.toggle('is-current', !!sectionKey && section.dataset.section === sectionKey);
                header.classList.toggle('active', !!rootLink && rootLink.classList.contains('active'));
            });
            if (sectionKey) remember(sectionKey, true);
            render();
        }

        function filter(text) {
            query = normalize(text);
            render();
        }

        function onClick(event) {
            var toggle = event.target.closest('.docs-toggle');
            if (toggle) {
                event.preventDefault();
                var section = toggle.closest('.docs-section');
                var open = !isSectionOpen(section);
                setSectionOpen(section, open);
                // Opening a section while filtering is not remembered.
                if (!query) remember(section.dataset.section, open);
                return;
            }
            var rootLink = event.target.closest('[data-section-link]');
            if (rootLink && !query) remember(rootLink.dataset.sectionLink, true);
        }

        function onInput() {
            filter(input.value);
        }

        function onInputKeydown(event) {
            if (event.key === 'Escape' && input.value) {
                event.preventDefault();
                input.value = '';
                filter('');
            }
        }

        function onDocumentKeydown(event) {
            if (event.key !== '/' || event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
            var target = event.target;
            if (target && (target.isContentEditable
                || (target.closest && target.closest('input, textarea, select')))) return;
            event.preventDefault();
            input.focus();
        }

        sidebar.addEventListener('click', onClick);
        if (input) {
            input.addEventListener('input', onInput);
            input.addEventListener('keydown', onInputKeydown);
            document.addEventListener('keydown', onDocumentKeydown);
        }

        return {
            markActive: markActive,
            filter: filter,
            destroy: function () {
                sidebar.removeEventListener('click', onClick);
                if (input) {
                    input.removeEventListener('input', onInput);
                    input.removeEventListener('keydown', onInputKeydown);
                    document.removeEventListener('keydown', onDocumentKeydown);
                }
            }
        };
    }

    /**
     * "On this page": the article's h2 and h3 headings, shown when there are
     * at least two, with the section being read marked as current. The same
     * list fills every container (beside the article on wide screens, above
     * it on narrow ones); CSS shows one of them.
     */
    function createToc(options) {
        var content = options.content;
        var containers = options.containers;
        var headings = [];
        var frame = null;

        function lists() {
            return containers.map(function (container) {
                return container.querySelector('.docs-toc-list');
            });
        }

        function entry(heading) {
            var item = document.createElement('li');
            item.className = 'docs-toc-item docs-toc-item--' + heading.tagName.toLowerCase();
            var link = document.createElement('a');
            link.href = '#' + heading.id;
            link.textContent = heading.textContent.replace(/\s+/g, ' ').trim();
            item.appendChild(link);
            return item;
        }

        function currentIndex() {
            if (!headings.length) return -1;
            if (SharedUtils.isScrolledToBottom()) return headings.length - 1;
            var index = -1;
            for (var i = 0; i < headings.length; i += 1) {
                if (headings[i].getBoundingClientRect().top > CURRENT_SECTION_OFFSET) break;
                index = i;
            }
            return index;
        }

        function update() {
            frame = null;
            var index = currentIndex();
            lists().forEach(function (list) {
                Array.prototype.forEach.call(list.querySelectorAll('a'), function (link, i) {
                    var current = i === index;
                    link.classList.toggle('active', current);
                    if (current) {
                        link.setAttribute('aria-current', 'location');
                    } else {
                        link.removeAttribute('aria-current');
                    }
                });
            });
        }

        function build() {
            headings = Array.prototype.filter.call(content.querySelectorAll(TOC_HEADINGS), function (heading) {
                return normalize(heading.textContent) !== '';
            });
            var shown = headings.length >= TOC_MIN_SECTIONS;
            lists().forEach(function (list) {
                list.replaceChildren.apply(list, shown ? headings.map(entry) : []);
            });
            containers.forEach(function (container) {
                container.hidden = !shown;
            });
            update();
        }

        function schedule() {
            if (frame === null) frame = window.requestAnimationFrame(update);
        }

        function onClick(event) {
            if (!event.target.closest('a')) return;
            // The list above the article closes once a section is chosen.
            containers.forEach(function (container) {
                if (container.tagName === 'DETAILS' && container.contains(event.target)) container.open = false;
            });
        }

        // Capture: scroll events do not bubble, and the page scrolls in <body>.
        document.addEventListener('scroll', schedule, { capture: true, passive: true });
        window.addEventListener('resize', schedule);
        containers.forEach(function (container) {
            container.addEventListener('click', onClick);
        });

        return {
            build: build,
            update: update,
            destroy: function () {
                document.removeEventListener('scroll', schedule, { capture: true, passive: true });
                window.removeEventListener('resize', schedule);
                containers.forEach(function (container) {
                    container.removeEventListener('click', onClick);
                });
                if (frame !== null) window.cancelAnimationFrame(frame);
                frame = null;
            }
        };
    }

    function createNavButton(id, page, direction, docsRoot) {
        if (!page || !page.slug) return null;

        var anchor = document.createElement('a');
        anchor.id = id;
        anchor.href = docsRoot + '/' + page.slug;
        anchor.className = 'docs-nav-btn';

        var text = document.createElement('span');
        text.className = direction === 'prev' ? 'text-start' : 'text-end';
        var label = document.createElement('span');
        label.className = 'nav-label';
        label.textContent = direction === 'prev' ? 'Previous' : 'Next';
        var title = document.createElement('span');
        title.className = 'nav-title';
        title.textContent = page.title || '';
        text.appendChild(label);
        text.appendChild(title);

        var icon = document.createElement('i');
        icon.className = direction === 'prev' ? 'fas fa-arrow-left' : 'fas fa-arrow-right';
        icon.setAttribute('aria-hidden', 'true');

        if (direction === 'prev') {
            anchor.appendChild(icon);
            anchor.appendChild(text);
        } else {
            anchor.appendChild(text);
            anchor.appendChild(icon);
        }
        return anchor;
    }

    function renderNav(nav, prevPage, nextPage, docsRoot) {
        nav.replaceChildren();
        nav.appendChild(createNavButton('docs-prev', prevPage, 'prev', docsRoot) || document.createElement('span'));
        var next = createNavButton('docs-next', nextPage, 'next', docsRoot);
        if (next) nav.appendChild(next);
    }

    // Draws the article's diagrams; the promise settles once they are drawn.
    function renderMermaid(content) {
        var nodes = content.querySelectorAll('.mermaid');
        if (!nodes.length || !window.mermaid || typeof window.mermaid.run !== 'function') return Promise.resolve();
        return Promise.resolve()
            .then(function () { return window.mermaid.run({ nodes: nodes }); })
            .catch(function (err) { console.warn('Mermaid render failed:', err); });
    }

    function initMobileSidebar(sidebar, pdfModal) {
        var toggle = document.getElementById('mobileSidebarToggle');
        var closeBtn = document.getElementById('closeMobileSidebar');
        var backdrop = document.getElementById('docsSidebarBackdrop');

        function show(open) {
            sidebar.classList.toggle('mobile-expanded', open);
            if (backdrop) backdrop.classList.toggle('active', open);
            document.body.style.overflow = open ? 'hidden' : '';
        }

        if (toggle) toggle.addEventListener('click', function () { show(true); });
        if (closeBtn) closeBtn.addEventListener('click', function () { show(false); });
        if (backdrop) backdrop.addEventListener('click', function () { show(false); });

        // The drawer would cover the PDF dialog opened from it.
        if (pdfModal) pdfModal.addEventListener('show.bs.modal', function () { show(false); });

        // Close the drawer once a page is chosen; the delay lets the fetch start.
        sidebar.addEventListener('click', function (event) {
            if (window.innerWidth >= 768 || !event.target.closest('a')) return;
            setTimeout(function () { show(false); }, 150);
        });
    }

    /**
     * PDF export dialog: this page, the whole documentation or chosen
     * sections. The button that opens it picks the choice (data-pdf-scope);
     * the page header's button describes the page being read.
     */
    function createPdfDialog(options) {
        var modal = options.modal;
        var form = modal.querySelector('form');
        var sectionList = modal.querySelector('[data-pdf-sections]');
        var pageLabel = modal.querySelector('[data-pdf-page-label]');
        var error = modal.querySelector('[data-pdf-error]');
        var page = null;

        function sectionBoxes() {
            return Array.prototype.slice.call(form.querySelectorAll('input[name="section"]'));
        }

        function scopeInput(value) {
            return form.querySelector('input[name="scope"][value="' + value + '"]');
        }

        function scope() {
            var checked = form.querySelector('input[name="scope"]:checked');
            return checked ? checked.value : 'all';
        }

        function render() {
            sectionList.hidden = scope() !== 'sections';
            error.hidden = true;
        }

        function open(requested) {
            var trigger = document.querySelector(options.pageTrigger);
            page = trigger && trigger.dataset.pageSlug ? {
                slug: trigger.dataset.pageSlug,
                section: trigger.dataset.pageSection,
                label: trigger.dataset.pageLabel
            } : null;
            scopeInput('page').disabled = !page;
            pageLabel.textContent = page ? page.label : '';
            var value = requested === 'sections' || (requested === 'page' && page) ? requested : 'all';
            scopeInput(value).checked = true;
            // Chosen sections start from the page being read.
            sectionBoxes().forEach(function (box) {
                box.checked = !!page && box.dataset.section === page.section;
            });
            render();
        }

        /** The export request for the current choice, or null after showing why not. */
        function selection() {
            var value = scope();
            if (value === 'page' && page) {
                return { included_pages: [page.slug], include_cover: false, selected_only: true };
            }
            if (value === 'sections') {
                var boxes = sectionBoxes();
                var chosen = boxes.filter(function (box) { return box.checked; });
                if (!chosen.length) {
                    error.hidden = false;
                    return null;
                }
                if (chosen.length < boxes.length) {
                    return {
                        included_sections: chosen.map(function (box) { return box.value; }),
                        include_cover: false,
                        selected_only: true
                    };
                }
            }
            // Every section is the whole documentation, which is cached.
            return { included_sections: null, include_cover: true, selected_only: false };
        }

        function onShow(event) {
            var trigger = event.relatedTarget;
            open(trigger && trigger.dataset ? trigger.dataset.pdfScope : 'all');
        }

        function onSubmit(event) {
            event.preventDefault();
            var params = selection();
            if (params) options.onSubmit(params);
        }

        modal.addEventListener('show.bs.modal', onShow);
        form.addEventListener('change', render);
        form.addEventListener('submit', onSubmit);

        return {
            open: open,
            selection: selection,
            destroy: function () {
                modal.removeEventListener('show.bs.modal', onShow);
                form.removeEventListener('change', render);
                form.removeEventListener('submit', onSubmit);
            }
        };
    }

    function startPdfExport(modal, params) {
        if (window.bootstrap && window.bootstrap.Modal) {
            (window.bootstrap.Modal.getInstance(modal) || new window.bootstrap.Modal(modal)).hide();
        }
        window.ExportProgress.open('Generating Documentation PDF');
        window.ExportProgress.start({
            generateUrl: '/api/docs/generate_pdf_async',
            params: params
        });
    }

    function init(root) {
        var docsRoot = root.dataset.docsRoot;
        var content = document.getElementById('docs-content-html');
        var header = document.getElementById('docs-page-header');
        var nav = document.getElementById('docs-nav');
        var sidebarEl = document.getElementById('docsSidebar');
        var sidebar = createSidebar({
            sidebar: sidebarEl,
            input: document.getElementById('docsSidebarFilter'),
            empty: document.getElementById('docsFilterEmpty')
        });
        var toc = createToc({
            content: content,
            containers: ['docsTocRail', 'docsTocInline']
                .map(function (id) { return document.getElementById(id); })
                .filter(Boolean)
        });

        function isRoutableDocsPath(pathname) {
            if (pathname !== docsRoot && pathname.indexOf(docsRoot + '/') !== 0) return false;
            return pathname.indexOf(docsRoot + '/assets/') !== 0 && pathname.indexOf(docsRoot + '/data/') !== 0;
        }

        function scrollToTop() {
            window.scrollTo({ top: 0, behavior: 'auto' });
            document.body.scrollTop = 0;
        }

        function sectionOf(hash) {
            return hash ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
        }

        // A drawn diagram is hundreds of pixels taller than its source, so the
        // section named in the address is scrolled to once the diagrams are drawn.
        function renderDiagramsThenScrollTo(section, behavior) {
            renderMermaid(content).then(function () {
                if (section) section.scrollIntoView({ behavior: behavior, block: 'start' });
            });
        }

        function load(url, pushState) {
            return SharedUtils.fetchJson(url.pathname + url.search, null, { headers: { 'X-Docs-Partial': '1' } })
                .then(function (payload) {
                    if (!payload || typeof payload.content_html !== 'string') {
                        throw new Error('Invalid documentation payload');
                    }
                    content.innerHTML = payload.content_html;
                    if (header && typeof payload.header_html === 'string') header.innerHTML = payload.header_html;
                    sidebar.markActive(payload.active_slug || '', payload.active_section || '');
                    if (nav) renderNav(nav, payload.prev_page, payload.next_page, docsRoot);
                    toc.build();
                    if (payload.title) document.title = payload.title + ' | OSM & ATLAS Documentation';

                    var canonicalUrl = payload.canonical_url || (url.pathname + url.search);
                    var canonicalLink = document.querySelector('link[rel="canonical"]');
                    if (canonicalLink) canonicalLink.href = new URL(canonicalUrl, window.location.origin).href;
                    if (url.hash) canonicalUrl += url.hash;
                    if (pushState) history.pushState({ docs: true }, '', canonicalUrl);

                    var target = sectionOf(url.hash);
                    if (!target) scrollToTop();
                    renderDiagramsThenScrollTo(target, 'smooth');
                });
        }

        sidebar.markActive(root.dataset.activeSlug || '', root.dataset.activeSection || '');
        toc.build();
        renderDiagramsThenScrollTo(sectionOf(window.location.hash), 'auto');

        if (!history.state || !history.state.docs) {
            history.replaceState({ docs: true }, '', window.location.href);
        }

        document.addEventListener('click', function (event) {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
                return;
            }
            var link = event.target.closest('a[href]');
            if (!link || (link.target && link.target !== '_self')) return;

            var url;
            try {
                url = new URL(link.href, window.location.href);
            } catch (_) {
                return;
            }
            if (url.origin !== window.location.origin || !isRoutableDocsPath(url.pathname)) return;
            // Keep same-page hash navigation native for heading jumps.
            if (url.pathname === window.location.pathname && url.hash) return;

            event.preventDefault();
            load(url, true).catch(function () {
                window.location.href = url.pathname + url.search + url.hash;
            });
        });

        window.addEventListener('popstate', function () {
            var url = new URL(window.location.href);
            if (!isRoutableDocsPath(url.pathname)) return;
            load(url, false).catch(function () {
                window.location.reload();
            });
        });

        var pdfModal = document.getElementById('docsPdfModal');
        initMobileSidebar(sidebarEl, pdfModal);
        if (pdfModal) {
            createPdfDialog({
                modal: pdfModal,
                pageTrigger: '#docs-page-header [data-pdf-scope="page"]',
                onSubmit: function (params) { startPdfExport(pdfModal, params); }
            });
        }
    }

    window.DocsPage = {
        createSidebar: createSidebar,
        createToc: createToc,
        createPdfDialog: createPdfDialog
    };

    function start() {
        var root = document.getElementById('docsPage');
        if (root) init(root);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
