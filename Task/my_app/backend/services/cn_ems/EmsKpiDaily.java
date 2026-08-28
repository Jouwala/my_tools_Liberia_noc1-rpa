import com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl;

import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.*;

/**
 * EmsKpiDaily - aggregate raw PM measurement files from SFTP by DAY for target counters.
 *
 * Usage: EmsKpiDaily <host> <startDay yyyy/MM/dd> <endDay yyyy/MM/dd> [counterFilters] [mode]
 *   counterFilters - '|' separated raw counter-name substrings; matched counters are aggregated
 *   mode:
 *     full  = fetch + aggregate (default)
 *     fetch = download window files into local cache only (no parse, no json)
 *     parse = aggregate ALL cached files in _pmcache (no network at all)
 *
 * Output: daily_raw.json
 *   {
 *     "window": {"start": "...", "end": "..."},
 *     "ne": "...",
 *     "counters": {
 *        "<counter name>": {"2026-08-24": {"sum": x, "max": y}}
 *     }
 *   }
 *
 * Source: /pmdata/download/ + module dirs, files PM_<start>-<end>_<task>.xml|.zip (5-min granularity)
 * Limitation: the server retains only ~1 day of raw files; keep syncing during the day
 * so the local cache preserves the whole day before server-side purge.
 */
public class EmsKpiDaily {

    static String host = "10.100.2.240";
    static int port = 21128;
    static String sftpUser = "uepcommon";
    static String base = "/pmdata/download";
    static File cacheDir = new File("_pmcache");

    public static void main(String[] args) throws Exception {
        // mode flag can appear anywhere; positional args keep legacy order:
        // <host(ignored)> <startDay> <endDay> [filter] ; extra bare word selects mode
        String mode = "full";
        String startDay = null, endDay = null;
        String filter = "40716.|40738.|40748.";
        ArrayList<String> pos = new ArrayList<String>();
        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            if (a.equals("full") || a.equals("fetch") || a.equals("parse")) { mode = a; continue; }
            pos.add(a);
        }
        if (pos.size() > 1) startDay = pos.get(1);
        if (pos.size() > 2) endDay = pos.get(2);
        if (pos.size() > 3) filter = pos.get(3);
        if (startDay == null || endDay == null) {
            SimpleDateFormat df = new SimpleDateFormat("yyyy/MM/dd");
            df.setTimeZone(TimeZone.getTimeZone("GMT"));
            Calendar c = Calendar.getInstance(TimeZone.getTimeZone("GMT"));
            c.add(Calendar.DAY_OF_MONTH, -1);
            startDay = df.format(c.getTime());
            endDay = df.format(new Date());
        }

        SimpleDateFormat dayFmt = new SimpleDateFormat("yyyy/MM/dd");
        dayFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        long tStart = dayFmt.parse(startDay).getTime();
        long tEnd   = dayFmt.parse(endDay).getTime();

        if (!cacheDir.exists()) cacheDir.mkdirs();

        // 聚合: day(yyyy-MM-dd) -> counterName -> {sum, max}
        TreeMap<String, HashMap<String, double[]>> daily = new TreeMap<String, HashMap<String, double[]>>();
        TreeSet<String> allCounters = new TreeSet<String>();
        int parsed = 0;
        int downloaded = 0;
        int totalInWindow = 0;

        SimpleDateFormat fFmt = new SimpleDateFormat("yyyyMMddHHmm");
        fFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        SimpleDateFormat dayKey = new SimpleDateFormat("yyyy-MM-dd");
        dayKey.setTimeZone(TimeZone.getTimeZone("GMT"));

