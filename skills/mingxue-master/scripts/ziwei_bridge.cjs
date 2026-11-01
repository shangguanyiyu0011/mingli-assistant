'use strict';

// ABI 1: a single JSON request on stdin and a single JSON response on stdout.
const fs = require('node:fs');
const path = require('node:path');
const VERSION = '2.6.3';
const ABI = 1;

function selected(obj, keys) {
  return Object.fromEntries(keys.filter(k => Object.hasOwn(obj, k)).map(k => [k, obj[k]]));
}

function plainChart(instance) {
  const chart = instance.toJSON();
  const result = selected(chart, [
    'gender', 'solarDate', 'lunarDate', 'chineseDate', 'time', 'timeRange',
    'earthlyBranchOfSoulPalace', 'earthlyBranchOfBodyPalace', 'soul', 'body', 'fiveElementsClass',
  ]);
  result.palaces = chart.palaces.map(p => {
    const row = selected(p, [
      'index', 'name', 'isBodyPalace', 'isOriginalPalace', 'heavenlyStem', 'earthlyBranch',
      'changsheng12', 'boshi12', 'jiangqian12', 'suiqian12', 'decadal', 'ages',
    ]);
    for (const group of ['majorStars', 'minorStars', 'adjectiveStars']) {
      row[group] = p[group].map(s => selected(s, ['name', 'type', 'scope', 'brightness', 'mutagen']));
    }
    const surroundings = instance.surroundedPalaces(p.index).toJSON();
    row.surroundedPalaces = Object.fromEntries(
      Object.entries(surroundings).filter(([, v]) => v && Number.isInteger(v.index)).map(([k, v]) => [k, v.index]),
    );
    return row;
  });
  return result;
}

function plainFlowItem(item) {
  const result = selected(item, ['index', 'name', 'heavenlyStem', 'earthlyBranch', 'palaceNames', 'mutagen', 'nominalAge']);
  if (Array.isArray(item.stars)) {
    result.stars = item.stars.map(group => group.map(star => selected(star, ['name', 'type', 'scope', 'brightness', 'mutagen'])));
  }
  if (item.yearlyDecStar) result.yearlyDecStar = selected(item.yearlyDecStar, ['jiangqian12', 'suiqian12']);
  return result;
}

function plainHoroscope(instance, target, scope) {
  // Always supply BOTH arguments. No current-date/host-timezone default is used.
  const raw = instance.horoscope(target.date, target.time_index).toJSON();
  const levels = ['yearly', 'monthly', 'daily'];
  const layers = Object.fromEntries(levels.slice(0, levels.indexOf(scope) + 1).map(level => [level, plainFlowItem(raw[level])]));
  return {
    solarDate: raw.solarDate, lunarDate: raw.lunarDate, layers,
    context: { decadal: plainFlowItem(raw.decadal), age: plainFlowItem(raw.age) },
  };
}

function run(request) {
  const modulePath = path.join(request.engine_dir, 'node_modules', 'iztro');
  const pkg = JSON.parse(fs.readFileSync(path.join(modulePath, 'package.json'), 'utf8'));
  if (pkg.version !== VERSION) throw new Error(`engine version mismatch: expected ${VERSION}, got ${pkg.version}`);
  const { astro } = require(modulePath);
  if (!astro || typeof astro.bySolar !== 'function' || typeof astro.resetConfig !== 'function') {
    throw new Error('engine does not expose required chart/config API');
  }
  astro.resetConfig();
  if (request.action === 'probe') {
    const sample = astro.bySolar('2000-8-16', 2, '女', true, 'zh-CN').toJSON();
    if (sample.palaces.length !== 12 || sample.fiveElementsClass !== '木三局' ||
        sample.earthlyBranchOfSoulPalace !== '午' || sample.earthlyBranchOfBodyPalace !== '戌') {
      throw new Error('engine sample contract failed');
    }
    const flow = astro.bySolar('2000-8-16', 2, '女', true, 'zh-CN').horoscope('2023-8-19', 2).toJSON();
    if (flow.yearly.index !== 1 || flow.monthly.index !== 3 || flow.daily.index !== 6) {
      throw new Error('engine horoscope sample contract failed');
    }
    return { status: 'available', engine: { name: 'iztro', version: VERSION, abi: ABI, node: process.versions.node },
      capabilities: ['origin', 'yearly', 'monthly', 'daily'] };
  }
  if (request.action !== 'chart') throw new Error('unsupported bridge action');
  const settings = request.settings;
  astro.config({
    algorithm: settings.algorithm, yearDivide: settings.year_divide,
    dayDivide: settings.day_divide, horoscopeDivide: settings.horoscope_divide || 'normal', ageDivide: 'normal',
  });
  const genders = request.gender ? [request.gender] : ['male', 'female'];
  const instances = genders.map(gender => astro.bySolar(
    request.solar_date, request.time_index, gender === 'male' ? '男' : '女', settings.fix_leap, 'zh-CN',
  ));
  const result = { status: 'ok', engine: { name: 'iztro', version: VERSION, abi: ABI, node: process.versions.node },
    charts: instances.map(plainChart) };
  if (request.target) {
    if (!['yearly', 'monthly', 'daily'].includes(request.scope)) throw new Error('invalid horoscope scope');
    result.horoscopes = instances.map(instance => plainHoroscope(instance, request.target, request.scope));
    const calendar = require(path.join(request.engine_dir, 'node_modules', 'lunar-lite'));
    result.target_lunar = selected(calendar.solar2lunar(request.target.date), ['lunarYear', 'lunarMonth', 'lunarDay', 'isLeap']);
  }
  return result;
}

try {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(run(request)) + '\n');
} catch (error) {
  process.stdout.write(JSON.stringify({ status: 'engine_error', error: String(error.message || error), abi: ABI }) + '\n');
  process.exitCode = 1;
}
