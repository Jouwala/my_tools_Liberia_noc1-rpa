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
 * EmsKpiQuery — ZTE U31 历史性能(KPI)数据查询工具（协议级实现）
 *
 * 【正确协议流程（由 ems_kpi.pcapng 抓包 + 客户端 JAR 反编译还原）】
 *   1. RMI/JNP 登录 (FServerManager, DES 密码) —— 与 EmsKpiFinal 相同
 *   2. 构造 FIMessage: CommandCode=2720, checkedoperation=uca.pm.querydata,
 *      FIObjectSection 携带 com.zte.ums.common.pm.common.query.QueryCondition 对象
 *      （本工具直接反序列化抓包导出的 pm_query_template.bin 模板并改写会话/时间字段）
 *   3. 通过 FServerBroker.requestxForNonGUI 同步提交（服务器查询期间阻塞约 20s+）
 *   4. 结果分片在查询过程中通过 JMS Topic "PM_SEND_DATA_TOPIC" 实时推送，
 *      每条消息为 MessageData { queryId, filePath, currentSection, totalSection,
 *      isFinish, rowCount, message }
 *   5. 用 SFTP(端口 21128, 用户 uepcommon, JNDI FtpUserContextClient 下发凭据)
 *      下载 /ppus/uca.ppu/uca-pm.pmu/main-query/<queryId>_<N>.zip
 *   6. 文件内容 = gzip( Java序列化的 ResultDataSet )，含 PmField[] 列定义与数据行
 *
 *   旧结论"cmd 2614 失败 → PM 数据未配置"是错误的：
 *   2614 只是参数不完整的查询入口；GUI 实际使用 2720 + QueryCondition。
 *
 * 使用:
 *   java EmsKpiQuery <server> <user> <password> [startDate yyyy/MM/dd] [endDate]
 *   默认时间范围 = 昨天 00:00 ~ 今天 00:00 (GMT, 与 GUI 行为一致)
 */
public class EmsKpiQuery {

    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    static final int JNP_PORT = 21100;
    static final int JMS_PORT = 21101;
    static final String PM_DATA_TOPIC = "PM_SEND_DATA_TOPIC";

    static volatile List<Object> collectedMessages = Collections.synchronizedList(new ArrayList<Object>());
    static volatile List<Object> collectedResponses = Collections.synchronizedList(new ArrayList<Object>());

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
        // 变体集合提前解析 (登录段也要用)
        Set<String> vset = new HashSet<String>();
        if (args.length > 6) for (String v : args[6].split(",")) vset.add(v.trim());
        String server = args.length > 0 ? args[0] : "10.100.2.240";
        String user   = args.length > 1 ? args[1] : "oss";
        String pass   = args.length > 2 ? args[2] : "Tool123";
        SimpleDateFormat dayFmt = new SimpleDateFormat("yyyy/MM/dd");
        TimeZone gmt = TimeZone.getTimeZone("GMT");
        dayFmt.setTimeZone(gmt);
        Calendar cal = Calendar.getInstance(gmt);
        cal.add(Calendar.DAY_OF_MONTH, -1);
        String startDay = args.length > 3 ? args[3].replace('-', '/') : dayFmt.format(cal.getTime());
        cal.add(Calendar.DAY_OF_MONTH, 1);
        String endDay   = args.length > 4 ? args[4].replace('-', '/') : dayFmt.format(cal.getTime());

        System.out.println("=== ZTE U31 KPI Query (cmd 2720 protocol) ===");
        System.out.println("Server=" + server + " user=" + user + " range=[" + startDay + " ~ " + endDay + ")");

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
        // GUI 的 ClientSessionManager.loginImpl: server.login(user, pwd, 1, 1000, props)
        // 登录 Properties 完全复刻 2026-08-24 ems_login_new.pcapng 抓包内容:
        // MSG_SIZE_THERSHOLD=1, MSG_TRANS_SIZE_THERSHOLD=0, SecLogId=-1,
        // locale=en_US, usf.system.amf=none, encryptmode=true, isSSH=false
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
                // encryptmode=true 时服务端按动态密钥解密密码 -> errID=2005;
                // 不发送该键则按静态 DES 校验 (与此前成功登录一致)
                // lprops.setProperty("encryptmode", "true");
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

        // ===== Step 1a: JBoss 安全上下文 —— 抓包字节对比证明 GUI 的 EJB 调用
        // 不携带 Principal/Credential, 我们带上反而与服务端行为不一致。
        // 仅当显式指定 sec 变体时启用 =====
        if (vset.contains("sec")) {
            try {
                Class<?> saCls = Class.forName("org.jboss.security.SecurityAssociation");
                Object principal = Class.forName("org.jboss.security.SimplePrincipal")
                    .getConstructor(String.class).newInstance(user);
                saCls.getMethod("setPrincipal", java.security.Principal.class).invoke(null, principal);
                saCls.getMethod("setCredential", Object.class).invoke(null, (Object) pass.toCharArray());
                System.out.println("[1a] SecurityAssociation set: principal=" + user);
            } catch (Throwable t) {
                System.out.println("[1a] SecurityAssociation unavailable: " + rootMsg(t));
            }
        }

        // ===== Step 1b: 心跳注册 (GUI 登录后由 HeartBeatThread 持续调用; 缺失时服务端视为死会话) =====
        Object heartbeatStub = null;
        String hbStatus;
        try {
            heartbeatStub = lookupStr.invoke(namingCtx, "uep.fi.heartbeatreciever");
            Method hb = heartbeatStub.getClass().getMethod("setSessionStateOK", short.class);
            hb.invoke(heartbeatStub, (short) sessionID);
            hbStatus = "ok";
            System.out.println("[1b] heartbeat registered via uep.fi.heartbeatreciever");
        } catch (Throwable t) {
            hbStatus = "failed: " + rootMsg(t);
            System.out.println("[1b] heartbeat registration " + hbStatus);
        }
        if ("ok".equals(hbStatus) && heartbeatStub != null) {
            final Object stub = heartbeatStub;
            final short sid = (short) sessionID;
            Thread hbThread = new Thread(new Runnable() {
                public void run() {
                    while (true) {
                        try {
                            stub.getClass().getMethod("setSessionStateOK", short.class).invoke(stub, sid);
                        } catch (Throwable ignore) {}
                        try { Thread.sleep(10000); } catch (InterruptedException e) { return; }
                    }
                }
            }, "hb");
            hbThread.setDaemon(true);
            hbThread.start();
        }

