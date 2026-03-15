/**
 * GridCodec — Maidenhead propagation matrix codec (full-featured).
 * Works in Node and browser. Wire format v1 compatible with C/Python/Java.
 */
'use strict';

const GC_FIELD_LONS = 18;
const GC_FIELD_LATS = 18;
const GC_FIELDS = 324;
const GC_SQ_LONS = 10;
const GC_SQ_LATS = 10;
const GC_SQUARES = 100;
const GC_GRIDS = 32400;
const GC_FIELD_MATRIX_BYTES = 13122;
const GC_SQ_MATRIX_BYTES = 1250;
const GC_VERSION = 0x01;
const GC_FLAG_LAYER2 = 0x01;
const GC_ERR_INVALID = -1;
const GC_ERR_OVERFLOW = -2;
const GC_ERR_FORMAT = -3;
const GC_ERR_CAPACITY = -4;

const POPCOUNT_TABLE = new Uint8Array([
  0,1,1,2,1,2,2,3,1,2,2,3,2,3,3,4,1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,
  1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
  1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8,
  1,2,2,3,2,3,3,4,2,3,3,4,3,4,4,5,2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8,
  2,3,3,4,3,4,4,5,3,4,4,5,4,5,5,6,3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,
  3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8,
  3,4,4,5,4,5,5,6,4,5,5,6,5,6,6,7,4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8,
  4,5,5,6,5,6,6,7,5,6,6,7,6,7,7,8,5,6,6,7,6,7,7,8,6,7,7,8,7,8,8,8
]);

function bitGet(buf, bit) {
  return (buf[bit >> 3] >> (bit & 7)) & 1;
}
function bitSet(buf, bit) {
  buf[bit >> 3] |= 1 << (bit & 7);
}
function popcount32(v) {
  v = v >>> 0;
  return POPCOUNT_TABLE[v & 0xff] + POPCOUNT_TABLE[(v >>> 8) & 0xff] +
    POPCOUNT_TABLE[(v >>> 16) & 0xff] + POPCOUNT_TABLE[(v >>> 24) & 0xff];
}
function packMask(buf, pos, mask, nbits) {
  for (let i = 0; i < nbits; i++) {
    if (mask & (1 << i)) bitSet(buf, pos[0]);
    pos[0]++;
  }
}
function unpackMask(buf, pos, nbits) {
  let mask = 0;
  for (let i = 0; i < nbits; i++) {
    if (bitGet(buf, pos[0])) mask |= 1 << i;
    pos[0]++;
  }
  return mask >>> 0;
}
function maskIndices(mask, nbits) {
  const out = [];
  for (let i = 0; i < nbits; i++) if (mask & (1 << i)) out.push(i);
  return out;
}

function fieldIndex(name) {
  if (!name || name.length < 2) return -1;
  const c0 = name[0].toUpperCase().charCodeAt(0);
  const c1 = name[1].toUpperCase().charCodeAt(0);
  if (c0 < 65 || c0 > 82 || c1 < 65 || c1 > 82) return -1;
  return (c0 - 65) * GC_FIELD_LATS + (c1 - 65);
}
function fieldName(idx) {
  if (idx < 0 || idx >= GC_FIELDS) return '??';
  return String.fromCharCode(65 + Math.floor(idx / GC_FIELD_LATS), 65 + (idx % GC_FIELD_LATS));
}
function gridIndex(name) {
  if (!name || name.length < 4) return -1;
  const c0 = name[0].toUpperCase().charCodeAt(0);
  const c1 = name[1].toUpperCase().charCodeAt(0);
  const c2 = name[2].charCodeAt(0);
  const c3 = name[3].charCodeAt(0);
  if (c0 < 65 || c0 > 82 || c1 < 65 || c1 > 82) return -1;
  if (c2 < 48 || c2 > 57 || c3 < 48 || c3 > 57) return -1;
  const fi = (c0 - 65) * GC_FIELD_LATS + (c1 - 65);
  const si = (c2 - 48) * GC_SQ_LATS + (c3 - 48);
  return fi * GC_SQUARES + si;
}
function gridName(idx) {
  if (idx < 0 || idx >= GC_GRIDS) return '????';
  const fi = Math.floor(idx / GC_SQUARES);
  const si = idx % GC_SQUARES;
  return String.fromCharCode(65 + Math.floor(fi / GC_FIELD_LATS), 65 + (fi % GC_FIELD_LATS),
    48 + Math.floor(si / GC_SQ_LATS), 48 + (si % GC_SQ_LATS));
}
function gridToField(gridIdx) {
  return gridIdx < 0 || gridIdx >= GC_GRIDS ? -1 : Math.floor(gridIdx / GC_SQUARES);
}
function gridToSquare(gridIdx) {
  return gridIdx < 0 || gridIdx >= GC_GRIDS ? -1 : gridIdx % GC_SQUARES;
}

