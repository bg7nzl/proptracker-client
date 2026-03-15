/**
 * GridCodec — Maidenhead propagation matrix codec (Java 8, full-featured).
 * Wire format v1 compatible with C/Python/JS.
 */
package gridcodec;

import java.util.ArrayList;
import java.util.List;

public final class GridCodec {

    public static final int GC_FIELD_LONS = 18;
    public static final int GC_FIELD_LATS = 18;
    public static final int GC_FIELDS = 324;
    public static final int GC_SQ_LONS = 10;
    public static final int GC_SQ_LATS = 10;
    public static final int GC_SQUARES = 100;
    public static final int GC_GRIDS = 32400;
    public static final int GC_FIELD_MATRIX_BYTES = 13122;
    public static final int GC_SQ_MATRIX_BYTES = 1250;
    public static final int GC_VERSION = 0x01;
    public static final int GC_FLAG_LAYER2 = 0x01;
    public static final int GC_ERR_INVALID = -1;
    public static final int GC_ERR_OVERFLOW = -2;
    public static final int GC_ERR_FORMAT = -3;
    public static final int GC_ERR_CAPACITY = -4;

    private static final int[] POPCOUNT_TABLE = new int[256];
    static {
        for (int i = 0; i < 256; i++) POPCOUNT_TABLE[i] = Integer.bitCount(i);
    }

    private static int bitGet(byte[] buf, int bit) {
        return (buf[bit >> 3] >> (bit & 7)) & 1;
    }
    private static void bitSet(byte[] buf, int bit) {
        buf[bit >> 3] |= (1 << (bit & 7));
    }
    private static int popcount32(int v) {
        return Integer.bitCount(v & 0xFFFFFFFF);
    }
    private static void packMask(byte[] buf, int[] pos, int mask, int nbits) {
        for (int i = 0; i < nbits; i++) {
            if ((mask & (1 << i)) != 0) bitSet(buf, pos[0]);
            pos[0]++;
        }
    }
    private static int unpackMask(byte[] buf, int[] pos, int nbits) {
        int mask = 0;
        for (int i = 0; i < nbits; i++) {
            if (bitGet(buf, pos[0]) != 0) mask |= (1 << i);
            pos[0]++;
        }
        return mask & 0xFFFFFFFF;
    }
    private static List<Integer> maskIndices(int mask, int nbits) {
        List<Integer> out = new ArrayList<>();
        for (int i = 0; i < nbits; i++)
            if ((mask & (1 << i)) != 0) out.add(i);
        return out;
    }

    public static int fieldIndex(String name) {
        if (name == null || name.length() < 2) return -1;
        int c0 = Character.toUpperCase(name.charAt(0)) - 'A';
        int c1 = Character.toUpperCase(name.charAt(1)) - 'A';
        if (c0 < 0 || c0 > 17 || c1 < 0 || c1 > 17) return -1;
        return c0 * GC_FIELD_LATS + c1;
    }
    public static String fieldName(int idx) {
        if (idx < 0 || idx >= GC_FIELDS) return "??";
        return "" + (char)('A' + idx / GC_FIELD_LATS) + (char)('A' + idx % GC_FIELD_LATS);
    }
    public static int gridIndex(String name) {
        if (name == null || name.length() < 4) return -1;
        int c0 = Character.toUpperCase(name.charAt(0)) - 'A';
        int c1 = Character.toUpperCase(name.charAt(1)) - 'A';
        int c2 = name.charAt(2) - '0';
        int c3 = name.charAt(3) - '0';
        if (c0 < 0 || c0 > 17 || c1 < 0 || c1 > 17) return -1;
        if (c2 < 0 || c2 > 9 || c3 < 0 || c3 > 9) return -1;
        int fi = c0 * GC_FIELD_LATS + c1;
        int si = c2 * GC_SQ_LATS + c3;
        return fi * GC_SQUARES + si;
    }
    public static String gridName(int idx) {
        if (idx < 0 || idx >= GC_GRIDS) return "????";
        int fi = idx / GC_SQUARES;
        int si = idx % GC_SQUARES;
        return "" + (char)('A' + fi / GC_FIELD_LATS) + (char)('A' + fi % GC_FIELD_LATS)
            + (char)('0' + si / GC_SQ_LATS) + (char)('0' + si % GC_SQ_LATS);
    }
    public static int gridToField(int gridIdx) {
        return gridIdx < 0 || gridIdx >= GC_GRIDS ? -1 : gridIdx / GC_SQUARES;
    }
    public static int gridToSquare(int gridIdx) {
        return gridIdx < 0 || gridIdx >= GC_GRIDS ? -1 : gridIdx % GC_SQUARES;
    }