        if (mode.equals("parse")) {
            // 纯本地聚合: 遍历整个缓存目录, 不联网
            System.out.println("[daily] PARSE-ONLY from cache dir " + cacheDir.getAbsolutePath());
            File[] cached = cacheDir.listFiles();
            if (cached != null) {
                Arrays.sort(cached);
                for (File local : cached) {
                    String fn = local.getName();
                    if (fn.indexOf("__inner") >= 0) continue;
                    if (!inWindow(fn, tStart, tEnd, fFmt)) continue;
                    try {
                        if (fn.endsWith(".xml")) {
                            parsed += parseXml(local, daily, allCounters, dayKey);
                        } else if (fn.endsWith(".zip")) {
                            FileInputStream fin = new FileInputStream(local);
                            ZipInputStream zin = new ZipInputStream(fin);
                            ByteArrayOutputStream bout = new ByteArrayOutputStream();
                            ZipEntry ze;
                            while ((ze = zin.getNextEntry()) != null) {
                                if (ze.getName().endsWith(".xml")) {
                                    byte[] buf = new byte[8192];
                                    int n;
                                    while ((n = zin.read(buf)) > 0) bout.write(buf, 0, n);
                                    break;
                                }
                            }
                            zin.close();
                            if (bout.size() > 0) {
                                File tmp = new File(cacheDir, fn + ".__inner.xml");
                                FileOutputStream fo = new FileOutputStream(tmp);
                                fo.write(bout.toByteArray()); fo.close();
                                parsed += parseXml(tmp, daily, allCounters, dayKey);
                                tmp.delete();
                            }
                        }
                    } catch (Throwable t) {
                        System.out.println("    parse FAIL " + fn + ": " + root(t).getMessage());
                    }
                }
            }
        } else {
            // full / fetch: 连接 SFTP, 按窗口挑文件, 缺的下载进缓存
            System.out.println("[daily] connect SFTP " + host + ":" + port + " window=[" + startDay + " ~ " + endDay + ") mode=" + mode);
            SftpClientImpl sftp = new SftpClientImpl(host, port, 30000, sftpUser, null, false);

            // 1) all module dirs
            String[] dirs = sftp.dir(base, false);
            System.out.println("[daily] module dirs: " + dirs.length);

            for (String d : dirs) {
                String full = base + "/" + d;
                String[] entries;
                try { entries = sftp.dir(full, true); } catch (Throwable t) { continue; }

                ArrayList<String> picked = new ArrayList<String>();
                for (String e : entries) {
                    int p1 = e.indexOf("PM_");
                    if (p1 < 0) continue;
                    String fn = e.substring(p1);
                    if (!fn.endsWith(".xml") && !fn.endsWith(".zip")) continue;
                    try {
                        String body = fn.substring(3, fn.lastIndexOf('.'));
                        int dash = body.indexOf('-');
                        Date fs = fFmt.parse(body.substring(0, dash));
                        long fEnd = fFmt.parse(body.substring(dash + 1)).getTime();
                        if (fEnd > tStart && fs.getTime() < tEnd) picked.add(fn);
                    } catch (Exception ignore) { }
                }
                Collections.sort(picked);
                if (picked.isEmpty()) continue;
                System.out.println("[daily] " + d + ": " + picked.size() + " files in window");
                totalInWindow += picked.size();

                for (String fn : picked) {
                    File local = new File(cacheDir, fn);
                    if (!local.exists() || local.length() == 0) {
                        try { sftp.get(local.getAbsolutePath(), full + "/" + fn); downloaded++; }
                        catch (Throwable t) { continue; }
                    }
                    if (mode.equals("full")) {
                        try {
                            if (fn.endsWith(".xml")) {
                                parsed += parseXml(local, daily, allCounters, dayKey);
                            } else {
                                FileInputStream fin = new FileInputStream(local);
                                ZipInputStream zin = new ZipInputStream(fin);
                                ByteArrayOutputStream bout = new ByteArrayOutputStream();
                                ZipEntry ze;
                                while ((ze = zin.getNextEntry()) != null) {
                                    if (ze.getName().endsWith(".xml")) {
                                        byte[] buf = new byte[8192];
                                        int n;
                                        while ((n = zin.read(buf)) > 0) bout.write(buf, 0, n);
                                        break;
                                    }
                                }
                                zin.close();
                                if (bout.size() > 0) {
                                    File tmp = new File(cacheDir, fn + ".__inner.xml");
                                    FileOutputStream fo = new FileOutputStream(tmp);
                                    fo.write(bout.toByteArray()); fo.close();
                                    parsed += parseXml(tmp, daily, allCounters, dayKey);
                                    tmp.delete();
                                }
                            }
                        } catch (Throwable t) {
                            System.out.println("    parse FAIL " + fn + ": " + root(t).getMessage());
                        }
                    }
                }
            }
            try { sftp.quit(); } catch (Exception ignore) { }
        }
        System.out.println("[daily] parsed files: " + parsed + ", distinct counters: " + allCounters.size());

