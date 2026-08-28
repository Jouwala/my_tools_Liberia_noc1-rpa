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
 * EmsKpiRawQuery — 兜底方案: 直接从 EMS SFTP 下载原始测量文件并解析为 KPI。
 *
 * 数据源: /pmdata/download/<ne>_<module>_module_dataCollect/PM_<start>-<end>_<task>.xml|.zip
 * 格式:   3GPP measCollectFile (allMeasTypes + measValue/measResults 按序对应)
 *
 * 用法: EmsKpiRawQuery <host> <startDate yyyy/MM/dd> <endDate yyyy/MM/dd> [counterSubstr]
 *   counterSubstr — 计数器名过滤子串(匹配任一即计入), 默认 "Occupancy##@##Duration"
 * 输出: kpi_result_raw.json
 */
public class EmsKpiRawQuery {

    static String host = "10.100.2.240";
    static int port = 21128;
    static String sftpUser = "uepcommon";
    static String neDir = "/pmdata/download/gzmulyxb-2_11_module_dataCollect";
    static File cacheDir = new File("_pmcache");

    public static void main(String[] args) throws Exception {
        String startDay = args.length > 1 ? args[1] : "2026/06/26";
        String endDay   = args.length > 2 ? args[2] : "2026/06/28";
        String counterPat = args.length > 3 ? args[3] : "Occupancy##@##Duration";

        SimpleDateFormat dayFmt = new SimpleDateFormat("yyyy/MM/dd");
        dayFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        long tStart = dayFmt.parse(startDay).getTime();
        long tEnd   = dayFmt.parse(endDay).getTime();

        if (!cacheDir.exists()) cacheDir.mkdirs();

        System.out.println("[raw] connecting SFTP " + host + ":" + port);
        SftpClientImpl sftp = new SftpClientImpl(host, port, 30000, sftpUser, null, false);

        // ---- 1. 全量列目录, 解析文件名时间窗 ----
        String[] entries = sftp.dir(neDir, true);
        System.out.println("[raw] directory entries: " + entries.length);

        ArrayList<String> picked = new ArrayList<String>();
        SimpleDateFormat fFmt = new SimpleDateFormat("yyyyMMddHHmm");
        fFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        for (String e : entries) {
            int p1 = e.indexOf("PM_");
            if (p1 < 0) continue;
            String fn = e.substring(p1);
            // PM_202608241150-202608241155_66239.xml
            try {
                String body = fn.substring(3, fn.lastIndexOf('.'));
                int dash = body.indexOf('-');
                Date fs = fFmt.parse(body.substring(0, dash));
                long fEnd = fFmt.parse(body.substring(dash + 1)).getTime();
                if (fEnd > tStart && fs.getTime() < tEnd) {
                    picked.add(fn);
                }
            } catch (Exception ignore) { }
        }
        Collections.sort(picked);
        System.out.println("[raw] files in window [" + startDay + " ~ " + endDay + "): " + picked.size());

        // ---- 2. 下载 + 解析 ----
        // 聚合结构: 时间戳(endTime ms) -> counterName -> sum
        TreeMap<Long, HashMap<String, Double>> series = new TreeMap<Long, HashMap<String, Double>>();
        TreeSet<String> allCounters = new TreeSet<String>();
        TreeSet<String> objects = new TreeSet<String>();
        int parsedFiles = 0;

        for (String fn : picked) {
            File local = new File(cacheDir, fn);
            if (!local.exists() || local.length() == 0) {
                try {
                    sftp.get(local.getAbsolutePath(), neDir + "/" + fn);
                } catch (Throwable t) {
                    Throwable r = root(t);
                    System.out.println("[raw] download FAIL " + fn + ": " + r.getMessage());
                    continue;
                }
            }
            try {
                if (fn.endsWith(".xml")) {
                    parseXml(local, series, allCounters, objects);
                    parsedFiles++;
                } else if (fn.endsWith(".zip")) {
                    // zip 内含 xml, 流式解出首个 .xml 条目
                    FileInputStream fin = new FileInputStream(local);
                    ZipInputStream zin = new ZipInputStream(fin);
                    ByteArrayOutputStream bout = new ByteArrayOutputStream();
                    boolean got = false;
                    ZipEntry ze;
                    while ((ze = zin.getNextEntry()) != null) {
                        if (ze.getName().endsWith(".xml")) {
                            byte[] buf = new byte[8192];
                            int n;
                            while ((n = zin.read(buf)) > 0) bout.write(buf, 0, n);
                            got = true;
                            break;
                        }
                    }
                    zin.close();
                    if (got) {
                        File tmp = new File(cacheDir, fn + ".__inner.xml");
                        FileOutputStream fo = new FileOutputStream(tmp);
                        fo.write(bout.toByteArray());
                        fo.close();
                        parseXml(tmp, series, allCounters, objects);
                        tmp.delete();
                        parsedFiles++;
                    }
                }
            } catch (Throwable t) {
                Throwable r = root(t);
                System.out.println("[raw] parse FAIL " + fn + ": " + r.getMessage());
            }
        }
        try { sftp.quit(); } catch (Exception ignore) { }
        System.out.println("[raw] parsed files: " + parsedFiles + ", distinct counters: " + allCounters.size()
            + ", timestamps: " + series.size() + ", objects: " + objects.size());

        // ---- 3. 匹配目标计数器并聚合 (支持 '|' 分隔多模式) ----
        String[] pats = counterPat.split("\\|");
        ArrayList<String> matched = new ArrayList<String>();
        for (String c : allCounters) {
            for (int pi = 0; pi < pats.length; pi++) {
                if (c.contains(pats[pi])) { matched.add(c); break; }
            }
        }
        System.out.println("[raw] counters matching \"" + counterPat + "\": " + matched.size());
        for (String c : matched) System.out.println("      " + c);

        // 每 5 分钟点: Erl = SUM(duration)/300 ; 日粒度再汇总
        StringBuilder json = new StringBuilder();
        json.append("{\n");
        json.append("  \"source\": \"sftp://").append(host).append(neDir).append("\",\n");
        json.append("  \"ne\": \"gzmulyxb-2 (elementid=11)\",\n");
        json.append("  \"window\": {\"start\": \"").append(startDay).append("\", \"end\": \"").append(endDay).append("\"},\n");
        json.append("  \"counterFilter\": \"").append(jesc(counterPat)).append("\",\n");
        json.append("  \"filesParsed\": ").append(parsedFiles).append(",\n");
        json.append("  \"countersMatched\": [");
        for (int i = 0; i < matched.size(); i++) {
            if (i > 0) json.append(", ");
            json.append('"').append(jesc(matched.get(i))).append('"');
        }
        json.append("],\n");

        // 5 分钟序列
        json.append("  \"series5min\": [\n");
        double grandTotal = 0;
        int pts = 0;
        Iterator<Map.Entry<Long, HashMap<String, Double>>> it = series.entrySet().iterator();
        while (it.hasNext()) {
            Map.Entry<Long, HashMap<String, Double>> en = it.next();
            double sum = 0;
            for (String c : matched) {
                Double v = en.getValue().get(c);
                if (v != null) sum += v.doubleValue();
            }
            double erl = sum / 300.0;
            grandTotal += erl;
            pts++;
            SimpleDateFormat tsFmt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
            tsFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
            json.append("    {\"ts\": \"").append(tsFmt.format(new Date(en.getKey())))
                .append("\", \"sumDurationS\": ").append(fmt(sum))
                .append(", \"erl\": ").append(fmt(erl)).append("}");
            if (it.hasNext()) json.append(",");
            json.append("\n");
        }
        json.append("  ],\n");
        json.append("  \"points\": ").append(pts).append(",\n");
        json.append("  \"avgErlOverWindow\": ").append(fmt(pts > 0 ? grandTotal / pts : 0)).append("\n");
        json.append("}\n");

        FileOutputStream fo = new FileOutputStream("kpi_result_raw.json");
        fo.write(json.toString().getBytes("UTF-8"));
        fo.close();
        System.out.println("[raw] === DONE -> kpi_result_raw.json (avg Erl over window: "
            + fmt(pts > 0 ? grandTotal / pts : 0) + ")");
    }

