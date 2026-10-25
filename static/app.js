/* 图维绩效管理平台 · 前端 SPA */
'use strict';

/* ================= 工具 ================= */
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));

class ApiError extends Error {
  constructor(msg, status) { super(msg); this.status = status; }
}

async function api(path, method = 'GET', data) {
  const opt = { method, headers: { 'X-Requested-With': 'XMLHttpRequest' } };
  if (data !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(data);
  }
  let res;
  try {
    res = await fetch(path, opt);
  } catch (e) {
    throw new ApiError('网络连接失败', 0);
  }
  const j = await res.json().catch(() => ({ ok: false, error: '服务异常(' + res.status + ')' }));
  if (!j.ok) {
    if (res.status === 401 && state.user) {
      state.user = null;
      render();
    }
    throw new ApiError(j.error || '请求失败', res.status);
  }
  return j.data;
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/upload', {
    method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' }, body: fd,
  });
  const j = await res.json().catch(() => ({ ok: false, error: '上传失败' }));
  if (!j.ok) throw new ApiError(j.error || '上传失败', res.status);
  return j.data;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtDate(s) { return s ? String(s).slice(0, 10) : ''; }
function fmtTime(s) { return s ? String(s).slice(0, 16).replace('T', ' ') : ''; }
function pct(w) { return (Math.round(w * 1000) / 10) + '%'; }
function num(v, d = 1) { const n = Number(v); return isNaN(n) ? '-' : n.toFixed(d); }

