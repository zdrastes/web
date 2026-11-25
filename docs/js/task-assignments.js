(() => {
  'use strict';
  const projectTasks = [
    { id: 'DEMO-101', title: 'Разобрать повторные обращения по интеграции', tag: 'Интеграция', status: 'open', date: '2026-11-17', employee: 0 },
    { id: 'DEMO-102', title: 'Исправить дублирование записей при повторной синхронизации', tag: 'Синхронизация', status: 'dev', date: '2026-11-18', employee: 2 },
    { id: 'DEMO-103', title: 'Пересчитать итог по обращениям за неделю', tag: 'Отчётность', status: 'recalc', date: '2026-11-19', employee: 3 },
    { id: 'DEMO-104', title: 'Проверить исправление ошибки выгрузки отчёта', tag: 'Выгрузка', status: 'fix', date: '2026-11-20', employee: 4 },
    { id: 'DEMO-105', title: 'Уточнить сценарий ошибки доступа к проекту', tag: 'Доступ', status: 'open', date: '2026-11-23', employee: 1 },
    { id: 'DEMO-106', title: 'Убрать ошибку при переключении фильтра', tag: 'Интерфейс', status: 'dev', date: '2026-11-24', employee: 0 },
    { id: 'DEMO-107', title: 'Сверить данные по закрытым обращениям', tag: 'Данные', status: 'recalc', date: '2026-11-25', employee: 1 },
    { id: 'DEMO-108', title: 'Проверить загрузку отчёта после обновления', tag: 'Отчётность', status: 'fix', date: '2026-11-26', employee: 2 },
  ];
  const projectStatusKey = 'zdrastes.web.demo.project-tasks.v1';
  const dailyActionKey = 'zdrastes.web.demo.daily-task-actions.v1';
  const date = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
  });
  function readMap(key) {
    try {
      const value = JSON.parse(localStorage.getItem(key));
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
      return {};
    }
  }
  function assignedToday(employee) {
    const statuses = readMap(projectStatusKey);
    return projectTasks.filter(task => task.employee === employee &&
      (['open', 'dev', 'recalc', 'fix'].includes(statuses[task.id]) ? statuses[task.id] : task.status) === 'open');
  }
  function pendingToday(employee) {
    const actions = readMap(dailyActionKey);
    return assignedToday(employee).filter(task => !['closed', 'moved'].includes(actions[task.id]?.status));
  }
  function todayLink(employee) {
    return 'tasks.html?view=today&employee=' + encodeURIComponent(employee) + '#tasks-heading';
  }
  window.L2TaskAssignments = {
    projectTasks, projectStatusKey, dailyActionKey, readMap, assignedToday, pendingToday, todayLink,
    todayKey: () => date.format(new Date()),
  };
})();