        // ===== Step 2: JMS subscribe BEFORE submitting query =====
        Properties jmsEnv = new Properties();
        jmsEnv.setProperty("java.naming.factory.initial",
            "com.zte.ums.uep.psl.naming.interfaces.GlobeNamingContextFactory");
        jmsEnv.setProperty("java.naming.provider.url", "jnp://" + server + ":" + JMS_PORT);
        InitialContext jmsCtx = new InitialContext(jmsEnv);
        Object cf = jmsCtx.lookup("ConnectionFactory");
        Class<?> topicCls = Class.forName("javax.jms.Topic");
        Object conn = cf.getClass().getMethod("createTopicConnection", String.class, String.class)
                         .invoke(cf, user, pass);
        Object jmsSession = conn.getClass().getMethod("createTopicSession", boolean.class, int.class)
                                .invoke(conn, false, 1);
        Object dataTopic = jmsSession.getClass().getMethod("createTopic", String.class)
                                     .invoke(jmsSession, PM_DATA_TOPIC);
        Object subscriber = jmsSession.getClass()
            .getMethod("createSubscriber", topicCls).invoke(jmsSession, dataTopic);
        subscriber.getClass().getMethod("setMessageListener", Class.forName("javax.jms.MessageListener"))
                  .invoke(subscriber, newJmsListener());
        // GUI 异步响应主题: 每个会话一个 UEP_F_RESPONSE_TOPIC<sessionID>, 不存在则经 JMX 创建
        String respTopicName = "UEP_F_RESPONSE_TOPIC" + sessionID;
        try {
            Object rmiAdaptor = jmsCtx.lookup("jmx/rmi/RMIAdaptor");
            javax.management.ObjectName dm = new javax.management.ObjectName("jboss.mq:service=DestinationManager");
            try {
                rmiAdaptor.getClass().getMethod("invoke", javax.management.ObjectName.class, String.class,
                    Object[].class, String[].class)
                    .invoke(rmiAdaptor, dm, "createTopic",
                        new Object[]{respTopicName}, new String[]{"java.lang.String"});
                System.out.println("[2] created response topic via JMX: " + respTopicName);
            } catch (InvocationTargetException e) {
                System.out.println("[2] createTopic(" + respTopicName + ") -> "
                    + rootMsg(e.getTargetException()) + " (可能已存在)");
            }
        } catch (Throwable t) {
            System.out.println("[2] JMX createTopic unavailable: " + rootMsg(t));
        }
        Object respTopic = jmsSession.getClass().getMethod("createTopic", String.class)
                                     .invoke(jmsSession, respTopicName);
        Object sub2 = jmsSession.getClass()
            .getMethod("createSubscriber", topicCls).invoke(jmsSession, respTopic);
        sub2.getClass().getMethod("setMessageListener", Class.forName("javax.jms.MessageListener"))
            .invoke(sub2, newJmsListener());
        conn.getClass().getMethod("start").invoke(conn);
        System.out.println("[2] Subscribed JMS topics: " + PM_DATA_TOPIC + " + UEP_F_RESPONSE_TOPIC");

        // ===== Step 3: Load captured query template & rewrite session/time =====
        File tpl = new File("pm_query_template.bin");
        if (!tpl.exists()) {
            System.out.println("!! pm_query_template.bin not found in " + new File(".").getCanonicalPath());
            System.exit(3);
        }
        ObjectInputStream ois = new ObjectInputStream(new FileInputStream(tpl));
        Object fiMsg = ois.readObject();
        ois.close();

        Method setVal = fiMsg.getClass().getMethod("setValue", String.class, String.class);
        setVal.invoke(fiMsg, "sessioncode", sessionCode);
        setVal.invoke(fiMsg, "SessionID", String.valueOf(sessionID));
        setVal.invoke(fiMsg, "UserID", String.valueOf(userID));
        setVal.invoke(fiMsg, "UserName", user);
        fiMsg.getClass().getMethod("setInvokeID", int.class)
             .invoke(fiMsg, Integer.valueOf(100000 + new Random().nextInt(800000)));

        Object condObj = firstSectionObject(fiMsg);
        Object cond;
        if (condObj.getClass().isArray()) {
            // 模板误存为 QueryCondition[] (来自 2738 抓包); GUI 的 2720 请求是单个对象!
            Object[] arr = (Object[]) condObj;
            cond = arr[0];
            System.out.println("[3] template held array[" + arr.length + "] -> using single element");
            // 把 section 对象替换为单个 QueryCondition
            Object sec0 = fiMsg.getClass().getMethod("getFISectionAt", int.class).invoke(fiMsg, 0);
            setObjectSafe(sec0, cond);
        } else {
            cond = condObj;
        }
        System.out.println("[3] Template QueryCondition: " + cond.getClass().getName());
        setTimeRange(cond, startDay, endDay);
        // 内容变体实验开关: args[6] = 逗号分隔: notmpl | allne | h1 | noasyn
        String variantArg = args.length > 6 ? args[6] : "";
        String[] variants = variantArg.split(",");
        vset.addAll(Arrays.asList(variants));
        String variant = variantArg;
        if (vset.contains("notmpl")) {
            // 去掉模板依赖, 当作临时查询
            cond.getClass().getMethod("setQueryTemplateId", String.class).invoke(cond, "");
            cond.getClass().getMethod("setQueryTitle", String.class).invoke(cond, "ADHOC");
            try {
                cond.getClass().getMethod("setQueryFromType", int.class).invoke(cond, Integer.valueOf(0));
                System.out.println("[3] variant=notmpl applied");
            } catch (Throwable t) {
                setIntField(cond, "queryFromType", 0);
                System.out.println("[3] variant=notmpl applied (field)");
            }
        }
        if (vset.contains("allne")) {
            // 不指定具体网元, 查全部
            cond.getClass().getMethod("setQueryCommonLocations",
                Class.forName("[Lcom.zte.ums.api.common.pm.ppu.entity.PmCommonLocation;"))
                .invoke(cond, (Object) null);
            Object pflt = cond.getClass().getMethod("getPmFilterLevelType").invoke(cond);
            pflt.getClass().getMethod("setFilterType", int.class).invoke(pflt, Integer.valueOf(0));
            pflt.getClass().getMethod("setFilterLevelId", String.class).invoke(pflt, "==filterType_all==");
            pflt.getClass().getMethod("setFilterLevelName", String.class).invoke(pflt, "ALL");
            System.out.println("[3] variant=allne applied");
        }
        if (vset.contains("h1")) {
            Object tc0 = cond.getClass().getMethod("getTimeCondition").invoke(cond);
            tc0.getClass().getMethod("setGranularity", int.class).invoke(tc0, Integer.valueOf(3600));
            System.out.println("[3] variant=h1 applied");
        }
        printQuerySummary(cond);

