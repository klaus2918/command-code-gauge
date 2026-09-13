/**
 * 数字单位格式化单元测试（Node 内置 test runner，无第三方依赖）
 *
 * 运行：node --test tests/js/
 * 覆盖：中文档位与进位保护、英文回归基线、原始数字、非法值兜底、中文输出无空格
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const units = require('../../app/web/units.js');
const { formatCompact, formatInt, effectiveUnitMode, UNIT_MODES } = units;

/** 中文单位模式期望表：档位与进位边界（不足一万显示原数）。 */
const CN_CASES = [
  [0, '0'],
  [1, '1'],
  [999, '999'],
  [9999, '9999'],           // 不足一万：原数（不出现「10千」这类表述）
  [10000, '1万'],
  [12345, '1.23万'],
  [99999, '10万'],           // 进位保护：不是 1十万
  [100000, '10万'],
  [999999, '1百万'],         // 进位保护：不是 10十万
  [1234567, '1.23百万'],
  [12345678, '1.23千万'],
  [123456789, '1.23亿'],
  [987654321, '9.88亿'],
  [1000000000, '10亿'],
  [123456789012, '1234.57亿'],   // 万亿档以下的最大档仍是亿
  [1234567890123, '1.23万亿'],
];

/** 英文单位模式回归基线：与历史 fmtCompact 输出逐字节一致。 */
const EN_CASES = [
  [0, '0'],
  [999, '999'],
  [1000, '1.0K'],
  [1234, '1.2K'],
  [1200000, '1.20M'],
  [1234567890, '1.23B'],
];

test('UNIT_MODES 覆盖三态并含默认 cn', () => {
  assert.deepEqual(UNIT_MODES, ['cn', 'en', 'plain']);
});

test('中文单位：档位与进位边界', () => {
  for (const [input, expected] of CN_CASES) {
    assert.equal(formatCompact(input, 'cn'), expected, `${input} → ${expected}`);
  }
});

test('中文单位：数字与单位紧贴，输出不含空白字符', () => {
  for (const [input, expected] of CN_CASES) {
    const out = formatCompact(input, 'cn');
    assert.equal(/\s/.test(out), false, `${input} → ${JSON.stringify(out)} 不应含空格`);
    assert.equal(out, expected);
  }
});

test('英文单位：与历史输出一致（回归基线）', () => {
  for (const [input, expected] of EN_CASES) {
    assert.equal(formatCompact(input, 'en'), expected, `${input} → ${expected}`);
  }
});

test('原始数字：千分位完整整数', () => {
  assert.equal(formatCompact(12345678, 'plain'), '12,345,678');
  assert.equal(formatCompact(999, 'plain'), '999');
  assert.equal(formatCompact(0, 'plain'), '0');
  assert.equal(formatCompact('1234567890', 'plain'), '1,234,567,890');
});

test('formatInt 与 plain 模式一致', () => {
  assert.equal(formatInt(12345678), '12,345,678');
  assert.equal(formatInt(0), '0');
});

test('非法值兜底为 0', () => {
  for (const bad of [null, undefined, NaN, 'abc', {}, [], -5, -0.5, Infinity, -Infinity]) {
    assert.equal(formatCompact(bad, 'cn'), '0', `cn 兜底：${String(bad)}`);
    assert.equal(formatCompact(bad, 'en'), '0', `en 兜底：${String(bad)}`);
    assert.equal(formatCompact(bad, 'plain'), '0', `plain 兜底：${String(bad)}`);
  }
});

test('非法模式回落中文单位', () => {
  assert.equal(formatCompact(12345678, undefined), '1.23千万');
  assert.equal(formatCompact(12345678, 'BOGUS'), '1.23千万');
  assert.equal(formatCompact(12345678, null), '1.23千万');
});

test('effectiveUnitMode：已设置值优先，未设置时按语言派生', () => {
  assert.equal(effectiveUnitMode('cn', 'en'), 'cn');
  assert.equal(effectiveUnitMode('en', 'zh'), 'en');
  assert.equal(effectiveUnitMode('plain', 'zh'), 'plain');
  assert.equal(effectiveUnitMode('', 'zh'), 'cn');
  assert.equal(effectiveUnitMode('', 'en'), 'en');
  assert.equal(effectiveUnitMode(null, 'en'), 'en');
  assert.equal(effectiveUnitMode(undefined, 'zh'), 'cn');
  assert.equal(effectiveUnitMode('bogus', 'en'), 'en');
  assert.equal(effectiveUnitMode('bogus', 'zh'), 'cn');
});
