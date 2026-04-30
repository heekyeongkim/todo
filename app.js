(function () {
  'use strict';

  const STORAGE_KEY = 'todo-app-data';

  // 상태
  let todos = loadTodos();
  let filter = 'all';
  let nextId = todos.length > 0 ? Math.max(...todos.map((t) => t.id)) + 1 : 1;

  // DOM 요소
  const $list = document.getElementById('list');
  const $count = document.getElementById('count');
  const $remaining = document.getElementById('remaining');
  const $newTodo = document.getElementById('new-todo');
  const $newDate = document.getElementById('new-date');
  const $addBtn = document.getElementById('add-btn');
  const $clearDone = document.getElementById('clear-done');
  const $filterBtns = document.querySelectorAll('.filter-btn');

  // localStorage 저장/불러오기
  function loadTodos() {
    try {
      const data = localStorage.getItem(STORAGE_KEY);
      if (data) return JSON.parse(data);
    } catch (e) {
      console.warn('할일 불러오기 실패:', e);
    }
    // 초기 샘플 데이터
    return [
      { id: 1, text: '주요통계집 오탈자 검수', due: '', done: false },
      { id: 2, text: '정보시스템 데이터 조사 마무리', due: '', done: true },
      { id: 3, text: 'SOXL 시그마 임계값 백테스트', due: '', done: false },
    ];
  }

  function saveTodos() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
    } catch (e) {
      console.warn('할일 저장 실패:', e);
    }
  }

  // 마감일 포맷
  function formatDue(due) {
    if (!due) return null;
    const today = new Date().toISOString().split('T')[0];
    if (due < today) return { text: '지남', cls: 'overdue' };
    if (due === today) return { text: '오늘', cls: 'today' };
    const d = new Date(due);
    return { text: `${d.getMonth() + 1}/${d.getDate()}`, cls: '' };
  }

  // XSS 방지
  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  // 렌더링
  function render() {
    const filtered = todos.filter((t) => {
      if (filter === 'active') return !t.done;
      if (filter === 'done') return t.done;
      return true;
    });

    if (filtered.length === 0) {
      const msg =
        filter === 'done'
          ? '완료된 할일이 없습니다'
          : filter === 'active'
          ? '진행중인 할일이 없습니다'
          : '할일이 없습니다';
      $list.innerHTML = `<div class="todo-empty">${msg}</div>`;
    } else {
      $list.innerHTML = filtered
        .map((t) => {
          const due = formatDue(t.due);
          const dueHtml = due
            ? `<span class="todo-due ${due.cls}">${due.text}</span>`
            : '';
          return `
            <li class="todo-item ${t.done ? 'done' : ''}" data-id="${t.id}">
              <div class="todo-checkbox ${t.done ? 'checked' : ''}" data-action="toggle" role="checkbox" aria-checked="${t.done}" tabindex="0"></div>
              <span class="todo-text">${escapeHtml(t.text)}</span>
              ${dueHtml}
              <button class="todo-delete" data-action="delete" aria-label="삭제">×</button>
            </li>
          `;
        })
        .join('');
    }

    const total = todos.length;
    const remaining = todos.filter((t) => !t.done).length;
    $count.textContent = `${total}개의 할일`;
    $remaining.textContent = `${remaining}개 남음`;
  }

  // 할일 추가
  function addTodo() {
    const text = $newTodo.value.trim();
    if (!text) {
      $newTodo.focus();
      return;
    }
    todos.push({
      id: nextId++,
      text,
      due: $newDate.value,
      done: false,
    });
    $newTodo.value = '';
    $newDate.value = '';
    saveTodos();
    render();
    $newTodo.focus();
  }

  // 할일 토글
  function toggleTodo(id) {
    const t = todos.find((x) => x.id === id);
    if (t) {
      t.done = !t.done;
      saveTodos();
      render();
    }
  }

  // 할일 삭제
  function deleteTodo(id) {
    todos = todos.filter((x) => x.id !== id);
    saveTodos();
    render();
  }

  // 이벤트 바인딩
  $addBtn.addEventListener('click', addTodo);

  $newTodo.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') addTodo();
  });

  $list.addEventListener('click', (e) => {
    const item = e.target.closest('.todo-item');
    if (!item) return;
    const id = parseInt(item.dataset.id, 10);
    const action = e.target.dataset.action;
    if (action === 'toggle') toggleTodo(id);
    else if (action === 'delete') deleteTodo(id);
  });

  $list.addEventListener('keydown', (e) => {
    if (e.target.classList.contains('todo-checkbox') && (e.key === ' ' || e.key === 'Enter')) {
      e.preventDefault();
      const item = e.target.closest('.todo-item');
      if (item) toggleTodo(parseInt(item.dataset.id, 10));
    }
  });

  $filterBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      $filterBtns.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      filter = btn.dataset.filter;
      render();
    });
  });

  $clearDone.addEventListener('click', () => {
    const doneCount = todos.filter((t) => t.done).length;
    if (doneCount === 0) return;
    if (confirm(`완료된 ${doneCount}개의 할일을 삭제하시겠습니까?`)) {
      todos = todos.filter((t) => !t.done);
      saveTodos();
      render();
    }
  });

  // 초기 렌더
  render();
})();