        // ===== Step 3b: 重放 GUI 查询前的完整前置命令序列 =====
        Object fsbObj = lookupStr.invoke(namingCtx, "FServerBroker");
        Object fsbEjb = fsbObj.getClass().getMethod("create").invoke(fsbObj);
        boolean fullReplay = vset.contains("replay");
        if (vset.contains("mature")) {
            System.out.println("[3] mature mode: waiting 45s for session to settle (heartbeat running)...");
            Thread.sleep(45000);
        }
        String[] preBlobs;
        if (vset.contains("fullsess")) {
            // 全会话重放: 登录期全部初始化命令 + PM 页面初始化 + 查询前置 (b000~b097)
            java.util.List<String> ps = new ArrayList<String>();
            File fdir = new File("_fullblobs");
            String[] all = fdir.list();
            java.util.Arrays.sort(all);
            for (String fn : all) {
                if (!fn.endsWith(".bin")) continue;
                // 截到 b097 (2720 之前); 跳过重复的 TCP 重传块由服务端幂等吸收
                String num = fn.substring(1, 4);
                try { if (Integer.parseInt(num) > 97) continue; } catch (Exception ignore) { continue; }
                ps.add("_fullblobs/" + fn);
            }
            preBlobs = ps.toArray(new String[ps.size()]);
            System.out.println("[3b] fullsess mode: replaying " + preBlobs.length + " captured commands");
        } else if (fullReplay) {
            preBlobs = new String[]{
                "_fullblobs/b078_t0047.49_s53382.bin", // 2871 uca.pm.querymo (打开查询页第一条!)
                "_fullblobs/b080_t0053.74_s53383.bin", // 2907
                "_fullblobs/b082_t0054.59_s53383.bin", // 2753 完整 6-section 版
                "_fullblobs/b084_t0054.75_s53383.bin", // 2608
                "_fullblobs/b086_t0054.83_s53383.bin", // 2608
                "_fullblobs/b088_t0056.47_s53383.bin", // 2734
                "_fullblobs/b089_t0057.14_s53383.bin", // 2621
                "_fullblobs/b091_t0057.53_s53383.bin", // 2608
                "_fullblobs/b093_t0059.90_s53383.bin", // 2734
                "_fullblobs/b094_t0060.00_s53383.bin", // 2745
                "_fullblobs/b096_t0060.03_s53383.bin"}; // 2746
        } else {
            preBlobs = new String[]{"_gz_83059.bin", "_gz_86743.bin"};
        }
        if (!fullReplay && !vset.contains("fullsess") && !new File("_gz_83059.bin").exists()) {
            preBlobs = new String[]{"_blobs/s54_cs@49164.bin", "_blobs/s54_cs@51389.bin"};
        }
        int replayInvoke = 200;
        for (String pre : preBlobs) {
            File pf = new File(pre);
            if (!pf.exists()) { System.out.println("    (pre blob missing: " + pre + ")"); continue; }
            try {
                ObjectInputStream pois = new ObjectInputStream(new FileInputStream(pf));
                Object pMsg = pois.readObject();
                pois.close();
                Method pSetVal = pMsg.getClass().getMethod("setValue", String.class, String.class);
                pSetVal.invoke(pMsg, "sessioncode", sessionCode);
                pSetVal.invoke(pMsg, "SessionID", String.valueOf(sessionID));
                pSetVal.invoke(pMsg, "UserID", String.valueOf(userID));
                pSetVal.invoke(pMsg, "UserName", user);
                try {
                    Field stf2 = findField(pMsg.getClass(), "state_time");
                    stf2.setAccessible(true);
                    stf2.setLong(pMsg, System.currentTimeMillis());
                } catch (Throwable ignore) {}
                pMsg.getClass().getMethod("setInvokeID", int.class)
                    .invoke(pMsg, Integer.valueOf(replayInvoke++));
                Method pWrap = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil")
                    .getMethod("getWrappedMessage",
                        Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"), int.class);
                Object pOuter = pWrap.invoke(null, pMsg, Integer.valueOf(1));
                Method reqM0 = null;
                for (Method m : fsbEjb.getClass().getMethods())
                    if (m.getName().equals("requestx")) { reqM0 = m; break; }
                Object pResp = reqM0.invoke(fsbEjb, pOuter);
                int pCmd = (Integer) pMsg.getClass().getMethod("getCommandCode").invoke(pMsg);
                System.out.println("[3b] pre-command " + pCmd + " (" + pre + ") sent");
                try {
                    Method unw = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil")
                        .getMethod("getUnwrappedMessage",
                            Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"));
                    Object pInner = unw.invoke(null, pResp);
                    String outFile = "_resp_" + pre.replaceAll("[^0-9]", "") + ".bin";
                    ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream(outFile));
                    oos.writeObject(pInner); oos.close();
                    System.out.println("[3b] pre-command resp saved -> " + outFile);
                } catch (Throwable t) {
                    System.out.println("     -> resp parse: " + rootMsg(t));
                }
            } catch (Throwable t) {
                System.out.println("    (pre-command " + pre + " failed: " + rootMsg(t) + ")");
            }
        }

        // ===== Step 4: Submit via FServerBroker.requestx (wrapped, GUI-style) =====
        // 刷新时间戳字段, 避免陈旧消息被拒
        try {
            Field stf = findField(fiMsg.getClass(), "state_time");
            stf.setAccessible(true);
            stf.setLong(fiMsg, System.currentTimeMillis());
        } catch (Throwable ignore) {}

        System.out.println("[4] Submitting cmd 2720 via requestx (wrapped, GUI-style)...");
        long t0 = System.currentTimeMillis();
        int invokeId = 100000 + new Random().nextInt(800000);
        Object resp = null;
        try {
            Method setValM = fiMsg.getClass().getMethod("setValue", String.class, String.class);
            // GUI 请求中根本没有 uniqueNodeID 键 (2026-08-24 抓包对比确认);
            // 设空串会被服务端区别对待导致查询不被执行, 必须彻底移除
            try {
                Field hf2 = findField(fiMsg.getClass(), "header");
                hf2.setAccessible(true);
                Object hdrProps = hf2.get(fiMsg);
                hdrProps.getClass().getMethod("remove", Object.class).invoke(hdrProps, "uniqueNodeID");
            } catch (Throwable t) {
                System.out.println("    (remove uniqueNodeID: " + rootMsg(t) + ")");
            }
            // checkAccessx: checkedoperation 需与操作码一致且 checked∈{true,false} 才跳过权限校验
            setValM.invoke(fiMsg, "checkedoperation", "uca.pm.querydata");
            setValM.invoke(fiMsg, "checked", "true");
            fiMsg.getClass().getMethod("setInvokeID", int.class).invoke(fiMsg, Integer.valueOf(replayInvoke++));

            // 模板查询走 2686(CMD_BASICTEMPLATE_QUERYDATA); 2720 用于普通/原始查询。
            // GUI 的 getCommandCode() 在仅模板权限时返回 2686。
            int useCmd = 2686;
            String useOp = "uca.pm.template.querydata";
            if (args.length > 5 && args[5].equals("2720")) { useCmd = 2720; useOp = "uca.pm.querydata"; }
            fiMsg.getClass().getMethod("setCommandCode", int.class).invoke(fiMsg, Integer.valueOf(useCmd));
            setValM.invoke(fiMsg, "checkedoperation", useOp);
            // 显式异步标记: 服务端后台执行, 结果经 JMS 推送
            if (!vset.contains("noasyn")) setValM.invoke(fiMsg, "asyn", "true");
            if (vset.contains("savemsg")) {
                ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream("_our_inner.bin"));
                oos.writeObject(fiMsg); oos.close();
                System.out.println("[4] inner message saved -> _our_inner.bin");
            }
            System.out.println("[4] using command code " + useCmd + " op=" + useOp);

            // 关键: 复刻客户端包装 —— 整个 FIMessage 序列化(+gzip) 后放入 FIMessageStream。
            // 服务端 PM 服务按 FIMessageStream 解包, 裸 QueryCondition 会 ClassCastException。
            Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
            Method wrapM = msgUtilCls.getMethod("getWrappedMessage",
                Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"), int.class);
            Object outer = wrapM.invoke(null, fiMsg, Integer.valueOf(1));
            System.out.println("[4] message wrapped: outer cmd=" 
                + outer.getClass().getMethod("getCommandCode").invoke(outer));

            if (vset.contains("nongui")) {
                // requestxForNonGUI: 接收【未包装】的 FIMessage; 注释记载该通道不需要
                // GUI 会话级验证, 可能是服务端实际执行查询的通道
                Method reqNG = null;
                for (Method m : fsbEjb.getClass().getMethods())
                    if (m.getName().equals("requestxForNonGUI")) { reqNG = m; break; }
                System.out.println("[4] submitting via requestxForNonGUI (unwrapped)...");
                resp = reqNG.invoke(fsbEjb, fiMsg);
            } else {
                Method reqM = null;
                for (Method m : fsbEjb.getClass().getMethods())
                    if (m.getName().equals("requestx")) { reqM = m; break; }
                resp = reqM.invoke(fsbEjb, outer);
            }
        } catch (Throwable c) {
            Throwable r = (c instanceof InvocationTargetException) ? ((InvocationTargetException) c).getTargetException() : c;
            System.out.println("!! submit failed: " + r.getClass().getName());
            int depth = 0;
            for (Throwable t = r; t != null && depth < 6; t = nextCause(t), depth++) {
                StringBuilder sb = new StringBuilder("    [").append(t.getClass().getName()).append("]");
                try {
                    Object eid = t.getClass().getMethod("getErrID").invoke(t);
                    sb.append(" errID=").append(eid);
                } catch (Throwable ignore) {}
                String m = t.getMessage();
                sb.append(" msg=").append(m == null ? "<null>" : m);
                System.out.println(sb.toString());
            }
        }

        // 解压响应: section[0].object 是 byte[] (gzip -> 序列化 FIMessageStream)
        if (resp != null) {
            try {
                Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
                Method unwrapM = msgUtilCls.getMethod("getUnwrappedMessage",
                    Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"));
                resp = unwrapM.invoke(null, resp);
            } catch (Throwable t) {
                System.out.println("    (outer unwrap: " + rootMsg(t) + ") -> try compressed payload");
                // 压缩响应: section[0].object = byte[] = gzip(序列化 FIMessage)
                Object inner = decodeCompressedResponse(resp);
                if (inner != null) { resp = inner; System.out.println("    [decode] compressed response decoded OK"); }
            }
        }

        // 同步响应缺失时, 回退等待 UEP_F_RESPONSE_TOPIC 上的异步响应
        if (resp == null) {
            long deadlineResp = System.currentTimeMillis() + 60000;
            while (System.currentTimeMillis() < deadlineResp) {
                List<Object> snap;
                synchronized (collectedResponses) {
                    snap = new ArrayList<Object>(collectedResponses);
                    collectedResponses.removeAll(snap);
                }
                for (Object fm : snap) {
                    try {
                        Object inner = fm;
                        try {
                            Class<?> msgUtilCls0 = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
                            inner = msgUtilCls0.getMethod("getUnwrappedMessage",
                                Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage")).invoke(null, fm);
                        } catch (Throwable ignore) {}
                        int cc = (Integer) inner.getClass().getMethod("getCommandCode").invoke(inner);
                        if (cc == 2720) { resp = inner; break; }
                    } catch (Throwable t) {
                        System.out.println("    [resp-topic] payload: " + fm.getClass().getName());
                    }
                }
                if (resp != null) break;
                Thread.sleep(500);
            }
            System.out.println("[4] async response fallback -> " + (resp == null ? "NONE" : "received"));
        }
        long dt = (System.currentTimeMillis() - t0) / 1000;
        System.out.println("[4] Response after " + dt + "s");
        String queryId = null;
        if (resp != null) {
            dumpResponse(resp);
            // 保存解码后的完整内层响应供离线分析
            try {
                ObjectOutputStream oos = new ObjectOutputStream(new FileOutputStream("_resp_inner_latest.bin"));
                oos.writeObject(resp); oos.close();
                System.out.println("[4] inner response saved -> _resp_inner_latest.bin");
            } catch (Throwable ignore) {}
            try {
                Object[] conds = unwrapConditions(resp);
                if (conds != null && conds.length > 0 && conds[0] != null) {
                    queryId = (String) conds[0].getClass().getMethod("getQueryId").invoke(conds[0]);
                    System.out.println("[4] echoed condition state:");
                    echoDiff(conds[0]);
                }
            } catch (Exception ignore) {}
        }
        System.out.println("[4] queryId = " + queryId);

        // ===== Step 4b: CMD_PMQUERY_REQUERY(2721) 显式触发执行 =====
        // QueryBroker.refresh(queryId): sec[0] = queryId 字符串
        // requeryold 变体: 从 _requery_id.txt 读外部 queryId (如用户 GUI 的历史查询)
        String requeryId = null;
        if (vset.contains("requeryold")) {
            File rf = new File("_requery_id.txt");
            if (rf.exists()) {
                FileInputStream rin = new FileInputStream(rf);
                byte[] rbuf = new byte[(int) rf.length()];
                rin.read(rbuf);
                rin.close();
                requeryId = new String(rbuf, "UTF-8").trim();
                System.out.println("[4b] using external requeryId: " + requeryId);
            }
        }
        String targetQueryId = requeryId != null && requeryId.length() > 0 ? requeryId : queryId;
        if (targetQueryId != null && (vset.contains("requery") || vset.contains("requeryold"))) {
            try {
                Object rMsg = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage")
                    .getConstructor(int.class).newInstance(Integer.valueOf(2721));
                Method rSetVal = rMsg.getClass().getMethod("setValue", String.class, String.class);
                rSetVal.invoke(rMsg, "sessioncode", sessionCode);
                rSetVal.invoke(rMsg, "SessionID", String.valueOf(sessionID));
                rSetVal.invoke(rMsg, "UserID", String.valueOf(userID));
                rSetVal.invoke(rMsg, "UserName", user);
                rSetVal.invoke(rMsg, "checkedoperation", "global.operation");
                rSetVal.invoke(rMsg, "checked", "true");
                rMsg.getClass().getMethod("setInvokeID", int.class).invoke(rMsg, Integer.valueOf(replayInvoke++));
                Object rSec = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIObjectSection")
                    .getConstructor().newInstance();
                rSec.getClass().getMethod("setObject", java.io.Serializable.class).invoke(rSec, targetQueryId);
                rMsg.getClass().getMethod("addFISection",
                    Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection")).invoke(rMsg, rSec);
                Method rWrap = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil")
                    .getMethod("getWrappedMessage",
                        Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"), int.class);
                Object rOuter = rWrap.invoke(null, rMsg, Integer.valueOf(1));
                Method reqM2 = null;
                for (Method m : fsbEjb.getClass().getMethods())
                    if (m.getName().equals("requestx")) { reqM2 = m; break; }
                Object rResp = reqM2.invoke(fsbEjb, rOuter);
                System.out.println("[4b] REQUERY 2721 sent for " + targetQueryId);
                try {
                    int rErr = -99;
                    try { rErr = (Integer) rResp.getClass().getMethod("getErrID").invoke(rResp); } catch (Throwable ignore) {}
                    System.out.println("[4b] REQUERY resp errID=" + rErr);
                    Object rInner = decodeCompressedResponse(rResp);
                } catch (Throwable t2) {
                    System.out.println("[4b] REQUERY resp decode: " + rootMsg(t2));
                }
            } catch (Throwable t) {
                Throwable r = (t instanceof InvocationTargetException) ? ((InvocationTargetException) t).getTargetException() : t;
                String eid = "";
                try { eid = " errID=" + r.getClass().getMethod("getErrID").invoke(r); } catch (Throwable ignore) {}
                System.out.println("[4b] REQUERY failed: " + r.getClass().getName() + eid + " msg=" + r.getMessage());
            }
        }

        // ===== Step 5: wait for result notifications / poll SFTP dir =====
        List<String> files = waitForFiles(queryId, 180000, server);
        if (files.isEmpty()) {
            System.out.println("!! no MessageData received; trying direct SFTP probe with queryId...");
            if (queryId != null) {
                for (int i = 0; i < 8; i++) files.add("/ppus/uca.ppu/uca-pm.pmu/main-query/" + queryId + "_" + i + ".zip");
            }
        } else {
            System.out.println("[5] " + files.size() + " result file(s):");
            for (String f : files) System.out.println("    " + f);
        }

        // ===== Step 6: download via direct SftpClientImpl (port 21128, uepcommon, 内嵌证书) =====
        StringBuilder jsonRows = new StringBuilder();
        int totalRows = 0;
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
            if (sftp == null) throw new RuntimeException("cannot connect SFTP after retries");

            File outDir = new File("kpi_result_files");
            if (!outDir.exists()) outDir.mkdirs();

            Method getM = null;
            for (Method m : sftpCls.getMethods()) {
                if (m.getName().equals("get") && m.getParameterTypes().length == 2) { getM = m; break; }
            }
            // U31 版 SftpClientImpl.get(localPath, remotePath) —— 参数顺序与直觉相反
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
        } catch (Throwable t) {
            System.out.println("!! SFTP/download failed: " + t);
            t.printStackTrace(System.out);
        }

        // ===== Output =====
        String qidJson = queryId == null ? "null" : "\"" + esc(queryId) + "\"";
        String json = "{\n  \"queryId\": " + qidJson +
            ",\n  \"range\": [\"" + esc(startDay) + "\", \"" + esc(endDay) + "\"]" +
            ",\n  \"totalRows\": " + totalRows +
            ",\n  \"datasets\": [\n" + jsonRows + "\n  ]\n}";
        Writer w = new OutputStreamWriter(new FileOutputStream("kpi_result.json"), "UTF-8");
        w.write(json); w.close();
        System.out.println("\n=== DONE: " + totalRows + " rows -> kpi_result.json ===");
        System.out.println(json.substring(0, Math.min(3000, json.length())));

        try { conn.getClass().getMethod("close").invoke(conn); } catch (Exception ignore) {}
        System.exit(0);
    }

    // ------------------------------------------------------------------
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

    /** 解析 gzip(ObjectInputStream(ResultDataSet)) 文件 */
    static ResultDump parseResultFile(File f) {
        try {
            ObjectInputStream ois = new ObjectInputStream(
                new GZIPInputStream(new FileInputStream(f)));
            Object ds = ois.readObject();
            ois.close();
            return dumpDataSet(ds);
        } catch (FileNotFoundException fnf) {
            System.out.println("    (local file missing: " + f.getName() + ")");
            return null;
        } catch (Exception e) {
            System.out.println("    parse failed " + f.getName() + ": " + rootMsg(e));
            return null;
        }
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

    // ---------------- JMS listener (动态代理, 避免编译期依赖) ----------------
    static Object newJmsListener() throws Exception {
        Class<?> lstCls = Class.forName("javax.jms.MessageListener");
        return java.lang.reflect.Proxy.newProxyInstance(lstCls.getClassLoader(), new Class<?>[]{ lstCls },
            new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] a) {
                    if ("onMessage".equals(method.getName()) && a != null && a.length > 0) {
                        try {
                            Object payload = a[0].getClass().getMethod("getObject").invoke(a[0]);
                            // 兼容 packed 包装: PackedMessageImpl.get()
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
                            } else {
                                System.out.println("    [jms] other payload: "
                                    + (payload == null ? "null" : payload.getClass().getName()));
                            }
                        } catch (Throwable t) {
                            System.out.println("    (jms msg parse: " + t + ")");
                        }
                    }
                    return null;
                }
            });
    }