    private static int[] computeDimMasks(byte[] matrixBits, int nLons, int nLats) {
        int N = nLons * nLats;
        int slm = 0, sam = 0, dlm = 0, dam = 0;
        for (int s = 0; s < N; s++) {
            for (int d = 0; d < N; d++) {
                if (bitGet(matrixBits, s * N + d) != 0) {
                    int sLon = s / nLats, sLat = s % nLats;
                    int dLon = d / nLats, dLat = d % nLats;
                    slm |= 1 << sLon;
                    sam |= 1 << sLat;
                    dlm |= 1 << dLon;
                    dam |= 1 << dLat;
                }
            }
        }
        return new int[]{ slm, sam, dlm, dam };
    }

    private static int buildEntryBitmap(byte[] matrixBits, int nLons, int nLats,
            List<Integer> activeLons, List<Integer> activeLats, boolean isSrc, byte[] out) {
        int N = nLons * nLats;
        int nAl = activeLons.size(), nAlat = activeLats.size();
        int count = 0;
        for (int li = 0; li < nAl; li++) {
            for (int ai = 0; ai < nAlat; ai++) {
                int entry = activeLons.get(li) * nLats + activeLats.get(ai);
                int bitIdx = li * nAlat + ai;
                boolean has = false;
                if (isSrc) {
                    for (int d = 0; d < N && !has; d++)
                        if (bitGet(matrixBits, entry * N + d) != 0) has = true;
                } else {
                    for (int s = 0; s < N && !has; s++)
                        if (bitGet(matrixBits, s * N + entry) != 0) has = true;
                }
                if (has) { bitSet(out, bitIdx); count++; }
            }
        }
        return count;
    }

    private static List<Integer> bitmapToEntries(byte[] bitmap, int nAl, int nAlat,
            List<Integer> activeLons, List<Integer> activeLats, int latsPerRow) {
        List<Integer> out = new ArrayList<>();
        for (int li = 0; li < nAl; li++)
            for (int ai = 0; ai < nAlat; ai++)
                if (bitGet(bitmap, li * nAlat + ai) != 0)
                    out.add(activeLons.get(li) * latsPerRow + activeLats.get(ai));
        return out;
    }

    private static void buildInnerMatrix(byte[] matrixBits, int nLons, int nLats,
            List<Integer> srcEntries, List<Integer> dstEntries, byte[] inner) {
        int N = nLons * nLats;
        int nSrc = srcEntries.size(), nDst = dstEntries.size();
        for (int si = 0; si < nSrc; si++)
            for (int di = 0; di < nDst; di++)
                if (bitGet(matrixBits, srcEntries.get(si) * N + dstEntries.get(di)) != 0)
                    bitSet(inner, si * nDst + di);
    }

