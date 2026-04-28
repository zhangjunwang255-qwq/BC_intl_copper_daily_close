/**
 * 沪铜 & 国际铜比价监测 - 前端逻辑
 * 
 * 核心逻辑：
 * - 日期 > 15 日：展示 M+2 / M+3 合约
 * - 日期 ≤ 15 日：展示 M+1 / M+2 合约
 * - 实时模式：每 10 分钟轮询 /api/latest
 * - 历史模式：用户选择日期后查询 /api/history
 */

const API_BASE = window.API_BASE || '';

// 全局状态
let state = {
  mode: 'live',       // 'live' | 'history'
  liveData: null,
  historyData: null,
  timer: null,
  REFRESH_INTERVAL: 10 * 60 * 1000, // 10 分钟
};

// DOM 元素
const $ = id => document.getElementById(id);

// 根据当前日期判断模式（M+1/M+2 还是 M+2/M+3）
function getContractMode(date) {
  const d = date instanceof Date ? date : new Date(date + 'T00:00:00');
  return d.getDate() > 15 ? 'M23' : 'M12';
}

// 合约代码转换：mode=M23 → { cuMain: cuM2, cuNext: cuM3, bcMain: bcM2, bcNext: bcM3 }
// mode=M12 → { cuMain: cuM1, cuNext: cuM2, bcMain: bcM1, bcNext: bcM2 }
function getContractKeys(mode) {
  if (mode === 'M23') {
    return { cuMainKey: 'cu_current', bcMainKey: 'bc_current', cuNextKey: null, bcNextKey: null };
  } else {
    return { cuMainKey: 'cu_current', bcMainKey: 'bc_current', cuNextKey: null, bcNextKey: null };
  }
}

// 格式化合约标签
function formatContractLabel(code) {
  if (!code) return '--';
  // e.g. "CU2606" → "沪铜 CU2606"
  const prefix = code.startsWith('CU') ? '沪铜' : '国际铜';
  return `${prefix} ${code}`;
}

// 渲染实时数据
function renderLive(data) {
  if (!data) return;

  const mode = getContractMode(data.date || todayStr());
  const isM23 = mode === 'M23';

  // 标签更新
  $('cuMainLabel').textContent = '沪铜 ' + (data.cu_main || data.cu_current || '--');
  $('bcMainLabel').textContent = '国际铜 ' + (data.bc_main || data.bc_current || '--');

  // Row 1 prices
  $('cuMainPrice').textContent = data.cu_main ?? data.cu_current ?? '--';
  $('bcMainPrice').textContent = data.bc_main ?? data.bc_current ?? '--';
  $('cuMainSub').textContent = 'M+2 合约';
  $('bcMainSub').textContent = 'M+2 合约';

  // Ratio
  $('ratioPrice').textContent = data.ratio != null ? data.ratio.toFixed(4) : '--';
  $('ratioSub').textContent = 'CU / BC';

  // Spread
  const spreadVal = data.spread;
  if (spreadVal != null) {
    const cls = spreadVal >= 0 ? 'positive' : 'negative';
    $('spreadPrice').innerHTML = `<span class="${cls}">${spreadVal >= 0 ? '+' : ''}${spreadVal.toFixed(2)}</span>`;
  } else {
    $('spreadPrice').textContent = '--';
  }
  $('spreadSub').textContent = 'CU/1.13 - BC';

  // Next contracts
  if (isM23) {
    // Row 4: CU(M+3)
    $('cuNextLabel').textContent = '沪铜 ' + (data.cu_next || '--');
    $('cuNextPrice').textContent = data.cu_next ?? '--';
    const cuDiff = data.cu_diff;
    if (cuDiff != null) {
      const cls = cuDiff >= 0 ? 'positive' : 'negative';
      $('cuNextSub').innerHTML = `M+3 合约 · <span class="${cls}">${cuDiff >= 0 ? '+' : ''}${cuDiff.toFixed(2)}</span>`;
    } else {
      $('cuNextSub').textContent = 'M+3 合约';
    }

    // Row 5: BC(M+3)
    $('bcNextLabel').textContent = '国际铜 ' + (data.bc_next || '--');
    $('bcNextPrice').textContent = data.bc_next ?? '--';
    const bcDiff = data.bc_diff;
    if (bcDiff != null) {
      const cls = bcDiff >= 0 ? 'positive' : 'negative';
      $('bcNextSub').innerHTML = `M+3 合约 · <span class="${cls}">${bcDiff >= 0 ? '+' : ''}${bcDiff.toFixed(2)}</span>`;
    } else {
      $('bcNextSub').textContent = 'M+3 合约';
    }
  } else {
    // M+1/M+2 mode
    $('cuNextLabel').textContent = '沪铜 ' + (data.cu_next || '--');
    $('cuNextPrice').textContent = data.cu_next ?? '--';
    const cuDiff = data.cu_diff;
    if (cuDiff != null) {
      const cls = cuDiff >= 0 ? 'positive' : 'negative';
      $('cuNextSub').innerHTML = `M+2 合约 · <span class="${cls}">${cuDiff >= 0 ? '+' : ''}${cuDiff.toFixed(2)}</span>`;
    } else {
      $('cuNextSub').textContent = 'M+2 合约';
    }

    $('bcNextLabel').textContent = '国际铜 ' + (data.bc_next || '--');
    $('bcNextPrice').textContent = data.bc_next ?? '--';
    const bcDiff = data.bc_diff;
    if (bcDiff != null) {
      const cls = bcDiff >= 0 ? 'positive' : 'negative';
      $('bcNextSub').innerHTML = `M+2 合约 · <span class="${cls}">${bcDiff >= 0 ? '+' : ''}${bcDiff.toFixed(2)}</span>`;
    } else {
      $('bcNextSub').textContent = 'M+2 合约';
    }
  }

  // Last update time
  const updateTime = data.update_time || data.date;
  $('lastUpdate').textContent = `数据时间：${updateTime}`;
}