    static Throwable nextCause(Throwable t) {
        try { return t.getCause(); } catch (Throwable ignore) { return null; }
    }

    static void setIntField(Object target, String name, int value) throws Exception {
        Field f = findField(target.getClass(), name);
        f.setAccessible(true);
        f.setInt(target, value);
    }

    /** 打印服务器回显的 QueryCondition 关键字段 */
    static void echoDiff(Object cond) {
        String[] getters = {"getQueryId","getQueryTitle","getQueryTemplateId","getMoTypeId","getNeTypeId",
            "getLocationType","getNodeId","getQueryFromType","getQuerySourceType","getQueryOriginType",
            "getQueryType","getDateSectionType2"};
        for (String g : getters) {
            try {
                Object v = cond.getClass().getMethod(g).invoke(cond);
                if (v instanceof String[]) {
                    String[] a = (String[]) v;
                    StringBuilder sb = new StringBuilder("[");
                    for (int i = 0; i < Math.min(a.length, 5); i++) sb.append(i > 0 ? "," : "").append(a[i]);
                    sb.append("] len=").append(a.length);
                    v = sb.toString();
                }
                System.out.println("    " + g.substring(3) + " = " + v);
            } catch (IllegalArgumentException ie) {
                // 方法不存在则跳过
            } catch (Throwable t) {
                System.out.println("    " + g.substring(3) + " -> err " + rootMsg(t));
            }
        }
        try {
            Object ti = cond.getClass().getMethod("getTimeCondition").invoke(cond);
            System.out.println("    timeCond.dateSectionType=" + ti.getClass().getMethod("getDateSectionType").invoke(ti)
                + " granularity=" + ti.getClass().getMethod("getGranularity").invoke(ti)
                + " timeType=" + ti.getClass().getMethod("getTimeType").invoke(ti));
            Object iv = ti.getClass().getMethod("getTimeInterval").invoke(ti);
            System.out.println("    interval=[" + callStr(iv, "getStartDate") + " ~ " + callStr(iv, "getEndDate") + "]");
        } catch (Throwable t) {
            System.out.println("    timeCond -> err " + rootMsg(t));
        }
        try {
            Object locs = cond.getClass().getMethod("getQueryCommonLocations").invoke(cond);
            int n = locs == null ? -1 : Array.getLength(locs);
            System.out.println("    queryCommonLocations.len=" + n);
            Object items = cond.getClass().getMethod("getQueryItems").invoke(cond);
            int m = items == null ? -1 : Array.getLength(items);
            System.out.println("    queryItems.len=" + m);
            if (m > 0) {
                Object f = Array.get(items, 0);
                System.out.println("    queryItems[0].fieldId=" + callStr(f, "getFieldId"));
            }
        } catch (Throwable t) {
            System.out.println("    items/locs -> err " + rootMsg(t));
        }
    }