    private static int encodeProjection(byte[] matrixBits, int nLons, int nLats,
            byte[] buf, int offset, int cap) {
        int[] masks = computeDimMasks(matrixBits, nLons, nLats);
        int srcLonMask = masks[0], srcLatMask = masks[1], dstLonMask = masks[2], dstLatMask = masks[3];
        int nSrcLon = popcount32(srcLonMask), nSrcLat = popcount32(srcLatMask);
        int nDstLon = popcount32(dstLonMask), nDstLat = popcount32(dstLatMask);
        int maskBytes = (nLons * 2 + nLats * 2 + 7) / 8;
        if (offset + maskBytes > cap) return GC_ERR_OVERFLOW;
        for (int i = 0; i < maskBytes; i++) buf[offset + i] = 0;
        int[] pos = { offset * 8 };
        packMask(buf, pos, srcLonMask, nLons);
        packMask(buf, pos, srcLatMask, nLats);
        packMask(buf, pos, dstLonMask, nLons);
        packMask(buf, pos, dstLatMask, nLats);
        int written = maskBytes;
        int posB = offset + maskBytes;

        List<Integer> srcActiveLons = maskIndices(srcLonMask, nLons);
        List<Integer> srcActiveLats = maskIndices(srcLatMask, nLats);
        List<Integer> dstActiveLons = maskIndices(dstLonMask, nLons);
        List<Integer> dstActiveLats = maskIndices(dstLatMask, nLats);

        int srcBmpBytes = (nSrcLon * nSrcLat + 7) / 8;
        if (posB + srcBmpBytes > cap) return GC_ERR_OVERFLOW;
        byte[] srcBmp = new byte[srcBmpBytes];
        int nActiveSrc = buildEntryBitmap(matrixBits, nLons, nLats, srcActiveLons, srcActiveLats, true, srcBmp);
        System.arraycopy(srcBmp, 0, buf, posB, srcBmpBytes);
        written += srcBmpBytes;
        posB += srcBmpBytes;

        int dstBmpBytes = (nDstLon * nDstLat + 7) / 8;
        if (posB + dstBmpBytes > cap) return GC_ERR_OVERFLOW;
        byte[] dstBmp = new byte[dstBmpBytes];
        int nActiveDst = buildEntryBitmap(matrixBits, nLons, nLats, dstActiveLons, dstActiveLats, false, dstBmp);
        System.arraycopy(dstBmp, 0, buf, posB, dstBmpBytes);
        written += dstBmpBytes;
        posB += dstBmpBytes;

        List<Integer> srcEntries = bitmapToEntries(srcBmp, nSrcLon, nSrcLat, srcActiveLons, srcActiveLats, nLats);
        List<Integer> dstEntries = bitmapToEntries(dstBmp, nDstLon, nDstLat, dstActiveLons, dstActiveLats, nLats);
        int innerBytes = (nActiveSrc * nActiveDst + 7) / 8;
        if (posB + innerBytes > cap) return GC_ERR_OVERFLOW;
        byte[] inner = new byte[innerBytes];
        buildInnerMatrix(matrixBits, nLons, nLats, srcEntries, dstEntries, inner);
        System.arraycopy(inner, 0, buf, posB, innerBytes);
        written += innerBytes;
        return written;
    }

    private static int decodeProjection(byte[] buf, int offset, int length, int nLons, int nLats, byte[] matrixBits) {
        int N = nLons * nLats;
        int matrixBytes = (N * N + 7) / 8;
        java.util.Arrays.fill(matrixBits, 0, matrixBytes, (byte)0);
        int maskBytes = (nLons * 2 + nLats * 2 + 7) / 8;
        if (maskBytes > length) return GC_ERR_FORMAT;
        int[] pos = { offset * 8 };
        int srcLonMask = unpackMask(buf, pos, nLons);
        int srcLatMask = unpackMask(buf, pos, nLats);
        int dstLonMask = unpackMask(buf, pos, nLons);
        int dstLatMask = unpackMask(buf, pos, nLats);
        int consumed = maskBytes;
        int posB = offset + maskBytes;

        int nSrcLon = popcount32(srcLonMask), nSrcLat = popcount32(srcLatMask);
        int nDstLon = popcount32(dstLonMask), nDstLat = popcount32(dstLatMask);
        int srcBmpBytes = (nSrcLon * nSrcLat + 7) / 8;
        if (posB - offset + srcBmpBytes > length) return GC_ERR_FORMAT;
        byte[] srcBmp = new byte[srcBmpBytes];
        System.arraycopy(buf, posB, srcBmp, 0, srcBmpBytes);
        consumed += srcBmpBytes;
        posB += srcBmpBytes;
        int dstBmpBytes = (nDstLon * nDstLat + 7) / 8;
        if (posB - offset + dstBmpBytes > length) return GC_ERR_FORMAT;
        byte[] dstBmp = new byte[dstBmpBytes];
        System.arraycopy(buf, posB, dstBmp, 0, dstBmpBytes);
        consumed += dstBmpBytes;
        posB += dstBmpBytes;

        List<Integer> srcActiveLons = maskIndices(srcLonMask, nLons);
        List<Integer> srcActiveLats = maskIndices(srcLatMask, nLats);
        List<Integer> dstActiveLons = maskIndices(dstLonMask, nLons);
        List<Integer> dstActiveLats = maskIndices(dstLatMask, nLats);
        List<Integer> srcEntries = bitmapToEntries(srcBmp, nSrcLon, nSrcLat, srcActiveLons, srcActiveLats, nLats);
        List<Integer> dstEntries = bitmapToEntries(dstBmp, nDstLon, nDstLat, dstActiveLons, dstActiveLats, nLats);
        int nActiveSrc = srcEntries.size(), nActiveDst = dstEntries.size();
        int innerBytes = (nActiveSrc * nActiveDst + 7) / 8;
        if (posB - offset + innerBytes > length) return GC_ERR_FORMAT;
        for (int si = 0; si < nActiveSrc; si++)
            for (int di = 0; di < nActiveDst; di++)
                if (bitGet(buf, (posB * 8) + si * nActiveDst + di) != 0)
                    bitSet(matrixBits, srcEntries.get(si) * N + dstEntries.get(di));
        consumed += innerBytes;
        return consumed;
    }

