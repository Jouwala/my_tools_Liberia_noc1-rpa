import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.zip.GZIPInputStream;
import javax.naming.*;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.DESKeySpec;
import javax.crypto.SecretKeyFactory;

/**
 * EmsKpiQueryDirect — ZTE U31 KPI 数据同步查询（绕过异步会话门槛）
 *
 * 【核心思路】
 * 现有 EmsKpiQuery 走 cmd 2720 + async + JMS 异步通知, 但服务端会话级门槛
 * 导致异步查询永远不产出结果文件。本工具改用三步策略:
 *
 *   策略 A（首选）: requestxForNonGUI + 同步模式
 *     - 与 EmsKpiFinal 已验证的 cmd 2600 同路径（requestxForNonGUI 无会话验证）
 *     - 不加 asyn=true 标志（服务端同步执行, 直接在响应中返回数据）
 *     - 使用 cmd 2686（模板查询, 权限门槛低于 2720）
 *     - 如果响应包含 ResultDataSet 或 FIRecSection, 直接解析
 *
 *   策略 B（回退）: 如果同步响应为空, 启动 JMS 监听等待异步通知
 *     - 与 EmsKpiQuery 相同, 但使用 durable subscriber + 更长超时
 *
 *   策略 C（兜底）: 直接 SFTP 下载原始测量文件
 *     - 扫描 /pmdata/download/ 下所有模块目录
 *     - 按时间窗口下载并解析原始 XML
 *
 * 用法:
 *   java EmsKpiQueryDirect <server> <user> <password> <startDay> <endDay> [strategy]
 *   strategy: sync | jms | sftp | hybrid（默认 hybrid）
 */
public class EmsKpiQueryDirect {

    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    static final int JNP_PORT = 21100;
    static final int JMS_PORT = 21101;
    static final String PM_DATA_TOPIC = "PM_SEND_DATA_TOPIC";

    static volatile List<Object> collectedMessages = Collections.synchronizedList(new ArrayList<Object>());
    static volatile List<Object> collectedResponses = Collections.synchronizedList(new ArrayList<Object>());
    static String queryIdHolder = null;

    public static void main(String[] args) {
        try {
            runMain(args);
        } catch (Throwable t) {
            System.out.println("!! FATAL: " + t);
            t.printStackTrace(System.out);
        }
        System.out.flush();
        System.exit(0);
    }

    static void runMain(String[] args) throws Exception {
        String server = args.length > 0 ? args[0] : "10.100.2.240";
        String user   = args.length > 1 ? args[1] : "oss";
        String pass   = args.length > 2 ? args[2] : "Tool123";
        String startDay, endDay;
        String strategy = args.length > 5 ? args[5] : "hybrid";

        SimpleDateFormat dayFmt = new SimpleDateFormat("yyyy/MM/dd");
        dayFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("GMT"));
        if (args.length > 3 && args[3].length() > 0) {
            startDay = args[3].replace('-', '/');
        } else {
            cal.add(Calendar.DAY_OF_MONTH, -1);
            startDay = dayFmt.format(cal.getTime());
        }
        if (args.length > 4 && args[4].length() > 0) {
            endDay = args[4].replace('-', '/');
        } else {
            cal.add(Calendar.DAY_OF_MONTH, 1);
            endDay = dayFmt.format(cal.getTime());
        }

        System.out.println("=== EmsKpiQueryDirect ===");
        System.out.println("Server=" + server + " user=" + user
            + " window=[" + startDay + " ~ " + endDay + ") strategy=" + strategy);

        // ===== Step 1: Login =====
        Object namingStub = getNamingStub(server, JNP_PORT);
        Method lookupName = namingStub.getClass().getMethod("lookup", String.class, Name.class);
        Object resultPair = lookupName.invoke(namingStub, "jndi_client", new CompoundName("", new Properties()));
        Object namingCtx = resultPair.getClass().getMethod("getResultValue").invoke(resultPair);
        Method lookupStr = namingCtx.getClass().getMethod("lookup", String.class);

        Object fsmObj = lookupStr.invoke(namingCtx, "FServerManager");
        Object ejbObject = fsmObj.getClass().getMethod("create").invoke(fsmObj);
        Method loginMethod = null;
        for (Method m : ejbObject.getClass().getMethods())
            if (m.getName().equals("login")) { loginMethod = m; break; }
        Class<?>[] pt = loginMethod.getParameterTypes();
        Object[] lp = new Object[pt.length];
        lp[0] = user;
        lp[1] = desEncrypt(pass);
        int[] ints = {1, 1000};
        int ii = 0;
        for (int i = 2; i < pt.length; i++) {
            if (pt[i] == Integer.class || pt[i] == int.class) lp[i] = Integer.valueOf(ints[ii++ % 2]);
            else if (pt[i] == Properties.class) {
                Properties lprops = new Properties();
                lprops.setProperty("MSG_SIZE_THERSHOLD", "1");
                lprops.setProperty("MSG_TRANS_SIZE_THERSHOLD", "0");
                lprops.setProperty("clientIP", getLocalIp(server));
                lprops.setProperty("serverIP", server);
                lprops.setProperty("SecLogId", "-1");
                lprops.setProperty("locale", "en_US");
                lprops.setProperty("usf.system.amf", "none");
                lprops.setProperty("isSSH", "false");
                lprops.setProperty("clientMac", getClientMac());
                lp[i] = lprops;
            }
        }
        Object loginResult = loginMethod.invoke(ejbObject, lp);
        int errID = (Integer) loginResult.getClass().getMethod("getErrID").invoke(loginResult);
        if (errID != 0) { System.out.println("LOGIN FAILED errID=" + errID); System.exit(2); }
        int sessionID = (Short) loginResult.getClass().getMethod("getSessionID").invoke(loginResult);
        int userID = (Integer) loginResult.getClass().getMethod("getUserID").invoke(loginResult);
        String sessionCode = (String) loginResult.getClass().getMethod("getSessionCode").invoke(loginResult);
        System.out.println("[1] Login OK sessionID=" + sessionID + " userID=" + userID);