function computeDimMasks(matrixBits, nLons, nLats) {
  const N = nLons * nLats;
  let slm = 0, sam = 0, dlm = 0, dam = 0;
  for (let s = 0; s < N; s++) {
    for (let d = 0; d < N; d++) {
      if (bitGet(matrixBits, s * N + d)) {
        slm |= 1 << (s / nLats | 0);
        sam |= 1 << (s % nLats);
        dlm |= 1 << (d / nLats | 0);
        dam |= 1 << (d % nLats);
      }
    }
  }
  return [slm >>> 0, sam >>> 0, dlm >>> 0, dam >>> 0];
}

function buildEntryBitmap(matrixBits, nLons, nLats, activeLons, activeLats, isSrc) {
  const N = nLons * nLats;
  const nAl = activeLons.length, nAlat = activeLats.length;
  const nbytes = (nAl * nAlat + 7) >> 3;
  const out = new Uint8Array(nbytes);
  let count = 0;
  for (let li = 0; li < nAl; li++) {
    for (let ai = 0; ai < nAlat; ai++) {
      const entry = activeLons[li] * nLats + activeLats[ai];
      const bitIdx = li * nAlat + ai;
      let has = false;
      if (isSrc) {
        for (let d = 0; d < N && !has; d++) if (bitGet(matrixBits, entry * N + d)) has = true;
      } else {
        for (let s = 0; s < N && !has; s++) if (bitGet(matrixBits, s * N + entry)) has = true;
      }
      if (has) { bitSet(out, bitIdx); count++; }
    }
  }
  return { bitmap: out, count };
}

function bitmapToEntries(bitmap, nAl, nAlat, activeLons, activeLats, latsPerRow) {
  const out = [];
  for (let li = 0; li < nAl; li++)
    for (let ai = 0; ai < nAlat; ai++)
      if (bitGet(bitmap, li * nAlat + ai))
        out.push(activeLons[li] * latsPerRow + activeLats[ai]);
  return out;
}

function buildInnerMatrix(matrixBits, nLons, nLats, srcEntries, dstEntries) {
  const N = nLons * nLats;
  const nSrc = srcEntries.length, nDst = dstEntries.length;
  const nbytes = (nSrc * nDst + 7) >> 3;
  const inner = new Uint8Array(nbytes);
  for (let si = 0; si < nSrc; si++)
    for (let di = 0; di < nDst; di++)
      if (bitGet(matrixBits, srcEntries[si] * N + dstEntries[di]))
        bitSet(inner, si * nDst + di);
  return inner;
}