    public static class GridCodecMatrix {
        private byte[] fieldBits = new byte[GC_FIELD_MATRIX_BYTES];
        private List<Integer> pairSrc = new ArrayList<>();
        private List<Integer> pairDst = new ArrayList<>();
        private List<byte[]> sqBits = new ArrayList<>();

        public int set(String from4, String to4) {
            int srcGi = gridIndex(from4);
            int dstGi = gridIndex(to4);
            if (srcGi < 0 || dstGi < 0) return GC_ERR_INVALID;
            int srcFi = srcGi / GC_SQUARES;
            int dstFi = dstGi / GC_SQUARES;
            int srcSi = srcGi % GC_SQUARES;
            int dstSi = dstGi % GC_SQUARES;
            bitSet(fieldBits, srcFi * GC_FIELDS + dstFi);
            int pairIdx = findOrCreatePair(srcFi, dstFi);
            bitSet(sqBits.get(pairIdx), srcSi * GC_SQUARES + dstSi);
            return 0;
        }

        private int findOrCreatePair(int srcFi, int dstFi) {
            for (int i = 0; i < pairSrc.size(); i++)
                if (pairSrc.get(i) == srcFi && pairDst.get(i) == dstFi) return i;
            pairSrc.add(srcFi);
            pairDst.add(dstFi);
            sqBits.add(new byte[GC_SQ_MATRIX_BYTES]);
            return sqBits.size() - 1;
        }

        private int findPair(int srcFi, int dstFi) {
            for (int i = 0; i < pairSrc.size(); i++)
                if (pairSrc.get(i) == srcFi && pairDst.get(i) == dstFi) return i;
            return -1;
        }

