package gridcodec;

import java.util.List;
import java.util.Random;

public class TestGridCodec {

    public static void main(String[] args) {
        System.out.println("=== GridCodec Java Test Suite ===\n");
        System.out.println("[Helpers]");
        testHelpers();
        System.out.println("\n[Round-trip]");
        testEmptyRoundtrip();
        testSinglePathRoundtrip();
        System.out.println("\n[Query]");
        testQueryFromTo();
        testDedup();
        System.out.println("\n[Realistic]");
        testRealistic(500);
        testRealistic(5000);
        testRealistic(2000);
        System.out.println("\n[C interop]");
        testCInterop();
        System.out.println("\n[Performance]");
        testPerformance();
        System.out.println("\n=== All tests passed ===\n");
    }

    static void testHelpers() {
        System.out.print("  test field_index / field_name... ");
        if (GridCodec.fieldIndex("FN") != 5 * 18 + 13) throw new AssertionError("fieldIndex FN");
        if (!GridCodec.fieldName(GridCodec.fieldIndex("FN")).equals("FN")) throw new AssertionError("fieldName");
        if (GridCodec.fieldIndex("OL") != 14 * 18 + 11) throw new AssertionError("fieldIndex OL");
        System.out.println("OK");

        System.out.print("  test grid_index / grid_name... ");
        if (!GridCodec.gridName(GridCodec.gridIndex("FN31")).equals("FN31")) throw new AssertionError("grid name");
        System.out.println("OK");
    }

    static void testEmptyRoundtrip() {
        System.out.print("  test_empty_roundtrip... ");
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        GridCodec.EncodeResult res = m.encode(1024 * 1024);
        if (res.len <= 0 || res.data[0] != 0x01 || res.data[1] != 0) throw new AssertionError("empty encode");
        GridCodec.GridCodecMatrix m2 = new GridCodec.GridCodecMatrix();
        int consumed = m2.decode(res.data);
        if (consumed != res.len) throw new AssertionError("decode len");
        System.out.println("OK (encoded " + res.len + " bytes)");
    }

    static void testSinglePathRoundtrip() {
        System.out.print("  test_single_path_roundtrip... ");
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        if (m.set("FN31", "PM02") != 0) throw new AssertionError("set");
        GridCodec.EncodeResult res = m.encode(1024 * 1024);
        if (res.len <= 0) throw new AssertionError("encode");
        GridCodec.GridCodecMatrix m2 = new GridCodec.GridCodecMatrix();
        int consumed = m2.decode(res.data);
        if (consumed != res.len) throw new AssertionError("decode");
        List<Integer> fromFn = m2.gcFrom("FN31", 32400);
        if (fromFn.size() != 1 || !GridCodec.gridName(fromFn.get(0)).equals("PM02")) throw new AssertionError("gc_from");
        List<Integer> toPm = m2.gcTo("PM02", 32400);
        if (toPm.size() != 1 || !GridCodec.gridName(toPm.get(0)).equals("FN31")) throw new AssertionError("gc_to");
        System.out.println("OK (encoded " + res.len + " bytes)");
    }

    static void testQueryFromTo() {
        System.out.print("  test_query_from_to... ");
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        m.set("FN31", "PM02");
        m.set("FN31", "PM03");
        m.set("JO22", "FN31");
        List<Integer> fromFn = m.gcFrom("FN31", 32400);
        if (fromFn.size() != 2) throw new AssertionError("from count");
        boolean has02 = false, has03 = false;
        for (int idx : fromFn) {
            String n = GridCodec.gridName(idx);
            if (n.equals("PM02")) has02 = true;
            if (n.equals("PM03")) has03 = true;
        }
        if (!has02 || !has03) throw new AssertionError("from names");
        List<Integer> toFn = m.gcTo("FN31", 32400);
        if (toFn.size() != 1 || !GridCodec.gridName(toFn.get(0)).equals("JO22")) throw new AssertionError("to");
        System.out.println("OK");
    }

    static void testDedup() {
        System.out.print("  test_dedup... ");
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        m.set("OL72", "FN31");
        m.set("OL72", "FN31");
        GridCodec.EncodeResult res = m.encode(1024 * 1024);
        GridCodec.GridCodecMatrix m2 = new GridCodec.GridCodecMatrix();
        m2.decode(res.data);
        List<Integer> fromOl = m2.gcFrom("OL72", 32400);
        if (fromOl.size() != 1 || !GridCodec.gridName(fromOl.get(0)).equals("FN31")) throw new AssertionError("dedup");
        System.out.println("OK");
    }

