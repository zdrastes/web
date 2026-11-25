(function () {
    'use strict';

    if (!location.protocol.startsWith('http')) return;

    const q = (selector, root) => (root || document).querySelector(selector);
    const dashboard = window.L2Dashboard;
    const login = q('#ld-login');
    const settingsButton = q('#ld-settings');
    const refreshButton = q('#ld-refresh');
    const logoutButton = q('#ld-logout');
    const downloadButton = q('#ld-download');
    const userChip = q('#ld-user');
    const syncStatus = q('#ld-sync-status');
    const settingsPanel = q('#ld-settings-panel');
    const groupsHost = q('#ld-groups');
    const poolHost = q('#ld-unassigned');
    const poolBadge = q('#ld-unassigned-badge');
    const settingsMessage = q('#ld-settings-msg');
    const sprintsHost = q('#ld-sprints');
    const notesHost = q('#ld-labels-list');
    const hiddenNotesHost = q('#ld-labels-hidden');
    const notesSearch = q('#ld-labels-search');
    const usersHost = q('#ld-users-list');
    const userCardHost = q('#ld-user-card');
    const addUserButton = q('#ld-add-user');
    const productsNav = q('#ld-products-nav');
    const groupsProductsNav = q('#ld-groups-products-nav');
    const labelsProductsNav = q('#ld-labels-products');
    const productForm = q('#ld-product-form');
    const productNameInput = q('#ld-product-name');
    const productNamespaceInput = q('#ld-product-namespace');
    const productCodeInput = q('#ld-product-code');
    const productSaveButton = q('#ld-product-save');
    const productCancelButton = q('#ld-product-cancel');
    const productDeleteButton = q('#ld-product-delete');

    const state = { me: null, reportRange: '', groups: [], trackerLabels: [], sprints: [], labelNotes: {}, notes: {}, noteItems: [], users: [], userEditing: null, products: [], selectedProduct: null, labelsProduct: null, trackerLabelsByProduct: {}, trackerLabelGroupsByProduct: {}, hiddenLabelsByProduct: {}, productEditing: null };
    try { state.reportRange = sessionStorage.getItem('l2-report-range') || ''; } catch {}
    const settingsPanes = { products: q('#ld-pane-products'), groups: q('#ld-pane-groups'), sprints: q('#ld-pane-sprints'), labels: q('#ld-pane-labels'), users: q('#ld-pane-users') };
    const periodDepth = q('#ld-period-depth');
    const dateFromInput = q('#ld-date-from');
    const dateToInput = q('#ld-date-to');
    let uidCounter = 0;
    const nextUid = () => 'g' + (++uidCounter);
    const importMessage = q('#ld-import-message');

    function reportData(text, isError) {
        if (!importMessage) return;
        importMessage.hidden = false;
        importMessage.textContent = text;
        importMessage.dataset.error = isError ? 'true' : 'false';
    }

    function formatDate(iso) {
        try {
            return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch {
            return '';
        }
    }

    async function api(url, options) {
        const response = await fetch(url, options);
        if (response.status === 401) { showLogin(); throw Error('unauthorized'); }
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw Error(body.detail || ('HTTP ' + response.status));
        return body;
    }

    function showLogin() {
        state.me = null;
        login.hidden = false;
        userChip.hidden = true;
        logoutButton.hidden = true;
        settingsButton.hidden = true;
        refreshButton.hidden = true;
        downloadButton.hidden = true;
    }

    function showUser(me) {
        state.me = me;
        const perms = me.permissions || [];
        login.hidden = true;
        userChip.hidden = false;
        userChip.textContent = me.display_name || me.username;
        logoutButton.hidden = false;
        // «period» даёт только панель периода в шапке — сама кнопка настроек без вкладок пуста.
        settingsButton.hidden = !['settings', 'sprints', 'users'].some(func => perms.includes(func));
        refreshButton.hidden = !perms.includes('sync');
        downloadButton.hidden = !perms.includes('dashboard');
        periodDepth.hidden = !perms.includes('period');
        applyReportRangeToInputs();
    }

    function applyReportRangeToInputs() {
        const [from, to] = state.reportRange ? state.reportRange.split('|') : ['', ''];
        dateFromInput.value = from;
        dateToInput.value = to;
    }

    function reportRangeQuery() {
        if (!state.reportRange) return '';
        const [from, to] = state.reportRange.split('|');
        const query = new URLSearchParams({ date_from: from, date_to: to });
        return '?' + query.toString();
    }

    function hasPermission(key) {
        return Boolean(state.me && (state.me.permissions || []).includes(key));
    }

    function noteSync(text) {
        syncStatus.hidden = !text;
        syncStatus.textContent = text || '';
    }

    let syncStatusTimer = null;

    function noteSyncFor(text, hideAfterSeconds) {
        noteSync(text);
        clearTimeout(syncStatusTimer);
        if (hideAfterSeconds) syncStatusTimer = setTimeout(() => noteSync(''), hideAfterSeconds * 1000);
    }

    async function loadData() {
        try {
            const payload = await api('/api/data' + reportRangeQuery());
            const data = payload.data || {};
            if (Array.isArray(data.products) && data.products.length && Array.isArray(data.weeks) && data.weeks.length) {
                dashboard.replaceData(data, 'трекер', null, { customPeriod: Boolean(state.reportRange) });
                noteSync(payload.stale ? 'кэш от ' + formatDate(payload.generated_at) : '');
                reportData(
                    payload.stale
                        ? 'Трекер недоступен: показан кэш от ' + formatDate(payload.generated_at) + '.'
                        : 'Данные трекера · синхронизация ' + formatDate(payload.generated_at) + '.',
                    Boolean(payload.stale)
                );
            } else {
                noteSync('Данных нет — назначьте метки группам в настройках');
                reportData('Пока нет данных: назначьте метки группам в «Настройках».', true);
            }
        } catch (error) {
            if (error.message === 'unauthorized') return null;
            noteSync('Данные недоступны (' + error.message + ')');
            reportData('Данные недоступны (' + error.message + ') — показаны сохранённые значения.', true);
            return null;
        }
    }

    logoutButton.addEventListener('click', async () => {
        // Полный выход: сначала локальная сессия, затем — страница выхода SSO,
        // чтобы SSO не впускал обратно без повторного ввода пароля.
        let target = '/';
        try {
            const body = await (await fetch('/auth/logout', { method: 'POST' })).json();
            if (body.logout_url) target = body.logout_url;
        } catch {}
        location.href = target;
    });

    refreshButton.addEventListener('click', async () => {
        const label = refreshButton.querySelector('span');
        const previous = label.textContent;
        refreshButton.disabled = true;
        label.textContent = 'Обновляю…';
        noteSyncFor('Обновление списка задач из трекера…');
        try {
            await api('/api/sync', { method: 'POST' });
            const payload = await loadData();
            if (payload && payload.stale)
                noteSyncFor('Обновлено, но трекер недоступен: показан кэш от ' + formatDate(payload.generated_at));
            else if (payload)
                noteSyncFor('Список задач обновлён · ' + formatDate(new Date().toISOString()), 8);
        } catch (error) {
            if (error.message !== 'unauthorized') noteSyncFor('Обновить не удалось: ' + error.message);
        } finally {
            refreshButton.disabled = false;
            label.textContent = previous;
        }
    });

    function onReportRangeChange() {
        const from = dateFromInput.value;
        const to = dateToInput.value;
        const range = from && to ? from + '|' + to : '';
        if (range === state.reportRange) return;
        state.reportRange = range;
        try { sessionStorage.setItem('l2-report-range', range); } catch {}
        loadData();
    }

    dateFromInput.addEventListener('change', onReportRangeChange);
    dateToInput.addEventListener('change', onReportRangeChange);

    q('#ld-week').addEventListener('change', () => {
        if (!state.reportRange) return;
        dateFromInput.value = '';
        dateToInput.value = '';
        onReportRangeChange();
    });


    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    };

    function moveGroup(index, step) {
        const target = index + step;
        if (target < 0 || target >= state.groups.length) return;
        const [group] = state.groups.splice(index, 1);
        state.groups.splice(target, 0, group);
        renderGroups();
    }


    function currentProduct() {
        return state.products.find(p => p.id === state.selectedProduct) || state.products[0] || null;
    }

    function productTabs(host, selectedId, onSelect, tailButton) {
        host.replaceChildren(...state.products.map(product => {
            const tab = el('span', 'product-tab');
            const button = el('button', null, product.name);
            button.type = 'button';
            button.setAttribute('aria-pressed', String(product.id === selectedId));
            button.addEventListener('click', () => onSelect(product.id));
            tab.append(button);
            return tab;
        }));
        if (tailButton) host.append(tailButton());
    }

    function renderProducts() {
        productTabs(productsNav, state.selectedProduct, selectProduct, productAddButton);
        productTabs(groupsProductsNav, state.selectedProduct, selectGroupsProduct);
        productTabs(labelsProductsNav, state.labelsProduct, selectLabelsProduct);
    }

    function selectProduct(productId) {
        state.selectedProduct = productId;
        const product = state.products.find(p => p.id === productId);
        if (product) {
            state.productEditing = { ...product };
            renderProductForm();
        }
        renderProducts();
        reloadTrackerLabels(productId).then(renderGroups);
    }

    function selectGroupsProduct(productId) {
        state.selectedProduct = productId;
        renderProducts();
        renderGroups();
        reloadTrackerLabels(productId).then(renderGroups);
    }

    function selectLabelsProduct(productId) {
        state.labelsProduct = productId;
        renderProducts();
        reloadTrackerLabels(productId).then(() => {
            buildNoteItems();
            renderNotes();
        });
    }

    function renderProductForm() {
        const product = state.productEditing;
        if (!product) {
            productForm.hidden = true;
            return;
        }
        productForm.hidden = false;
        productDeleteButton.hidden = !product.id;
        productNameInput.value = product.name || '';
        productNamespaceInput.value = product.namespace || '';
        productCodeInput.value = product.project_code || '';
    }

    async function saveProduct() {
        const product = state.productEditing;
        if (!product) return;
        const body = {
            name: productNameInput.value.trim(),
            namespace: productNamespaceInput.value.trim(),
            project_code: productCodeInput.value.trim(),
        };
        if (!body.name) { settingsMessage.textContent = 'Укажите название проекта'; return; }
        try {
            if (product.id) {
                const response = await api('/api/products/' + product.id, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                state.products = response.products;
            } else {
                const response = await api('/api/products', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                state.products = response.products;
                const created = state.products[state.products.length - 1];
                if (created) state.selectedProduct = created.id;
            }
            state.productEditing = null;
            settingsMessage.textContent = 'Проект сохранён';
            renderProducts();
            renderProductForm();
            renderGroups();
        } catch (error) {
            settingsMessage.textContent = 'Не удалось сохранить проект: ' + error.message;
        }
    }

    async function deleteProduct(productId) {
        const product = state.products.find(p => p.id === productId);
        if (!product) return;
        if (!confirm('Удалить проект «' + product.name + '» с его группами и метками?')) return;
        try {
            const response = await api('/api/products/' + productId, { method: 'DELETE' });
            state.products = response.products;
            state.groups = response.groups.map(group => ({
                uid: nextUid(),
                product_id: group.product_id,
                name: group.name,
                category: group.category || '',
                labels: group.labels.map(item => ({ label: item.label, category: item.category || null }))
            }));
            if (!state.products.some(p => p.id === state.selectedProduct))
                state.selectedProduct = state.products[0]?.id ?? null;
            state.productEditing = null;
            productForm.hidden = true;
            settingsMessage.textContent = 'Проект удалён';
            renderProducts();
            renderGroups();
        } catch (error) {
            settingsMessage.textContent = 'Не удалось удалить проект: ' + error.message;
        }
    }

    function removeLabel(group, label) {
        group.labels = group.labels.filter(item => item.label !== label);
        renderGroups();
    }

    function groupRow(group, index) {
        const row = el('div', 'settings-group');
        const head = el('div', 'settings-group-head');
        const up = el('button', 'icon-btn', '↑');
        up.type = 'button';
        up.title = 'Выше';
        const down = el('button', 'icon-btn', '↓');
        down.type = 'button';
        down.title = 'Ниже';
        up.addEventListener('click', () => moveGroup(index, -1));
        down.addEventListener('click', () => moveGroup(index, 1));
        const name = el('input', 'settings-name');
        name.value = group.name;
        name.addEventListener('input', () => { group.name = name.value; });
        const remove = el('button', 'icon-btn', '✕');
        remove.type = 'button';
        remove.title = 'Удалить группу';
        remove.addEventListener('click', () => {
            if (state.groups.length <= 1) { settingsMessage.textContent = 'Нужна хотя бы одна группа'; return; }
            if (!confirm('Удалить группу «' + (group.name || 'без названия') + '»?')) return;
            state.groups.splice(index, 1);
            renderGroups();
        });
        head.append(up, down, name, remove);
        const chips = el('div', 'settings-labels');
        group.labels.forEach(item => {
            const chip = el('span', 'settings-tag');
            chip.append(el('span', null, item.label));
            const drop = el('button', null, '×');
            drop.type = 'button';
            drop.title = 'Убрать метку из группы';
            drop.addEventListener('click', () => removeLabel(group, item.label));
            chip.append(drop);
            chips.append(chip);
        });
        if (!group.labels.length) chips.append(el('span', 'settings-tag', 'меток нет'));
        row.append(head, chips);
        return row;
    }

    function unassigned() {
        const product = currentProduct();
        if (!product) return [];
        const assigned = new Set(state.groups
            .filter(group => group.product_id === product.id)
            .flatMap(group => group.labels.map(item => item.label)));
        const hidden = new Set(state.hiddenLabelsByProduct[product.id] || []);
        return (state.trackerLabelsByProduct[product.id] || [])
            .filter(label => !assigned.has(label) && !hidden.has(label));
    }

    function renderPool() {
        const rest = unassigned();
        poolBadge.hidden = !rest.length;
        poolBadge.textContent = rest.length ? rest.length + ' не распределено' : '';
        poolHost.replaceChildren(...rest.map(label => {
            const chip = el('span', 'settings-tag');
            chip.append(el('span', null, label));
            state.groups.filter(group => group.product_id === currentProduct()?.id).forEach(group => {
                const target = el('button', 'pool-target', group.name || 'Без названия');
                target.type = 'button';
                target.title = 'Добавить в группу «' + (group.name || 'Без названия') + '»';
                target.addEventListener('click', () => {
                    group.labels.push({ label: label, category: null });
                    renderGroups();
                });
                chip.append(target);
            });
            return chip;
        }));
    }

    function renderGroups() {
        const product = currentProduct();
        if (!product) {
            groupsHost.replaceChildren();
            renderPool();
            return;
        }
        groupsHost.replaceChildren(...state.groups
            .filter(group => group.product_id === product.id)
            .map(groupRow));
        renderPool();
    }

    function showSettingsTab(name) {
        for (const key of Object.keys(settingsPanes)) {
            settingsPanes[key].hidden = key !== name;
            q('#ld-tab-' + key).setAttribute('aria-pressed', String(key === name));
        }
    }

    const SETTINGS_TABS = [
        { key: 'products', func: 'settings' },
        { key: 'groups', func: 'settings' },
        { key: 'sprints', func: 'sprints' },
        { key: 'labels', func: 'settings' },
        { key: 'users', func: 'users' },
    ];

    function renderSettingsTabs() {
        for (const tab of SETTINGS_TABS) {
            q('#ld-tab-' + tab.key).hidden = !hasPermission(tab.func);
        }
        q('#ld-labels-reload').hidden = !hasPermission('settings');
    }

    q('#ld-tab-products').addEventListener('click', () => showSettingsTab('products'));
    q('#ld-tab-groups').addEventListener('click', () => showSettingsTab('groups'));
    q('#ld-tab-sprints').addEventListener('click', () => showSettingsTab('sprints'));
    q('#ld-tab-labels').addEventListener('click', () => showSettingsTab('labels'));
    q('#ld-tab-users').addEventListener('click', () => showSettingsTab('users'));
    notesSearch.addEventListener('input', () => {
        state.notesSearch = notesSearch.value;
        renderNotes();
    });

    function sprintRow(sprint, index) {
        const row = el('div', 'settings-sprint');
        const name = el('input', 'settings-name');
        name.placeholder = 'w47';
        name.value = sprint.name;
        name.addEventListener('input', () => { sprint.name = name.value; });
        const from = el('input', 'settings-date');
        from.type = 'date';
        from.value = sprint.date_from;
        from.addEventListener('change', () => { sprint.date_from = from.value; });
        const to = el('input', 'settings-date');
        to.type = 'date';
        to.value = sprint.date_to;
        to.addEventListener('change', () => { sprint.date_to = to.value; });
        const remove = el('button', 'icon-btn', '✕');
        remove.type = 'button';
        remove.title = 'Удалить спринт';
        remove.addEventListener('click', () => {
            state.sprints.splice(index, 1);
            renderSprints();
        });
        row.append(name, from, el('span', 'dash', '—'), to, remove);
        return row;
    }

    function renderSprints() {
        sprintsHost.replaceChildren(...state.sprints.map(sprintRow));
    }


    function buildNoteItems() {
        const productId = state.labelsProduct;
        const hidden = new Set(state.hiddenLabelsByProduct[productId] || []);
        const labels = (state.trackerLabelsByProduct[productId] || []).filter(label => !hidden.has(label));
        const defaults = state.notesDefaults || {};
        const labelsSet = new Set(labels);
        state.notes = {};
        state.noteItems = [...labelsSet].sort((a, b) => a.localeCompare(b, 'ru')).map(label => {
            const saved = state.labelNotes[label];
            state.notes[label] = saved !== undefined ? saved : (defaults[label] || '');
            return { label: label };
        });
    }

    function noteRow(item) {
        const row = el('div', 'settings-label-note');
        const name = el('code', null, item.label);
        const input = el('input', 'settings-name');
        input.placeholder = 'расшифровка (пусто — показывать имя метки)';
        input.value = state.notes[item.label] || '';
        input.addEventListener('input', () => { state.notes[item.label] = input.value; });
        row.append(name, input);
        if (!(state.trackerLabelGroupsByProduct[state.labelsProduct]?.[item.label] || []).length) {
            const remove = el('button', 'icon-btn', '✕');
            remove.type = 'button';
            remove.title = 'Удалить метку';
            remove.addEventListener('click', () => hideLabel(item.label));
            row.append(remove);
        }
        return row;
    }

    function renderNotes() {
        const filter = (state.notesSearch || '').trim().toLowerCase();
        const rows = state.noteItems.filter(item =>
            !filter || item.label.toLowerCase().includes(filter) || (state.notes[item.label] || '').toLowerCase().includes(filter));
        notesHost.replaceChildren(...rows.map(noteRow));
        if (!rows.length) notesHost.append(el('p', 'settings-sub', 'Нет меток для этого проекта'));
        renderHiddenNotes();
    }

    function renderHiddenNotes() {
        const hidden = state.hiddenLabelsByProduct[state.labelsProduct] || [];
        if (!hidden.length) {
            hiddenNotesHost.replaceChildren();
            return;
        }
        const rows = [el('p', 'settings-sub', 'Удалённые метки — их можно вернуть в список')];
        for (const label of hidden) {
            const row = el('div', 'settings-label-note');
            row.append(el('code', null, label));
            const restore = el('button', 'icon-btn', '↺');
            restore.type = 'button';
            restore.title = 'Вернуть метку в список';
            restore.addEventListener('click', () => restoreLabel(label));
            row.append(restore);
            rows.push(row);
        }
        hiddenNotesHost.replaceChildren(...rows);
    }

    async function saveHiddenLabels(productId, hidden, message) {
        try {
            const labels = await api('/api/tracker/labels/hidden?product=' + productId, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ labels: hidden })
            });
            state.trackerLabelsByProduct[productId] = labels.labels.map(item => item.label);
            state.trackerLabelGroupsByProduct[productId] = Object.fromEntries(labels.labels.map(item => [item.label, item.groups]));
            state.hiddenLabelsByProduct[productId] = labels.hidden || [];
            buildNoteItems();
            renderGroups();
            renderNotes();
            settingsMessage.textContent = message;
        } catch (error) {
            settingsMessage.textContent = 'Не удалось обновить список меток: ' + error.message;
        }
    }

    function hideLabel(label) {
        if (!confirm('Удалить метку «' + label + '» из списка? Вернуть её можно в блоке «Удалённые метки».')) return;
        const hidden = state.hiddenLabelsByProduct[state.labelsProduct] || [];
        saveHiddenLabels(state.labelsProduct, [...new Set([...hidden, label])], 'Метка удалена');
    }

    function restoreLabel(label) {
        const hidden = (state.hiddenLabelsByProduct[state.labelsProduct] || []).filter(item => item !== label);
        saveHiddenLabels(state.labelsProduct, hidden, 'Метка возвращена в список');
    }

    async function reloadTrackerLabels(productId) {
        const id = productId ?? currentProduct()?.id;
        if (!id) return;
        const labels = await api('/api/tracker/labels?product=' + id);
        state.trackerLabelsByProduct[id] = labels.labels.map(item => item.label);
        state.trackerLabelGroupsByProduct[id] = Object.fromEntries(labels.labels.map(item => [item.label, item.groups]));
        state.hiddenLabelsByProduct[id] = labels.hidden || [];
    }


    const USER_FUNCTIONS = [
        { key: 'dashboard', label: 'Доступ к отчёту' },
        { key: 'sync', label: 'Обновить данные' },
        { key: 'settings', label: 'Проекты, группы, метки' },
        { key: 'period', label: 'Период отчёта (свои даты и выбор спринтов)' },
        { key: 'sprints', label: 'Спринты (изменение периодов)' },
        { key: 'users', label: 'Пользователи' },
    ];

    const USER_ROLES = {
        admin: 'Админ',
        editor: 'Редактор',
        viewer: 'Наблюдатель',
    };

    const USER_ROLE_PRESETS = {
        admin: USER_FUNCTIONS.map(func => func.key),
        editor: ['dashboard', 'sync', 'settings', 'period', 'sprints'],
        viewer: ['dashboard'],
    };

    function userRow(user) {
        const row = el('div', 'settings-user');
        const name = el('span', 'settings-user-name', user.display_name || user.username);
        const login = el('span', 'settings-user-login', user.username);
        const role = el('span', 'settings-tag', USER_ROLES[user.role] || user.role);
        const edit = el('button', 'upload', 'Изменить');
        edit.type = 'button';
        edit.addEventListener('click', () => {
            state.userEditing = { ...user, permissions: [...(user.permissions || [])] };
            renderUsers();
        });
        row.append(name, login, role, edit);
        return row;
    }

    function renderUserCard() {
        const user = state.userEditing;
        addUserButton.hidden = Boolean(user);
        if (!user) {
            userCardHost.replaceChildren();
            return;
        }
        const card = el('div', 'panel settings-user-card');
        card.append(el('h3', null, user.isNew ? 'Новый пользователь' : 'Пользователь «' + user.username + '»'));

        const nameLabel = el('label', 'settings-user-field');
        nameLabel.append('Имя');
        const nameInput = el('input', 'settings-name');
        nameInput.value = user.display_name || '';
        nameInput.addEventListener('input', () => { user.display_name = nameInput.value; });
        nameLabel.append(nameInput);
        card.append(nameLabel);

        if (user.isNew) {
            const loginLabel = el('label', 'settings-user-field');
            loginLabel.append('Логин (SSO)');
            const loginInput = el('input', 'settings-name');
            loginInput.value = user.username || '';
            loginInput.addEventListener('input', () => { user.username = loginInput.value; });
            loginLabel.append(loginInput);
            card.append(loginLabel);
        }

        const roleLabel = el('label', 'settings-user-field');
        roleLabel.append('Роль');
        const roleSelect = el('select', 'settings-name');
        Object.keys(USER_ROLES).forEach(role => {
            const option = el('option', null, USER_ROLES[role]);
            option.value = role;
            if (user.role === role) option.selected = true;
            roleSelect.append(option);
        });
        roleSelect.addEventListener('change', () => {
            user.role = roleSelect.value;
            user.permissions = [...USER_ROLE_PRESETS[roleSelect.value]];
            renderUserCard();
        });
        roleLabel.append(roleSelect);
        card.append(roleLabel);

        const perms = el('div', 'settings-user-perms');
        USER_FUNCTIONS.forEach(func => {
            const label = el('label', 'settings-user-perm');
            const checkbox = el('input');
            checkbox.type = 'checkbox';
            checkbox.checked = user.permissions.includes(func.key);
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    if (!user.permissions.includes(func.key)) user.permissions.push(func.key);
                } else {
                    user.permissions = user.permissions.filter(p => p !== func.key);
                }
            });
            label.append(checkbox, ' ' + func.label);
            perms.append(label);
        });
        card.append(perms);

        const actions = el('div', 'settings-user-actions');
        const save = el('button', 'download', 'Сохранить');
        save.type = 'button';
        save.addEventListener('click', () => saveUser());
        const cancel = el('button', 'upload', 'Отмена');
        cancel.type = 'button';
        cancel.addEventListener('click', () => {
            state.userEditing = null;
            renderUsers();
        });
        actions.append(save, cancel);
        card.append(actions);
        userCardHost.replaceChildren(card);
    }

    async function saveUser() {
        const user = state.userEditing;
        if (!user) return;
        const body = {
            display_name: user.display_name || '',
            role: user.role,
            permissions: user.permissions,
        };
        try {
            if (user.isNew) {
                body.username = user.username;
                if (!body.username) { settingsMessage.textContent = 'Укажите логин'; return; }
                const response = await api('/api/users', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                state.users = response.users;
                settingsMessage.textContent = 'Пользователь создан';
            } else {
                const response = await api('/api/users/' + encodeURIComponent(user.username), {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                state.users = response.users;
                settingsMessage.textContent = 'Сохранено';
            }
            state.userEditing = null;
            renderUsers();
        } catch (error) {
            settingsMessage.textContent = 'Не удалось сохранить: ' + error.message;
        }
    }

    function renderUsers() {
        usersHost.replaceChildren(...state.users.map(userRow));
        renderUserCard();
    }

    addUserButton.addEventListener('click', () => {
        state.userEditing = { isNew: true, username: '', display_name: '', role: 'viewer', permissions: [...USER_ROLE_PRESETS.viewer] };
        renderUsers();
    });

    function sprintValidationError() {
        for (const sprint of state.sprints) {
            const name = sprint.name.trim();
            if (!name) return 'У каждого спринта должно быть имя';
            if (!sprint.date_from || !sprint.date_to) return 'У спринта «' + name + '» должны быть даты начала и конца';
            if (sprint.date_to < sprint.date_from) return 'У спринта «' + name + '» дата конца раньше даты начала';
        }
        const ordered = [...state.sprints].sort((a, b) => a.date_from.localeCompare(b.date_from));
        for (let i = 1; i < ordered.length; i++) {
            if (ordered[i - 1].date_to >= ordered[i].date_from) {
                return 'Диапазоны спринтов «' + ordered[i - 1].name.trim() + '» и «' + ordered[i].name.trim() + '» пересекаются';
            }
        }
        return '';
    }

    settingsButton.addEventListener('click', async () => {
        settingsPanel.hidden = false;
        settingsMessage.textContent = 'Загрузка…';
        renderSettingsTabs();
        try {
            const [settings, notes, sprints, users] = await Promise.all([
                hasPermission('settings') ? api('/api/settings') : null,
                hasPermission('settings') ? api('/api/labels') : null,
                hasPermission('sprints') ? api('/api/sprints') : null,
                hasPermission('users') ? api('/api/users') : null,
            ]);
            if (settings) {
                state.products = settings.products || [];
                state.groups = settings.groups.map(group => ({
                    uid: nextUid(),
                    product_id: group.product_id,
                    name: group.name,
                    category: group.category || '',
                    labels: group.labels.map(item => ({ label: item.label, category: item.category || null }))
                }));
            }
            if (notes) {
                state.labelNotes = notes.notes || {};
                state.notesDefaults = notes.defaults || {};
            }
            if (sprints) state.sprints = sprints.sprints.map(sprint => ({ name: sprint.name, date_from: sprint.date_from, date_to: sprint.date_to }));
            if (users) state.users = users.users;
            state.selectedProduct = state.products[0]?.id ?? null;
            state.labelsProduct = state.selectedProduct;
            state.productEditing = null;
            productForm.hidden = true;
            if (hasPermission('settings')) await reloadTrackerLabels();
            buildNoteItems();
            showSettingsTab(hasPermission('settings') ? 'groups' : hasPermission('sprints') ? 'sprints' : 'users');
            renderProducts();
            renderGroups();
            renderSprints();
            renderNotes();
            renderUsers();
            settingsMessage.textContent = '';
        } catch (error) {
            settingsMessage.textContent = 'Не удалось загрузить настройки: ' + error.message;
        }
    });

    q('#ld-settings-close').addEventListener('click', () => { settingsPanel.hidden = true; });

    function productAddButton() {
        const button = el('button', 'product-add', '+');
        button.type = 'button';
        button.title = 'Добавить проект';
        button.setAttribute('aria-label', 'Добавить проект');
        button.addEventListener('click', () => {
            state.productEditing = { name: '', namespace: '', project_code: '' };
            renderProductForm();
            productNameInput.focus();
        });
        return button;
    }
    productSaveButton.addEventListener('click', () => saveProduct());
    productCancelButton.addEventListener('click', () => {
        state.productEditing = null;
        productForm.hidden = true;
    });
    productDeleteButton.addEventListener('click', () => {
        if (state.productEditing?.id) deleteProduct(state.productEditing.id);
    });
    q('#ld-add-group').addEventListener('click', () => {
        const product = currentProduct();
        if (!product) { settingsMessage.textContent = 'Сначала добавьте проект'; return; }
        state.groups.push({ uid: nextUid(), product_id: product.id, name: 'Новая группа', category: '', labels: [] });
        renderGroups();
    });
    q('#ld-add-sprint').addEventListener('click', () => {
        state.sprints.push({ name: '', date_from: '', date_to: '' });
        renderSprints();
    });
    q('#ld-labels-reload').addEventListener('click', async () => {
        try {
            await reloadTrackerLabels(state.labelsProduct);
            buildNoteItems();
            renderGroups();
            renderNotes();
            settingsMessage.textContent = (state.trackerLabelsByProduct[state.labelsProduct] || []).length
                ? 'Список меток обновлён'
                : 'Список меток пуст: синхронизируйте трекер (кнопка «Обновить»), затем повторите.';
        } catch (error) {
            settingsMessage.textContent = 'Не удалось обновить метки: ' + error.message;
        }
    });

    q('#ld-settings-save').addEventListener('click', async () => {
        const manageSettings = hasPermission('settings');
        const manageSprints = hasPermission('sprints');
        if (!manageSettings && !manageSprints) return;
        if (manageSettings) {
            if (state.groups.some(group => !group.name.trim())) {
                settingsMessage.textContent = 'У каждой группы должно быть имя';
                return;
            }
            const totalLabels = state.groups.reduce((sum, group) => sum + group.labels.length, 0);
            if (!totalLabels && state.trackerLabels.length
                && !confirm('Ни одна метка не распределена — обращения не попадут ни в одну группу. Сохранить?')) return;
        }
        if (manageSprints) {
            const sprintError = sprintValidationError();
            if (sprintError) {
                settingsMessage.textContent = sprintError;
                return;
            }
        }
        const putJson = (path, body) => api(path, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        try {
            const counts = [];
            if (manageSprints) {
                await putJson('/api/sprints', {
                    sprints: state.sprints.map(sprint => ({
                        name: sprint.name.trim(),
                        date_from: sprint.date_from,
                        date_to: sprint.date_to
                    }))
                });
                counts.push('спринтов ' + state.sprints.length);
            }
            if (manageSettings) {
                const notesToSave = { ...state.labelNotes, ...state.notes };
                const savedNotes = await putJson('/api/labels', { notes: notesToSave });
                state.labelNotes = savedNotes.notes || {};
                await putJson('/api/settings', {
                    groups: state.groups.map(group => ({
                        name: group.name.trim(),
                        category: group.category || null,
                        product_id: group.product_id,
                        labels: group.labels.map(item => ({ label: item.label, category: item.category || null }))
                    }))
                });
                counts.push('групп ' + state.groups.length
                    + ', меток ' + state.groups.reduce((sum, group) => sum + group.labels.length, 0)
                    + ', расшифровок ' + Object.values(notesToSave).filter(value => value.trim()).length);
            }
            settingsMessage.textContent = 'Сохранено: ' + counts.join(', ');
            await loadData();
        } catch (error) {
            settingsMessage.textContent = 'Не удалось сохранить: ' + error.message;
        }
    });

    async function init() {
        let me;
        try {
            me = await api('/api/me');
        } catch {
            me = { username: null, is_admin: false };
        }
        if (!me.username) { showLogin(); return; }
        showUser(me);
        await loadData();
    }

    init();
})();