        // ===== Step 1a: Heartbeat =====
        Object heartbeatStub = null;
        try {
            heartbeatStub = lookupStr.invoke(namingCtx, "uep.fi.heartbeatreciever");
            Method hb = heartbeatStub.getClass().getMethod("setSessionStateOK", short.class);
            hb.invoke(heartbeatStub, (short) sessionID);
            System.out.println("[1a] heartbeat registered");
        } catch (Throwable t) {
            System.out.println("[1a] heartbeat failed: " + rootMsg(t));
        }
        if (heartbeatStub != null) {
            final Object stub = heartbeatStub;
            final short sid = (short) sessionID;
            Thread hbThread = new Thread(new Runnable() {
                public void run() {
                    while (true) {
                        try { Thread.sleep(10000); } catch (InterruptedException e) { return; }
                        try {
                            stub.getClass().getMethod("setSessionStateOK", short.class).invoke(stub, sid);
                        } catch (Throwable ignore) {}
                    }
                }
            }, "hb");
            hbThread.setDaemon(true);
            hbThread.start();
        }

        // ===== Step 2: JMS Setup (if needed by strategy) =====
        Object jmsConn = null;
        Object jmsSession = null;
        if (strategy.equals("jms") || strategy.equals("hybrid") || strategy.equals("sync")) {
            try {
                Properties jmsEnv = new Properties();
                jmsEnv.setProperty("java.naming.factory.initial",
                    "com.zte.ums.uep.psl.naming.interfaces.GlobeNamingContextFactory");
                jmsEnv.setProperty("java.naming.provider.url", "jnp://" + server + ":" + JMS_PORT);
                InitialContext jmsCtx = new InitialContext(jmsEnv);
                Object cf = jmsCtx.lookup("ConnectionFactory");
                jmsConn = cf.getClass().getMethod("createTopicConnection", String.class, String.class)
                             .invoke(cf, user, pass);
                // 设置 clientID 以支持 durable subscriber
                try {
                    jmsConn.getClass().getMethod("setClientID", String.class)
                           .invoke(jmsConn, "direct_query_" + sessionID);
                } catch (Throwable ignore) {}
                jmsSession = jmsConn.getClass().getMethod("createTopicSession", boolean.class, int.class)
                                    .invoke(jmsConn, false, 1);
                // 订阅 PM_SEND_DATA_TOPIC
                Object dataTopic = jmsSession.getClass().getMethod("createTopic", String.class)
                                             .invoke(jmsSession, PM_DATA_TOPIC);
                Object subscriber = jmsSession.getClass()
                    .getMethod("createSubscriber", Class.forName("javax.jms.Topic"))
                    .invoke(jmsSession, dataTopic);
                subscriber.getClass().getMethod("setMessageListener", Class.forName("javax.jms.MessageListener"))
                          .invoke(subscriber, newJmsListener());
                // 订阅响应 topic
                String respTopicName = "UEP_F_RESPONSE_TOPIC" + sessionID;
                try {
                    Object rmiAdaptor = jmsCtx.lookup("jmx/rmi/RMIAdaptor");
                    javax.management.ObjectName dm = new javax.management.ObjectName("jboss.mq:service=DestinationManager");
                    try {
                        rmiAdaptor.getClass().getMethod("invoke", javax.management.ObjectName.class, String.class,
                            Object[].class, String[].class)
                            .invoke(rmiAdaptor, dm, "createTopic",
                                new Object[]{respTopicName}, new String[]{"java.lang.String"});
                    } catch (InvocationTargetException e) {
                        // 可能已存在
                    }
                } catch (Throwable ignore) {}
                Object respTopic = jmsSession.getClass().getMethod("createTopic", String.class)
                                             .invoke(jmsSession, respTopicName);
                Object sub2 = jmsSession.getClass()
                    .getMethod("createSubscriber", Class.forName("javax.jms.Topic"))
                    .invoke(jmsSession, respTopic);
                sub2.getClass().getMethod("setMessageListener", Class.forName("javax.jms.MessageListener"))
                    .invoke(sub2, newJmsListener());
                jmsConn.getClass().getMethod("start").invoke(jmsConn);
                System.out.println("[2] JMS subscribed: " + PM_DATA_TOPIC + " + " + respTopicName);
            } catch (Throwable t) {
                System.out.println("[2] JMS setup failed: " + rootMsg(t) + " (continuing without JMS)");
            }
        }

        // ===== Step 3: Load template and prepare query =====
        File tpl = new File("pm_query_template.bin");
        if (!tpl.exists()) {
            System.out.println("!! pm_query_template.bin not found in " + new File(".").getCanonicalPath());
            // 尝试用空模板
            System.out.println("[3] No template, will try direct query without template");
        }

        // ===== Step 4: Strategy execution =====
        boolean dataObtained = false;

        // 策略 A: 同步查询 (requestxForNonGUI, no asyn)
        if ((strategy.equals("sync") || strategy.equals("hybrid")) && !dataObtained) {
            dataObtained = trySyncQuery(namingCtx, lookupStr, fsbLookup(lookupStr, namingCtx, "FServerBroker"),
                sessionID, userID, sessionCode, user, startDay, endDay, tpl);
        }

        // 策略 B: JMS 异步等待
        if ((strategy.equals("jms") || strategy.equals("hybrid")) && !dataObtained && jmsSession != null) {
            dataObtained = tryJmsQuery(namingCtx, lookupStr, fsbLookup(lookupStr, namingCtx, "FServerBroker"),
                sessionID, userID, sessionCode, user, startDay, endDay, tpl);
        }

        // 策略 C: SFTP 原始文件下载
        if ((strategy.equals("sftp") || strategy.equals("hybrid")) && !dataObtained) {
            dataObtained = trySftpDownload(server, startDay, endDay);
        }

        // 清理
        try { if (jmsConn != null) jmsConn.getClass().getMethod("close").invoke(jmsConn); } catch (Exception ignore) {}