function encodeProjection(matrixBits, nLons, nLats, buf, offset, cap) {
  const [srcLonMask, srcLatMask, dstLonMask, dstLatMask] = computeDimMasks(matrixBits, nLons, nLats);
  const nSrcLon = popcount32(srcLonMask), nSrcLat = popcount32(srcLatMask);
  const nDstLon = popcount32(dstLonMask), nDstLat = popcount32(dstLatMask);
  const maskBytes = (nLons * 2 + nLats * 2 + 7) >> 3;
  if (offset + maskBytes > cap) return GC_ERR_OVERFLOW;
  const tmp = new Uint8Array(maskBytes);
  const pos = [0];
  packMask(tmp, pos, srcLonMask, nLons);
  packMask(tmp, pos, srcLatMask, nLats);
  packMask(tmp, pos, dstLonMask, nLons);
  packMask(tmp, pos, dstLatMask, nLats);
  buf.set(tmp, offset);
  let written = maskBytes;
  let posB = offset + maskBytes;

  const srcActiveLons = maskIndices(srcLonMask, nLons);
  const srcActiveLats = maskIndices(srcLatMask, nLats);
  const dstActiveLons = maskIndices(dstLonMask, nLons);
  const dstActiveLats = maskIndices(dstLatMask, nLats);

  const srcRes = buildEntryBitmap(matrixBits, nLons, nLats, srcActiveLons, srcActiveLats, true);
  const srcBmpBytes = (nSrcLon * nSrcLat + 7) >> 3;
  if (posB + srcBmpBytes > cap) return GC_ERR_OVERFLOW;
  buf.set(srcRes.bitmap.subarray(0, srcBmpBytes), posB);
  written += srcBmpBytes;
  posB += srcBmpBytes;

  const dstRes = buildEntryBitmap(matrixBits, nLons, nLats, dstActiveLons, dstActiveLats, false);
  const dstBmpBytes = (nDstLon * nDstLat + 7) >> 3;
  if (posB + dstBmpBytes > cap) return GC_ERR_OVERFLOW;
  buf.set(dstRes.bitmap.subarray(0, dstBmpBytes), posB);
  written += dstBmpBytes;
  posB += dstBmpBytes;

  const srcEntries = bitmapToEntries(srcRes.bitmap, nSrcLon, nSrcLat, srcActiveLons, srcActiveLats, nLats);
  const dstEntries = bitmapToEntries(dstRes.bitmap, nDstLon, nDstLat, dstActiveLons, dstActiveLats, nLats);
  const inner = buildInnerMatrix(matrixBits, nLons, nLats, srcEntries, dstEntries);
  const innerBytes = (srcEntries.length * dstEntries.length + 7) >> 3;
  if (posB + innerBytes > cap) return GC_ERR_OVERFLOW;
  buf.set(inner.subarray(0, innerBytes), posB);
  written += innerBytes;
  return written;
}