        public EncodeResult encode(int cap) {
            if (cap < 2) return new EncodeResult(null, GC_ERR_OVERFLOW);
            byte[] buf = new byte[cap];
            int hasL2 = pairSrc.isEmpty() ? 0 : 1;
            buf[0] = (byte) GC_VERSION;
            buf[1] = (byte) (hasL2 != 0 ? GC_FLAG_LAYER2 : 0);
            int written = 2;
            int l1Bytes = encodeProjection(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, buf, written, cap);
            if (l1Bytes < 0) return new EncodeResult(null, l1Bytes);
            written += l1Bytes;
            if (hasL2 == 0) return new EncodeResult(java.util.Arrays.copyOf(buf, written), written);

            int[] masks = computeDimMasks(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS);
            List<Integer> srcActiveLons = maskIndices(masks[0], GC_FIELD_LONS);
            List<Integer> srcActiveLats = maskIndices(masks[1], GC_FIELD_LATS);
            List<Integer> dstActiveLons = maskIndices(masks[2], GC_FIELD_LONS);
            List<Integer> dstActiveLats = maskIndices(masks[3], GC_FIELD_LATS);
            byte[] srcBmp = new byte[(srcActiveLons.size() * srcActiveLats.size() + 7) / 8];
            buildEntryBitmap(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, srcActiveLons, srcActiveLats, true, srcBmp);
            byte[] dstBmp = new byte[(dstActiveLons.size() * dstActiveLats.size() + 7) / 8];
            buildEntryBitmap(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, dstActiveLons, dstActiveLats, false, dstBmp);
            List<Integer> srcEntries = bitmapToEntries(srcBmp, srcActiveLons.size(), srcActiveLats.size(), srcActiveLons, srcActiveLats, GC_FIELD_LATS);
            List<Integer> dstEntries = bitmapToEntries(dstBmp, dstActiveLons.size(), dstActiveLats.size(), dstActiveLons, dstActiveLats, GC_FIELD_LATS);
            int needEmpty = (GC_SQ_LONS * 2 + GC_SQ_LATS * 2 + 7) / 8;
            for (int si = 0; si < srcEntries.size(); si++) {
                for (int di = 0; di < dstEntries.size(); di++) {
                    int srcFi = srcEntries.get(si), dstFi = dstEntries.get(di);
                    if (bitGet(fieldBits, srcFi * GC_FIELDS + dstFi) == 0) continue;
                    int pairIdx = findPair(srcFi, dstFi);
                    if (pairIdx < 0) {
                        if (written + needEmpty > cap) return new EncodeResult(null, GC_ERR_OVERFLOW);
                        for (int i = 0; i < needEmpty; i++) buf[written + i] = 0;
                        written += needEmpty;
                    } else {
                        int sub = encodeProjection(sqBits.get(pairIdx), GC_SQ_LONS, GC_SQ_LATS, buf, written, cap);
                        if (sub < 0) return new EncodeResult(null, sub);
                        written += sub;
                    }
                }
            }
            return new EncodeResult(java.util.Arrays.copyOf(buf, written), written);
        }

        public int decode(byte[] data) {
            if (data.length < 2) return GC_ERR_FORMAT;
            if ((data[0] & 0xFF) != GC_VERSION) return GC_ERR_FORMAT;
            int flags = data[1] & 0xFF;
            int consumed = 2;
            fieldBits = new byte[GC_FIELD_MATRIX_BYTES];
            pairSrc.clear();
            pairDst.clear();
            sqBits.clear();
            int l1Bytes = decodeProjection(data, consumed, data.length - consumed, GC_FIELD_LONS, GC_FIELD_LATS, fieldBits);
            if (l1Bytes < 0) return l1Bytes;
            consumed += l1Bytes;
            if ((flags & GC_FLAG_LAYER2) == 0) return consumed;

            int[] masks = computeDimMasks(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS);
            List<Integer> srcActiveLons = maskIndices(masks[0], GC_FIELD_LONS);
            List<Integer> srcActiveLats = maskIndices(masks[1], GC_FIELD_LATS);
            List<Integer> dstActiveLons = maskIndices(masks[2], GC_FIELD_LONS);
            List<Integer> dstActiveLats = maskIndices(masks[3], GC_FIELD_LATS);
            byte[] srcBmp = new byte[(srcActiveLons.size() * srcActiveLats.size() + 7) / 8];
            buildEntryBitmap(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, srcActiveLons, srcActiveLats, true, srcBmp);
            byte[] dstBmp = new byte[(dstActiveLons.size() * dstActiveLats.size() + 7) / 8];
            buildEntryBitmap(fieldBits, GC_FIELD_LONS, GC_FIELD_LATS, dstActiveLons, dstActiveLats, false, dstBmp);
            List<Integer> srcEntries = bitmapToEntries(srcBmp, srcActiveLons.size(), srcActiveLats.size(), srcActiveLons, srcActiveLats, GC_FIELD_LATS);
            List<Integer> dstEntries = bitmapToEntries(dstBmp, dstActiveLons.size(), dstActiveLats.size(), dstActiveLons, dstActiveLats, GC_FIELD_LATS);
            for (int si = 0; si < srcEntries.size(); si++) {
                for (int di = 0; di < dstEntries.size(); di++) {
                    int srcFi = srcEntries.get(si), dstFi = dstEntries.get(di);
                    if (bitGet(fieldBits, srcFi * GC_FIELDS + dstFi) == 0) continue;
                    byte[] sq = new byte[GC_SQ_MATRIX_BYTES];
                    int sub = decodeProjection(data, consumed, data.length - consumed, GC_SQ_LONS, GC_SQ_LATS, sq);
                    if (sub < 0) return sub;
                    pairSrc.add(srcFi);
                    pairDst.add(dstFi);
                    sqBits.add(sq);
                    consumed += sub;
                }
            }
            return consumed;
        }