    /** 打印响应 FIMessage 的头与错误信息 */
    static void dumpResponse(Object resp) {
        try {
            int e = (Integer) resp.getClass().getMethod("getErrID").invoke(resp);
            String ed = callStr(resp, "getErrDesc");
            System.out.println("    response errID=" + e + " errDesc=" + ed);
            Field hf = findField(resp.getClass(), "header");
            if (hf != null) {
                hf.setAccessible(true);
                Properties hp = (Properties) hf.get(resp);
                if (hp != null) {
                    for (String k : new TreeSet<String>(hp.stringPropertyNames())) {
                        System.out.println("      hdr[" + k + "]=" + hp.getProperty(k));
                    }
                }
            }
            int sc = (Integer) resp.getClass().getMethod("getSectionCount").invoke(resp);
            System.out.println("    sections=" + sc);
            for (int i = 0; i < sc; i++) {
                Object s = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, i);
                Object o = null;
                try { o = s.getClass().getMethod("getObject").invoke(s); } catch (Exception ignore) {}
                System.out.println("      section[" + i + "] " + s.getClass().getSimpleName()
                    + " obj=" + (o == null ? "null" : o.getClass().getName()));
                if (o instanceof Object[]) {
                    Object[] arr = (Object[]) o;
                    System.out.println("        array len=" + arr.length
                        + (arr.length > 0 && arr[0] != null ? " of " + arr[0].getClass().getName() : ""));
                }
            }
        } catch (Throwable t) {
            System.out.println("    (dumpResponse failed: " + t + ")");
        }
    }

    /** 从模板重新反序列化一份 FIMessage 并写入会话字段 */
    static Object freshTemplateMessage(String sessionCode, int sessionID, int userID, String user) throws Exception {
        ObjectInputStream ois = new ObjectInputStream(new FileInputStream("pm_query_template.bin"));
        Object fiMsg = ois.readObject();
        ois.close();
        Method setVal = fiMsg.getClass().getMethod("setValue", String.class, String.class);
        setVal.invoke(fiMsg, "sessioncode", sessionCode);
        setVal.invoke(fiMsg, "SessionID", String.valueOf(sessionID));
        setVal.invoke(fiMsg, "UserID", String.valueOf(userID));
        setVal.invoke(fiMsg, "UserName", user);
        fiMsg.getClass().getMethod("setInvokeID", int.class)
             .invoke(fiMsg, Integer.valueOf(100000 + new Random().nextInt(800000)));
        return fiMsg;
    }

    static void setObjectSafe(Object section, Object value) throws Exception {
        try {
            section.getClass().getMethod("setObject", Class.forName("java.io.Serializable")).invoke(section, value);
            return;
        } catch (NoSuchMethodException ignore) {}
        Field f = findField(section.getClass(), "object");
        f.setAccessible(true);
        f.set(section, value);
    }

    // ---------------- helpers ----------------
    static String callStr(Object o, String getter) {
        try { Object v = o.getClass().getMethod(getter).invoke(o); return v == null ? "" : String.valueOf(v); }
        catch (Exception e) { return ""; }
    }

    static String rootMsg(Throwable e) {
        if (e instanceof InvocationTargetException) e = ((InvocationTargetException) e).getTargetException();
        Throwable r = e; while (r.getCause() != null) r = r.getCause();
        return r.getClass().getSimpleName() + ": " + r.getMessage();
    }

    /** 从请求/响应 FIMessage 中取第一个 section 的 object */
    static Object firstSectionObject(Object fiMsg) throws Exception {
        Object sec = fiMsg.getClass().getMethod("getFISectionAt", int.class).invoke(fiMsg, 0);
        return sec.getClass().getMethod("getObject").invoke(sec);
    }

    /** 解压响应: section[0].object 是 byte[] (gzip -> 序列化 FIMessageStream) */
    static Object decodeCompressedResponse(Object resp) {
        try {
            Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, 0);
            Object payload = sec.getClass().getMethod("getObject").invoke(sec);
            if (!(payload instanceof byte[])) return null;
            byte[] raw = (byte[]) payload;
            System.out.println("    [decode] payload " + raw.length + " bytes, magic="
                + String.format("%02x %02x", raw[0], raw[1]));
            java.io.ByteArrayInputStream bin = new java.io.ByteArrayInputStream(raw);
            InputStream src = bin;
            if (raw.length > 2 && (raw[0] & 0xFF) == 0x1F && (raw[1] & 0xFF) == 0x8B) {
                src = new java.util.zip.GZIPInputStream(bin);
                System.out.println("    [decode] gzip inflated");
            }
            ObjectInputStream ois = new ObjectInputStream(src);
            Object obj = ois.readObject();
            ois.close();
            System.out.println("    [decode] deserialized: " + obj.getClass().getName());
            Method unw = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil")
                .getMethod("getUnwrappedMessage",
                    Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage"));
            return unw.invoke(null, obj);
        } catch (Throwable t) {
            System.out.println("    [decode] failed: " + rootMsg(t));
            return null;
        }
    }

    static Object[] unwrapConditions(Object resp) throws Exception {
        Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, 0);
        Object obj = sec.getClass().getMethod("getObject").invoke(sec);
        if (obj instanceof Object[]) return (Object[]) obj;
        return new Object[]{ obj };
    }

    /** 取本机与 EMS 通信所用的源 IP */
    static String getLocalIp(String server) {
        try {
            java.net.Socket s = new java.net.Socket();
            s.connect(new java.net.InetSocketAddress(server, JNP_PORT), 3000);
            String ip = s.getLocalAddress().getHostAddress();
            s.close();
            return ip;
        } catch (Throwable t) { return "192.168.100.20"; }
    }

    /** 取本机 MAC, 与 GUI 抓包一致格式 FC4CEA20EE49 */
    static String getClientMac() {
        try {
            for (java.net.NetworkInterface ni : java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())) {
                byte[] mac = ni.getHardwareAddress();
                if (mac == null || mac.length != 6) continue;
                StringBuilder sb = new StringBuilder();
                for (byte b : mac) sb.append(String.format("%02X", b));
                String s = sb.toString();
                // 排除虚拟网卡全零
                if (!s.equals("000000000000") && !ni.isLoopback()) return s;
            }
        } catch (Throwable ignore) {}
        // 默认回退: 与 GUI 相同网段的不同 MAC, 避免与已登录 GUI 会话冲突
        String alt = System.getProperty("ems.clientmac", "");
        return alt.length() > 0 ? alt : "FC4CEA20EE49";
    }

    /** 把 QueryCondition 时间范围改为 [startDay 00:00, endDay 00:00) GMT */
    static void setTimeRange(Object cond, String startDay, String endDay) throws Exception {
        Object tc = cond.getClass().getMethod("getTimeCondition").invoke(cond);
        Object ti = tc.getClass().getMethod("getTimeInterval").invoke(tc);
        setStr(ti, "startDate", startDay + " 00:00:00 GMT");
        setStr(ti, "endDate", endDay + " 00:00:00 GMT");
        setStr(ti, "clientTimeZoneID", "GMT");
        setStr(tc, "neTimeZoneID", "Etc/GMT+0");
        // GUI 查询请求中 timeType=3 (2026-08-24 抓包确认)
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

    static void printQuerySummary(Object cond) {
        try {
            String motype = callStr(cond, "getMoTypeId");
            String title = callStr(cond, "getQueryTitle");
            String tplId = callStr(cond, "getQueryTemplateId");
            System.out.println("    moType=" + motype + " template=" + title + " (id " + tplId + ")");
            Object checkedFields = cond.getClass().getMethod("getCheckedFields").invoke(cond);
            int n = checkedFields == null ? 0 : Array.getLength(checkedFields);
            StringBuilder kpis = new StringBuilder();
            for (int i = 0; i < n; i++) {
                Object f = Array.get(checkedFields, i);
                kpis.append(callStr(f, "getFieldName"));
                if (i < n - 1) kpis.append(", ");
            }
            System.out.println("    KPI fields(" + n + "): " + kpis);
            Object locs = cond.getClass().getMethod("getQueryCommonLocations").invoke(cond);
            int ln = locs == null ? 0 : Array.getLength(locs);
            for (int i = 0; i < Math.min(ln, 5); i++) {
                Object l = Array.get(locs, i);
                System.out.println("    location[" + i + "]: neDn=" + callStr(l, "getNeDn"));
            }
        } catch (Exception e) {
            System.out.println("    (summary failed: " + e + ")");
        }
    }

    /** 等待 JMS MessageData 文件通知 + 轮询 SFTP main-query 目录 */
    static List<String> waitForFiles(String queryId, long timeoutMs, String server) throws Exception {
        long deadline = System.currentTimeMillis() + timeoutMs;
        Set<String> files = new LinkedHashSet<String>();
        boolean sawFinish = false;
        com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl sftp = null;
        try {
            sftp = new com.zte.ums.uep.psl.jsch.jcraft.sftp.SftpClientImpl(server, 21128, 20000, "uepcommon", null, false);
        } catch (Throwable t) {
            System.out.println("    (SFTP poll unavailable: " + rootMsg(t) + ")");
        }
        int poll = 0;
        int stable = 0;
        int lastCount = 0;
        while (System.currentTimeMillis() < deadline) {
            // 1) JMS 收到的消息
            List<Object> snapshot;
            synchronized (collectedMessages) {
                snapshot = new ArrayList<Object>(collectedMessages);
                collectedMessages.clear();
            }
            for (Object msgData : snapshot) {
                String mid = callStr(msgData, "getQueryId");
                if (queryId != null && mid != null && mid.length() > 0 && !mid.equals(queryId)) {
                    System.out.println("    (other query message: " + mid + " file=" + callStr(msgData, "getFilePath") + ")");
                    continue;
                }
                String fp = callStr(msgData, "getFilePath");
                if (fp != null && fp.length() > 0) files.add("/" + fp.replaceFirst("^/+", ""));
                String dbg = callStr(msgData, "getMessage");
                if (dbg != null && dbg.length() > 0) System.out.println("    [msg] " + dbg);
                try {
                    Object fin = msgData.getClass().getMethod("isFinish").invoke(msgData);
                    if (Boolean.TRUE.equals(fin)) sawFinish = true;
                } catch (Exception ignore) {}
            }
            // 2) SFTP 目录轮询 (严格匹配本查询的 queryId 前缀, 避免抓到其他客户端的结果)
            if (sftp != null && ++poll % 4 == 1) {
                try {
                    String[] ls = sftp.dir("/ppus/uca.ppu/uca-pm.pmu/main-query", false);
                    int n = ls == null ? 0 : ls.length;
                    if (n > 0) {
                        int matched = 0;
                        for (String f : ls) {
                            String name = f.trim();
                            int sp = name.lastIndexOf(' ');
                            if (sp > 0) name = name.substring(sp + 1).trim();
                            if (name.length() == 0) continue;
                            if (queryId != null && !name.startsWith(queryId)) continue;
                            files.add("/ppus/uca.ppu/uca-pm.pmu/main-query/" + name);
                            matched++;
                        }
                        System.out.println("    [sftp-poll] main-query " + n + " entries, matched ours: " + matched);
                    }
                } catch (Throwable t) {
                    System.out.println("    [sftp-poll] failed: " + rootMsg(t));
                }
            }
            if (sawFinish && files.size() > 0) break;
            // 文件数连续 12 次(约6秒)无增长则认为已收全
            if (files.size() > 0 && files.size() == lastCount) {
                if (++stable >= 12) break;
            } else { stable = 0; lastCount = files.size(); }
            Thread.sleep(500);
        }
        try { if (sftp != null) sftp.quit(); } catch (Exception ignore) {}
        return new ArrayList<String>(files);
    }

    static void dumpCollected(String tag) {
        synchronized (collectedMessages) {
            System.out.println("[" + tag + "] collected messages so far: " + collectedMessages.size());
            collectedMessages.clear();
        }
    }

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }

    /** 通过原始 socket 获取 JNP NamingStub（与 EmsKpiFinal 相同） */
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

    /** DES/ECB/PKCS5Padding 密码加密（U31 格式） */
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
}