function decodeProjection(buf, offset, length, nLons, nLats, matrixBits) {
  const N = nLons * nLats;
  const matrixBytes = (N * N + 7) >> 3;
  for (let i = 0; i < matrixBytes; i++) matrixBits[i] = 0;
  const seg = buf.subarray(offset, offset + length);
  const segLen = seg.length;
  const maskBytes = (nLons * 2 + nLats * 2 + 7) >> 3;
  if (maskBytes > segLen) return GC_ERR_FORMAT;
  const pos = [0];
  const srcLonMask = unpackMask(seg, pos, nLons);
  const srcLatMask = unpackMask(seg, pos, nLats);
  const dstLonMask = unpackMask(seg, pos, nLons);
  const dstLatMask = unpackMask(seg, pos, nLats);
  let consumed = maskBytes;
  let posB = maskBytes;
  const nSrcLon = popcount32(srcLonMask), nSrcLat = popcount32(srcLatMask);
  const nDstLon = popcount32(dstLonMask), nDstLat = popcount32(dstLatMask);
  const srcBmpBytes = (nSrcLon * nSrcLat + 7) >> 3;
  if (posB + srcBmpBytes > segLen) return GC_ERR_FORMAT;
  const srcBmp = seg.subarray(posB, posB + srcBmpBytes);
  consumed += srcBmpBytes;
  posB += srcBmpBytes;
  const dstBmpBytes = (nDstLon * nDstLat + 7) >> 3;
  if (posB + dstBmpBytes > segLen) return GC_ERR_FORMAT;
  const dstBmp = seg.subarray(posB, posB + dstBmpBytes);
  consumed += dstBmpBytes;
  posB += dstBmpBytes;
  const srcActiveLons = maskIndices(srcLonMask, nLons);
  const srcActiveLats = maskIndices(srcLatMask, nLats);
  const dstActiveLons = maskIndices(dstLonMask, nLons);
  const dstActiveLats = maskIndices(dstLatMask, nLats);
  const srcEntries = bitmapToEntries(srcBmp, nSrcLon, nSrcLat, srcActiveLons, srcActiveLats, nLats);
  const dstEntries = bitmapToEntries(dstBmp, nDstLon, nDstLat, dstActiveLons, dstActiveLats, nLats);
  const innerBytes = (srcEntries.length * dstEntries.length + 7) >> 3;
  if (posB + innerBytes > segLen) return GC_ERR_FORMAT;
  const inner = seg.subarray(posB, posB + innerBytes);
  consumed += innerBytes;
  for (let si = 0; si < srcEntries.length; si++)
    for (let di = 0; di < dstEntries.length; di++)
      if (bitGet(inner, si * dstEntries.length + di))
        bitSet(matrixBits, srcEntries[si] * N + dstEntries[di]);
  return consumed;
}

class GridCodecMatrix {
  constructor() {
    this.fieldBits = new Uint8Array(GC_FIELD_MATRIX_BYTES);
    this.pairSrc = [];
    this.pairDst = [];
    this.sqBits = [];
  }

  set(from4, to4) {
    const srcGi = gridIndex(from4);
    const dstGi = gridIndex(to4);
    if (srcGi < 0 || dstGi < 0) return GC_ERR_INVALID;
    const srcFi = (srcGi / GC_SQUARES) | 0;
    const dstFi = (dstGi / GC_SQUARES) | 0;
    const srcSi = srcGi % GC_SQUARES;
    const dstSi = dstGi % GC_SQUARES;
    bitSet(this.fieldBits, srcFi * GC_FIELDS + dstFi);
    let pairIdx = -1;
    for (let i = 0; i < this.pairSrc.length; i++) {
      if (this.pairSrc[i] === srcFi && this.pairDst[i] === dstFi) { pairIdx = i; break; }
    }
    if (pairIdx < 0) {
      this.pairSrc.push(srcFi);
      this.pairDst.push(dstFi);
      const b = new Uint8Array(GC_SQ_MATRIX_BYTES);
      this.sqBits.push(b);
      pairIdx = this.sqBits.length - 1;
    }
    bitSet(this.sqBits[pairIdx], srcSi * GC_SQUARES + dstSi);
    return 0;
  }

  _findPair(srcFi, dstFi) {
    for (let i = 0; i < this.pairSrc.length; i++)
      if (this.pairSrc[i] === srcFi && this.pairDst[i] === dstFi) return i;
    return -1;
  }