        // fetch 模式到此为止: 只保证缓存齐全, 不解析不出 JSON
        if (mode.equals("fetch")) {
            System.out.println("[daily] FETCH_RESULT downloaded=" + downloaded
                + " total_in_window=" + totalInWindow + " cache_files=" + cacheDir.list().length);
            System.out.println("[daily] === DONE (fetch-only)");
            return;
        }

        // 2) filter target counters (prefix/substring, '|' separated)
        String[] pats = filter.split("\\|");
        ArrayList<String> matched = new ArrayList<String>();
        for (String c : allCounters) {
            for (int pi = 0; pi < pats.length; pi++) {
                if (pats[pi].length() > 0 && c.contains(pats[pi])) { matched.add(c); break; }
            }
        }
        System.out.println("[daily] counters matching \"" + filter + "\": " + matched.size());
        for (String c : matched) System.out.println("      " + c);

        // 3) emit JSON
        StringBuilder json = new StringBuilder();
        json.append("{\n");
        json.append("  \"window\": {\"start\": \"").append(startDay).append("\", \"end\": \"").append(endDay).append("\"},\n");
        json.append("  \"source\": \"sftp://").append(host).append(base).append("\",\n");
        json.append("  \"ne\": \"all modules\",\n");
        json.append("  \"counterFilter\": \"").append(jesc(filter)).append("\",\n");
        json.append("  \"counters\": {\n");
        boolean firstC = true;
        for (String c : matched) {
            if (!firstC) json.append(",\n");
            firstC = false;
            json.append("    \"").append(jesc(c)).append("\": {");
            HashMap<String, double[]> byDay = daily.get(c);
            boolean firstD = true;
            if (byDay != null) {
                for (Map.Entry<String, double[]> en : byDay.entrySet()) {
                    if (!firstD) json.append(", ");
                    firstD = false;
                    json.append("\"").append(en.getKey())
                        .append("\": {\"sum\": ").append(fmt(en.getValue()[0]))
                        .append(", \"max\": ").append(fmt(en.getValue()[1])).append("}");
                }
            }
            json.append("}");
        }
        json.append("\n  }\n}\n");

