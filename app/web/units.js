/*!
 * CCGauge 数字单位格式化（纯函数，无依赖）
 *
 * 三种数字单位模式（设置键 number_unit）：
 *   cn    中文单位：亿 / 万（不足一万显示原数），数字与单位紧贴（如 120万、1.2亿）
 *   en    英文单位：B / M / K（与历史输出逐字节一致，作为回归基线）
 *   plain 原始数字：千分位完整整数（如 12,345,678）
 *
 * 浏览器下挂 window.CCGaugeUnits，Node 下可 require，供 node --test 直接测试。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.CCGaugeUnits = api;
})(typeof self !== 'undefined' ? self : (typeof globalThis !== 'undefined' ? globalThis : null), function () {
  'use strict';

  /** 合法模式；顺序即设置页分段顺序。 */
  const UNIT_MODES = ['cn', 'en', 'plain'];

  /** 中文档位表（从大到小）。不足一万的数值不使用档位，直接显示原数。 */
  const CN_UNITS = [
    { value: 1e8, label: '亿' },
    { value: 1e4, label: '万' },
  ];

  /** 中文档位下限：低于一万显示原数。 */
  const CN_UNIT_MIN = 1e4;

  /** 归一化：非有限值 / 负值一律按 0 处理。 */
  function toNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  /** 千分位完整整数（原始数字模式与悬停提示用）。 */
  function formatInt(value) {
    return toNumber(value).toLocaleString('en-US');
  }

  /** 去掉无意义的小数尾零："1.20"→"1.2"、"1.00"→"1"。 */
  function trimZeros(text) {
    return text.indexOf('.') < 0 ? text : text.replace(/0+$/, '').replace(/\.$/, '');
  }

  /**
   * 中文单位：从大到小取第一个「保留 2 位小数后 ≥ 1」的档位；不足一万显示原数。
   * 进位保护示例：999,999 → 100万、99,999 → 10万。
   */
  function formatCn(n) {
    if (n < CN_UNIT_MIN) return String(n);
    for (let i = 0; i < CN_UNITS.length; i += 1) {
      const unit = CN_UNITS[i];
      const text = trimZeros((n / unit.value).toFixed(2));
      if (Number(text) >= 1) return text + unit.label;
    }
    return formatInt(n);   // 兜底：档位表覆盖不到的超大值退回完整数字
  }

  /** 英文单位：保持历史 fmtCompact 行为不变（回归基线）。 */
  function formatEn(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  }

  /** 按模式格式化紧凑数字；非法模式回落到 cn。 */
  function formatCompact(value, mode) {
    const n = toNumber(value);
    if (mode === 'plain') return formatInt(n);
    if (mode === 'en') return formatEn(n);
    return formatCn(n);
  }

  /**
   * 生效模式：已显式设置过则用设置值；未设置（空串 / 非法）时按界面语言派生。
   * zh → cn、en → en，与服务端「不预写默认值」的约定一致。
   */
  function effectiveUnitMode(stored, lang) {
    return UNIT_MODES.indexOf(stored) >= 0 ? stored : (lang === 'en' ? 'en' : 'cn');
  }

  return {
    UNIT_MODES: UNIT_MODES,
    CN_UNITS: CN_UNITS,
    formatInt: formatInt,
    formatCompact: formatCompact,
    effectiveUnitMode: effectiveUnitMode,
  };
});