    static void testRealistic(int nPaths) {
        System.out.print("  test_realistic_roundtrip (" + nPaths + " paths)... ");
        Random r = new Random(42);
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        String[] grids = new String[nPaths * 2];
        for (int i = 0; i < nPaths * 2; i++) {
            int fi = r.nextInt(GridCodec.GC_FIELDS);
            int si = r.nextInt(GridCodec.GC_SQUARES);
            grids[i] = GridCodec.fieldName(fi) + (si / 10) + (si % 10);
        }
        for (int i = 0; i < nPaths * 2 - 1; i += 2)
            m.set(grids[i], grids[i + 1]);
        long t0 = System.nanoTime();
        GridCodec.EncodeResult res = m.encode(1024 * 1024);
        long t1 = System.nanoTime();
        GridCodec.GridCodecMatrix m2 = new GridCodec.GridCodecMatrix();
        int consumed = m2.decode(res.data);
        long t2 = System.nanoTime();
        if (consumed != res.len) throw new AssertionError("decode len");
        int verified = 0;
        for (int i = 0; i < nPaths * 2 - 1; i += 2) {
            List<Integer> out = m2.gcFrom(grids[i], 32400);
            for (int idx : out)
                if (GridCodec.gridName(idx).equals(grids[i + 1])) { verified++; break; }
        }
        if (verified != nPaths) throw new AssertionError("verified " + verified);
        double encMs = (t1 - t0) / 1e6;
        double decMs = (t2 - t1) / 1e6;
        System.out.println("OK");
        System.out.println("    Encoded: " + res.len + " bytes, Encode: " + String.format("%.2f", encMs) + " ms, Decode: " + String.format("%.2f", decMs) + " ms, Verified: " + verified);
    }

    static void testCInterop() {
        System.out.print("  test_c_interop (decode C payload)... ");
        byte[] payload = new byte[] {
            0x01, 0x00, (byte)0x20, 0x02, 0x00, (byte)0x80, 0x01, 0x02, 0x08, 0x00, 0x0c, 0x09,
            0x06, 0x06
        };
        GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
        int consumed = m.decode(payload);
        if (consumed != payload.length) throw new AssertionError("consumed");
        List<Integer> fromFn = m.gcFrom("FN", 324);
        if (fromFn.size() != 1 || !GridCodec.fieldName(fromFn.get(0)).equals("PM")) throw new AssertionError("from FN");
        List<Integer> toFn = m.gcTo("FN", 324);
        if (toFn.size() != 1 || !GridCodec.fieldName(toFn.get(0)).equals("JO")) throw new AssertionError("to FN");
        System.out.println("OK");
    }

    static void testPerformance() {
        System.out.println("  [Performance] 500 / 5000 / 2000 paths...");
        for (int n : new int[] { 500, 5000, 2000 }) {
            Random r = new Random(123);
            GridCodec.GridCodecMatrix m = new GridCodec.GridCodecMatrix();
            for (int i = 0; i < n; i++) {
                int fi1 = r.nextInt(GridCodec.GC_FIELDS);
                int si1 = r.nextInt(GridCodec.GC_SQUARES);
                int fi2 = r.nextInt(GridCodec.GC_FIELDS);
                int si2 = r.nextInt(GridCodec.GC_SQUARES);
                String fromG = GridCodec.fieldName(fi1) + (si1 / 10) + (si1 % 10);
                String toG = GridCodec.fieldName(fi2) + (si2 / 10) + (si2 % 10);
                m.set(fromG, toG);
            }
            long t0 = System.nanoTime();
            GridCodec.EncodeResult res = m.encode(1024 * 1024);
            long t1 = System.nanoTime();
            GridCodec.GridCodecMatrix m2 = new GridCodec.GridCodecMatrix();
            m2.decode(res.data);
            long t2 = System.nanoTime();
            double encMs = (t1 - t0) / 1e6;
            double decMs = (t2 - t1) / 1e6;
            System.out.println("    " + n + " paths: encoded " + res.len + " bytes, encode " + String.format("%.2f", encMs) + " ms, decode " + String.format("%.2f", decMs) + " ms");
        }
    }
}