// 获取日期字符串
function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// 显示错误
function showError(msg) {
  const toast = $('errorToast');
  $('errorMsg').textContent = msg;
  toast.classList.remove('hidden');
  setTimeout(() => toast.classList.add('hidden'), 4000);
}

// 显示/隐藏 loading
function setLoading(on) {
  $('loadingOverlay').classList.toggle('hidden', !on);
}

// 切换到实时模式
function switchToLive() {
  state.mode = 'live';
  $('modeText').innerHTML = '<i class="fa-solid fa-bolt mr-1"></i>实时模式';
  $('datePicker').disabled = false;
  $('switchBtn').innerHTML = '<i class="fa-solid fa-clock-rotate-left mr-1"></i>查看历史';
  $('switchBtn').onclick = switchToHistory;
  $('modeBanner').style.display = 'none';

  if (state.liveData) {
    renderLive(state.liveData);
  } else {
    fetchLatest();
  }

  startTimer();
}

// 切换到历史模式
function switchToHistory() {
  state.mode = 'history';
  $('modeText').innerHTML = '<i class="fa-regular fa-clock mr-1"></i>历史模式';
  $('datePicker').disabled = false;
  $('switchBtn').innerHTML = '<i class="fa-solid fa-bolt mr-1"></i>切至实时';
  $('switchBtn').onclick = switchToLive;
  $('modeBanner').style.display = 'block';

  stopTimer();
  const date = $('datePicker').value || todayStr();
  fetchHistory(date);
}

// 从 /api/latest 获取实时数据
async function fetchLatest() {
  setLoading(true);
  try {
    const resp = await fetch(`${API_BASE}/api/latest`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    state.liveData = data;
    if (state.mode === 'live') {
      renderLive(data);
    }
  } catch (e) {
    showError('获取实时数据失败：' + e.message);
  } finally {
    setLoading(false);
  }
}

// 从 /api/history 获取历史数据
async function fetchHistory(date) {
  setLoading(true);
  try {
    const resp = await fetch(`${API_BASE}/api/history?date=${date}`);
    if (!resp.ok) {
      if (resp.status === 404) throw new Error('该日期无数据');
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = await resp.json();
    state.historyData = data;
    renderLive(data); // 历史数据字段和实时数据共用一套渲染逻辑
  } catch (e) {
    showError('获取历史数据失败：' + e.message);
    // 清空显示
    ['cuMainPrice','bcMainPrice','ratioPrice','spreadPrice','cuNextPrice','bcNextPrice'].forEach(id => {
      $(id).textContent = '--';
    });
  } finally {
    setLoading(false);
  }
}

// 启动定时轮询
function startTimer() {
  stopTimer();
  state.timer = setInterval(fetchLatest, state.REFRESH_INTERVAL);
}

// 停止定时轮询
function stopTimer() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

// 初始化
async function init() {
  const today = todayStr();
  $('datePicker').value = today;
  $('datePicker').max = today;

  // 日期选择变化 → 历史查询
  $('datePicker').addEventListener('change', (e) => {
    if (state.mode === 'history') {
      fetchHistory(e.target.value);
    } else {
      // 自动切换到历史模式
      switchToHistory();
    }
  });

  // 初始加载
  await fetchLatest();
  switchToLive();
}

init();
