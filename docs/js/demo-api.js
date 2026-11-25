/* Демо-режим GitHub Pages: все запросы к API отвечаются из встроенных данных.
 * Мутации (создание/правка/удаление) обновляют состояние в памяти,
 * поэтому интерфейс живёт как настоящий без бэкенда.
 */
(function () {
    'use strict';
    if (!window.L2_DEMO_DATA) return;

    const payload = window.L2_DEMO_DATA;
    const dashboardData = payload.data || {};

    const DEMO_USER = {
        username: 'demo',
        display_name: 'Demo User',
        is_admin: true,
        permissions: ['dashboard', 'sync', 'settings', 'period', 'sprints', 'users'],
    };

    // Изменяемое состояние: мутации обновляют его, интерфейс отвечает как настоящий.
    const state = {
        products: [
            { id: 1, name: 'DEMO', namespace: 'demo-namespace', project_code: 'DEMO', sort_order: 0 },
            { id: 2, name: 'DEMO-STORE', namespace: 'demo-namespace', project_code: 'DEMO-STORE', sort_order: 1 },
            { id: 3, name: 'DEMO-TRANS', namespace: 'demo-namespace', project_code: 'DEMO-TRANS', sort_order: 2 },
        ],
        groups: [],
        trackerLabels: {},
        trackerLabelGroups: {},
        hiddenLabels: {},
        labelNotes: Object.assign({}, dashboardData.label_notes || {}),
        notesDefaults: {},
        sprints: [],
        users: [
            { username: 'demo', display_name: 'Demo User', role: 'admin',
              permissions: ['dashboard', 'sync', 'settings', 'period', 'sprints', 'users'] },
            { username: 'viewer', display_name: 'Demo Viewer', role: 'viewer',
              permissions: ['dashboard'] },
        ],
    };

    let nextGroupId = 100;
    (dashboardData.products || []).forEach(product => {
        (product.groups || []).forEach(group => {
            state.groups.push({
                id: nextGroupId++,
                name: group.name,
                category: null,
                sort_order: nextGroupId,
                product_id: product.id,
                labels: (group.reasons || []).map(reason => ({ label: reason.name, category: null })),
            });
        });
    });

    // Метки трекера: собираем из групп + свободные метки демо-набора.
    const FREE_LABELS = ['free_label_1', 'free_label_2'];
    function rebuildTrackerLabels() {
        state.products.forEach(product => {
            const labels = [];
            const groupsByLabel = {};
            state.groups.filter(group => group.product_id === product.id).forEach(group => {
                group.labels.forEach(item => {
                    if (!groupsByLabel[item.label]) {
                        groupsByLabel[item.label] = [];
                        labels.push(item.label);
                    }
                    groupsByLabel[item.label].push(group.name);
                });
            });
            FREE_LABELS.forEach(label => {
                if (!groupsByLabel[label]) {
                    groupsByLabel[label] = [];
                    labels.push(label);
                }
            });
            state.trackerLabels[product.id] = labels;
            state.trackerLabelGroups[product.id] = groupsByLabel;
            if (!state.hiddenLabels[product.id]) state.hiddenLabels[product.id] = [];
        });
    }
    rebuildTrackerLabels();

    function groupsForLabelsResponse(productId) {
        const hidden = new Set(state.hiddenLabels[productId] || []);
        return (state.trackerLabels[productId] || [])
            .filter(label => !hidden.has(label))
            .map(label => ({ label: label, groups: state.trackerLabelGroups[productId]?.[label] || [] }));
    }

    function groupsPayload() {
        return {
            products: state.products,
            groups: state.groups.map(group => ({
                id: group.id,
                name: group.name,
                category: group.category,
                sort_order: group.sort_order,
                product_id: group.product_id,
                labels: group.labels.map(item => ({ label: item.label, category: item.category })),
            })),
        };
    }

    function nextProductId() {
        return state.products.reduce((max, product) => Math.max(max, product.id), 0) + 1;
    }

    function readJson(options) {
        try {
            return JSON.parse((options && options.body) || '{}');
        } catch {
            return {};
        }
    }

    function ok(body) {
        return Promise.resolve(body);
    }

    function reportFor(url) {
        const params = new URLSearchParams(url.split('?')[1]);
        const from = Date.parse(params.get('date_from'));
        const to = Date.parse(params.get('date_to'));
        if (!Number.isFinite(from) || !Number.isFinite(to) || from > to) return payload;

        const day = 86400000;
        const week = 7 * day;
        const today = new Date();
        const monday = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
            - ((today.getUTCDay() + 6) % 7) * day;
        const first = monday - (dashboardData.weeks.length - 1) * week;
        const indexes = dashboardData.weeks.flatMap((_, index) => {
            const start = first + index * week;
            return start <= to && start + 6 * day >= from ? [index] : [];
        });
        if (!indexes.length) throw Error('За эти даты нет демо-данных. Доступны последние 12 недель.');

        const select = values => Array.isArray(values) ? indexes.map(index => values[index]) : values;
        function trimSeries(series) {
            const result = { ...series, counts: select(series.counts), rates: select(series.rates) };
            for (const key of ['groups', 'reasons']) {
                if (Array.isArray(series[key])) result[key] = series[key].map(trimSeries);
            }
            return result;
        }
        const dateLabel = timestamp => new Date(timestamp).toISOString().slice(5, 10).split('-').reverse().join('.');
        return {
            ...payload,
            data: {
                ...dashboardData,
                weeks: indexes.map(index => {
                    const start = first + index * week;
                    return dateLabel(start) + '-' + dateLabel(start + 6 * day);
                }),
                default_weeks: dashboardData.weeks,
                products: dashboardData.products.map(trimSeries),
            },
        };
    }

    const routes = [
        // --- GET ---
        { method: 'GET', pattern: /^\/api\/me$/, handler: () => ok(DEMO_USER) },
        { method: 'GET', pattern: /^\/api\/data$/, handler: url => Promise.resolve().then(() => reportFor(url)) },
        { method: 'GET', pattern: /^\/api\/settings$/, handler: () => ok(groupsPayload()) },
        { method: 'GET', pattern: /^\/api\/labels$/, handler: () => ok({ notes: state.labelNotes, defaults: state.notesDefaults }) },
        { method: 'GET', pattern: /^\/api\/sprints$/, handler: () => ok({ sprints: state.sprints }) },
        { method: 'GET', pattern: /^\/api\/users$/, handler: () => ok({ users: state.users }) },
        { method: 'GET', pattern: /^\/api\/products$/, handler: () => ok(groupsPayload()) },
        {
            method: 'GET', pattern: /^\/api\/tracker\/labels$/,
            handler: (url) => {
                const productId = Number(new URLSearchParams(url.split('?')[1] || '').get('product'));
                return ok({ labels: groupsForLabelsResponse(productId), hidden: state.hiddenLabels[productId] || [] });
            },
        },
        // --- PUT ---
        {
            method: 'PUT', pattern: /^\/api\/settings$/,
            handler: (url, options) => {
                const body = readJson(options);
                (body.groups || []).forEach(incoming => {
                    const existing = state.groups.find(group => group.product_id === incoming.product_id
                        && group.name === incoming.name);
                    if (existing) {
                        existing.labels = (incoming.labels || []).map(item => ({ label: item.label, category: item.category || null }));
                    } else {
                        state.groups.push({
                            id: nextGroupId++,
                            name: incoming.name,
                            category: incoming.category || null,
                            sort_order: nextGroupId,
                            product_id: incoming.product_id,
                            labels: (incoming.labels || []).map(item => ({ label: item.label, category: item.category || null })),
                        });
                    }
                });
                rebuildTrackerLabels();
                return ok(groupsPayload());
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/labels$/,
            handler: (url, options) => {
                const body = readJson(options);
                state.labelNotes = Object.assign({}, state.labelNotes, body.notes || {});
                return ok({ notes: state.labelNotes });
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/sprints$/,
            handler: (url, options) => {
                const body = readJson(options);
                state.sprints = (body.sprints || []).map(sprint => ({
                    name: sprint.name, date_from: sprint.date_from, date_to: sprint.date_to,
                }));
                return ok({ sprints: state.sprints });
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/products\/(\d+)$/,
            handler: (url, options) => {
                const productId = Number(url.match(/\/api\/products\/(\d+)$/)[1]);
                const body = readJson(options);
                const product = state.products.find(item => item.id === productId);
                if (product) {
                    product.name = body.name;
                    product.namespace = body.namespace;
                    product.project_code = body.project_code;
                }
                return ok(groupsPayload());
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/tracker\/labels\/hidden$/,
            handler: (url, options) => {
                const productId = Number(new URLSearchParams(url.split('?')[1] || '').get('product'));
                const body = readJson(options);
                state.hiddenLabels[productId] = body.labels || [];
                rebuildTrackerLabels();
                return ok({ labels: groupsForLabelsResponse(productId), hidden: state.hiddenLabels[productId] });
            },
        },
        // --- POST ---
        {
            method: 'POST', pattern: /^\/api\/products$/,
            handler: (url, options) => {
                const body = readJson(options);
                const product = {
                    id: nextProductId(),
                    name: body.name,
                    namespace: body.namespace || 'demo-namespace',
                    project_code: body.project_code || 'DEMO',
                    sort_order: state.products.length,
                };
                state.products.push(product);
                rebuildTrackerLabels();
                return ok(groupsPayload());
            },
        },
        {
            method: 'POST', pattern: /^\/api\/users$/,
            handler: (url, options) => {
                const body = readJson(options);
                state.users.push({
                    username: body.username,
                    display_name: body.display_name || body.username,
                    role: body.role || 'viewer',
                    permissions: body.permissions || ['dashboard'],
                });
                return ok({ users: state.users });
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/users\/([^/]+)$/,
            handler: (url, options) => {
                const username = decodeURIComponent(url.match(/\/api\/users\/([^/]+)$/)[1]);
                const body = readJson(options);
                const user = state.users.find(item => item.username === username);
                if (user) {
                    user.display_name = body.display_name || user.display_name;
                    user.role = body.role || user.role;
                    user.permissions = body.permissions || user.permissions;
                }
                return ok({ users: state.users });
            },
        },
        { method: 'POST', pattern: /^\/api\/sync$/, handler: () => ok({ ok: true }) },
        // --- DELETE ---
        {
            method: 'DELETE', pattern: /^\/api\/products\/(\d+)$/,
            handler: (url) => {
                const productId = Number(url.match(/\/api\/products\/(\d+)$/)[1]);
                state.products = state.products.filter(product => product.id !== productId);
                state.groups = state.groups.filter(group => group.product_id !== productId);
                delete state.trackerLabels[productId];
                delete state.trackerLabelGroups[productId];
                delete state.hiddenLabels[productId];
                return ok(groupsPayload());
            },
        },
    ];

    window.L2DemoApi = function (url, options) {
        const method = ((options && options.method) || 'GET').toUpperCase();
        for (const route of routes) {
            if (route.method === method && route.pattern.test(url.split('?')[0])) {
                return route.handler(url, options);
            }
        }
        return Promise.reject(new Error('Демо-режим: нет обработчика для ' + method + ' ' + url));
    };
})();
