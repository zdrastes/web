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

    const storageKey = 'zdrastes.web.l2-demo.settings.v1';
    const savedKeys = ['products', 'groups', 'hiddenLabels', 'labelNotes', 'sprints', 'users'];
    const catalog = new Map(dashboardData.products.map(product => [
        product.id,
        new Map(product.groups.flatMap(group => group.reasons.map(reason => [reason.name, reason]))),
    ]));
    state.groups = dashboardData.products.flatMap(product => product.groups.map(group => ({
        name: group.name,
        category: null,
        product_id: product.id,
        labels: group.reasons.map(reason => ({ label: reason.name, category: reason.type ?? null })),
    })));

    try {
        const saved = JSON.parse(window.localStorage.getItem(storageKey));
        if (saved) {
            for (const key of savedKeys) state[key] = saved[key] ?? state[key];
        }
    } catch {}

    function rebuildTrackerLabels() {
        for (const product of state.products) {
            const groupsByLabel = Object.create(null);
            for (const label of [...(catalog.get(product.id)?.keys() || []), 'free_label_1', 'free_label_2']) {
                groupsByLabel[label] = [];
            }
            for (const group of state.groups.filter(group => group.product_id === product.id)) {
                for (const { label } of group.labels) {
                    (groupsByLabel[label] ??= []).push(group.name);
                }
            }
            state.trackerLabels[product.id] = Object.keys(groupsByLabel);
            state.trackerLabelGroups[product.id] = groupsByLabel;
        }
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
            groups: state.groups.map((group, index) => ({
                id: index + 1,
                name: group.name,
                category: group.category,
                sort_order: index,
                product_id: group.product_id,
                labels: group.labels.map(item => ({ label: item.label, category: item.category })),
            })),
        };
    }

    function nextProductId() {
        return [...dashboardData.products, ...state.products].reduce((max, product) => Math.max(max, product.id), 0) + 1;
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

    function configuredReport() {
        const zero = () => dashboardData.weeks.map(() => 0);
        const rates = (counts, totals) => counts.map((count, i) => totals[i] ? count / totals[i] : 0);
        const products = state.products.map(product => {
            const original = dashboardData.products.find(item => item.id === product.id);
            const counts = original?.counts ?? zero();
            const hidden = new Set(state.hiddenLabels[product.id] || []);
            const groups = state.groups.filter(group => group.product_id === product.id).map(group => {
                const labels = group.labels.filter(item => !hidden.has(item.label));
                const originalGroup = original?.groups.find(item =>
                    item.name === group.name && item.reasons.length === labels.length &&
                    item.reasons.every((reason, i) => reason.name === labels[i].label));
                const reasons = labels.map(item => ({
                    ...catalog.get(product.id)?.get(item.label),
                    name: item.label,
                    type: item.category,
                    counts: catalog.get(product.id)?.get(item.label)?.counts ?? zero(),
                }));
                const groupCounts = originalGroup?.counts ?? counts.map((_, i) =>
                    reasons.reduce((sum, reason) => sum + (reason.counts[i] ?? 0), 0));
                return {
                    name: group.name,
                    counts: groupCounts,
                    rates: originalGroup?.rates ?? rates(groupCounts, counts),
                    reasons: reasons.map((reason, i) => ({
                        ...reason,
                        rates: originalGroup?.reasons[i].rates ?? rates(reason.counts, groupCounts),
                    })),
                };
            });
            return { id: product.id, name: product.name, counts, rates: original?.rates ?? zero(), groups };
        });
        return {
            ...dashboardData,
            products: products.length ? products : [{
                name: '\u041d\u0435\u0442 \u043f\u0440\u043e\u0435\u043a\u0442\u043e\u0432', counts: zero(), rates: zero(), groups: [],
            }],
            label_notes: { ...state.labelNotes },
        };
    }

    function reportFor(url) {
        const data = configuredReport();
        const params = new URLSearchParams(url.split('?')[1]);
        const from = Date.parse(params.get('date_from'));
        const to = Date.parse(params.get('date_to'));
        const custom = Number.isFinite(from) && Number.isFinite(to) && from <= to;
        if (!custom && !state.sprints.length) return { ...payload, data };

        const day = 86400000;
        const week = 7 * day;
        const today = new Date();
        const monday = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
            - ((today.getUTCDay() + 6) % 7) * day;
        const dateLabel = timestamp => new Date(timestamp).toISOString().slice(5, 10).split('-').reverse().join('.');
        const sourceWeeks = data.weeks.map((_, index) => monday - (data.weeks.length - 1 - index) * week);
        const indexesFor = (start, end) => sourceWeeks.flatMap((date, index) =>
            date <= end && date + 6 * day >= start ? [index] : []);
        const sprintPeriods = state.sprints.map(sprint => ({
            name: sprint.name,
            indexes: indexesFor(Date.parse(sprint.date_from), Date.parse(sprint.date_to)),
        }));
        let periods = sprintPeriods;
        if (custom) {
            periods = indexesFor(from, to).map(index => ({
                name: dateLabel(sourceWeeks[index]) + '-' + dateLabel(sourceWeeks[index] + 6 * day),
                indexes: [index],
            }));
            if (!periods.length) throw Error('\u0417\u0430 \u044d\u0442\u0438 \u0434\u0430\u0442\u044b \u043d\u0435\u0442 \u0434\u0435\u043c\u043e-\u0434\u0430\u043d\u043d\u044b\u0445.');
        }
        function aggregate(series, totals, nestedKey) {
            const counts = periods.map(({ indexes }) =>
                indexes.reduce((sum, index) => sum + (series.counts[index] ?? 0), 0));
            const rates = periods.map(({ indexes }, i) =>
                custom ? series.rates?.[indexes[0]] ?? null : totals?.[i] ? counts[i] / totals[i] : null);
            const result = { ...series, counts, rates };
            if (nestedKey) result[nestedKey] = series[nestedKey].map(item =>
                aggregate(item, counts, nestedKey === 'groups' ? 'reasons' : null));
            return result;
        }
        return {
            ...payload,
            data: {
                ...data,
                weeks: periods.map(period => period.name),
                default_weeks: custom ? (sprintPeriods.length ? sprintPeriods.map(period => period.name) : data.weeks) : undefined,
                products: data.products.map(product => aggregate(product, null, 'groups')),
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
                state.groups = body.groups ?? [];
                rebuildTrackerLabels();
                return ok(groupsPayload());
            },
        },
        {
            method: 'PUT', pattern: /^\/api\/labels$/,
            handler: (url, options) => {
                const body = readJson(options);
                state.labelNotes = body.notes ?? {};
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

    window.L2DemoApi = async function (url, options) {
        const method = ((options && options.method) || 'GET').toUpperCase();
        for (const route of routes) {
            if (route.method === method && route.pattern.test(url.split('?')[0])) {
                const result = await route.handler(url, options);
                if (method !== 'GET') {
                    try {
                        const saved = Object.fromEntries(savedKeys.map(key => [key, state[key]]));
                        window.localStorage.setItem(storageKey, JSON.stringify(saved));
                    } catch {}
                }
                return result;
            }
        }
        return Promise.reject(new Error('Демо-режим: нет обработчика для ' + method + ' ' + url));
    };
})();