function toast(msg, isErr) {
  let wrap = $('.toast-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'toast-wrap';
    document.body.appendChild(wrap);
  }
  const el = document.createElement('div');
  el.className = 'toast' + (isErr ? ' err' : '');
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

/* ================= 弹窗 ================= */
function openModal(title, bodyHtml, footerHtml, wide) {
  const mask = document.createElement('div');
  mask.className = 'mask';
  mask.innerHTML = `<div class="modal${wide ? ' wide' : ''}">
    <div class="hd"><span>${esc(title)}</span><span class="x" data-close>&times;</span></div>
    <div class="bd">${bodyHtml}</div>
    ${footerHtml ? `<div class="ft">${footerHtml}</div>` : ''}
  </div>`;
  document.body.appendChild(mask);
  const close = () => mask.remove();
  $('[data-close]', mask).onclick = close;
  mask.addEventListener('mousedown', e => { if (e.target === mask) close(); });
  return { el: mask, root: $('.modal', mask), close };
}

function confirmDialog(msg, danger) {
  return new Promise(resolve => {
    const m = openModal('确认操作', `<p>${esc(msg)}</p>`,
      `<button class="btn" data-no>取消</button>
       <button class="btn ${danger ? 'danger' : 'primary'}" data-yes>确定</button>`);
    $('[data-no]', m.el).onclick = () => { m.close(); resolve(false); };
    $('[data-yes]', m.el).onclick = () => { m.close(); resolve(true); };
  });
}

/* ================= 状态 ================= */
const TASK_STATUS = {
  pending_self: ['待自评', 'orange'], pending_score: ['待评分', 'blue'],
  pending_review: ['待审核', 'purple'], published: ['已发布', 'green'], closed: ['已关闭', 'gray'],
};
const ISC_STATUS = {
  pending: ['待评分', 'orange'], scored: ['待HR核对', 'blue'], hr_checked: ['待负责人审核', 'purple'],
  approved: ['待发布', 'green'], published: ['已发布', 'green'], rejected: ['已退回', 'red'],
};
const SA_STATUS = { draft: ['草稿', 'gray'], submitted: ['已提交', 'green'], returned: ['已退回', 'red'] };
const FREQ = { monthly: '月度', quarterly: '季度', both: '月度＋季度' };
const ROLE = { employee: '普通员工', hr: '绩效HR', admin: '系统管理员' };
const ACTION_TEXT = {
  login: '登录', login_fail: '登录失败', logout: '退出登录', change_password: '修改密码',
  self_assessment_submit: '提交自评', self_assessment_return: '退回自评', score_submit: '提交评分',
  hr_check: 'HR核对', approve: '审核通过', approve_reject: '审核退回', result_publish: '发布结果',
  tasks_batch_create: '批量生成任务', task_close: '关闭任务', config_save: '保存考核配置',
  user_create: '新建用户', user_update: '修改用户', user_reset_password: '重置密码',
  user_delete: '删除用户',
  user_toggle_active: '启用/停用用户', settings_save: '保存系统设置', upload: '上传附件',
};

const state = {
  user: null, perms: null, unread: 0, bands: null, page: {}, route: [], myPending: null,
};

function badge(map, key) {
  const it = map[key];
  return it ? `<span class="badge ${it[1]}">${it[0]}</span>` : esc(key);
}

async function loadMe() {
  const d = await api('/api/me');
  state.user = d.user;
  state.perms = d.perms;
  state.unread = d.unread;
  if (!state.bands) {
    try { state.bands = (await api('/api/admin/settings')).grade_bands; } catch (e) { state.bands = []; }
  }
  try {
    const tasks = await api('/api/my/tasks');
    state.myPending = tasks.filter(t => t.status === 'pending_self').length;
  } catch (e) { state.myPending = 0; }
}

function gradeOf(total) {
  if (!state.bands || !state.bands.length) return '-';
  for (const b of state.bands) if (total >= b.min) return b.grade;
  return state.bands[state.bands.length - 1].grade;
}

/* ================= 布局 ================= */
function menuHtml() {
  const p = state.perms || {};
  const cur = state.route.join('/');
  const item = (hash, ico, txt, extra) =>
    `<a href="#/${hash}" class="${cur === hash || cur.startsWith(hash + '/') ? 'active' : ''}">
       <span class="ico">${ico}</span><span class="txt">${txt}</span>${extra || ''}</a>`;
  const pend = state.myPending;
  const pendBadge = pend ? `<span class="menu-badge">${pend > 99 ? '99+' : pend}</span>` : '';
  let h = `<div class="group">我的</div>` +
    item('my/dashboard', '台', '我的工作台') +
    item('my/tasks', '任', '我的任务', pendBadge) +
    item('my/results', '果', '我的绩效结果');
  if (p.supervisor) h += `<div class="group">主管</div>` + item('supervisor/tasks', '评', '评分任务');
  if (p.approver && !p.hr) h += item('hr/scores', '审', '评分审批');
  if (p.hr) {
    h += `<div class="group">绩效HR</div>` + item('hr/overview', '台', '工作台') +
      item('hr/configs', '配', '考核配置') + item('hr/tasks', '务', '考核任务') +
      item('hr/scores', '审', '评分审批') + item('hr/results', '发', '结果发布');
  }
  if (p.admin) h += `<div class="group">系统管理</div>` + item('admin/users', '户', '用户管理') +
    item('admin/settings', '则', '等级规则') + item('admin/logs', '志', '审计日志');
  return h;
}

function layout(title, content) {
  const u = state.user;
  return `<div class="layout">
    <aside class="sidebar">
      <div class="brand"><div class="name">图维绩效</div><div class="en">TUWEI PERFORMANCE</div></div>
      <nav class="menu">${menuHtml()}</nav>
      <div class="me"><div class="n">${esc(u.name)}</div><div class="r">${esc(u.department || '')} · ${ROLE[u.role] || u.role}</div></div>
    </aside>
    <div class="main">
      <div class="topbar">
        <div class="title">${esc(title)}</div>
        <div class="spacer"></div>
        <div class="bell" id="bell">🔔<span class="badge" id="bellBadge" style="display:none">0</span></div>
        <button class="btn sm" id="btnPwd">修改密码</button>
        <button class="btn sm" id="btnLogout">退出登录</button>
      </div>
      <div class="content">${content}</div>
    </div>
  </div>`;
}

function bindLayout() {
  $('#btnLogout').onclick = async () => {
    await api('/api/logout', 'POST', {}).catch(() => {});
    state.user = null;
    location.hash = '';
    render();
  };
  $('#btnPwd').onclick = openChangePwd;
  const bell = $('#bell');
  bell.onclick = async e => {
    e.stopPropagation();
    if ($('.bell-drop')) { $$('.bell-drop').forEach(x => x.remove()); return; }
    let items = [];
    try { items = await api('/api/notifications'); } catch (err) { toast(err.message, 1); return; }
    state.unread = 0; updateBell();
    const drop = document.createElement('div');
    drop.className = 'bell-drop';
    drop.innerHTML = `<div class="hd">通知</div>` + (items.length ? items.map(n =>
      `<div class="item" data-link="${esc(n.link || '')}">
         <div class="t">${esc(n.title)}</div><div class="b">${esc(n.body || '')}</div>
         <div class="b">${esc(fmtTime(n.created_at))}</div></div>`).join('')
      : '<div class="empty">暂无通知</div>');
    document.body.appendChild(drop);
    $$('.item', drop).forEach(el => el.onclick = () => {
      drop.remove();
      if (el.dataset.link) location.hash = el.dataset.link;
    });
    setTimeout(() => document.addEventListener('click', function h() {
      drop.remove(); document.removeEventListener('click', h);
    }), 0);
  };
}

function updateBell() {
  const b = $('#bellBadge');
  if (!b) return;
  b.style.display = state.unread > 0 ? 'flex' : 'none';
  b.textContent = state.unread > 99 ? '99+' : state.unread;
}

/* ================= 登录 ================= */
function loginView(errMsg) {
  return `<div class="login-wrap"><div class="login-card">
    <div class="logo"><div class="mark">图</div><h1>图维绩效管理平台</h1><div class="sub">TUWEI PERFORMANCE SYSTEM</div></div>
    ${errMsg ? `<div class="alert warn">${esc(errMsg)}</div>` : ''}
    <form id="loginForm">
      <div class="field"><label>账号</label><input class="input" id="lgUser" autocomplete="username" placeholder="请输入账号"></div>
      <div class="field"><label>密码</label><input class="input" id="lgPwd" type="password" autocomplete="current-password" placeholder="请输入密码"></div>
      <button class="btn primary block" type="submit">登 录</button>
    </form>
    <div class="hint">初始密码由管理员发放，首次登录后请立即修改密码。如忘记密码，请联系绩效HR重置。</div>
  </div></div>`;
}

function bindLogin(errMsg) {
  $('#loginForm').onsubmit = async e => {
    e.preventDefault();
    const username = $('#lgUser').value.trim();
    const password = $('#lgPwd').value;
    if (!username || !password) return toast('请输入账号和密码', 1);
    try {
      await api('/api/login', 'POST', { username, password });
    } catch (err) {
      return renderLogin(err.message);
    }
    await loadMe();
    toast('登录成功');
    afterLogin();
  };
}

function renderLogin(errMsg) {
  $('#app').innerHTML = loginView(errMsg);
  bindLogin(errMsg);
}

function afterLogin() {
  if (state.user.must_change_password) {
    openChangePwd(true);
  }
  const p = state.perms;
  const target = p.hr ? '#/hr/overview' : (p.supervisor ? '#/supervisor/tasks' : '#/my/dashboard');
  if (!location.hash || location.hash === '#/' || location.hash === '#/login') location.hash = target;
  render();
}

/* ================= 修改密码 ================= */
function openChangePwd(force) {
  const m = openModal('修改密码', `
    <div class="field"><label>原密码</label><input class="input" id="pwdOld" type="password"></div>
    <div class="field"><label>新密码</label><input class="input" id="pwdNew" type="password" placeholder="至少 8 位，包含字母和数字"></div>
    <div class="field"><label>确认新密码</label><input class="input" id="pwdNew2" type="password"></div>`,
    `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>确认修改</button>`);
  if (force) $('[data-no]', m.el).style.display = 'none';
  $('[data-no]', m.el).onclick = m.close;
  $('[data-ok]', m.el).onclick = async () => {
    const old_password = $('#pwdOld').value, new_password = $('#pwdNew').value;
    if (new_password !== $('#pwdNew2').value) return toast('两次输入的新密码不一致', 1);
    try {
      await api('/api/change-password', 'POST', { old_password, new_password });
      toast('密码已修改');
      state.user.must_change_password = 0;
      m.close();
    } catch (err) { toast(err.message, 1); }
  };
}

/* ================= 通用片段 ================= */
function pageHead(title, sub, opsHtml) {
  return `<div class="flex between mb16"><div><div style="font-size:18px;font-weight:600">${esc(title)}</div>
    ${sub ? `<div class="muted small mt8">${esc(sub)}</div>` : ''}</div>
    <div class="flex">${opsHtml || ''}</div></div>`;
}

function kv(label, value, raw) {
  return `<div class="flex between" style="padding:7px 0;border-bottom:1px solid var(--gray-bg)">
    <span class="muted">${esc(label)}</span><span>${raw ? value : (value == null || value === '' ? '-' : esc(value))}</span></div>`;
}

function indicatorCards(indicators, renderItem) {
  return indicators.map((ind, i) => `<div class="ind-card">
    <div class="ind-hd"><span class="no">${i + 1}</span><span class="nm">${esc(ind.name)}</span>
      <span class="wt">权重 ${pct(ind.weight)}</span></div>
    <div class="ind-bd">
      <div class="std">
        <div><b>100% 目标值：</b>${esc(ind.standard_100 || '未设置')}</div>
        <div><b>120% 目标值：</b>${esc(ind.standard_120 || '未设置')}</div>
        <div><b>数据来源：</b>${esc(ind.data_source || '未设置')}</div>
      </div>
      ${renderItem ? renderItem(ind, i) : ''}
    </div></div>`).join('');
}

function attachList(atts) {
  if (!atts || !atts.length) return '<div class="muted small">无附件</div>';
  return '<div class="file-list">' + atts.map(a =>
    `<div class="f"><a href="/api/files/${encodeURIComponent(a.stored_name)}" target="_blank">${esc(a.filename)}</a>
     <span class="muted small">(${(a.size / 1024).toFixed(0)} KB)</span></div>`).join('') + '</div>';
}

/* ================= 视图：我的工作台 ================= */
async function viewMyDashboard() {
  const tasks = await api('/api/my/tasks');
  const pending = tasks.filter(t => t.status === 'pending_self');
  const ongoing = tasks.filter(t => t.status === 'pending_score' || t.status === 'pending_review');
  const done = tasks.filter(t => t.status === 'published');
  state.myPending = pending.length;

  const todoCard = t => {
    const returned = t.sa_status === 'returned';
    return `<div class="card todo${t.overdue ? ' overdue' : ''}"><div class="bd flex between wrap gap12">
      <div class="flex1" style="min-width:240px">
        <div class="flex center gap8 mb8">
          <span class="todo-period">${esc(t.period_code)}</span>
          <span class="badge ${t.period_type === 'monthly' ? 'blue' : 'purple'}">${t.period_type === 'monthly' ? '月度' : '季度'}考核</span>
          ${returned ? '<span class="badge red">主管已退回，请修改</span>' : ''}
          ${t.overdue ? '<span class="badge red">已逾期</span>' : ''}
        </div>
        <div class="muted small">任务编号 ${esc(t.task_no)} · 评分主管：${esc(t.supervisor_name || '未指定')}<br>
          自评截止：${fmtDate(t.self_deadline) ? fmtDate(t.self_deadline) + ' 前' : '不限'}</div>
      </div>
      <a class="btn primary lg" href="#/my/tasks/${t.id}">${returned ? '修改后重新提交' : '立即填写自评'}</a>
    </div></div>`;
  };

  const simpleRows = (list, emptyTxt) => list.length ? `<table class="tbl"><thead><tr>
      <th>任务编号</th><th>类型</th><th>周期</th><th>状态</th><th>操作</th>
    </tr></thead><tbody>${list.map(t => `<tr>
      <td>${esc(t.task_no)}</td>
      <td>${t.period_type === 'monthly' ? '月度' : '季度'}</td>
      <td class="nowrap">${esc(t.period_code)}</td>
      <td>${badge(TASK_STATUS, t.status)}</td>
      <td>${t.status === 'published'
        ? `<a class="btn sm" href="#/my/results/${t.result_id}">查看结果</a>`
        : `<a class="btn sm" href="#/my/tasks/${t.id}">查看</a>`}</td>
    </tr>`).join('')}</tbody></table>` : `<div class="empty">${emptyTxt}</div>`;

  $('#app').innerHTML = layout('我的工作台', `
    ${pageHead('我的工作台', esc(state.user.name) + ' · ' + esc(state.user.department || '') + ' · ' + esc(state.user.position || ''))}
    <div class="grid c3 mb16">
      <div class="card stat o"><div class="num">${pending.length}</div><div class="lbl">待填写自评</div></div>
      <div class="card stat b"><div class="num">${ongoing.length}</div><div class="lbl">评分进行中</div></div>
      <div class="card stat g"><div class="num">${done.length}</div><div class="lbl">已发布结果</div></div>
    </div>
    <div class="sec-title">待填写自评${pending.length ? '（共 ' + pending.length + ' 项）' : ''}</div>
    ${pending.length ? pending.map(todoCard).join('')
      : `<div class="card"><div class="bd empty">当前没有待填写的自评。考核任务由绩效HR按周期发放，截止前请留意右上角通知提醒。</div></div>`}
    <div class="sec-title mt16">评分进行中</div>
    <div class="card"><div class="bd" style="padding:0">${simpleRows(ongoing, '暂无进行中的考核')}</div></div>
    <div class="sec-title mt16">已发布结果</div>
    <div class="card"><div class="bd" style="padding:0">${simpleRows(done, '暂无已发布的绩效结果')}</div></div>`);
  bindLayout(); updateBell();
}

/* ================= 视图：我的任务 ================= */
async function viewMyTasks() {
  const tasks = await api('/api/my/tasks');
  state.myPending = tasks.filter(t => t.status === 'pending_self').length;
  const now = new Date().toISOString().slice(0, 10);
  const rows = tasks.map(t => {
    let act = '';
    if (t.status === 'pending_self') act = `<button class="btn sm primary" data-act="fill" data-id="${t.id}">填写自评</button>`;
    else if (t.status === 'pending_score' && t.sa_status === 'submitted') act = `<button class="btn sm" data-act="fill" data-id="${t.id}">查看自评</button>`;
    else if (t.status === 'pending_score' && t.sa_status === 'returned') act = `<button class="btn sm primary" data-act="fill" data-id="${t.id}">修改自评</button>`;
    else if (t.status === 'published') act = `<a class="btn sm" href="#/my/results/${t.result_id}">查看结果</a>`;
    else act = `<button class="btn sm" data-act="fill" data-id="${t.id}">查看</button>`;
    return `<tr>
      <td>${esc(t.task_no)}</td>
      <td>${t.period_type === 'monthly' ? '月度' : '季度'}</td>
      <td class="nowrap">${esc(t.period_code)}</td>
      <td>${badge(TASK_STATUS, t.status)}${t.overdue ? ' <span class="badge red">已逾期</span>' : ''}</td>
      <td class="nowrap">${fmtDate(t.self_deadline) || '-'}</td>
      <td class="nowrap">${esc(t.supervisor_name || '-')}</td>
      <td class="acts">${act}</td></tr>`;
  }).join('');
  $('#app').innerHTML = layout('我的任务', `
    ${pageHead('我的任务', '每位员工只可见本人的考核任务与结果')}
    <div class="card"><div class="bd" style="padding:0">
      ${tasks.length ? `<table class="tbl"><thead><tr>
        <th>任务编号</th><th>类型</th><th>周期</th><th>状态</th><th>自评截止</th><th>评分主管</th><th>操作</th>
      </tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty">暂无考核任务</div>'}
    </div></div>`);
  bindLayout(); updateBell();
  $$('[data-act="fill"]').forEach(b => b.onclick = () => { location.hash = '#/my/tasks/' + b.dataset.id; });
}

/* ================= 视图：自评表单（字段对齐 Excel 模板） ================= */
async function viewSelfForm(taskId) {
  const t = await api('/api/my/tasks/' + taskId);
  const sa = t.self_assessment;
  const editable = t.status === 'pending_self';
  const draftKey = 'tp_draft_' + taskId;
  const u = state.user;
  // 指标定义以员工已提交版本为准（后端已回填缺失字段），未提交则用任务快照
  const eff = (sa && sa.items) ? sa.items : t.indicators;

  // 行模型：员工可增加/删除指标行，所有编辑直接写入模型后重渲染
  let rows = eff.map(ind => ({
    name: ind.name || '', standard_100: ind.standard_100 || '', standard_120: ind.standard_120 || '',
    data_source: ind.data_source || '', weight: ind.weight == null ? null : ind.weight,
    completion: ind.completion || '', self_score: ind.self_score == null ? null : ind.self_score,
  }));
  const selected = new Set();

  const readCell = (i, key) => {
    const src = rows[i];
    const val = src ? (src[key] == null ? '' : src[key]) : '';
    return val === '' && !editable && ['name', 'standard_100', 'standard_120', 'data_source'].includes(key)
      ? '未设置' : val;
  };
  const cell = (i, key) => {
    if (!editable) {
      const cls = key === 'name' ? 'cell-text nm' : (key === 'data_source' ? 'cell-text small' : 'cell-text');
      const v = key === 'weight' ? pct(rows[i] && rows[i].weight) : readCell(i, key);
      return `<td class="${cls}">${esc(v)}</td>`;
    }
    if (key === 'self_score') {
      return `<td><input class="input ind-score" data-i="${i}" type="number" min="0" max="120" step="1"
        value="${rows[i] && rows[i].self_score != null ? rows[i].self_score : ''}"></td>`;
    }
    if (key === 'completion') {
      return `<td><textarea class="textarea ind-completion" data-i="${i}"
        placeholder="请填写本项指标的实际完成情况">${esc(rows[i] && rows[i].completion || '')}</textarea></td>`;
    }
    if (key === 'weight') {
      return `<td class="center"><input class="input ind-w" data-i="${i}" type="number" min="10" max="60" step="1"
        value="${rows[i] && rows[i].weight != null ? Math.round(rows[i].weight * 100) : ''}"></td>`;
    }
    if (key === 'name') {
      return `<td><input class="input ind-name" data-i="${i}" value="${esc(rows[i] && rows[i].name || '')}" placeholder="指标名称"></td>`;
    }
    const ph = key === 'standard_100' ? '请填写 100% 目标值衡量标准'
      : key === 'standard_120' ? '请填写 120% 目标值衡量标准' : '部门：文档名称';
    const cls = key === 'standard_100' ? 'ind-100' : key === 'standard_120' ? 'ind-120' : 'ind-src';
    return `<td><textarea class="textarea ${cls}" data-i="${i}" placeholder="${ph}">${esc(rows[i] && rows[i][key] || '')}</textarea></td>`;
  };

  const headCols = editable
    ? `<th style="width:34px"><input type="checkbox" id="chkAll" title="全选"></th><th style="width:36px">序号</th>`
    : `<th style="width:36px">序号</th>`;

  const renderBody = () => {
    const trs = rows.map((r, i) => `<tr data-row="${i}" class="${selected.has(i) ? 'row-sel' : ''}">
      ${editable ? `<td class="center"><input type="checkbox" class="chk-row" data-i="${i}" ${selected.has(i) ? 'checked' : ''}></td>` : ''}
      <td class="nowrap center">${i + 1}</td>
      ${cell(i, 'name')}
      ${cell(i, 'standard_100')}
      ${cell(i, 'standard_120')}
      ${cell(i, 'data_source')}
      ${cell(i, 'weight')}
      ${cell(i, 'completion')}
      ${cell(i, 'self_score')}
    </tr>`).join('');
    $('#tplBody').innerHTML = trs;
    // 全选框状态
    const all = $('#chkAll');
    if (all) all.checked = rows.length > 0 && selected.size === rows.length;
    // 工具栏按钮状态
    const btnDel = $('#btnDelRow');
    if (btnDel) {
      btnDel.disabled = selected.size === 0;
      btnDel.textContent = selected.size ? `删除选中（${selected.size}）` : '删除选中';
    }
    const btnAdd = $('#btnAddRow');
    if (btnAdd) btnAdd.disabled = false;
    updateWsum();
    bindRowEvents();
  };

  const bindRowEvents = () => {
    $$('.chk-row').forEach(el => el.onchange = () => {
      const i = Number(el.dataset.i);
      if (el.checked) selected.add(i); else selected.delete(i);
      renderBody();
    });
    const all = $('#chkAll');
    if (all) all.onchange = () => {
      selected.clear();
      if (all.checked) rows.forEach((_, i) => selected.add(i));
      renderBody();
    };
    const setVal = (el, key) => {
      const i = Number(el.dataset.i);
      if (!rows[i]) return;
      if (key === 'weight') {
        // 权重输入框按百分数填写（填 15 表示 15%），模型统一存小数（0.15），
        // 与初始数据、本地暂存、提交载荷保持一致；否则勾选其他行触发重渲染时
        // 会按小数再乘 100，导致已填的权重显示跳变（如 20 变 2000）
        const n = el.value === '' ? NaN : Number(el.value);
        rows[i].weight = isNaN(n) ? null : n / 100;
      } else {
        rows[i][key] = key === 'self_score' ? (el.value === '' ? null : el.value) : el.value;
      }
      updateWsum();
    };
    $$('.ind-name').forEach(el => el.addEventListener('input', () => setVal(el, 'name')));
    $$('.ind-100').forEach(el => el.addEventListener('input', () => setVal(el, 'standard_100')));
    $$('.ind-120').forEach(el => el.addEventListener('input', () => setVal(el, 'standard_120')));
    $$('.ind-src').forEach(el => el.addEventListener('input', () => setVal(el, 'data_source')));
    $$('.ind-w').forEach(el => el.addEventListener('input', () => setVal(el, 'weight')));
    $$('.ind-completion').forEach(el => el.addEventListener('input', () => setVal(el, 'completion')));
    $$('.ind-score').forEach(el => el.addEventListener('input', () => setVal(el, 'self_score')));
  };

  const updateWsum = () => {
    let sum = 0, wsum = 0, ok = true;
    rows.forEach((r) => {
      const w = r.weight == null || r.weight === '' || isNaN(Number(r.weight))
        ? 0 : (Number(r.weight) > 1 ? Number(r.weight) / 100 : Number(r.weight));
      wsum += w;
      const v = r.self_score == null || r.self_score === '' || isNaN(Number(r.self_score))
        ? null : Number(r.self_score);
      if (v == null) { ok = false; return; }
      sum += v * w;
    });
    const wEl = $('#wsumWeight');
    if (wEl) {
      const wPct = Math.round(wsum * 100);
      wEl.textContent = wPct + '%';
      wEl.className = 'nowrap center wsum ' + (Math.abs(wsum - 1) < 0.005 ? 'ok' : 'bad');
    }
    const txt = ok ? num(sum, 2) + ' 分' : '待完成';
    ['#wsum', '#wsum2'].forEach(s => { const el = $(s); if (el) { el.textContent = txt; el.className = 'wsum ' + (ok ? 'ok' : 'bad'); } });
  };

  $('#app').innerHTML = layout('考核自评 · ' + t.period_code, `
    ${pageHead(t.period_code + (t.period_type === 'monthly' ? ' 月度考核' : ' 季度考核'),
      '任务编号 ' + t.task_no,
      `<button class="btn" onclick="location.hash='#/my/tasks'">返回列表</button>`)}
    ${sa && sa.status === 'returned' ? `<div class="alert warn">主管退回原因：${esc(sa.supervisor_comment || '')}，请修改后重新提交。</div>` : ''}
    ${t.status === 'pending_score' ? `<div class="alert info">自评已提交，等待评分主管评分，当前不可修改。</div>` : ''}
    ${t.result ? `<div class="alert info">本周期结果已发布，<a href="#/my/results/${t.result.id}">查看绩效结果</a>。</div>` : ''}

    <div class="card mb16"><div class="hd">业务目标设定及评估 · 员工自评</div><div class="bd">
      <div class="tpl-info">
        <div><label>员工姓名</label><span>${esc(u.name)}</span></div>
        <div><label>职位名称</label><span>${esc(u.position || '-')}</span></div>
        <div><label>所属部门</label><span>${esc(u.department || '-')}</span></div>
        <div><label>直属主管</label><span>${esc(t.supervisor_name || '未指定')}</span></div>
        <div><label>评估周期</label><span>${fmtDate(t.period_start) || '-'} ~ ${fmtDate(t.period_end) || '-'}</span></div>
        <div><label>任务编号</label><span>${esc(t.task_no)}</span></div>
      </div>
    </div></div>

    <div class="card mb16"><div class="hd flex between">
      <span>业务目标设定及评估 · 指标明细</span>
      ${editable ? `<span class="flex" style="gap:8px">
        <button class="btn primary" id="btnAddRow">＋ 增加指标</button>
        <button class="btn" id="btnDelRow" disabled>删除选中</button>
      </span>` : ''}
    </div><div class="bd" style="padding:0">
      <div class="tbl-wrap"><table class="tbl tpl-tbl">
        <thead><tr>
          ${headCols}
          <th style="min-width:150px">目标/关键业务领域<br>名称及描述</th>
          <th style="min-width:170px">衡量标准 &amp;100%目标值</th>
          <th style="min-width:170px">衡量标准 &amp;120%目标值</th>
          <th style="min-width:110px">数据来源<br>部门：文档名称</th>
          <th style="width:64px">权重%<br>（10%-60%）</th>
          <th style="min-width:230px">评估结果<br>（实际完成情况）</th>
          <th style="min-width:88px">员工自评<br>（0-120分）</th>
        </tr></thead>
        <tbody id="tplBody"></tbody>
        <tfoot><tr>
          <td colspan="${editable ? 6 : 5}" class="nowrap">合计</td>
          <td class="nowrap center" id="wsumWeight">-</td>
          <td colspan="2" class="nowrap">加权自评总分：<b id="wsum" class="wsum">-</b></td>
        </tr></tfoot>
      </table></div>
      ${editable ? `<div class="bd muted small" style="border-top:1px solid var(--border)">
        可点击「＋ 增加指标」添加自定义指标行，或勾选行后点击「删除选中」移除；序号自动重排，权重合计须为 100%（单项 10%-60%），至少保留一项指标。</div>` : ''}
    </div></div>

    <div class="alert info mb16">评估加减分（-10~+10）由总监级及以上人员在评分环节填写；主管评分与同级同事评分由评分人填写，员工无需填写。</div>

    <div class="card mb16"><div class="hd">本期总结</div><div class="bd">
      <div class="field"><label>本期成果</label>
        <textarea class="textarea" id="fAch" ${editable ? '' : 'disabled'}>${esc((sa && sa.achievements) || '')}</textarea></div>
      <div class="field"><label>未完成原因（选填）</label>
        <textarea class="textarea" id="fUnf" ${editable ? '' : 'disabled'}>${esc((sa && sa.unfinished_reason) || '')}</textarea></div>
      <div class="field"><label>需要支持（选填）</label>
        <textarea class="textarea" id="fSup" ${editable ? '' : 'disabled'}>${esc((sa && sa.support_needed) || '')}</textarea></div>
      <div class="field"><label>工作证据附件（选填，支持 pdf/图片/office 文档，单个≤10MB）</label>
        <div id="fileBox">${attachList(sa && sa.attachments)}</div>
        ${editable ? `<div class="flex mt8"><input type="file" id="fileIn" class="input flex1">
          <button class="btn" id="btnUp">上传</button></div>` : ''}
      </div>
    </div></div>

    <div class="card"><div class="hd">员工确认签字</div><div class="bd">
      ${!editable && sa ? `<div class="kv-line"><span class="muted">签字</span><span class="sign-name">${esc(sa.signature || '-')}</span></div>
        <div class="kv-line"><span class="muted">提交时间</span><span>${fmtTime(sa.submitted_at) || '-'}</span></div>`
      : `<label class="confirm-line"><input type="checkbox" id="saConfirm" ${sa && sa.confirmed ? 'checked' : ''}>
          本人确认以上自评内容真实有效</label>
        <div class="field"><label>签名（请输入姓名，作为电子签名）</label>
          <input class="input" id="saSign" style="max-width:260px" placeholder="请输入姓名"
            value="${esc((sa && sa.signature) || '')}"></div>`}
    </div>
    ${editable ? `<div class="ft flex between">
      <span class="muted small">加权自评：<b id="wsum2" class="wsum">-</b></span>
      <span><button class="btn" id="btnSaveDraft">暂存本地</button>
      <button class="btn primary" id="btnSubmit">提交自评</button></span>
    </div>` : ''}</div>`);
  bindLayout(); updateBell();
  renderBody();
  updateWsum();

  if (!editable) return;
  let attachments = (sa && sa.attachments) ? sa.attachments.slice() : [];

  const readForm = () => ({ items: rows.slice() });
  const saveDraft = () => {
    const { items } = readForm();
    localStorage.setItem(draftKey, JSON.stringify({
      items, ach: $('#fAch').value, unf: $('#fUnf').value, sup: $('#fSup').value,
      confirm: $('#saConfirm').checked, sign: $('#saSign').value, attachments,
    }));
    toast('已暂存到本地浏览器');
  };
  const restoreDraft = () => {
    const d = JSON.parse(localStorage.getItem(draftKey) || 'null');
    if (!d) return;
    if (Array.isArray(d.items) && d.items.length) {
      rows = d.items.map(it => ({
        name: it.name || '', standard_100: it.standard_100 || '', standard_120: it.standard_120 || '',
        data_source: it.data_source || '',
        weight: it.weight == null ? null : (it.weight > 1 ? it.weight / 100 : it.weight),
        completion: it.completion || '', self_score: it.self_score == null ? null : it.self_score,
      }));
      renderBody();
    }
    if (d.ach) $('#fAch').value = d.ach;
    if (d.unf) $('#fUnf').value = d.unf;
    if (d.sup) $('#fSup').value = d.sup;
    if (d.confirm) $('#saConfirm').checked = true;
    if (d.sign) $('#saSign').value = d.sign;
    if (d.attachments && d.attachments.length) {
      attachments = d.attachments;
      $('#fileBox').innerHTML = attachList(attachments);
    }
    updateWsum();
  };
  restoreDraft();

  $('#btnSaveDraft').onclick = saveDraft;
  $('#btnAddRow').onclick = () => {
    rows.push({ name: '', standard_100: '', standard_120: '', data_source: '',
                weight: null, completion: '', self_score: null });
    selected.clear();
    renderBody();
    const inputs = $$('#tplBody .ind-name');
    if (inputs.length) inputs[inputs.length - 1].focus();
    toast('已添加一行，请填写指标内容');
  };
  $('#btnDelRow').onclick = () => {
    if (selected.size === 0) return toast('请先勾选要删除的行', 1);
    if (selected.size >= rows.length) return toast('至少需要保留一项指标', 1);
    rows = rows.filter((_, i) => !selected.has(i));
    selected.clear();
    renderBody();
    toast('已删除选中指标，序号自动重排');
  };
  $('#btnUp').onclick = async () => {
    const f = $('#fileIn').files[0];
    if (!f) return toast('请选择文件', 1);
    try {
      const r = await uploadFile(f);
      attachments.push(r);
      $('#fileBox').innerHTML = attachList(attachments);
      $('#fileIn').value = '';
      toast('上传成功');
    } catch (err) { toast(err.message, 1); }
  };
  $('#btnSubmit').onclick = async () => {
    const { items } = readForm();
    let wsum = 0;
    for (const it of items) {
      if (!it.name) return toast('有指标未填写名称', 1);
      if (!it.completion) return toast('有指标未填写实际完成情况', 1);
      if (it.self_score == null || it.self_score === '' || isNaN(Number(it.self_score))) return toast('有指标未填写自评分', 1);
      const w = it.weight == null || it.weight === '' || isNaN(Number(it.weight))
        ? NaN : (Number(it.weight) > 1 ? Number(it.weight) / 100 : Number(it.weight));
      if (isNaN(w)) return toast('有指标未填写权重', 1);
      if (w < 0.1 || w > 0.6) {
        return toast('权重「' + it.name + '」须在 10%-60% 之间', 1);
      }
      wsum += w;
    }
    if (Math.abs(wsum - 1) > 0.005) {
      return toast('各指标权重合计须为 100%，当前为 ' + Math.round(wsum * 100) + '%', 1);
    }
    if (!$('#saConfirm').checked) return toast('请先勾选确认「本人确认以上自评内容真实有效」', 1);
    const signature = $('#saSign').value.trim();
    if (signature.length < 2) return toast('请填写员工确认签字（签名）', 1);
    const payloadItems = items.map(it => ({
      name: it.name, standard_100: it.standard_100, standard_120: it.standard_120,
      data_source: it.data_source,
      weight: Number(it.weight) > 1 ? Number(it.weight) / 100 : Number(it.weight),
      completion: it.completion, self_score: Number(it.self_score),
    }));
    try {
      await api('/api/my/tasks/' + taskId + '/self-assessment', 'POST', {
        items: payloadItems, achievements: $('#fAch').value.trim(), unfinished_reason: $('#fUnf').value.trim(),
        support_needed: $('#fSup').value.trim(), attachments,
        signature, confirmed: true,
      });
      localStorage.removeItem(draftKey);
      state.myPending = Math.max(0, (state.myPending || 1) - 1);
      toast('自评已提交');
      location.hash = '#/my/tasks';
    } catch (err) { toast(err.message, 1); }
  };
}

/* ================= 视图：我的结果 ================= */
async function viewMyResults() {
  const rows = await api('/api/my/results');
  $('#app').innerHTML = layout('我的绩效结果', `
    ${pageHead('我的绩效结果', '仅显示已正式发布的结果，内部评分过程不对外展示')}
    <div class="card"><div class="bd" style="padding:0">
      ${rows.length ? `<table class="tbl"><thead><tr>
        <th>周期</th><th>类型</th><th>总分</th><th>等级</th><th>奖金系数</th><th>发布时间</th><th>操作</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td class="nowrap">${esc(r.period_code)}</td>
        <td>${r.period_type === 'monthly' ? '月度' : '季度'}</td>
        <td class="nowrap"><b>${num(r.total_score, 2)}</b></td>
        <td><span class="badge blue">${esc(r.grade)}</span></td>
        <td class="nowrap">${num(r.bonus_factor, 3)}</td>
        <td class="nowrap">${fmtDate(r.published_at)}</td>
        <td><a class="btn sm" href="#/my/results/${r.id}">查看</a></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">暂无已发布的绩效结果</div>'}
    </div></div>`);
  bindLayout(); updateBell();
}

async function viewResultDetail(resultId) {
  const r = await api('/api/my/results/' + resultId);
  $('#app').innerHTML = layout('绩效结果 · ' + r.period_code, `
    ${pageHead(r.period_code + (r.period_type === 'monthly' ? ' 月度绩效结果' : ' 季度绩效结果'),
      '发布时间 ' + fmtDate(r.published_at),
      `<button class="btn" onclick="location.hash='#/my/results'">返回列表</button>`)}
    <div class="grid c4 mb16">
      <div class="card stat b"><div class="num">${num(r.total_score, 2)}</div><div class="lbl">总得分（满分120）</div></div>
      <div class="card stat g"><div class="num">${esc(r.grade)}</div><div class="lbl">绩效等级</div></div>
      <div class="card stat o"><div class="num">${num(r.bonus_factor, 3)}</div><div class="lbl">当期奖金系数</div></div>
      <div class="card stat p"><div class="num">${num(r.base_score, 2)}</div><div class="lbl">业务目标得分</div></div>
    </div>
    <div class="card"><div class="hd">各指标最终得分</div><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>得分</th><th>加权得分</th></tr></thead>
      <tbody>${r.items.map(it => `<tr><td>${esc(it.name)}</td><td>${pct(it.weight)}</td>
        <td>${num(it.score, 1)}</td><td>${num(it.weighted, 2)}</td></tr>`).join('')}</tbody></table>
    </div></div>
    <div class="card"><div class="hd">评语与改进建议</div><div class="bd">
      <div class="mb16"><div class="muted small mb8">公开反馈</div><div>${esc(r.public_feedback).replace(/\n/g, '<br>')}</div></div>
      <div><div class="muted small mb8">改进建议</div><div>${r.improvement ? esc(r.improvement).replace(/\n/g, '<br>') : '无'}</div></div>
    </div></div>`);
  bindLayout(); updateBell();
}

/* ================= 视图：主管评分 ================= */
async function viewSupervisorTasks() {
  const rows = await api('/api/supervisor/tasks');
  const filter = state.page.supFilter || 'all';
  const show = rows.filter(r => filter === 'all' ? true
    : filter === 'pending' ? r.status === 'pending_score' : r.status !== 'pending_score');
  const tab = (k, txt) => `<a href="javascript:void(0)" data-f="${k}" class="${filter === k ? 'active' : ''}">${txt}</a>`;
  $('#app').innerHTML = layout('评分任务', `
    ${pageHead('评分任务', '仅显示分配给您的评分任务，其他主管负责的记录不可见')}
    <div class="tabs">${tab('pending', '待评分')}${tab('done', '已评分/审核中')}${tab('all', '全部')}</div>
    <div class="card"><div class="bd" style="padding:0">
      ${show.length ? `<table class="tbl"><thead><tr>
        <th>任务编号</th><th>员工</th><th>部门</th><th>类型</th><th>周期</th><th>自评状态</th><th>任务状态</th><th>操作</th>
      </tr></thead><tbody>${show.map(r => `<tr>
        <td>${esc(r.task_no)}</td><td>${esc(r.user_name)}</td><td>${esc(r.department || '-')}</td>
        <td>${r.period_type === 'monthly' ? '月度' : '季度'}</td><td class="nowrap">${esc(r.period_code)}</td>
        <td>${r.status === 'pending_self' ? '<span class="badge orange">填写中</span>'
          : r.status === 'pending_score' ? '<span class="badge green">已提交</span>'
          : badge(ISC_STATUS, r.isc_status || 'pending')}</td>
        <td>${badge(TASK_STATUS, r.status)}</td>
        <td class="acts">${r.status === 'pending_score'
          ? `<button class="btn sm primary" data-score="${r.id}">评分</button>
             <button class="btn sm danger" data-return="${r.id}">退回</button>`
          : `<button class="btn sm" data-view="${r.id}">查看</button>`}</td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">暂无任务</div>'}
    </div></div>`);
  bindLayout(); updateBell();
  $$('[data-f]').forEach(a => a.onclick = () => { state.page.supFilter = a.dataset.f; viewSupervisorTasks(); });
  $$('[data-score]').forEach(b => b.onclick = () => { location.hash = '#/supervisor/tasks/' + b.dataset.score; });
  $$('[data-view]').forEach(b => b.onclick = () => { location.hash = '#/supervisor/tasks/' + b.dataset.view; });
  $$('[data-return]').forEach(b => b.onclick = async () => {
    const m = openModal('退回自评', `
      <div class="field"><label>退回原因（将通知员工修改后重新提交）</label>
      <textarea class="textarea" id="rtComment"></textarea></div>`,
      `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>确认退回</button>`);
    $('[data-no]', m.el).onclick = m.close;
    $('[data-ok]', m.el).onclick = async () => {
      const comment = $('#rtComment').value.trim();
      if (!comment) return toast('请填写退回原因', 1);
      try {
        await api('/api/supervisor/tasks/' + b.dataset.return + '/return', 'POST', { comment });
        toast('已退回'); m.close(); viewSupervisorTasks();
      } catch (err) { toast(err.message, 1); }
    };
  });
}

async function viewSupervisorScore(taskId) {
  const t = await api('/api/supervisor/tasks/' + taskId);
  const sa = t.self_assessment;
  const isc = t.internal_score;
  // 员工可能已在自评中修改指标名称/标准/权重：主管评分以员工版为基准
  const eff = t.effective_indicators || t.indicators;
  const editable = t.status === 'pending_score' || (isc && isc.status === 'scored' && t.status === 'pending_review');
  $('#app').innerHTML = layout('评分 · ' + (t.user_name || '') + ' ' + t.period_code, `
    ${pageHead(t.user_name + ' · ' + t.period_code + (t.period_type === 'monthly' ? ' 月度考核' : ' 季度考核'),
      t.department + ' · ' + (t.position || '') + ' · 任务编号 ' + t.task_no,
      `<button class="btn" onclick="location.hash='#/supervisor/tasks'">返回列表</button>`)}
    <div class="card"><div class="hd">员工自评</div><div class="bd">
      ${sa ? `<dl class="dl mb16">
        <dt>提交时间</dt><dd>${fmtTime(sa.submitted_at)}</dd>
        <dt>本期成果</dt><dd>${esc(sa.achievements || '-')}</dd>
        <dt>未完成原因</dt><dd>${esc(sa.unfinished_reason || '-')}</dd>
        <dt>需要支持</dt><dd>${esc(sa.support_needed || '-')}</dd>
      </dl>
      <div class="mb16"><div class="muted small mb8">附件</div>${attachList(sa.attachments)}</div>
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>实际完成情况</th><th>自评分</th></tr></thead>
      <tbody>${sa.items.map(it => `<tr><td>${esc(it.name)}</td><td>${pct(it.weight)}</td>
        <td style="white-space:pre-wrap">${esc(it.completion)}</td><td>${num(it.self_score, 0)}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">员工尚未提交自评</div>'}
    </div></div>
    ${sa ? (editable ? `
    <div class="card"><div class="hd">主管评分（0-120 分）</div><div class="bd">
      <div id="scoreList">${eff.map((ind, i) => {
        const pre = isc && isc.scores ? isc.scores[i] : null;
        return `<div class="ind-card"><div class="ind-hd"><span class="no">${i + 1}</span>
          <span class="nm">${esc(ind.name)}</span><span class="wt">权重 ${pct(ind.weight)}</span></div>
          <div class="ind-bd"><div class="score-row">
            <div class="score-in"><label class="muted small">主管评分</label>
              <input class="input sp-score" data-i="${i}" type="number" min="0" max="120" step="1"
                value="${pre ? pre.supervisor_score : ''}"></div>
            <div class="score-in"><label class="muted small">同级评分（选填）</label>
              <input class="input sp-peer" data-i="${i}" type="number" min="0" max="120" step="1"
                value="${pre && pre.peer_score != null ? pre.peer_score : ''}"></div>
            <div class="flex1"><label class="muted small">评分说明（选填）</label>
              <input class="input sp-cmt" data-i="${i}" value="${pre ? esc(pre.comment || '') : ''}"></div>
          </div></div></div>`;
      }).join('')}</div>
      <div class="grid c2">
        <div class="field"><label>加分事项（选填，0-10 分）</label><input class="input" id="bItems" value="${isc ? esc(isc.bonus_items || '') : ''}"></div>
        <div class="field"><label>加分分值</label><input class="input" id="bScore" type="number" min="0" max="10" step="0.5" value="${isc ? isc.bonus_score : 0}"></div>
        <div class="field"><label>减分事项（选填）</label><input class="input" id="pItems" value="${isc ? esc(isc.penalty_items || '') : ''}"></div>
        <div class="field"><label>减分分值（-10-0）</label><input class="input" id="pScore" type="number" min="-10" max="0" step="0.5" value="${isc ? isc.penalty_score : 0}"></div>
      </div>
      <div class="field"><label>主管评语</label><textarea class="textarea" id="spComment">${isc ? esc(isc.supervisor_comment || '') : ''}</textarea></div>
    </div>
    <div class="ft flex between">
      <span class="muted small">业务目标得分 <b id="pvBase">-</b> · 总分 <b id="pvTotal">-</b> · 等级 <b id="pvGrade">-</b></span>
      <span><button class="btn primary" id="btnScore">提交评分</button></span>
    </div></div>`
      : `<div class="card"><div class="hd">主管评分</div><div class="bd">
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>主管评分</th><th>同级评分</th><th>说明</th></tr></thead>
      <tbody>${isc ? isc.scores.map(s => `<tr><td>${esc(s.name)}</td><td>${pct(s.weight)}</td>
        <td>${num(s.supervisor_score, 1)}</td><td>${s.peer_score == null ? '-' : num(s.peer_score, 1)}</td>
        <td>${esc(s.comment || '-')}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">尚未评分</td></tr>'}</tbody></table>
      ${isc ? `<div class="mt16"><dl class="dl">
        <dt>加分</dt><dd>${esc(isc.bonus_items || '-')}（${num(isc.bonus_score, 1)}）</dd>
        <dt>减分</dt><dd>${esc(isc.penalty_items || '-')}（${num(isc.penalty_score, 1)}）</dd>
        <dt>业务目标得分</dt><dd>${num(isc.base_score, 2)}</dd>
        <dt>总分</dt><dd><b>${num(isc.total_score, 2)}</b></dd>
        <dt>建议等级</dt><dd>${esc(isc.suggested_grade || '-')}</dd>
        <dt>主管评语</dt><dd>${esc(isc.supervisor_comment || '-')}</dd>
      </dl></div>` : ''}
    </div></div>`) : ''}`);
  bindLayout(); updateBell();

  if (!editable) return;
  const upd = () => {
    let base = 0, ok = true;
    $$('.sp-score').forEach(el => {
      const v = el.value === '' ? null : Number(el.value);
      if (v == null || isNaN(v)) { ok = false; return; }
      base += v * eff[Number(el.dataset.i)].weight;
    });
    const bonus = Number($('#bScore').value || 0), penalty = Number($('#pScore').value || 0);
    const total = ok ? base + bonus + penalty : null;
    $('#pvBase').textContent = ok ? num(base, 2) : '-';
    $('#pvTotal').textContent = total == null ? '-' : num(total, 2);
    $('#pvGrade').textContent = total == null ? '-' : gradeOf(total);
  };
  $$('.sp-score, #bScore, #pScore').forEach(el => el.addEventListener('input', upd));
  upd();

  $('#btnScore').onclick = async () => {
    const scores = eff.map((ind, i) => ({
      name: ind.name,
      supervisor_score: $(`.sp-score[data-i="${i}"]`).value === '' ? null : Number($(`.sp-score[data-i="${i}"]`).value),
      peer_score: $(`.sp-peer[data-i="${i}"]`).value === '' ? null : Number($(`.sp-peer[data-i="${i}"]`).value),
      comment: $(`.sp-cmt[data-i="${i}"]`).value.trim(),
    }));
    try {
      const r = await api('/api/supervisor/tasks/' + taskId + '/score', 'POST', {
        scores,
        bonus_items: $('#bItems').value.trim(), bonus_score: Number($('#bScore').value || 0),
        penalty_items: $('#pItems').value.trim(), penalty_score: Number($('#pScore').value || 0),
        supervisor_comment: $('#spComment').value.trim(),
      });
      toast('评分已提交：总分 ' + r.total_score + '，等级 ' + r.grade);
      location.hash = '#/supervisor/tasks';
    } catch (err) { toast(err.message, 1); }
  };
}

/* ================= 视图：HR 工作台 ================= */
async function viewHrOverview() {
  const d = await api('/api/hr/overview');
  $('#app').innerHTML = layout('工作台', `
    ${pageHead('绩效工作台', '全公司考核进度总览')}
    <div class="grid c4 mb16">
      <div class="card stat o"><div class="num">${d.pending_self}</div><div class="lbl">待自评</div></div>
      <div class="card stat b"><div class="num">${d.pending_score}</div><div class="lbl">待评分</div></div>
      <div class="card stat p"><div class="num">${d.pending_review}</div><div class="lbl">待审核</div></div>
      <div class="card stat g"><div class="num">${d.published}</div><div class="lbl">已发布</div></div>
    </div>
    <div class="grid c2">
      <div class="card"><div class="hd">快捷操作</div><div class="bd flex wrap">
        <a class="btn primary" href="#/hr/tasks">生成考核任务</a>
        <a class="btn" href="#/hr/scores">评分审批</a>
        <a class="btn" href="#/hr/results">结果发布${d.ready_publish ? `（${d.ready_publish} 条待发布）` : ''}</a>
        <a class="btn" href="#/hr/configs">考核配置</a>
      </div></div>
      <div class="card"><div class="hd">基本信息</div><div class="bd">
        ${kv('在册账号', d.users_active + ' 人')}
        ${kv('待发布结果', d.ready_publish + ' 条')}
        ${kv('已关闭任务', d.closed + ' 条')}
      </div></div>
    </div>
    <div class="card"><div class="hd">最近动态</div><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr><th>任务编号</th><th>员工</th><th>周期</th><th>状态</th><th>更新时间</th></tr></thead>
      <tbody>${d.recent.map(r => `<tr><td>${esc(r.task_no)}</td><td>${esc(r.user_name)}</td>
        <td class="nowrap">${esc(r.period_code)}</td><td>${badge(TASK_STATUS, r.status)}</td>
        <td class="nowrap">${fmtTime(r.updated_at) || '-'}</td></tr>`).join('')}</tbody></table>
    </div></div>`);
  bindLayout(); updateBell();
}

/* ================= 视图：考核配置 ================= */
async function viewHrConfigs() {
  const [configs, users] = await Promise.all([api('/api/hr/configs'), api('/api/hr/users')]);
  const supOptions = users.map(u =>
    `<option value="${u.id}">${esc(u.name)}（${esc(u.department || '')}）</option>`).join('');
  $('#app').innerHTML = layout('考核配置', `
    ${pageHead('员工考核配置', '配置只影响后续生成的任务，历史任务保留当时的指标与主管',
      `<button class="btn primary" id="btnAddCfg">＋ 新建配置</button>`)}
    <div class="card"><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr>
        <th>员工</th><th>部门／职位</th><th>考核频率</th><th>月度主管</th><th>季度主管</th><th>最终审核人</th>
        <th>指标数</th><th>参与考核</th><th>操作</th>
      </tr></thead><tbody>${configs.map(c => `<tr>
        <td>${esc(c.user_name)}</td>
        <td>${esc(c.department || '-')} / ${esc(c.position || '-')}</td>
        <td>${FREQ[c.frequency] || c.frequency}</td>
        <td>${esc(c.monthly_supervisor_name || '-')}</td>
        <td>${esc(c.quarterly_supervisor_name || '-')}</td>
        <td>${esc(c.final_approver_name || '-')}</td>
        <td>月 ${c.indicators.monthly.length} / 季 ${c.indicators.quarterly.length}</td>
        <td>${c.participate ? '<span class="badge green">是</span>' : '<span class="badge gray">否</span>'}</td>
        <td class="acts"><button class="btn sm" data-edit="${c.id}">编辑</button></td>
      </tr>`).join('')}</tbody></table>
    </div></div>`);
  bindLayout(); updateBell();

  const openEditor = async (cfg) => {
    const inds = cfg ? cfg.indicators : { monthly: [], quarterly: [] };
    let freq = cfg ? cfg.frequency : 'monthly';
    let curTab = 'monthly';
    const m = openModal(cfg ? '编辑考核配置 · ' + cfg.user_name : '新建考核配置', `
      <div class="field"><label>员工</label>
        <select class="select" id="cfgUser" ${cfg ? 'disabled' : ''}>
          ${users.map(u => `<option value="${u.id}" ${cfg && cfg.user_id === u.id ? 'selected' : ''}>${esc(u.name)}（${esc(u.department || '')}）</option>`).join('')}
        </select></div>
      <div class="field"><label>考核频率</label>
        <select class="select" id="cfgFreq">
          <option value="monthly" ${freq === 'monthly' ? 'selected' : ''}>月度</option>
          <option value="quarterly" ${freq === 'quarterly' ? 'selected' : ''}>季度</option>
          <option value="both" ${freq === 'both' ? 'selected' : ''}>月度＋季度</option>
        </select></div>
      <div class="grid c2">
        <div class="field"><label>月度评分主管</label><select class="select" id="cfgMSup">
          <option value="">不设置</option>${supOptions}</select></div>
        <div class="field"><label>季度评分主管</label><select class="select" id="cfgQSup">
          <option value="">不设置</option>${supOptions}</select></div>
      </div>
      <div class="grid c2">
        <div class="field"><label>最终审核人</label><select class="select" id="cfgAppr">
          <option value="">不设置（HR核对后可直接发布）</option>${supOptions}</select></div>
        <div class="field"><label>生效日期</label><input class="input" id="cfgEff" type="date"
          value="${cfg && cfg.effective_date ? cfg.effective_date.slice(0, 10) : ''}"></div>
      </div>
      <div class="field"><label class="flex" style="gap:8px"><input type="checkbox" id="cfgJoin"
        ${!cfg || cfg.participate ? 'checked' : ''}> 参与考核</label></div>
      <div class="tabs">
        <a href="javascript:void(0)" data-tab="monthly" class="active">月度指标</a>
        <a href="javascript:void(0)" data-tab="quarterly">季度指标</a>
      </div>
      <div id="indEditor"></div>
      <div class="flex between mt16">
        <span>权重合计：<b id="wsumTxt" class="wsum">-</b></span>
        <button class="btn sm" id="btnAddInd">＋ 添加指标</button>
      </div>`,
      `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>保存配置</button>`, true);
    if (cfg) {
      $('#cfgMSup').value = cfg.monthly_supervisor_id || '';
      $('#cfgQSup').value = cfg.quarterly_supervisor_id || '';
      $('#cfgAppr').value = cfg.final_approver_id || '';
    }
    const state2 = { monthly: inds.monthly.slice(), quarterly: inds.quarterly.slice() };

    const renderInds = () => {
      const list = state2[curTab];
      $('#indEditor').innerHTML = list.length ? `<table class="tbl ind-row"><thead><tr>
        <th style="width:22%">指标名称</th><th>100% 目标值</th><th>120% 目标值</th>
        <th style="width:13%">数据来源</th><th style="width:9%">权重%</th><th style="width:6%"></th>
      </tr></thead><tbody>${list.map((ind, i) => `<tr>
        <td><input class="input in-name" data-i="${i}" value="${esc(ind.name)}"></td>
        <td><textarea class="textarea in-100" data-i="${i}" style="min-height:38px">${esc(ind.standard_100 || '')}</textarea></td>
        <td><textarea class="textarea in-120" data-i="${i}" style="min-height:38px">${esc(ind.standard_120 || '')}</textarea></td>
        <td><input class="input in-src" data-i="${i}" value="${esc(ind.data_source || '')}"></td>
        <td><input class="input in-w" data-i="${i}" type="number" min="10" max="60" step="1"
          value="${ind.weight ? Math.round(ind.weight * 100) : ''}"></td>
        <td><button class="btn link danger" data-del="${i}">×</button></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">暂无指标，请点击下方「添加指标」</div>';
      const sum = list.reduce((s, x) => s + (Number(x.weight) || 0), 0);
      const el = $('#wsumTxt');
      el.textContent = Math.round(sum * 100) + '%';
      el.className = 'wsum ' + (Math.abs(sum - 1) < 0.001 && list.length ? 'ok' : 'bad');
      $$('.in-w').forEach(el2 => el2.addEventListener('input', () => {
        const s2 = $$('.in-w').reduce((acc, x) => acc + (Number(x.value) || 0), 0) / 100;
        const e2 = $('#wsumTxt');
        e2.textContent = $$('.in-w').reduce((acc, x) => acc + (Number(x.value) || 0), 0) + '%';
        e2.className = 'wsum ' + (Math.abs(s2 - 1) < 0.001 ? 'ok' : 'bad');
      }));
    };
    const readCur = () => state2[curTab].map((ind, i) => ({
      name: $(`.in-name[data-i="${i}"]`).value.trim(),
      standard_100: $(`.in-100[data-i="${i}"]`).value.trim(),
      standard_120: $(`.in-120[data-i="${i}"]`).value.trim(),
      data_source: $(`.in-src[data-i="${i}"]`).value.trim(),
      weight: (Number($(`.in-w[data-i="${i}"]`).value) || 0) / 100,
    }));
    const flush = () => { state2[curTab] = readCur(); };
    $$('[data-tab]', m.root).forEach(a => a.onclick = () => {
      flush();
      curTab = a.dataset.tab;
      $$('[data-tab]', m.root).forEach(x => x.classList.toggle('active', x === a));
      renderInds();
    });
    $('#btnAddInd').onclick = () => { state2[curTab].push({ name: '', weight: 0 }); renderInds(); };
    $('#indEditor').addEventListener('click', e => {
      const del = e.target.closest('[data-del]');
      if (del) { flush(); state2[curTab].splice(Number(del.dataset.del), 1); renderInds(); }
    });
    renderInds();

    $('[data-no]', m.el).onclick = m.close;
    $('[data-ok]', m.el).onclick = async () => {
      flush();
      const payload = {
        user_id: Number($('#cfgUser').value), frequency: $('#cfgFreq').value,
        monthly_supervisor_id: $('#cfgMSup').value || null,
        quarterly_supervisor_id: $('#cfgQSup').value || null,
        final_approver_id: $('#cfgAppr').value || null,
        effective_date: $('#cfgEff').value || null,
        participate: $('#cfgJoin').checked ? 1 : 0,
        indicators: { monthly: state2.monthly, quarterly: state2.quarterly },
      };
      try {
        await api('/api/hr/configs', 'POST', payload);
        toast('配置已保存'); m.close(); viewHrConfigs();
      } catch (err) { toast(err.message, 1); }
    };
  };
  $('#btnAddCfg').onclick = () => openEditor(null);
  $$('[data-edit]').forEach(b => b.onclick = async () => {
    const cfg = configs.find(c => c.id === Number(b.dataset.edit));
    openEditor(cfg);
  });
}

/* ================= 视图：考核任务 ================= */
async function viewHrTasks() {
  const [configs, users] = await Promise.all([api('/api/hr/configs'), api('/api/hr/users')]);
  const f = state.page.taskFilter || {};
  const q = new URLSearchParams();
  if (f.period_code) q.set('period_code', f.period_code);
  if (f.status) q.set('status', f.status);
  if (f.user_id) q.set('user_id', f.user_id);
  const rows = await api('/api/hr/tasks?' + q.toString());
  const stOpts = Object.entries(TASK_STATUS).map(([k, v]) =>
    `<option value="${k}" ${f.status === k ? 'selected' : ''}>${v[0]}</option>`).join('');
  $('#app').innerHTML = layout('考核任务', `
    ${pageHead('考核任务', '任务生成后指标快照固化，不受后续配置变更影响',
      `<button class="btn primary" id="btnBatch">批量生成任务</button>`)}
    <div class="card"><div class="bd flex wrap">
      <input class="input" id="fPeriod" placeholder="周期，如 2026-10 / 2026-Q4" style="width:220px"
        value="${esc(f.period_code || '')}">
      <select class="select" id="fStatus" style="width:140px"><option value="">全部状态</option>${stOpts}</select>
      <select class="select" id="fUser" style="width:180px"><option value="">全部员工</option>
        ${users.map(u => `<option value="${u.id}" ${String(f.user_id) === String(u.id) ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}</select>
      <button class="btn" id="btnFilter">筛选</button>
      <button class="btn" id="btnFilterReset">重置</button>
    </div></div>
    <div class="card"><div class="bd" style="padding:0">
      ${rows.length ? `<table class="tbl"><thead><tr>
        <th>任务编号</th><th>员工</th><th>部门</th><th>类型</th><th>周期</th><th>状态</th>
        <th>评分主管</th><th>自评截止</th><th>操作</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td>${esc(r.task_no)}</td><td>${esc(r.user_name)}</td><td>${esc(r.department || '-')}</td>
        <td>${r.period_type === 'monthly' ? '月度' : '季度'}</td><td class="nowrap">${esc(r.period_code)}</td>
        <td>${badge(TASK_STATUS, r.status)}</td><td>${esc(r.supervisor_name || '-')}</td>
        <td class="nowrap">${fmtDate(r.self_deadline) || '-'}</td>
        <td class="acts"><a class="btn sm" href="#/hr/tasks/${r.id}">详情</a></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">没有符合条件的任务</div>'}
    </div></div>`);
  bindLayout(); updateBell();

  const doFilter = () => {
    state.page.taskFilter = {
      period_code: $('#fPeriod').value.trim(), status: $('#fStatus').value, user_id: $('#fUser').value,
    };
    viewHrTasks();
  };
  $('#btnFilter').onclick = doFilter;
  $('#btnFilterReset').onclick = () => { state.page.taskFilter = {}; viewHrTasks(); };

  // 批量生成
  $('#btnBatch').onclick = () => {
    const now = new Date();
    const ym = now.toISOString().slice(0, 7);
    const q = Math.floor(now.getMonth() / 3) + 1;
    const m = openModal('批量生成考核任务', `
      <div class="grid c2">
        <div class="field"><label>周期类型</label><select class="select" id="bType">
          <option value="monthly">月度</option><option value="quarterly">季度</option></select></div>
        <div class="field"><label>周期编号</label><input class="input" id="bCode" value="${ym}"></div>
        <div class="field"><label>开始日期</label><input class="input" id="bStart" type="date"></div>
        <div class="field"><label>结束日期</label><input class="input" id="bEnd" type="date"></div>
        <div class="field"><label>自评截止日期</label><input class="input" id="bDeadline" type="date"></div>
        <div class="field"></div>
      </div>
      <div class="field"><label>选择员工（仅显示参与考核且频率匹配的员工）</label>
        <div id="userPick" style="max-height:260px;overflow-y:auto"></div></div>`,
      `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>生成任务</button>`, true);

    const fillDates = () => {
      const type = $('#bType').value;
      const code = $('#bCode').value.trim();
      if (type === 'monthly') {
        $('#bCode').placeholder = '2026-10';
        const mm = code.match(/^(\d{4})-(\d{2})$/);
        if (mm) {
          const y = +mm[1], mo = +mm[2];
          $('#bStart').value = code + '-01';
          $('#bEnd').value = new Date(y, mo, 0).toISOString().slice(0, 10);
          $('#bDeadline').value = new Date(y, mo, 5).toISOString().slice(0, 10);
        }
      } else {
        $('#bCode').placeholder = '2026-Q4';
        const qq = code.match(/^(\d{4})-Q([1-4])$/);
        if (qq) {
          const y = +qq[1], qi = +qq[2];
          const sm = (qi - 1) * 3;
          $('#bStart').value = `${y}-${String(sm + 1).padStart(2, '0')}-01`;
          $('#bEnd').value = new Date(y, sm + 3, 0).toISOString().slice(0, 10);
          const dl = new Date(y, sm + 3, 10);
          $('#bDeadline').value = dl.toISOString().slice(0, 10);
        }
      }
    };
    const renderPick = () => {
      const type = $('#bType').value;
      const eligible = configs.filter(c => c.participate &&
        (c.frequency === 'both' || c.frequency === type) &&
        ((type === 'monthly' && c.indicators.monthly.length) ||
         (type === 'quarterly' && c.indicators.quarterly.length)));
      const uMap = Object.fromEntries(users.map(u => [u.id, u]));
      $('#userPick').innerHTML = eligible.length ? eligible.map(c => {
        const u = uMap[c.user_id];
        return `<label class="checkline sel"><input type="checkbox" class="pick" value="${u.id}" checked>
          <span>${esc(u.name)}</span><span class="muted small">${esc(u.department || '')}</span>
          <span class="tag">${FREQ[c.frequency]}</span>
          <span class="tag">${type === 'monthly' ? c.indicators.monthly.length + ' 项月度指标' : c.indicators.quarterly.length + ' 项季度指标'}</span></label>`;
      }).join('') : '<div class="empty">没有符合条件的员工，请先在「考核配置」中设置</div>';
    };
    $('#bType').onchange = () => {
      $('#bCode').value = $('#bType').value === 'monthly' ? ym : `${now.getFullYear()}-Q${q}`;
      fillDates(); renderPick();
    };
    $('#bCode').oninput = fillDates;
    fillDates(); renderPick();
    $('[data-no]', m.el).onclick = m.close;
    $('[data-ok]', m.el).onclick = async () => {
      const type = $('#bType').value, code = $('#bCode').value.trim();
      const ids = $$('.pick:checked', m.root).map(x => Number(x.value));
      if (!code) return toast('请填写周期编号', 1);
      if (!ids.length) return toast('请至少选择一名员工', 1);
      try {
        const r = await api('/api/hr/tasks/batch', 'POST', {
          period_type: type, period_code: code,
          period_start: $('#bStart').value || null, period_end: $('#bEnd').value || null,
          self_deadline: $('#bDeadline').value || null, user_ids: ids,
        });
        let msg = `成功创建 ${r.created.length} 条任务`;
        if (r.skipped.length) msg += `，跳过 ${r.skipped.length} 条：` +
          r.skipped.map(s => `${s.user}（${s.reason}）`).join('；');
        toast(msg);
        m.close(); viewHrTasks();
      } catch (err) { toast(err.message, 1); }
    };
  };
}

async function viewHrTaskDetail(taskId) {
  const t = await api('/api/hr/tasks/' + taskId);
  const isc = t.internal_score;
  const sa = t.self_assessment;
  $('#app').innerHTML = layout('任务详情 · ' + t.task_no, `
    ${pageHead(t.task_no, t.user_name + ' · ' + t.department + ' · ' + t.period_code,
      `<button class="btn" onclick="location.hash='#/hr/tasks'">返回列表</button>
       ${t.status !== 'published' && t.status !== 'closed' ? `<button class="btn danger" id="btnClose">关闭任务</button>` : ''}`)}
    <div class="grid c2">
      <div class="card"><div class="hd">任务信息</div><div class="bd">
        ${kv('被考核人', t.user_name + '（' + (t.department || '') + '）')}
        ${kv('周期', t.period_code + '（' + (t.period_type === 'monthly' ? '月度' : '季度') + '）')}
        ${kv('起止日期', (fmtDate(t.period_start) || '-') + ' ~ ' + (fmtDate(t.period_end) || '-'))}
        ${kv('自评截止', fmtDate(t.self_deadline) || '-')}
        ${kv('评分主管', t.supervisor_name || '-')}
        ${kv('最终审核人', t.approver_name || '-')}
        ${kv('当前状态', badge(TASK_STATUS, t.status), true)}
      </div></div>
      <div class="card"><div class="hd">流程记录</div><div class="bd">
        <div class="timeline">${(t.logs || []).map(l => `<div class="tl">
          <div>${ACTION_TEXT[l.action] || l.action}${l.detail ? ' · ' + esc(l.detail) : ''}</div>
          <div class="t">${esc(l.user_name || '系统')} · ${fmtTime(l.created_at)}</div></div>`).join('')
          || '<div class="muted">暂无记录</div>'}</div>
      </div></div>
    </div>
    <div class="card"><div class="hd">指标快照（生成任务时固化）</div><div class="bd">
      ${indicatorCards(t.indicators)}
    </div></div>
    ${sa ? `<div class="card"><div class="hd">员工自评 ${badge(SA_STATUS, sa.status)}</div><div class="bd">
      <dl class="dl mb16">
        <dt>提交时间</dt><dd>${fmtTime(sa.submitted_at)}</dd>
        <dt>本期成果</dt><dd>${esc(sa.achievements || '-')}</dd>
        <dt>未完成原因</dt><dd>${esc(sa.unfinished_reason || '-')}</dd>
        <dt>需要支持</dt><dd>${esc(sa.support_needed || '-')}</dd>
        ${sa.status === 'returned' ? `<dt>退回原因</dt><dd>${esc(sa.supervisor_comment || '')}</dd>` : ''}
      </dl>
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>实际完成情况</th><th>自评分</th></tr></thead>
      <tbody>${sa.items.map(it => `<tr><td>${esc(it.name)}</td><td>${pct(it.weight)}</td>
        <td style="white-space:pre-wrap">${esc(it.completion)}</td><td>${num(it.self_score, 0)}</td></tr>`).join('')}</tbody></table>
      <div class="mt16"><div class="muted small mb8">附件</div>${attachList(sa.attachments)}</div>
    </div></div>` : ''}
    ${isc ? `<div class="card"><div class="hd">内部评分 ${badge(ISC_STATUS, isc.status)}</div><div class="bd">
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>主管评分</th><th>同级评分</th><th>说明</th></tr></thead>
      <tbody>${(isc.scores || []).map(s => `<tr><td>${esc(s.name)}</td><td>${pct(s.weight)}</td>
        <td>${num(s.supervisor_score, 1)}</td><td>${s.peer_score == null ? '-' : num(s.peer_score, 1)}</td>
        <td>${esc(s.comment || '-')}</td></tr>`).join('')}</tbody></table>
      <dl class="dl mt16">
        <dt>加分</dt><dd>${esc(isc.bonus_items || '-')}（${num(isc.bonus_score, 1)}）</dd>
        <dt>减分</dt><dd>${esc(isc.penalty_items || '-')}（${num(isc.penalty_score, 1)}）</dd>
        <dt>业务目标得分</dt><dd>${num(isc.base_score, 2)}</dd>
        <dt>总分</dt><dd><b>${num(isc.total_score, 2)}</b></dd>
        <dt>建议等级</dt><dd>${esc(isc.suggested_grade || '-')}</dd>
        <dt>主管评语</dt><dd>${esc(isc.supervisor_comment || '-')}</dd>
        <dt>HR核对意见</dt><dd>${esc(isc.hr_comment || '-')}</dd>
        <dt>审核意见</dt><dd>${esc(isc.approver_comment || '-')}</dd>
        <dt>内部备注</dt><dd>${esc(isc.internal_notes || '-')}</dd>
      </dl></div></div>` : ''}`);
  bindLayout(); updateBell();
  const bc = $('#btnClose');
  if (bc) bc.onclick = async () => {
    if (!await confirmDialog('关闭后该任务将不再流转，确定关闭？', 1)) return;
    try { await api('/api/hr/tasks/' + taskId + '/close', 'POST', {}); toast('已关闭'); viewHrTaskDetail(taskId); }
    catch (err) { toast(err.message, 1); }
  };
}

/* ================= 视图：评分审批 ================= */
async function viewHrScores() {
  const status = state.page.scoreTab || 'scored';
  const rows = await api('/api/hr/scores?status=' + status);
  const tabs = [['scored', '待HR核对'], ['hr_checked', '待负责人审核'], ['approved', '待发布'], ['published', '已发布'], ['', '全部']];
  $('#app').innerHTML = layout('评分审批', `
    ${pageHead('评分审批', '内部评分与审核意见仅HR、审核人可见，员工不可见')}
    <div class="tabs">${tabs.map(([k, txt]) =>
      `<a href="javascript:void(0)" data-t="${k}" class="${status === k ? 'active' : ''}">${txt}</a>`).join('')}</div>
    <div class="card"><div class="bd" style="padding:0">
      ${rows.length ? `<table class="tbl"><thead><tr>
        <th>任务编号</th><th>员工</th><th>部门</th><th>周期</th><th>总分</th><th>建议等级</th><th>状态</th><th>操作</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td>${esc(r.task_no)}</td><td>${esc(r.user_name)}</td><td>${esc(r.department || '-')}</td>
        <td class="nowrap">${esc(r.period_code)}</td><td><b>${num(r.total_score, 2)}</b></td>
        <td>${esc(r.suggested_grade || '-')}</td><td>${badge(ISC_STATUS, r.status)}</td>
        <td class="acts"><a class="btn sm" href="#/hr/scores/${r.task_id}">处理</a></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">暂无记录</div>'}
    </div></div>`);
  bindLayout(); updateBell();
  $$('[data-t]').forEach(a => a.onclick = () => { state.page.scoreTab = a.dataset.t; viewHrScores(); });
}

async function viewHrScoreDetail(taskId) {
  const t = await api('/api/hr/scores/' + taskId);
  const isc = t.internal_score;
  const sa = t.self_assessment;
  // 员工可能已在自评中修改指标名称/权重：核对与校准以员工版为基准
  const eff = t.effective_indicators || t.indicators;
  const canHr = state.perms.hr && isc.status === 'scored';
  const canApprove = (state.perms.approver || state.perms.admin) && isc.status === 'hr_checked'
    && (t.final_approver_id === state.user.id || state.perms.admin);
  const canPublish = state.perms.hr && isc.status === 'approved';
  $('#app').innerHTML = layout('评分审批 · ' + t.task_no, `
    ${pageHead(t.user_name + ' · ' + t.period_code,
      t.department + ' · 任务编号 ' + t.task_no + ' · ' + ISC_STATUS[isc.status][0],
      `<button class="btn" onclick="location.hash='#/hr/scores'">返回列表</button>`)}
    ${sa ? `<div class="card"><div class="hd">员工自评摘要</div><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>实际完成情况</th><th>自评分</th></tr></thead>
      <tbody>${sa.items.map(it => `<tr><td>${esc(it.name)}</td><td>${pct(it.weight)}</td>
        <td style="white-space:pre-wrap;max-width:420px">${esc(it.completion)}</td><td>${num(it.self_score, 0)}</td></tr>`).join('')}</tbody></table>
    </div></div>` : ''}
    <div class="card"><div class="hd">主管评分</div><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th>
        ${canHr ? '<th>主管评分（HR可校准）</th>' : '<th>主管评分</th>'}<th>同级评分</th><th>说明</th></tr></thead>
      <tbody>${isc.scores.map((s, i) => `<tr>
        <td>${esc(s.name)}</td><td>${pct(s.weight)}</td>
        <td>${canHr ? `<input class="input adj-score" data-i="${i}" style="width:100px" type="number" min="0" max="120" step="1" value="${s.supervisor_score}">` : num(s.supervisor_score, 1)}</td>
        <td>${s.peer_score == null ? '-' : num(s.peer_score, 1)}</td><td>${esc(s.comment || '-')}</td></tr>`).join('')}</tbody></table>
      <dl class="dl mt16">
        <dt>加分</dt><dd>${esc(isc.bonus_items || '-')}（${num(isc.bonus_score, 1)}）</dd>
        <dt>减分</dt><dd>${esc(isc.penalty_items || '-')}（${num(isc.penalty_score, 1)}）</dd>
        <dt>业务目标得分</dt><dd id="baseNow">${num(isc.base_score, 2)}</dd>
        <dt>总分</dt><dd id="totalNow"><b>${num(isc.total_score, 2)}</b></dd>
        <dt>建议等级</dt><dd>${esc(isc.suggested_grade || '-')}</dd>
        <dt>主管评语</dt><dd>${esc(isc.supervisor_comment || '-')}</dd>
      </dl></div></div>
    ${canHr ? `<div class="card"><div class="hd">HR 核对</div><div class="bd">
      <div class="field"><label>核对意见</label><textarea class="textarea" id="hrCmt">${esc(isc.hr_comment || '')}</textarea></div>
      <div class="alert info">如需校准分数，请直接修改上表「主管评分」列，系统将记录校准前分值。核对通过后进入最终审核（未配置审核人则直接进入待发布）。</div>
    </div><div class="ft right"><button class="btn primary" id="btnHrCheck">核对通过</button></div></div>` : ''}
    ${isc.hr_comment && !canHr ? `<div class="card"><div class="hd">HR 核对意见</div><div class="bd">${esc(isc.hr_comment)}</div></div>` : ''}
    ${canApprove ? `<div class="card"><div class="hd">最终审核</div><div class="bd">
      <div class="field"><label>审核意见</label><textarea class="textarea" id="apCmt">${esc(isc.approver_comment || '')}</textarea></div>
    </div><div class="ft right">
      <button class="btn danger" id="btnReject">退回修改</button>
      <button class="btn primary" id="btnApprove">审核通过</button>
    </div></div>` : ''}
    ${canPublish ? `<div class="card"><div class="hd">发布绩效结果</div><div class="bd">
      <div class="alert info">发布后员工即可在「我的绩效结果」中查看。内部审核意见不会对员工展示。</div>
      <div class="field"><label>对员工公开的反馈</label><textarea class="textarea" id="pubFb" placeholder="将展示给员工，请填写得分说明与总体评价"></textarea></div>
      <div class="field"><label>改进建议（选填）</label><textarea class="textarea" id="pubImp"></textarea></div>
    </div><div class="ft right"><button class="btn primary" id="btnPublish">确认发布</button></div></div>` : ''}
    ${isc.status === 'published' ? `<div class="alert info">结果已发布，员工已可见。</div>` : ''}`);
  bindLayout(); updateBell();

  if (canHr) {
    const recompute = () => {
      let base = 0;
      $$('.adj-score').forEach(el => { base += (Number(el.value) || 0) * eff[Number(el.dataset.i)].weight; });
      const total = base + isc.bonus_score + isc.penalty_score;
      $('#baseNow').textContent = num(base, 2);
      $('#totalNow').innerHTML = '<b>' + num(total, 2) + '</b>';
    };
    $$('.adj-score').forEach(el => el.addEventListener('input', recompute));
    $('#btnHrCheck').onclick = async () => {
      const scores = $$('.adj-score').map(el => ({ name: eff[Number(el.dataset.i)].name, supervisor_score: Number(el.value) }));
      try {
        await api('/api/hr/scores/' + taskId + '/check', 'POST', {
          hr_comment: $('#hrCmt').value.trim(), scores,
        });
        toast('核对通过'); viewHrScoreDetail(taskId);
      } catch (err) { toast(err.message, 1); }
    };
  }
  if (canApprove) {
    $('#btnApprove').onclick = async () => {
      try {
        await api('/api/approval/scores/' + taskId + '/approve', 'POST', { approver_comment: $('#apCmt').value.trim() });
        toast('已审核通过'); viewHrScoreDetail(taskId);
      } catch (err) { toast(err.message, 1); }
    };
    $('#btnReject').onclick = async () => {
      const c = $('#apCmt').value.trim();
      if (!c) return toast('请先填写审核意见（退回原因）', 1);
      try {
        await api('/api/approval/scores/' + taskId + '/reject', 'POST', { approver_comment: c });
        toast('已退回评分主管'); viewHrScoreDetail(taskId);
      } catch (err) { toast(err.message, 1); }
    };
  }
  if (canPublish) {
    $('#btnPublish').onclick = async () => {
      if (!$('#pubFb').value.trim()) return toast('请填写对员工公开的反馈', 1);
      try {
        await api('/api/hr/results/publish', 'POST', {
          task_id: taskId, public_feedback: $('#pubFb').value.trim(), improvement: $('#pubImp').value.trim(),
        });
        toast('结果已发布，员工已可见'); viewHrScoreDetail(taskId);
      } catch (err) { toast(err.message, 1); }
    };
  }
}

/* ================= 视图：结果发布 ================= */
async function viewHrResults() {
  const rows = await api('/api/hr/results');
  $('#app').innerHTML = layout('结果发布', `
    ${pageHead('已发布绩效结果', '全公司发布记录，点击查看对员工展示的完整内容')}
    <div class="card"><div class="bd" style="padding:0">
      ${rows.length ? `<table class="tbl"><thead><tr>
        <th>员工</th><th>部门</th><th>周期</th><th>类型</th><th>总分</th><th>等级</th><th>奖金系数</th><th>发布时间</th><th>操作</th>
      </tr></thead><tbody>${rows.map(r => `<tr>
        <td>${esc(r.user_name)}</td><td>${esc(r.department || '-')}</td>
        <td class="nowrap">${esc(r.period_code)}</td><td>${r.period_type === 'monthly' ? '月度' : '季度'}</td>
        <td><b>${num(r.total_score, 2)}</b></td><td><span class="badge blue">${esc(r.grade)}</span></td>
        <td>${num(r.bonus_factor, 3)}</td><td class="nowrap">${fmtDate(r.published_at)}</td>
        <td><button class="btn sm" data-v="${r.id}">查看</button></td>
      </tr>`).join('')}</tbody></table>` : '<div class="empty">暂无已发布结果</div>'}
    </div></div>`);
  bindLayout(); updateBell();
  $$('[data-v]').forEach(b => b.onclick = async () => {
    const r = rows.find(x => x.id === Number(b.dataset.v));
    const m = openModal('绩效结果 · ' + r.user_name + ' ' + r.period_code, `
      <div class="grid c3 mb16">
        <div class="card stat b"><div class="num">${num(r.total_score, 2)}</div><div class="lbl">总分</div></div>
        <div class="card stat g"><div class="num">${esc(r.grade)}</div><div class="lbl">等级</div></div>
        <div class="card stat o"><div class="num">${num(r.bonus_factor, 3)}</div><div class="lbl">奖金系数</div></div>
      </div>
      <table class="tbl"><thead><tr><th>指标</th><th>权重</th><th>得分</th><th>加权</th></tr></thead>
      <tbody>${JSON.parse(r.items).map(it => `<tr><td>${esc(it.name)}</td><td>${pct(it.weight)}</td>
        <td>${num(it.score, 1)}</td><td>${num(it.weighted, 2)}</td></tr>`).join('')}</tbody></table>
      <div class="mt16"><div class="muted small mb8">公开反馈</div><div>${esc(r.public_feedback).replace(/\n/g, '<br>')}</div></div>
      <div class="mt16"><div class="muted small mb8">改进建议</div><div>${r.improvement ? esc(r.improvement).replace(/\n/g, '<br>') : '无'}</div></div>`,
      `<button class="btn primary" data-ok>关闭</button>`);
    $('[data-ok]', m.el).onclick = m.close;
  });
}

/* ================= 视图：用户管理 ================= */
async function viewAdminUsers() {
  const users = await api('/api/admin/users');
  const supOpts = users.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join('');
  $('#app').innerHTML = layout('用户管理', `
    ${pageHead('用户管理', '管理员权限仅保留给必要人员；停用后该用户立即无法登录',
      `<button class="btn primary" id="btnAddUser">＋ 新建用户</button>`)}
    <div class="card"><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr>
        <th>账号</th><th>姓名</th><th>部门／职位</th><th>直属主管</th><th>角色</th><th>可任审核人</th><th>状态</th><th>操作</th>
      </tr></thead><tbody>${users.map(u => `<tr>
        <td>${esc(u.username)}</td><td>${esc(u.name)}</td>
        <td>${esc(u.department || '-')} / ${esc(u.position || '-')}</td>
        <td>${esc((users.find(x => x.id === u.supervisor_id) || {}).name || '-')}</td>
        <td>${ROLE[u.role] || u.role}</td><td>${u.is_final_approver ? '是' : '否'}</td>
        <td>${u.is_active ? '<span class="badge green">正常</span>' : '<span class="badge gray">已停用</span>'}</td>
        <td class="acts">
          <button class="btn sm" data-edit="${u.id}">编辑</button>
          <button class="btn sm" data-pwd="${u.id}">重置密码</button>
          <button class="btn sm ${u.is_active ? 'danger' : ''}" data-toggle="${u.id}">${u.is_active ? '停用' : '启用'}</button>
          <button class="btn sm danger" data-del="${u.id}">删除</button>
        </td></tr>`).join('')}</tbody></table>
    </div></div>`);
  bindLayout(); updateBell();

  const openUserEditor = (u) => {
    const m = openModal(u ? '编辑用户 · ' + u.username : '新建用户', `
      <div class="grid c2">
        <div class="field"><label>账号（登录名）</label>
          <input class="input" id="uName" value="${u ? esc(u.username) : ''}" ${u ? 'disabled' : ''} placeholder="小写字母/数字/点/下划线，3-32位"></div>
        <div class="field"><label>姓名</label><input class="input" id="uReal" value="${u ? esc(u.name) : ''}"></div>
        <div class="field"><label>部门</label><input class="input" id="uDept" value="${u ? esc(u.department || '') : ''}"></div>
        <div class="field"><label>职位</label><input class="input" id="uPos" value="${u ? esc(u.position || '') : ''}"></div>
        <div class="field"><label>直属主管</label><select class="select" id="uSup">
          <option value="">无</option>${supOpts}</select></div>
        <div class="field"><label>角色</label><select class="select" id="uRole">
          <option value="employee" ${u && u.role === 'employee' ? 'selected' : ''}>普通员工</option>
          <option value="hr" ${u && u.role === 'hr' ? 'selected' : ''}>绩效HR</option>
          <option value="admin" ${u && u.role === 'admin' ? 'selected' : ''}>系统管理员</option>
        </select></div>
        <div class="field"><label>可担任最终审核人</label>
          <select class="select" id="uAppr"><option value="0" ${u && !u.is_final_approver ? 'selected' : ''}>否</option>
          <option value="1" ${u && u.is_final_approver ? 'selected' : ''}>是</option></select></div>
        ${u ? '' : `<div class="field"><label>初始密码</label><input class="input" id="uPwd" value="Perf@2026"></div>`}
      </div>`,
      `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>保存</button>`);
    if (u) $('#uSup').value = u.supervisor_id || '';
    $('[data-no]', m.el).onclick = m.close;
    $('[data-ok]', m.el).onclick = async () => {
      const payload = {
        name: $('#uReal').value.trim(), department: $('#uDept').value.trim(),
        position: $('#uPos').value.trim(), supervisor_id: $('#uSup').value || null,
        role: $('#uRole').value, is_final_approver: $('#uAppr').value === '1',
      };
      try {
        if (u) {
          await api('/api/admin/users/' + u.id, 'PUT', payload);
        } else {
          payload.username = $('#uName').value.trim();
          payload.password = $('#uPwd').value;
          await api('/api/admin/users', 'POST', payload);
        }
        toast('已保存'); m.close(); viewAdminUsers();
      } catch (err) { toast(err.message, 1); }
    };
  };
  $('#btnAddUser').onclick = () => openUserEditor(null);
  $$('[data-edit]').forEach(b => b.onclick = () => openUserEditor(users.find(u => u.id === Number(b.dataset.edit))));
  $$('[data-pwd]').forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === Number(b.dataset.pwd));
    const m = openModal('重置密码 · ' + u.username, `
      <div class="field"><label>新密码（至少 8 位，包含字母和数字）</label>
      <input class="input" id="np" value="Perf@2026"></div>
      <div class="alert warn">重置后该用户所有已登录会话将失效，并强制首次登录修改密码。</div>`,
      `<button class="btn" data-no>取消</button><button class="btn primary" data-ok>重置</button>`);
    $('[data-no]', m.el).onclick = m.close;
    $('[data-ok]', m.el).onclick = async () => {
      try {
        await api('/api/admin/users/' + u.id + '/reset-password', 'POST', { password: $('#np').value });
        toast('密码已重置'); m.close();
      } catch (err) { toast(err.message, 1); }
    };
  });
  $$('[data-toggle]').forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === Number(b.dataset.toggle));
    if (!await confirmDialog(`确定${u.is_active ? '停用' : '启用'}账号 ${u.username}？`, 1)) return;
    try { await api('/api/admin/users/' + u.id + '/toggle-active', 'POST', {}); toast('已更新'); viewAdminUsers(); }
    catch (err) { toast(err.message, 1); }
  });
  $$('[data-del]').forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === Number(b.dataset.del));
    if (!await confirmDialog(
      `确定删除账号 ${u.username}（${u.name}）？删除后无法恢复：该用户的登录会话、站内通知和考核配置将被清除，` +
      `其下属员工将暂无所属主管；已有考核记录或仍关联他人考核的用户无法删除，请改用「停用」。`, 1)) return;
    try { await api('/api/admin/users/' + u.id, 'DELETE'); toast('已删除'); viewAdminUsers(); }
    catch (err) { toast(err.message, 1); }
  });
}

/* ================= 视图：等级规则 ================= */
async function viewAdminSettings() {
  const s = await api('/api/admin/settings');
  $('#app').innerHTML = layout('等级规则', `
    ${pageHead('等级规则与系统设置', '总分区间决定绩效等级；发布结果时自动套用')}
    <div class="card"><div class="hd">等级区间（总分 0-120）</div><div class="bd">
      <table class="tbl"><thead><tr><th style="width:200px">总分不低于</th><th>等级</th><th style="width:60px"></th></tr></thead>
      <tbody id="bandRows">${s.grade_bands.map((b, i) => `<tr>
        <td><input class="input bmin" data-i="${i}" type="number" min="0" max="120" step="1" value="${b.min}"></td>
        <td><input class="input bgrade" data-i="${i}" style="width:80px" value="${esc(b.grade)}"></td>
        <td><button class="btn link danger" data-delb="${i}">×</button></td></tr>`).join('')}</tbody></table>
      <button class="btn sm mt8" id="btnAddBand">＋ 添加区间</button>
    </div>
    <div class="ft right"><button class="btn primary" id="btnSaveBands">保存等级规则</button></div></div>
    <div class="card"><div class="hd">其他</div><div class="bd">
      <div class="alert info">评分规则：各指标 0-120 分，权重合计 100%；业务目标得分＝Σ(主管评分×权重)；总分＝业务目标得分＋加分(0-10)＋减分(-10-0)；当期奖金系数＝MIN(总分,120)/100。以上规则内置于系统，暂不可修改。</div>
      ${kv('评分区间', '0 - 120 分')}
      ${kv('单项权重范围', '10% - 60%')}
    </div></div>`);
  bindLayout(); updateBell();
  const bindDel = () => $$('[data-delb]').forEach(b => b.onclick = () => { b.closest('tr').remove(); });
  $('#btnAddBand').onclick = () => {
    $('#bandRows').insertAdjacentHTML('beforeend',
      `<tr><td><input class="input bmin" type="number" min="0" max="120" step="1" value="0"></td>
       <td><input class="input bgrade" style="width:80px" value=""></td>
       <td><button class="btn link danger" data-delb="-1">×</button></td></tr>`);
    bindDel();
  };
  bindDel();
  $('#btnSaveBands').onclick = async () => {
    const bands = $$('#bandRows tr').map(tr => ({
      min: Number($('.bmin', tr).value), grade: $('.bgrade', tr).value.trim(),
    })).filter(b => b.grade);
    try {
      await api('/api/admin/settings', 'PUT', { grade_bands: bands });
      state.bands = null;
      await loadMe();
      toast('等级规则已保存');
    } catch (err) { toast(err.message, 1); }
  };
}

/* ================= 视图：审计日志 ================= */
async function viewAdminLogs() {
  const page = state.page.logPage || 1;
  const d = await api('/api/admin/audit-logs?page=' + page);
  $('#app').innerHTML = layout('审计日志', `
    ${pageHead('审计日志', '记录登录、评分、发布、权限变更等关键操作，共 ' + d.total + ' 条')}
    <div class="card"><div class="bd" style="padding:0">
      <table class="tbl"><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>详情</th><th>IP</th></tr></thead>
      <tbody>${d.items.map(l => `<tr>
        <td class="nowrap">${fmtTime(l.created_at)}</td><td>${esc(l.user_name || '-')}</td>
        <td>${esc(ACTION_TEXT[l.action] || l.action)}</td><td>${esc(l.target || '-')}</td>
        <td>${esc(l.detail || '-')}</td><td class="nowrap">${esc(l.ip || '-')}</td></tr>`).join('')}</tbody></table>
    </div></div>
    <div class="pager">
      <span class="muted small">第 ${d.page} 页 / 共 ${Math.max(1, Math.ceil(d.total / d.size))} 页</span>
      <button class="btn sm" id="pgPrev" ${d.page <= 1 ? 'disabled' : ''}>上一页</button>
      <button class="btn sm" id="pgNext" ${d.page * d.size >= d.total ? 'disabled' : ''}>下一页</button>
    </div>`);
  bindLayout(); updateBell();
  $('#pgPrev').onclick = () => { state.page.logPage = page - 1; viewAdminLogs(); };
  $('#pgNext').onclick = () => { state.page.logPage = page + 1; viewAdminLogs(); };
}

/* ================= 路由 ================= */
const ROUTES = [
  [/^my\/dashboard$/, viewMyDashboard],
  [/^my\/tasks\/(\d+)$/, viewSelfForm],
  [/^my\/tasks$/, viewMyTasks],
  [/^my\/results\/(\d+)$/, viewResultDetail],
  [/^my\/results$/, viewMyResults],
  [/^supervisor\/tasks\/(\d+)$/, viewSupervisorScore],
  [/^supervisor\/tasks$/, viewSupervisorTasks],
  [/^hr\/overview$/, viewHrOverview],
  [/^hr\/configs$/, viewHrConfigs],
  [/^hr\/tasks\/(\d+)$/, viewHrTaskDetail],
  [/^hr\/tasks$/, viewHrTasks],
  [/^hr\/scores\/(\d+)$/, viewHrScoreDetail],
  [/^hr\/scores$/, viewHrScores],
  [/^hr\/results$/, viewHrResults],
  [/^admin\/users$/, viewAdminUsers],
  [/^admin\/settings$/, viewAdminSettings],
  [/^admin\/logs$/, viewAdminLogs],
];

async function render() {
  $$('.bell-drop').forEach(x => x.remove());
  if (!state.user) { renderLogin(); return; }
  const hash = location.hash.replace(/^#\/?/, '');
  const path = hash || (state.perms.hr ? 'hr/overview' : (state.perms.supervisor ? 'supervisor/tasks' : 'my/dashboard'));
  if (!hash) { location.replace('#/' + path); return; }
  state.route = path.split('/');
  for (const [re, view] of ROUTES) {
    const m = path.match(re);
    if (m) {
      try {
        await view(...m.slice(1).map(Number).map((n, i) => isNaN(n) ? m[i + 1] : n));
      } catch (err) {
        if (err instanceof ApiError) toast(err.message, 1);
        $('#app').innerHTML = layout('出错了', `<div class="card"><div class="bd empty">${esc(err.message)}</div></div>`);
        bindLayout(); updateBell();
      }
      return;
    }
  }
  location.replace('#/' + (state.perms.hr ? 'hr/overview' : 'my/dashboard'));
}

window.addEventListener('hashchange', render);

/* ================= 启动 ================= */
(async function init() {
  try {
    await loadMe();
    if (state.user) afterLogin();
    else renderLogin();
  } catch (e) {
    renderLogin();
  }
})();