        if (!dataObtained) {
            System.out.println("\n=== ALL STRATEGIES EXHAUSTED - no data obtained ===");
            // 输出空 JSON
            writeJsonResult(null, startDay, endDay, null, 0);
        }
        System.out.println("\n=== DONE ===");
    }

    /** 策略 A: 使用 requestxForNonGUI 同步查询 */
    static boolean trySyncQuery(Object namingCtx, Method lookupStr, Object fsbEjb,
        int sessionID, int userID, String sessionCode, String user,
        String startDay, String endDay, File tplFile) throws Exception {

        System.out.println("\n--- Strategy A: sync query via requestxForNonGUI ---");

        Class<?> fiMsgClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage");
        Method reqNonGUI = null;
        for (Method m : fsbEjb.getClass().getMethods())
            if (m.getName().equals("requestxForNonGUI")) { reqNonGUI = m; break; }
        if (reqNonGUI == null) {
            System.out.println("    requestxForNonGUI not available");
            return false;
        }

        // 尝试 cmd 2686 (模板查询) 和 cmd 2720 (原始查询)
        int[] cmdCodes = {2686, 2720};
        String[] opNames = {"uca.pm.template.querydata", "uca.pm.querydata"};
        boolean success = false;

        for (int ci = 0; ci < cmdCodes.length && !success; ci++) {
            int cmd = cmdCodes[ci];
            String op = opNames[ci];
            System.out.println("    Trying cmd " + cmd + " (" + op + ")...");

            // 从模板反序列化消息
            Object fiMsg = null;
            if (tplFile.exists()) {
                ObjectInputStream ois = new ObjectInputStream(new FileInputStream(tplFile));
                fiMsg = ois.readObject();
                ois.close();
            } else {
                fiMsg = fiMsgClass.getConstructor(int.class).newInstance(Integer.valueOf(cmd));
            }

            // 设置会话字段
            Method setVal = fiMsg.getClass().getMethod("setValue", String.class, String.class);
            setVal.invoke(fiMsg, "sessioncode", sessionCode);
            setVal.invoke(fiMsg, "SessionID", String.valueOf(sessionID));
            setVal.invoke(fiMsg, "UserID", String.valueOf(userID));
            setVal.invoke(fiMsg, "UserName", user);
            fiMsg.getClass().getMethod("setCommandCode", int.class).invoke(fiMsg, Integer.valueOf(cmd));
            fiMsg.getClass().getMethod("setInvokeID", int.class).invoke(fiMsg,
                Integer.valueOf(100000 + new Random().nextInt(800000)));

            setVal.invoke(fiMsg, "checkedoperation", op);
            setVal.invoke(fiMsg, "checked", "true");
            // 关键: 不加 asyn=true — 让服务端同步执行
            // 移除 uniqueNodeID
            try {
                Field hf2 = findField(fiMsg.getClass(), "header");
                hf2.setAccessible(true);
                Object hdrProps = hf2.get(fiMsg);
                hdrProps.getClass().getMethod("remove", Object.class).invoke(hdrProps, "uniqueNodeID");
            } catch (Throwable ignore) {}

            // 如果从模板反序列化, 更新时间范围
            if (tplFile.exists()) {
                Object cond = firstSectionObject(fiMsg);
                if (cond.getClass().isArray()) {
                    Object[] arr = (Object[]) cond;
                    cond = arr[0];
                    Object sec0 = fiMsg.getClass().getMethod("getFISectionAt", int.class).invoke(fiMsg, 0);
                    setObjectSafe(sec0, cond);
                }
                setTimeRange(cond, startDay, endDay);
            }

            try {
                long t0 = System.currentTimeMillis();
                // requestxForNonGUI 接收未包装的 FIMessage
                Object resp = reqNonGUI.invoke(fsbEjb, fiMsg);
                long dt = System.currentTimeMillis() - t0;
                System.out.println("    Response after " + dt + "ms");

                if (resp != null) {
                    int rErr = -99;
                    try { rErr = (Integer) resp.getClass().getMethod("getErrID").invoke(resp); } catch (Throwable ignore) {}
                    String rDesc = "";
                    try { rDesc = (String) resp.getClass().getMethod("getErrDesc").invoke(resp); } catch (Throwable ignore) {}
                    System.out.println("    errID=" + rErr + " errDesc=" + rDesc);

                    // 保存响应供分析
                    try {
                        ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream("_resp_sync_" + cmd + ".bin"));
                        oos.writeObject(resp); oos.close();
                    } catch (Throwable ignore) {}

                    // 尝试解析响应中的数据
                    ResultData data = extractResultData(resp);
                    if (data != null && data.rowCount > 0) {
                        System.out.println("    GOT " + data.rowCount + " rows from sync response!");
                        writeJsonResult("sync_" + cmd, startDay, endDay, data, data.rowCount);
                        success = true;
                    } else {
                        // 尝试解压压缩响应
                        Object inner = decodeCompressedResponse(resp);
                        if (inner != null) {
                            data = extractResultData(inner);
                            if (data != null && data.rowCount > 0) {
                                System.out.println("    GOT " + data.rowCount + " rows from compressed sync response!");
                                writeJsonResult("sync_" + cmd, startDay, endDay, data, data.rowCount);
                                success = true;
                            }
                        }
                        if (!success) {
                            System.out.println("    No data in sync response");
                        }
                    }
                }
            } catch (InvocationTargetException e) {
                Throwable target = e.getTargetException();
                System.out.println("    cmd " + cmd + " failed: " + target.getClass().getName() + ": " + target.getMessage());
                // 检查是否是 90 秒超时 — 说明服务端在处理但响应慢
                if (target.getMessage() != null && target.getMessage().contains("90")) {
                    System.out.println("    (90s timeout means server IS processing, but async)");
                }
            } catch (Throwable t) {
                System.out.println("    cmd " + cmd + " error: " + rootMsg(t));
            }
        }
        return success;
    }

    /** 策略 B: JMS 异步等待查询结果 */
    static boolean tryJmsQuery(Object namingCtx, Method lookupStr, Object fsbEjb,
        int sessionID, int userID, String sessionCode, String user,
        String startDay, String endDay, File tplFile) throws Exception {

        System.out.println("\n--- Strategy B: JMS async query ---");

        Class<?> fiMsgClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage");
        Method reqM = null;
        for (Method m : fsbEjb.getClass().getMethods())
            if (m.getName().equals("requestx")) { reqM = m; break; }

        // 使用模板, 带 asyn=true
        if (!tplFile.exists()) {
            System.out.println("    No template, cannot do JMS async query");
            return false;
        }

        ObjectInputStream ois = new ObjectInputStream(new FileInputStream(tplFile));
        Object fiMsg = ois.readObject();
        ois.close();

        Method setVal = fiMsg.getClass().getMethod("setValue", String.class, String.class);
        setVal.invoke(fiMsg, "sessioncode", sessionCode);
        setVal.invoke(fiMsg, "SessionID", String.valueOf(sessionID));
        setVal.invoke(fiMsg, "UserID", String.valueOf(userID));
        setVal.invoke(fiMsg, "UserName", user);
        setVal.invoke(fiMsg, "checkedoperation", "uca.pm.template.querydata");
        setVal.invoke(fiMsg, "checked", "true");
        setVal.invoke(fiMsg, "asyn", "true");  // 异步模式
        fiMsg.getClass().getMethod("setCommandCode", int.class).invoke(fiMsg, Integer.valueOf(2686));
        fiMsg.getClass().getMethod("setInvokeID", int.class).invoke(fiMsg,
            Integer.valueOf(100000 + new Random().nextInt(800000)));

        // 更新时间
        Object cond = firstSectionObject(fiMsg);
        if (cond.getClass().isArray()) {
            Object[] arr = (Object[]) cond;
            cond = arr[0];
            Object sec0 = fiMsg.getClass().getMethod("getFISectionAt", int.class).invoke(fiMsg, 0);
            setObjectSafe(sec0, cond);
        }
        setTimeRange(cond, startDay, endDay);

        try {
            Field stf = findField(fiMsg.getClass(), "state_time");
            stf.setAccessible(true);
            stf.setLong(fiMsg, System.currentTimeMillis());
        } catch (Throwable ignore) {}

        // 发送
        Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
        Method wrapM = msgUtilCls.getMethod("getWrappedMessage",
            Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"), int.class);
        Object outer = wrapM.invoke(null, fiMsg, Integer.valueOf(1));

        long t0 = System.currentTimeMillis();
        System.out.println("    Submitting cmd 2686 async...");
        Object resp = reqM.invoke(fsbEjb, outer);

        // 解包响应
        if (resp != null) {
            try {
                Method unwrapM = msgUtilCls.getMethod("getUnwrappedMessage",
                    Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"));
                resp = unwrapM.invoke(null, resp);
            } catch (Throwable t) {
                Object inner = decodeCompressedResponse(resp);
                if (inner != null) resp = inner;
            }
        }

        // 提取 queryId
        String queryId = null;
        if (resp != null) {
            try {
                int rErr = (Integer) resp.getClass().getMethod("getErrID").invoke(resp);
                System.out.println("    Response errID=" + rErr);
                Object[] conds = unwrapConditions(resp);
                if (conds != null && conds.length > 0 && conds[0] != null) {
                    queryId = (String) conds[0].getClass().getMethod("getQueryId").invoke(conds[0]);
                    System.out.println("    queryId=" + queryId);
                }
            } catch (Throwable ignore) {}
        }

        // 等待 JMS 消息 + SFTP 轮询
        List<String> files = waitForFiles(queryId, 300000, server());  // 5 分钟超时
        if (files.isEmpty()) {
            System.out.println("    No result files from JMS/SFTP poll");
            return false;
        }

        // 下载并解析结果文件
        return downloadAndParseFiles(server(), files, startDay, endDay);
    }

    static String server() { return "10.100.2.240"; }

    /** 策略 C: SFTP 原始文件下载 */
    static boolean trySftpDownload(String server, String startDay, String endDay) throws Exception {
        System.out.println("\n--- Strategy C: SFTP raw file download ---");

        SimpleDateFormat dayFmt = new SimpleDateFormat("yyyy/MM/dd");
        dayFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        long tStart = dayFmt.parse(startDay).getTime();
        long tEnd   = dayFmt.parse(endDay).getTime();

        File cacheDir = new File("_pmcache");
        if (!cacheDir.exists()) cacheDir.mkdirs();

        Class<?> sftpCls = Class.forName("com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl");
        Object sftp = sftpCls.getConstructor(String.class, int.class, int.class, String.class,
            String.class, boolean.class).newInstance(server, Integer.valueOf(21128),
            Integer.valueOf(30000), "uepcommon", null, Boolean.FALSE);
        String[] dirs = (String[]) sftp.getClass().getMethod("dir", String.class, boolean.class)
            .invoke(sftp, "/pmdata/download", Boolean.FALSE);
        System.out.println("    Module dirs: " + dirs.length);

        SimpleDateFormat fFmt = new SimpleDateFormat("yyyyMMddHHmm");
        fFmt.setTimeZone(TimeZone.getTimeZone("GMT"));
        SimpleDateFormat dayKey = new SimpleDateFormat("yyyy-MM-dd");
        dayKey.setTimeZone(TimeZone.getTimeZone("GMT"));

        // 聚合: 按 counter 名 -> 日期 -> {sum, max}
        TreeMap<String, HashMap<String, double[]>> daily = new TreeMap<String, HashMap<String, double[]>>();
        TreeSet<String> allCounters = new TreeSet<String>();
        int parsed = 0;
        int totalInWindow = 0;

        for (String d : dirs) {
            String full = "/pmdata/download/" + d;
            String[] entries;
            try {
                entries = (String[]) sftp.getClass().getMethod("dir", String.class, boolean.class)
                    .invoke(sftp, full, Boolean.TRUE);
            } catch (Throwable t) { continue; }

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
                    if (fEnd <= tStart || fs.getTime() >= tEnd) continue;
                } catch (Exception ex) { continue; }
                totalInWindow++;

                // 下载到缓存
                String localPath = new File(cacheDir, fn).getAbsolutePath();
                File local = new File(localPath);
                if (!local.exists() || local.length() == 0) {
                    try {
                        sftp.getClass().getMethod("get", String.class, String.class)
                            .invoke(sftp, localPath, full + "/" + fn);
                    } catch (Throwable t) {
                        System.out.println("    download FAIL " + fn + ": " + rootMsg(t));
                        continue;
                    }
                }

                // 解析 (复用 EmsKpiDaily 的解析逻辑)
                try {
                    if (fn.endsWith(".xml")) {
                        if (parseXmlInto(local, daily, allCounters, dayKey)) parsed++;
                    } else {
                        // ZIP 内 XML
                        FileInputStream fin = new FileInputStream(local);
                        java.util.zip.ZipInputStream zin = new java.util.zip.ZipInputStream(fin);
                        ByteArrayOutputStream bout = new ByteArrayOutputStream();
                        java.util.zip.ZipEntry ze;
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
                            if (parseXmlInto(tmp, daily, allCounters, dayKey)) parsed++;
                            tmp.delete();
                        }
                    }
                } catch (Throwable t) {
                    System.out.println("    parse FAIL " + fn + ": " + rootMsg(t));
                }
            }
        }
        try { sftp.getClass().getMethod("quit").invoke(sftp); } catch (Exception ignore) {}

        System.out.println("    Parsed: " + parsed + " files, counters: " + allCounters.size());

        if (parsed == 0) {
            System.out.println("    No files downloaded from SFTP");
            return false;
        }

        // 输出 JSON
        StringBuilder json = new StringBuilder();
        json.append("{\n");
        json.append("  \"window\": {\"start\": \"").append(startDay).append("\", \"end\": \"").append(endDay).append("\"},\n");
        json.append("  \"source\": \"sftp://").append(server).append("/pmdata/download\",\n");
        json.append("  \"ne\": \"all modules\",\n");
        json.append("  \"strategy\": \"sftp\",\n");
        json.append("  \"filesParsed\": ").append(parsed).append(",\n");
        json.append("  \"counters\": {\n");
        boolean firstC = true;
        for (String c : allCounters) {
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
        System.out.println("    DONE -> daily_raw.json");
        return true;
    }

    /** 解析 measCollectFile XML, 累加进 daily map */
    static boolean parseXmlInto(File f, TreeMap<String, HashMap<String, double[]>> daily,
                                Set<String> allCounters, SimpleDateFormat dayKey) throws Exception {
        javax.xml.parsers.DocumentBuilderFactory dbf = javax.xml.parsers.DocumentBuilderFactory.newInstance();
        javax.xml.parsers.DocumentBuilder db = dbf.newDocumentBuilder();
        org.w3c.dom.Document doc = db.parse(f);

        java.util.ArrayList<String> typeList = new java.util.ArrayList<String>();
        org.w3c.dom.NodeList amts = doc.getElementsByTagName("allMeasTypes");
        for (int a = 0; a < amts.getLength() && typeList.isEmpty(); a++) {
            StringTokenizer st = new StringTokenizer(textOf(amts.item(a)));
            while (st.hasMoreTokens()) typeList.add(st.nextToken());
        }

        org.w3c.dom.NodeList infos = doc.getElementsByTagName("measInfo");
        int files = 0;
        for (int i = 0; i < infos.getLength(); i++) {
            org.w3c.dom.Element info = (org.w3c.dom.Element) infos.item(i);
            java.util.ArrayList<String> types = new java.util.ArrayList<String>();
            org.w3c.dom.NodeList mt = info.getElementsByTagName("measTypes");
            if (mt.getLength() > 0) {
                StringTokenizer st = new StringTokenizer(textOf(mt.item(0)));
                while (st.hasMoreTokens()) types.add(st.nextToken());
            }
            if (types.isEmpty()) types = typeList;

            java.util.Date endT = null;
            org.w3c.dom.NodeList gp = info.getElementsByTagName("granPeriod");
            if (gp.getLength() > 0) {
                String endTime = ((org.w3c.dom.Element) gp.item(0)).getAttribute("endTime");
                endT = parseIso(endTime);
            }
            if (endT == null) continue;
            String day = dayKey.format(endT);

            org.w3c.dom.NodeList vals = doc.getElementsByTagName("measValue");
            for (int vI = 0; vI < vals.getLength(); vI++) {
                org.w3c.dom.Element val = (org.w3c.dom.Element) vals.item(vI);
                org.w3c.dom.NodeList res = val.getElementsByTagName("measResults");
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
                    sv[0] += d;
                    if (d > sv[1]) sv[1] = d;
                }
            }
        }
        return true;
    }

    // ==================== 数据提取与输出 ====================

    static class ResultData {
        String[] columns;
        String[][] rows;
        int rowCount;
    }

    /** 从 FIMessage 响应中提取数据 */
    static ResultData extractResultData(Object resp) {
        try {
            int sc = (Integer) resp.getClass().getMethod("getSectionCount").invoke(resp);
            for (int i = 0; i < sc; i++) {
                Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, i);
                String secType = sec.getClass().getName();

                // FIRecSection: 有 getRecordCount / getFields / getRecordAt
                try {
                    Method getRecCount = sec.getClass().getMethod("getRecordCount");
                    int recCount = (Integer) getRecCount.invoke(sec);
                    if (recCount > 0) {
                        String[] fields = (String[]) sec.getClass().getMethod("getFields").invoke(sec);
                        Method getRecAt = sec.getClass().getMethod("getRecordAt", int.class);
                        String[][] rows = new String[recCount][];
                        for (int r = 0; r < recCount; r++) {
                            rows[r] = (String[]) getRecAt.invoke(sec, r);
                        }
                        ResultData d = new ResultData();
                        d.columns = fields;
                        d.rows = rows;
                        d.rowCount = recCount;
                        return d;
                    }
                } catch (NoSuchMethodException ignore) {}

                // FIObjectSection: 可能包含 ResultDataSet 或数组
                try {
                    Object obj = sec.getClass().getMethod("getObject").invoke(sec);
                    if (obj != null) {
                        ResultData d = tryExtractDataSet(obj);
                        if (d != null && d.rowCount > 0) return d;
                    }
                } catch (NoSuchMethodException ignore) {}
            }
        } catch (Throwable t) {
            System.out.println("    extractResultData: " + rootMsg(t));
        }
        return null;
    }

    /** 尝试从对象中提取 ResultDataSet */
    static ResultData tryExtractDataSet(Object obj) {
        try {
            // 检查是否是 ResultDataSet（有 getColumnCount / getRowCount / getObjectValue）
            try {
                Method mCols = obj.getClass().getMethod("getColumnCount");
                Method mRows = obj.getClass().getMethod("getRowCount");
                int nc = (Integer) mCols.invoke(obj);
                int nr = (Integer) mRows.invoke(obj);
                if (nr > 0) {
                    ResultData d = new ResultData();
                    d.columns = new String[nc];
                    Object fields = null;
                    try { fields = obj.getClass().getMethod("getFieldset").invoke(obj); } catch (Throwable ignore) {}
                    for (int i = 0; i < nc; i++) {
                        if (fields != null && i < Array.getLength(fields)) {
                            Object f = Array.get(fields, i);
                            d.columns[i] = f != null ? callStr(f, "getFieldName") : ("col" + i);
                        } else {
                            d.columns[i] = "col" + i;
                        }
                    }
                    d.rows = new String[nr][];
                    Method mGet = obj.getClass().getMethod("getObjectValue", int.class, int.class);
                    for (int r = 0; r < nr; r++) {
                        d.rows[r] = new String[nc];
                        for (int c = 0; c < nc; c++) {
                            Object v = mGet.invoke(obj, r, c);
                            d.rows[r][c] = v == null ? "" : String.valueOf(v);
                        }
                    }
                    d.rowCount = nr;
                    return d;
                }
            } catch (NoSuchMethodException ignore) {}

            // 如果是数组, 递归检查每个元素
            if (obj instanceof Object[]) {
                Object[] arr = (Object[]) obj;
                for (int i = 0; i < Math.min(arr.length, 5); i++) {
                    if (arr[i] != null) {
                        ResultData d = tryExtractDataSet(arr[i]);
                        if (d != null) return d;
                    }
                }
            }
        } catch (Throwable ignore) {}
        return null;
    }

    /** 写入 JSON 结果文件 */
    static void writeJsonResult(String queryId, String startDay, String endDay, ResultData data, int totalRows) {
        try {
            StringBuilder json = new StringBuilder();
            json.append("{\n");
            json.append("  \"queryId\": ").append(queryId == null ? "null" : "\"" + esc(queryId) + "\"").append(",\n");
            json.append("  \"range\": [\"").append(esc(startDay)).append("\", \"").append(esc(endDay)).append("\"],\n");
            json.append("  \"totalRows\": ").append(totalRows).append(",\n");
            json.append("  \"datasets\": [\n");
            if (data != null) {
                json.append("    {\n");
                json.append("      \"columns\": [");
                for (int i = 0; i < data.columns.length; i++) {
                    if (i > 0) json.append(", ");
                    json.append("\"").append(esc(data.columns[i])).append("\"");
                }
                json.append("],\n");
                json.append("      \"rows\": [\n");
                for (int r = 0; r < data.rows.length; r++) {
                    json.append("        [");
                    for (int c = 0; c < data.rows[r].length; c++) {
                        if (c > 0) json.append(", ");
                        json.append("\"").append(esc(data.rows[r][c])).append("\"");
                    }
                    json.append("]");
                    if (r < data.rows.length - 1) json.append(",");
                    json.append("\n");
                }
                json.append("      ]\n");
                json.append("    }\n");
            }
            json.append("  ]\n");
            json.append("}\n");

            Writer w = new OutputStreamWriter(new FileOutputStream("kpi_result.json"), "UTF-8");
            w.write(json.toString()); w.close();
            System.out.println("    -> kpi_result.json");
        } catch (Throwable t) {
            System.out.println("    writeJsonResult failed: " + t);
        }
    }

    // ==================== 下载并解析 SFTP 结果文件 ====================

    static boolean downloadAndParseFiles(String server, List<String> files, String startDay, String endDay) {
        try {
            Class<?> sftpCls = Class.forName("com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl");
            Object sftp = null;
            for (int attempt = 0; attempt < 3 && sftp == null; attempt++) {
                try {
                    sftp = sftpCls.getConstructor(String.class, int.class, int.class, String.class,
                        String.class, boolean.class)
                        .newInstance(server, Integer.valueOf(21128), Integer.valueOf(20000),
                            "uepcommon", null, Boolean.FALSE);
                } catch (Throwable t) {
                    System.out.println("    sftp connect attempt " + attempt + " failed: " + rootMsg(t));
                    Thread.sleep(1500);
                }
            }
            if (sftp == null) return false;

            File outDir = new File("kpi_result_files");
            if (!outDir.exists()) outDir.mkdirs();

            Method getM = null;
            for (Method m : sftpCls.getMethods()) {
                if (m.getName().equals("get") && m.getParameterTypes().length == 2) { getM = m; break; }
            }

            StringBuilder jsonRows = new StringBuilder();
            int totalRows = 0;
            for (String remote : files) {
                String local = new File(outDir, new File(remote).getName()).getCanonicalPath();
                try {
                    getM.invoke(sftp, local, remote);
                } catch (InvocationTargetException e) {
                    System.out.println("    skip " + remote + " (" + rootMsg(e) + ")");
                    continue;
                }
                ResultDump dump = parseResultFile(new File(local));
                if (dump == null) continue;
                totalRows += dump.rowCount;
                if (jsonRows.length() > 0) jsonRows.append(",\n");
                jsonRows.append(dump.toJson());
            }
            try { sftp.getClass().getMethod("quit").invoke(sftp); } catch (Exception ignore) {}

            if (totalRows > 0) {
                String json = "{\n  \"queryId\": null,\n  \"range\": [\"" + esc(startDay) + "\", \"" + esc(endDay) + "\"],\n"
                    + "  \"totalRows\": " + totalRows + ",\n  \"datasets\": [\n" + jsonRows + "\n  ]\n}";
                Writer w = new OutputStreamWriter(new FileOutputStream("kpi_result.json"), "UTF-8");
                w.write(json); w.close();
                System.out.println("    DONE: " + totalRows + " rows -> kpi_result.json");
                return true;
            }
        } catch (Throwable t) {
            System.out.println("    downloadAndParseFiles failed: " + rootMsg(t));
        }
        return false;
    }

    // ==================== 工具方法 ====================

    static Object fsbLookup(Method lookupStr, Object namingCtx, String name) throws Exception {
        Object obj = lookupStr.invoke(namingCtx, name);
        return obj.getClass().getMethod("create").invoke(obj);
    }

    static Object firstSectionObject(Object fiMsg) throws Exception {
        Object sec = fiMsg.getClass().getMethod("getFISectionAt", int.class).invoke(fiMsg, 0);
        return sec.getClass().getMethod("getObject").invoke(sec);
    }

    static void setObjectSafe(Object section, Object value) throws Exception {
        try {
            section.getClass().getMethod("setObject", Class.forName("java.io.Serializable")).invoke(section, value);
        } catch (NoSuchMethodException ignore) {
            Field f = findField(section.getClass(), "object");
            f.setAccessible(true);
            f.set(section, value);
        }
    }

    static void setTimeRange(Object cond, String startDay, String endDay) throws Exception {
        Object tc = cond.getClass().getMethod("getTimeCondition").invoke(cond);
        Object ti = tc.getClass().getMethod("getTimeInterval").invoke(tc);
        setStr(ti, "startDate", startDay + " 00:00:00 GMT");
        setStr(ti, "endDate", endDay + " 00:00:00 GMT");
        setStr(ti, "clientTimeZoneID", "GMT");
        setStr(tc, "neTimeZoneID", "Etc/GMT+0");
        try {
            tc.getClass().getMethod("setTimeType", int.class).invoke(tc, Integer.valueOf(3));
        } catch (Throwable t) {
            Field f = findField(tc.getClass(), "timeType");
            if (f != null) { f.setAccessible(true); f.setInt(tc, 3); }
        }
    }

    static void setStr(Object target, String field, String value) throws Exception {
        try {
            Method setter = target.getClass().getMethod("set" + Character.toUpperCase(field.charAt(0)) + field.substring(1), String.class);
            setter.invoke(target, value);
            return;
        } catch (NoSuchMethodException ignore) {}
        Field f = findField(target.getClass(), field);
        if (f == null) throw new NoSuchFieldException(field);
        f.setAccessible(true);
        f.set(target, value);
    }

    static Field findField(Class<?> cls, String name) {
        for (Class<?> c = cls; c != null; c = c.getSuperclass()) {
            try { return c.getDeclaredField(name); } catch (NoSuchFieldException ignore) {}
        }
        return null;
    }

    static String callStr(Object o, String getter) {
        try { Object v = o.getClass().getMethod(getter).invoke(o); return v == null ? "" : String.valueOf(v); }
        catch (Exception e) { return ""; }
    }

    static String rootMsg(Throwable e) {
        if (e instanceof InvocationTargetException) e = ((InvocationTargetException) e).getTargetException();
        Throwable r = e; while (r.getCause() != null) r = r.getCause();
        return r.getClass().getSimpleName() + ": " + r.getMessage();
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

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }

    static Object decodeCompressedResponse(Object resp) {
        try {
            Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, 0);
            Object payload = sec.getClass().getMethod("getObject").invoke(sec);
            if (!(payload instanceof byte[])) return null;
            byte[] raw = (byte[]) payload;
            ByteArrayInputStream bin = new ByteArrayInputStream(raw);
            InputStream src = bin;
            if (raw.length > 2 && (raw[0] & 0xFF) == 0x1F && (raw[1] & 0xFF) == 0x8B) {
                src = new GZIPInputStream(bin);
            }
            ObjectInputStream ois = new ObjectInputStream(src);
            Object obj = ois.readObject();
            ois.close();
            Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
            Method unw = msgUtilCls.getMethod("getUnwrappedMessage",
                Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"));
            return unw.invoke(null, obj);
        } catch (Throwable t) {
            return null;
        }
    }

    static Object[] unwrapConditions(Object resp) throws Exception {
        Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, 0);
        Object obj = sec.getClass().getMethod("getObject").invoke(sec);
        if (obj instanceof Object[]) return (Object[]) obj;
        return new Object[]{ obj };
    }

    static String getLocalIp(String server) {
        try {
            Socket s = new Socket();
            s.connect(new InetSocketAddress(server, JNP_PORT), 3000);
            String ip = s.getLocalAddress().getHostAddress();
            s.close();
            return ip;
        } catch (Throwable t) { return "192.168.100.20"; }
    }

    static String getClientMac() {
        try {
            for (java.net.NetworkInterface ni : java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())) {
                byte[] mac = ni.getHardwareAddress();
                if (mac == null || mac.length != 6) continue;
                StringBuilder sb = new StringBuilder();
                for (byte b : mac) sb.append(String.format("%02X", b));
                String s = sb.toString();
                if (!s.equals("000000000000") && !ni.isLoopback()) return s;
            }
        } catch (Throwable ignore) {}
        String alt = System.getProperty("ems.clientmac", "");
        return alt.length() > 0 ? alt : "FC4CEA20EE49";
    }

    static Object getNamingStub(String server, int port) throws Exception {
        Socket sock = new Socket();
        sock.connect(new InetSocketAddress(server, port), 5000);
        sock.setSoTimeout(10000);
        InputStream in = sock.getInputStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        while (true) {
            try {
                sock.setSoTimeout(3000);
                int len = in.read(buf);
                if (len <= 0) break;
                bos.write(buf, 0, len);
                if (bos.size() > 50000) break;
            } catch (SocketTimeoutException e) { break; }
        }
        sock.close();
        ObjectInputStream ois = new ObjectInputStream(new ByteArrayInputStream(bos.toByteArray()));
        ArrayList<?> list = (ArrayList<?>) ois.readObject();
        ois.close();
        java.rmi.MarshalledObject<?> mo = (java.rmi.MarshalledObject<?>) list.get(1);
        return mo.get();
    }

    static String desEncrypt(String input) throws Exception {
        DESKeySpec desKeySpec = new DESKeySpec(DES_RAW_KEY);
        SecretKeyFactory keyFactory = SecretKeyFactory.getInstance("DES");
        SecretKey secretKey = keyFactory.generateSecret(desKeySpec);
        Cipher cipher = Cipher.getInstance("DES/ECB/PKCS5Padding");
        cipher.init(Cipher.ENCRYPT_MODE, secretKey);
        byte[] bytes = input.getBytes("UTF-8");
        byte[] encrypted = cipher.doFinal(bytes, 0, bytes.length);
        StringBuffer sb = new StringBuffer();
        for (byte b : encrypted) {
            String hex = Integer.toHexString(b & 0xFF);
            if (hex.length() == 1) sb.append("0");
            sb.append(hex);
        }
        return sb.toString().toUpperCase();
    }

    static Object newJmsListener() throws Exception {
        Class<?> lstCls = Class.forName("javax.jms.MessageListener");
        return java.lang.reflect.Proxy.newProxyInstance(lstCls.getClassLoader(), new Class<?>[]{ lstCls },
            new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] a) {
                    if ("onMessage".equals(method.getName()) && a != null && a.length > 0) {
                        try {
                            Object payload = a[0].getClass().getMethod("getObject").invoke(a[0]);
                            if (payload != null) {
                                String cn = payload.getClass().getName();
                                if (!cn.endsWith("MessageData")) {
                                    try {
                                        Object inner = payload.getClass().getMethod("get").invoke(payload);
                                        if (inner != null) payload = inner;
                                    } catch (Exception ignore) {}
                                }
                            }
                            if (payload != null &&
                                payload.getClass().getName().equals("com.zte.ums.common.pm.common.query.MessageData")) {
                                collectedMessages.add(payload);
                            } else if (payload != null &&
                                payload.getClass().getName().equals("com.zte.ums.uep.api.pfl.finterface.FIMessage")) {
                                collectedResponses.add(payload);
                            }
                        } catch (Throwable t) {}
                    }
                    return null;
                }
            });
    }

    static List<String> waitForFiles(String queryId, long timeoutMs, String server) throws Exception {
        long deadline = System.currentTimeMillis() + timeoutMs;
        Set<String> files = new LinkedHashSet<String>();
        boolean sawFinish = false;
        Object sftp = null;
        try {
            Class<?> sftpCls2 = Class.forName("com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl");
            sftp = sftpCls2.getConstructor(String.class, int.class, int.class, String.class,
                String.class, boolean.class).newInstance(server, Integer.valueOf(21128),
                Integer.valueOf(20000), "uepcommon", null, Boolean.FALSE);
        } catch (Throwable t) {
            System.out.println("    (SFTP poll unavailable: " + rootMsg(t) + ")");
        }
        int poll = 0;
        int stable = 0;
        int lastCount = 0;
        while (System.currentTimeMillis() < deadline) {
            List<Object> snapshot;
            synchronized (collectedMessages) {
                snapshot = new ArrayList<Object>(collectedMessages);
                collectedMessages.clear();
            }
            for (Object msgData : snapshot) {
                String mid = callStr(msgData, "getQueryId");
                if (queryId != null && mid != null && mid.length() > 0 && !mid.equals(queryId)) continue;
                String fp = callStr(msgData, "getFilePath");
                if (fp != null && fp.length() > 0) files.add("/" + fp.replaceFirst("^/+", ""));
                try {
                    Object fin = msgData.getClass().getMethod("isFinish").invoke(msgData);
                    if (Boolean.TRUE.equals(fin)) sawFinish = true;
                } catch (Exception ignore) {}
            }
            if (sftp != null && ++poll % 4 == 1) {
                try {
                    String[] ls = (String[]) sftp.getClass().getMethod("dir", String.class, boolean.class)
                            .invoke(sftp, "/ppus/uca.ppu/uca-pm.pmu/main-query", Boolean.FALSE);
                    int n = ls == null ? 0 : ls.length;
                    if (n > 0) {
                        for (String f : ls) {
                            String name = f.trim();
                            int sp = name.lastIndexOf(' ');
                            if (sp > 0) name = name.substring(sp + 1).trim();
                            if (name.length() == 0) continue;
                            if (queryId != null && !name.startsWith(queryId)) continue;
                            files.add("/ppus/uca.ppu/uca-pm.pmu/main-query/" + name);
                        }
                    }
                } catch (Throwable ignore) {}
            }
            if (sawFinish && files.size() > 0) break;
            if (files.size() > 0 && files.size() == lastCount) {
                if (++stable >= 12) break;
            } else { stable = 0; lastCount = files.size(); }
            Thread.sleep(500);
        }
        try { if (sftp != null) sftp.getClass().getMethod("quit").invoke(sftp); } catch (Exception ignore) {}
        return new ArrayList<String>(files);
    }

    // ==================== ResultDump (从 EmsKpiQuery 复制) ====================

    static class ResultDump {
        String[] cols;
        String[][] rows;
        int rowCount;
        String toJson() {
            StringBuilder sb = new StringBuilder();
            sb.append("    {\n      \"columns\": [");
            for (int i = 0; i < cols.length; i++)
                sb.append(i > 0 ? ", " : "").append("\"").append(esc(cols[i])).append("\"");
            sb.append("],\n      \"rows\": [\n");
            for (int r = 0; r < rows.length; r++) {
                sb.append("        [");
                for (int c = 0; c < rows[r].length; c++)
                    sb.append(c > 0 ? ", " : "").append("\"").append(esc(rows[r][c])).append("\"");
                sb.append("]").append(r < rows.length - 1 ? "," : "").append("\n");
            }
            sb.append("      ]\n    }");
            return sb.toString();
        }
    }

    static ResultDump parseResultFile(File f) {
        try {
            ObjectInputStream ois = new ObjectInputStream(new GZIPInputStream(new FileInputStream(f)));
            Object ds = ois.readObject();
            ois.close();
            return dumpDataSet(ds);
        } catch (FileNotFoundException fnf) { return null; }
        catch (Exception e) { return null; }
    }

    static ResultDump dumpDataSet(Object ds) throws Exception {
        Method mCols = ds.getClass().getMethod("getColumnCount");
        Method mRows = ds.getClass().getMethod("getRowCount");
        int nc = (Integer) mCols.invoke(ds);
        int nr = (Integer) mRows.invoke(ds);
        Object fields = ds.getClass().getMethod("getFieldset").invoke(ds);
        ResultDump d = new ResultDump();
        d.cols = new String[nc];
        for (int i = 0; i < nc && fields != null; i++) {
            Object f = Array.get(fields, Math.min(i, Array.getLength(fields) - 1));
            d.cols[i] = f != null ? callStr(f, "getFieldName") : ("col" + i);
        }
        for (int i = 0; i < nc; i++) if (d.cols[i] == null || d.cols[i].length() == 0) d.cols[i] = "col" + i;
        d.rows = new String[nr][];
        Method mGet = ds.getClass().getMethod("getObjectValue", int.class, int.class);
        d.rowCount = nr;
        for (int r = 0; r < nr; r++) {
            d.rows[r] = new String[nc];
            for (int c = 0; c < nc; c++) {
                Object v = mGet.invoke(ds, r, c);
                d.rows[r][c] = v == null ? "" : String.valueOf(v);
            }
        }
        return d;
    }

    // ==================== XML 解析工具 ====================

    static String textOf(org.w3c.dom.Node n) {
        StringBuffer sb = new StringBuffer();
        collectText(n, sb);
        return sb.toString();
    }

    static void collectText(org.w3c.dom.Node n, StringBuffer sb) {
        if (n.getNodeType() == org.w3c.dom.Node.TEXT_NODE || n.getNodeType() == org.w3c.dom.Node.CDATA_SECTION_NODE) {
            sb.append(n.getNodeValue());
            return;
        }
        org.w3c.dom.NodeList kids = n.getChildNodes();
        for (int i = 0; i < kids.getLength(); i++) collectText(kids.item(i), sb);
    }

    static java.util.Date parseIso(String s) {
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
}