  encode(cap = 1024 * 1024) {
    const buf = new Uint8Array(cap);
    if (cap < 2) return { data: null, len: GC_ERR_OVERFLOW };
    const hasL2 = this.pairSrc.length > 0 ? 1 : 0;
    buf[0] = GC_VERSION;
    buf[1] = hasL2 ? GC_FLAG_LAYER2 : 0;
    let written = 2;
    const l1Bytes = encodeProjection(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, buf, written, cap);
    if (l1Bytes < 0) return { data: null, len: l1Bytes };
    written += l1Bytes;
    if (!hasL2) return { data: buf.subarray(0, written), len: written };
    const [slm, sam, dlm, dam] = computeDimMasks(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS);
    const srcActiveLons = maskIndices(slm, GC_FIELD_LONS);
    const srcActiveLats = maskIndices(sam, GC_FIELD_LATS);
    const dstActiveLons = maskIndices(dlm, GC_FIELD_LONS);
    const dstActiveLats = maskIndices(dam, GC_FIELD_LATS);
    const srcRes = buildEntryBitmap(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, srcActiveLons, srcActiveLats, true);
    const dstRes = buildEntryBitmap(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, dstActiveLons, dstActiveLats, false);
    const srcEntries = bitmapToEntries(srcRes.bitmap, srcActiveLons.length, srcActiveLats.length, srcActiveLons, srcActiveLats, GC_FIELD_LATS);
    const dstEntries = bitmapToEntries(dstRes.bitmap, dstActiveLons.length, dstActiveLats.length, dstActiveLons, dstActiveLats, GC_FIELD_LATS);
    for (let si = 0; si < srcEntries.length; si++) {
      for (let di = 0; di < dstEntries.length; di++) {
        const srcFi = srcEntries[si], dstFi = dstEntries[di];
        if (!bitGet(this.fieldBits, srcFi * GC_FIELDS + dstFi)) continue;
        const pairIdx = this._findPair(srcFi, dstFi);
        if (pairIdx < 0) {
          const need = (GC_SQ_LONS * 2 + GC_SQ_LATS * 2 + 7) >> 3;
          if (written + need > cap) return { data: null, len: GC_ERR_OVERFLOW };
          written += need;
        } else {
          const sub = encodeProjection(this.sqBits[pairIdx], GC_SQ_LONS, GC_SQ_LATS, buf, written, cap);
          if (sub < 0) return { data: null, len: sub };
          written += sub;
        }
      }
    }
    return { data: buf.subarray(0, written), len: written };
  }

  decode(data) {
    if (data.length < 2) return GC_ERR_FORMAT;
    if (data[0] !== GC_VERSION) return GC_ERR_FORMAT;
    const flags = data[1];
    let consumed = 2;
    this.fieldBits = new Uint8Array(GC_FIELD_MATRIX_BYTES);
    this.pairSrc = [];
    this.pairDst = [];
    this.sqBits = [];
    const view = data instanceof Uint8Array ? data : new Uint8Array(data);
    let l1Bytes = decodeProjection(view, consumed, data.length - consumed, GC_FIELD_LONS, GC_FIELD_LATS, this.fieldBits);
    if (l1Bytes < 0) return l1Bytes;
    consumed += l1Bytes;
    if (!(flags & GC_FLAG_LAYER2)) return consumed;
    const [slm, sam, dlm, dam] = computeDimMasks(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS);
    const srcActiveLons = maskIndices(slm, GC_FIELD_LONS);
    const srcActiveLats = maskIndices(sam, GC_FIELD_LATS);
    const dstActiveLons = maskIndices(dlm, GC_FIELD_LONS);
    const dstActiveLats = maskIndices(dam, GC_FIELD_LATS);
    const srcRes = buildEntryBitmap(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, srcActiveLons, srcActiveLats, true);
    const dstRes = buildEntryBitmap(this.fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, dstActiveLons, dstActiveLats, false);
    const srcEntries = bitmapToEntries(srcRes.bitmap, srcActiveLons.length, srcActiveLats.length, srcActiveLons, srcActiveLats, GC_FIELD_LATS);
    const dstEntries = bitmapToEntries(dstRes.bitmap, dstActiveLons.length, dstActiveLats.length, dstActiveLons, dstActiveLats, GC_FIELD_LATS);
    for (let si = 0; si < srcEntries.length; si++) {
      for (let di = 0; di < dstEntries.length; di++) {
        const srcFi = srcEntries[si], dstFi = dstEntries[di];
        if (!bitGet(this.fieldBits, srcFi * GC_FIELDS + dstFi)) continue;
        const sq = new Uint8Array(GC_SQ_MATRIX_BYTES);
        const sub = decodeProjection(view, consumed, data.length - consumed, GC_SQ_LONS, GC_SQ_LATS, sq);
        if (sub < 0) return sub;
        this.pairSrc.push(srcFi);
        this.pairDst.push(dstFi);
        this.sqBits.push(sq);
        consumed += sub;
      }
    }
    return consumed;
  }

