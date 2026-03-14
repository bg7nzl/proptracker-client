/**
 * GridCodec tests + performance. Run with: node test_gridcodec.js
 */
const gc = require('./gridcodec.js');

const { fieldIndex, fieldName, gridIndex, gridName, GridCodecMatrix } = gc;

function testHelpers() {
  console.log('  test field_index / field_name...');
  if (fieldIndex('FN') !== 5 * 18 + 13) throw new Error('fieldIndex FN');
  if (fieldName(fieldIndex('FN')) !== 'FN') throw new Error('fieldName');
  if (fieldIndex('OL') !== 14 * 18 + 11) throw new Error('fieldIndex OL');
  console.log('  OK');

  console.log('  test grid_index / grid_name...');
  if (gridName(gridIndex('FN31')) !== 'FN31') throw new Error('grid name');
  console.log('  OK');
}

function testEmptyRoundtrip() {
  console.log('  test_empty_roundtrip...');
  const m = new GridCodecMatrix();
  const { data, len } = m.encode();
  if (len <= 0 || data[0] !== 0x01 || data[1] !== 0) throw new Error('empty encode');
  const m2 = new GridCodecMatrix();
  const consumed = m2.decode(data);
  if (consumed !== len) throw new Error('decode len');
  console.log(' OK (encoded ' + len + ' bytes)');
}

function testSinglePathRoundtrip() {
  console.log('  test_single_path_roundtrip...');
  const m = new GridCodecMatrix();
  if (m.set('FN31', 'PM02') !== 0) throw new Error('set');
  const { data, len } = m.encode();
  if (len <= 0) throw new Error('encode');
  const m2 = new GridCodecMatrix();
  const consumed = m2.decode(data);
  if (consumed !== len) throw new Error('decode');
  const fromFn = m2.gcFrom('FN31');
  if (fromFn.length !== 1 || gridName(fromFn[0]) !== 'PM02') throw new Error('gc_from');
  const toPm = m2.gcTo('PM02');
  if (toPm.length !== 1 || gridName(toPm[0]) !== 'FN31') throw new Error('gc_to');
  console.log(' OK (encoded ' + len + ' bytes)');
}

function testQueryFromTo() {
  console.log('  test_query_from_to...');
  const m = new GridCodecMatrix();
  m.set('FN31', 'PM02');
  m.set('FN31', 'PM03');
  m.set('JO22', 'FN31');
  const fromFn = m.gcFrom('FN31');
  if (fromFn.length !== 2) throw new Error('from count');
  const names = fromFn.map(i => gridName(i));
  if (!names.includes('PM02') || !names.includes('PM03')) throw new Error('from names');
  const toFn = m.gcTo('FN31');
  if (toFn.length !== 1 || gridName(toFn[0]) !== 'JO22') throw new Error('to');
  console.log(' OK');
}

function testDedup() {
  console.log('  test_dedup...');
  const m = new GridCodecMatrix();
  m.set('OL72', 'FN31');
  m.set('OL72', 'FN31');
  const { data, len } = m.encode();
  const m2 = new GridCodecMatrix();
  m2.decode(data);
  const fromOl = m2.gcFrom('OL72');
  if (fromOl.length !== 1 || gridName(fromOl[0]) !== 'FN31') throw new Error('dedup');
  console.log(' OK');
}

function testCInterop() {
  console.log('  test_c_interop (decode C payload)...');
  const payload = new Uint8Array([
    0x01, 0x00, 0x20, 0x02, 0x00, 0x80, 0x01, 0x02, 0x08, 0x00, 0x0c, 0x09,
    0x06, 0x06
  ]);
  const m = new GridCodecMatrix();
  const consumed = m.decode(payload);
  if (consumed !== payload.length) throw new Error('consumed');
  const fromFn = m.gcFrom('FN');
  if (fromFn.length !== 1 || fieldName(fromFn[0]) !== 'PM') throw new Error('from FN');
  const toFn = m.gcTo('FN');
  if (toFn.length !== 1 || fieldName(toFn[0]) !== 'JO') throw new Error('to FN');
  console.log(' OK');
}

function testRealistic(nPaths) {
  console.log('  test_realistic_roundtrip (' + nPaths + ' paths)...');
  const m = new GridCodecMatrix();
  const grids = [];
  for (let i = 0; i < nPaths * 2; i++) {
    const fi = Math.floor(Math.random() * gc.GC_FIELDS);
    const si = Math.floor(Math.random() * gc.GC_SQUARES);
    const lon = Math.floor(si / 10), lat = si % 10;
    grids.push(fieldName(fi) + lon + lat);
  }
  for (let i = 0; i < nPaths * 2 - 1; i += 2) m.set(grids[i], grids[i + 1]);
  const t0 = performance.now();
  const { data, len } = m.encode();
  const t1 = performance.now();
  const m2 = new GridCodecMatrix();
  const consumed = m2.decode(data);
  const t2 = performance.now();
  if (consumed !== len) throw new Error('decode len');
  let verified = 0;
  for (let i = 0; i < nPaths * 2 - 1; i += 2) {
    const out = m2.gcFrom(grids[i]);
    if (out.some(idx => gridName(idx) === grids[i + 1])) verified++;
  }
  if (verified !== nPaths) throw new Error('verified ' + verified);
  console.log(' OK');
  console.log('    Encoded: ' + len + ' bytes, Encode: ' + (t1 - t0).toFixed(2) + ' ms, Decode: ' + (t2 - t1).toFixed(2) + ' ms, Verified: ' + verified);
}

function testPerformance() {
  console.log('  [Performance] 500 / 5000 / 2000 paths...');
  for (const n of [500, 5000, 2000]) {
    const m = new GridCodecMatrix();
    for (let i = 0; i < n; i++) {
      const a = [Math.floor(Math.random() * gc.GC_FIELDS), Math.floor(Math.random() * gc.GC_SQUARES)];
      const b = [Math.floor(Math.random() * gc.GC_FIELDS), Math.floor(Math.random() * gc.GC_SQUARES)];
      const fromG = fieldName(a[0]) + Math.floor(a[1] / 10) + (a[1] % 10);
      const toG = fieldName(b[0]) + Math.floor(b[1] / 10) + (b[1] % 10);
      m.set(fromG, toG);
    }
    const t0 = performance.now();
    const { data, len } = m.encode();
    const t1 = performance.now();
    const m2 = new GridCodecMatrix();
    m2.decode(data);
    const t2 = performance.now();
    console.log('    ' + n + ' paths: encoded ' + len + ' bytes, encode ' + (t1 - t0).toFixed(2) + ' ms, decode ' + (t2 - t1).toFixed(2) + ' ms');
  }
}

function main() {
  console.log('=== GridCodec JavaScript Test Suite ===\n');
  Math.seedrandom ? Math.seedrandom(42) : null;
  console.log('[Helpers]');
  testHelpers();
  console.log('\n[Round-trip]');
  testEmptyRoundtrip();
  testSinglePathRoundtrip();
  console.log('\n[Query]');
  testQueryFromTo();
  testDedup();
  console.log('\n[Realistic]');
  testRealistic(500);
  testRealistic(5000);
  testRealistic(2000);
  console.log('\n[C interop]');
  testCInterop();
  console.log('\n[Performance]');
  testPerformance();
  console.log('\n=== All tests passed ===\n');
}

main();