    /** 解析单个 measCollectFile XML, 累加进 series */
    static void parseXml(File f, TreeMap<Long, HashMap<String, Double>> series,
                         Set<String> allCounters, Set<String> objects) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        DocumentBuilder db = dbf.newDocumentBuilder();
        Document doc = db.parse(f);

        // allMeasTypes: 空格分隔的计数器名列表
        ArrayList<String> typeList = new ArrayList<String>();
        NodeList amts = doc.getElementsByTagName("allMeasTypes");
        if (amts.getLength() > 0) {
            String txt = textOf(amts.item(0));
            StringTokenizer st = new StringTokenizer(txt);
            while (st.hasMoreTokens()) typeList.add(st.nextToken());
        }

        NodeList infos = doc.getElementsByTagName("measInfo");
        for (int i = 0; i < infos.getLength(); i++) {
            Element info = (Element) infos.item(i);
            // 本 measInfo 的 measTypes 若非空则覆盖全局表
            ArrayList<String> types = new ArrayList<String>();
            NodeList mt = info.getElementsByTagName("measTypes");
            if (mt.getLength() > 0) {
                String txt = textOf(mt.item(0));
                StringTokenizer st = new StringTokenizer(txt);
                while (st.hasMoreTokens()) types.add(st.nextToken());
            }
            if (types.isEmpty()) types = typeList;

            // granPeriod endTime -> 时间戳
            Date endT = null;
            NodeList gp = info.getElementsByTagName("granPeriod");
            if (gp.getLength() > 0) {
                String endTime = ((Element) gp.item(0)).getAttribute("endTime");
                endT = parseIso(endTime);
            }
            if (endT == null) continue;
            long ts = endT.getTime();

            NodeList vals = info.getElementsByTagName("measValue");
            for (int vI = 0; vI < vals.getLength(); vI++) {
                Element val = (Element) vals.item(vI);
                String ldn = val.getAttribute("measObjLdn");
                objects.add(ldn);
                NodeList res = val.getElementsByTagName("measResults");
                if (res.getLength() == 0) continue;
                StringTokenizer rst = new StringTokenizer(textOf(res.item(0)));
                HashMap<String, Double> bucket = series.get(ts);
                if (bucket == null) { bucket = new HashMap<String, Double>(); series.put(ts, bucket); }
                int idx = 0;
                while (rst.hasMoreTokens() && idx < types.size()) {
                    String raw = rst.nextToken();
                    String name = types.get(idx);
                    idx++;
                    allCounters.add(name);
                    double d;
                    try { d = Double.parseDouble(raw); } catch (Exception e2) { continue; }
                    Double old = bucket.get(name);
                    bucket.put(name, (old == null ? 0 : old.doubleValue()) + d);
                }
            }
        }
    }

    /** Crimson(DOM1) 兼容: 取节点下全部 Text 内容 */
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
        // 2026-08-24T11:55:00+00:00
        try {
            String base = s.substring(0, 19);
            SimpleDateFormat iso = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss");
            iso.setTimeZone(TimeZone.getTimeZone("GMT"));
            Calendar c = Calendar.getInstance(TimeZone.getTimeZone("GMT"));
            c.setTime(iso.parse(base));
            // 应用偏移 (+00:00 / +08:00)
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