  gcFrom(grid, maxOut = 32400) {
    if (!grid || maxOut <= 0) return [];
    const s = String(grid).trim();
    if (s.length === 2) {
      const fi = fieldIndex(s);
      if (fi < 0) return [];
      return this._queryFieldFrom(fi, maxOut);
    }
    if (s.length >= 4) {
      const gi = gridIndex(s);
      if (gi < 0) return [];
      return this._queryGridFrom(gi, maxOut);
    }
    return [];
  }

  gcTo(grid, maxOut = 32400) {
    if (!grid || maxOut <= 0) return [];
    const s = String(grid).trim();
    if (s.length === 2) {
      const fi = fieldIndex(s);
      if (fi < 0) return [];
      return this._queryFieldTo(fi, maxOut);
    }
    if (s.length >= 4) {
      const gi = gridIndex(s);
      if (gi < 0) return [];
      return this._queryGridTo(gi, maxOut);
    }
    return [];
  }

  _queryFieldFrom(srcFi, maxOut) {
    const out = [];
    for (let d = 0; d < GC_FIELDS && out.length < maxOut; d++)
      if (bitGet(this.fieldBits, srcFi * GC_FIELDS + d)) out.push(d);
    return out;
  }
  _queryFieldTo(dstFi, maxOut) {
    const out = [];
    for (let s = 0; s < GC_FIELDS && out.length < maxOut; s++)
      if (bitGet(this.fieldBits, s * GC_FIELDS + dstFi)) out.push(s);
    return out;
  }
  _queryGridFrom(srcGi, maxOut) {
    const srcFi = (srcGi / GC_SQUARES) | 0, srcSi = srcGi % GC_SQUARES;
    const out = [];
    for (let dstFi = 0; dstFi < GC_FIELDS; dstFi++) {
      if (!bitGet(this.fieldBits, srcFi * GC_FIELDS + dstFi)) continue;
      const pairIdx = this._findPair(srcFi, dstFi);
      if (pairIdx < 0) continue;
      for (let dstSi = 0; dstSi < GC_SQUARES && out.length < maxOut; dstSi++)
        if (bitGet(this.sqBits[pairIdx], srcSi * GC_SQUARES + dstSi))
          out.push(dstFi * GC_SQUARES + dstSi);
    }
    return out;
  }
  _queryGridTo(dstGi, maxOut) {
    const dstFi = (dstGi / GC_SQUARES) | 0, dstSi = dstGi % GC_SQUARES;
    const out = [];
    for (let srcFi = 0; srcFi < GC_FIELDS; srcFi++) {
      if (!bitGet(this.fieldBits, srcFi * GC_FIELDS + dstFi)) continue;
      const pairIdx = this._findPair(srcFi, dstFi);
      if (pairIdx < 0) continue;
      for (let srcSi = 0; srcSi < GC_SQUARES && out.length < maxOut; srcSi++)
        if (bitGet(this.sqBits[pairIdx], srcSi * GC_SQUARES + dstSi))
          out.push(srcFi * GC_SQUARES + srcSi);
    }
    return out;
  }
}

// Export for Node (CommonJS) and browser (global or module)
const api = {
  GC_FIELDS, GC_SQUARES, GC_GRIDS, GC_VERSION,
  GC_ERR_INVALID, GC_ERR_OVERFLOW, GC_ERR_FORMAT, GC_ERR_CAPACITY,
  fieldIndex, fieldName, gridIndex, gridName, gridToField, gridToSquare,
  GridCodecMatrix
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') globalThis.gridcodec = api;