        FileOutputStream fo = new FileOutputStream("daily_raw.json");
        fo.write(json.toString().getBytes("UTF-8"));
        fo.close();
        System.out.println("[daily] RESULT mode=" + mode + " downloaded=" + downloaded
            + " total_in_window=" + totalInWindow + " parsed=" + parsed + " matched=" + matched.size());
        System.out.println("[daily] === DONE -> daily_raw.json");
    }

    static boolean inWindow(String filename, long tStart, long tEnd, SimpleDateFormat fFmt) {
        // filename 形如 PM_<startyyyyMMddHHmm>-<endyyyyMMddHHmm>_<task>.xml|.zip
        int p1 = filename.indexOf("PM_");
        int dot = filename.lastIndexOf('.');
        if (p1 < 0 || dot < 0) return true;
        String body = filename.substring(3, dot);
        int dash = body.indexOf('-');
        if (dash < 0) return true;
        try {
            Date fs = fFmt.parse(body.substring(0, dash));
            long fEnd = fFmt.parse(body.substring(dash + 1)).getTime();
            return (fEnd > tStart && fs.getTime() < tEnd);
        } catch (Exception e) { return true; }
    }

    /** parse one measCollectFile, accumulate by day: sum and max per counter */
    static int parseXml(File f, TreeMap<String, HashMap<String, double[]>> daily,
                        Set<String> allCounters, SimpleDateFormat dayKey) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        DocumentBuilder db = dbf.newDocumentBuilder();
        Document doc = db.parse(f);

        ArrayList<String> typeList = new ArrayList<String>();
        NodeList amts = doc.getElementsByTagName("allMeasTypes");
        for (int a = 0; a < amts.getLength() && typeList.isEmpty(); a++) {
            StringTokenizer st = new StringTokenizer(textOf(amts.item(a)));
            while (st.hasMoreTokens()) typeList.add(st.nextToken());
        }

        NodeList infos = doc.getElementsByTagName("measInfo");
        int files = 0;
        for (int i = 0; i < infos.getLength(); i++) {
            Element info = (Element) infos.item(i);
            ArrayList<String> types = new ArrayList<String>();
            NodeList mt = info.getElementsByTagName("measTypes");
            if (mt.getLength() > 0) {
                StringTokenizer st = new StringTokenizer(textOf(mt.item(0)));
                while (st.hasMoreTokens()) types.add(st.nextToken());
            }
            if (types.isEmpty()) types = typeList;

            Date endT = null;
            NodeList gp = info.getElementsByTagName("granPeriod");
            if (gp.getLength() > 0) {
                String endTime = ((Element) gp.item(0)).getAttribute("endTime");
                endT = parseIso(endTime);
            }
            if (endT == null) continue;
            String day = dayKey.format(endT);

            NodeList vals = info.getElementsByTagName("measValue");
            for (int vI = 0; vI < vals.getLength(); vI++) {
                Element val = (Element) vals.item(vI);
                NodeList res = val.getElementsByTagName("measResults");
                if (res.getLength() == 0) continue;
                StringTokenizer rst = new StringTokenizer(textOf(res.item(0)));
                int idx = 0;
                while (rst.hasMoreTokens() && idx < types.size()) {
                    String raw = rst.nextToken();
                    String name = types.get(idx);
                    idx++;
                    allCounters.add(name);
                    double d;
                    try { d = Double.parseDouble(raw); } catch (Exception e2) { continue; }
                    HashMap<String, double[]> dayMap = daily.get(name);
                    if (dayMap == null) { dayMap = new HashMap<String, double[]>(); daily.put(name, dayMap); }
                    double[] sv = dayMap.get(day);
                    if (sv == null) { sv = new double[]{0.0, 0.0}; dayMap.put(day, sv); }
                    sv[0] += d;          // sum
                    if (d > sv[1]) sv[1] = d;  // max
                }
            }
        }
        return 1;
    }

    static String textOf(Node n) {
        StringBuffer sb = new StringBuffer();
        collectText(n, sb);
        return sb.toString();
    }
    static void collectText(Node n, StringBuffer sb) {
        if (n.getNodeType() == Node.TEXT_NODE || n.getNodeType() == Node.CDATA_SECTION_NODE) {
            sb.append(n.getNodeValue());
            return;
        }
        NodeList kids = n.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) collectText(kids.item(i), sb);
    }

    static Date parseIso(String s) {
        try {
            String base = s.substring(0, 19);
            SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss");
            iso.setTimeZone(TimeZone.getTimeZone("GMT"));
            Calendar c = Calendar.getInstance(TimeZone.getTimeZone("GMT"));
            c.setTime(iso.parse(base));
            int sign = 1;
            int k = s.indexOf('+', 19);
            if (k < 0) { k = s.indexOf('-', 19); sign = -1; }
            if (k > 0) {
                String off = s.substring(k + 1);
                int hh = Integer.parseInt(off.substring(0, 2));
                int mm = off.length() >= 5 ? Integer.parseInt(off.substring(3, 5)) : 0;
                c.add(Calendar.HOUR, -sign * hh);
                c.add(Calendar.MINUTE, -sign * mm);
            }
            return c.getTime();
        } catch (Exception e) { return null; }
    }

    static String fmt(double d) {
        if (d == Math.floor(d) && !Double.isInfinite(d) && Math.abs(d) < 1e15) {
            return Long.toString((long) d);
        }
        return new java.math.BigDecimal(d).setScale(4, java.math.BigDecimal.ROUND_HALF_UP).stripTrailingZeros().toPlainString();
    }

    static String jesc(String s) {
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    static Throwable root(Throwable t) {
        Throwable r = t;
        while (r.getCause() != null) r = r.getCause();
        return r;
    }
}