        public List<Integer> gcFrom(String grid, int maxOut) {
            if (grid == null || maxOut <= 0) return new ArrayList<>();
            String s = grid.trim();
            if (s.length() == 2) {
                int fi = fieldIndex(s);
                if (fi < 0) return new ArrayList<>();
                return queryFieldFrom(fi, maxOut);
            }
            if (s.length() >= 4) {
                int gi = gridIndex(s);
                if (gi < 0) return new ArrayList<>();
                return queryGridFrom(gi, maxOut);
            }
            return new ArrayList<>();
        }

        public List<Integer> gcTo(String grid, int maxOut) {
            if (grid == null || maxOut <= 0) return new ArrayList<>();
            String s = grid.trim();
            if (s.length() == 2) {
                int fi = fieldIndex(s);
                if (fi < 0) return new ArrayList<>();
                return queryFieldTo(fi, maxOut);
            }
            if (s.length() >= 4) {
                int gi = gridIndex(s);
                if (gi < 0) return new ArrayList<>();
                return queryGridTo(gi, maxOut);
            }
            return new ArrayList<>();
        }

        private List<Integer> queryFieldFrom(int srcFi, int maxOut) {
            List<Integer> out = new ArrayList<>();
            for (int d = 0; d < GC_FIELDS && out.size() < maxOut; d++)
                if (bitGet(fieldBits, srcFi * GC_FIELDS + d) != 0) out.add(d);
            return out;
        }
        private List<Integer> queryFieldTo(int dstFi, int maxOut) {
            List<Integer> out = new ArrayList<>();
            for (int s = 0; s < GC_FIELDS && out.size() < maxOut; s++)
                if (bitGet(fieldBits, s * GC_FIELDS + dstFi) != 0) out.add(s);
            return out;
        }
        private List<Integer> queryGridFrom(int srcGi, int maxOut) {
            int srcFi = srcGi / GC_SQUARES, srcSi = srcGi % GC_SQUARES;
            List<Integer> out = new ArrayList<>();
            for (int dstFi = 0; dstFi < GC_FIELDS; dstFi++) {
                if (bitGet(fieldBits, srcFi * GC_FIELDS + dstFi) == 0) continue;
                int pairIdx = findPair(srcFi, dstFi);
                if (pairIdx < 0) continue;
                for (int dstSi = 0; dstSi < GC_SQUARES && out.size() < maxOut; dstSi++)
                    if (bitGet(sqBits.get(pairIdx), srcSi * GC_SQUARES + dstSi) != 0)
                        out.add(dstFi * GC_SQUARES + dstSi);
            }
            return out;
        }
        private List<Integer> queryGridTo(int dstGi, int maxOut) {
            int dstFi = dstGi / GC_SQUARES, dstSi = dstGi % GC_SQUARES;
            List<Integer> out = new ArrayList<>();
            for (int srcFi = 0; srcFi < GC_FIELDS; srcFi++) {
                if (bitGet(fieldBits, srcFi * GC_FIELDS + dstFi) == 0) continue;
                int pairIdx = findPair(srcFi, dstFi);
                if (pairIdx < 0) continue;
                for (int srcSi = 0; srcSi < GC_SQUARES && out.size() < maxOut; srcSi++)
                    if (bitGet(sqBits.get(pairIdx), srcSi * GC_SQUARES + dstSi) != 0)
                        out.add(srcFi * GC_SQUARES + srcSi);
            }
            return out;
        }
    }

    public static class EncodeResult {
        public final byte[] data;
        public final int len;
        EncodeResult(byte[] data, int len) { this.data = data; this.len = len; }
    }
}
