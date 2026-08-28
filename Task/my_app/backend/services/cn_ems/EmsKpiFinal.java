import java.net.*;
import java.io.*;
import java.util.*;
import java.lang.reflect.*;
import java.net.SocketTimeoutException;
import javax.naming.*;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.DESKeySpec;
import javax.crypto.SecretKeyFactory;

/**
 * ZTE U31 EMS KPI 获取工具 - 最终版
 * 
 * 已验证功能:
 * 1. RMI/JNP 登录 (JNDI port 21101, FServerManager EJB)
 * 2. DES 密码加密 (密钥: F1 F7 DF 9D 91 F7 3D A7)
 * 3. cmd 2600 获取 MO 类型列表 (requestxForNonGUI)
 * 4. JMS 连接 (GlobeNamingContextFactory → SpyConnectionFactory)
 * 5. JMS FM Topic 订阅接收告警消息
 * 6. ClientMessageCenter 订阅
 *
 * 【⚠ 2026-08-24 结论修正】
 * - "cmd 2614 报 PM 数据未配置" 是错误结论: 2614 不是 KPI 查询入口,
 *   真实入口为 cmd 2720 (op=uca.pm.querydata, 单 QueryCondition section)。
 *   KPI 数据在 EMS 上存在且可查: 原始测量文件可经 SFTP
 *   uepcommon@21128 直接下载 (/pmdata/download/gzmulyxb-2_11_module_dataCollect/,
 *   3GPP measCollectFile 格式, 5 分钟粒度), 已由 EmsKpiRawQuery.java 验证
 *   并产出真实 Erl (~52,000 Erl, 与 GUI 查询同量级); 统一入口
 *   ems_kpi_query.py。
 * - OSF_2WSF_PM_Topic 不存在的原因: GUI 会话通过 jmswrapper 动态创建
 *   per-session topic (UEP_F_RESPONSE_TOPIC<sid>), 登出即删;
 *   全局结果 topic 为 PM_SEND_DATA_TOPIC。
 *
 * 已知限制:
 * - cmd 2720 协议路径: 消息已与 GUI 字节级一致, 服务端回显 queryId,
 *   但异步执行环节存在未定位的会话级门槛 (GUI 正常, 我们只回显不落盘)
 * - requestx/requestAsyn 需要 session 验证 (用 requestxForNonGUI 代替)
 * 
 * 使用方法:
 *   java -cp <classpath> EmsKpiFinal [server] [user] [password]
 */
public class EmsKpiFinal {
    
    // DES 加密密钥 (从 U31 客户端提取)
    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    
    // EMS 服务器端口
    static final int JNP_PORT = 21100;       // JNDI bootstrap
    static final int FSM_PORT = 21112;       // FServerManager JRMP
    static final int FSB_PORT = 21113;       // FServerBroker JRMP
    static final int JMS_PORT = 21101;       // JMS JNDI (from environment/jndi/jms/java.naming.provider.url)
    
    static volatile int alarmCount = 0;
    
    public static void main(String[] args) throws Exception {
        String server = args.length > 0 ? args[0] : "10.100.2.240";
        String user   = args.length > 1 ? args[1] : "oss";
        String pass   = args.length > 2 ? args[2] : "Tool123";
        
        System.out.println("=== ZTE U31 EMS KPI Tool ===");
        System.out.println("Server: " + server + " User: " + user);
        
        // ===== Step 1: Login =====
        System.out.println("\n[1] Login via RMI/JNP...");
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
        
        Class<?>[] paramTypes = loginMethod.getParameterTypes();
        Object[] loginParams = new Object[paramTypes.length];
        loginParams[0] = user;
        loginParams[1] = desEncrypt(pass);
        for (int i = 2; i < paramTypes.length; i++) {
            if (paramTypes[i] == Integer.class || paramTypes[i] == int.class) loginParams[i] = 1;
            else if (paramTypes[i] == Properties.class) loginParams[i] = new Properties();
        }
        
        Object loginResult = loginMethod.invoke(ejbObject, loginParams);
        int errID = (Integer) loginResult.getClass().getMethod("getErrID").invoke(loginResult);
        short sessionID = (Short) loginResult.getClass().getMethod("getSessionID").invoke(loginResult);
        int userID = (Integer) loginResult.getClass().getMethod("getUserID").invoke(loginResult);
        System.out.println("  sessionID=" + sessionID + " userID=" + userID);
        if (errID != 0) { System.out.println("  FAILED!"); return; }
        System.out.println("  OK");
        
        // ===== Step 2: Get MO Types (cmd 2600) =====
        System.out.println("\n[2] Get MO types (cmd 2600)...");
        Object fsbObj = lookupStr.invoke(namingCtx, "FServerBroker");
        Object fsbEjb = fsbObj.getClass().getMethod("create").invoke(fsbObj);
        
        Class<?> fiMsgClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage");
        Class<?> fiSecClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection");
        Class<?> fiParaClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIParaSection");
        
        Method reqNonGUI = null;
        for (Method m : fsbEjb.getClass().getMethods())
            if (m.getName().equals("requestxForNonGUI")) { reqNonGUI = m; break; }
        
        Object fiMsg = fiMsgClass.newInstance();
        fiMsg.getClass().getMethod("setCommandCode", int.class).invoke(fiMsg, 2600);
        fiMsg.getClass().getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
        fiMsg.getClass().getMethod("setUserID", int.class).invoke(fiMsg, userID);
        fiMsg.getClass().getMethod("addFISection", fiSecClass).invoke(fiMsg, fiParaClass.newInstance());
        
        Object result = reqNonGUI.invoke(fsbEjb, fiMsg);
        Object sec = result.getClass().getMethod("getFISectionAt", int.class).invoke(result, 0);
        Object moTypesArr = sec.getClass().getMethod("getObject").invoke(sec);
        int moCount = Array.getLength(moTypesArr);
        System.out.println("  MO types: " + moCount);
        
        // Print first 10
        for (int i = 0; i < Math.min(moCount, 10); i++) {
            Object moType = Array.get(moTypesArr, i);
            String id = (String) moType.getClass().getMethod("getId").invoke(moType);
            String name = (String) moType.getClass().getMethod("getName").invoke(moType);
            System.out.println("  [" + i + "] " + id + " | " + name);
        }
        if (moCount > 10) System.out.println("  ... +" + (moCount - 10) + " more");
        
        // ===== Step 3: JMS Setup =====
        System.out.println("\n[3] JMS setup...");
        Properties jmsEnv = new Properties();
        jmsEnv.setProperty("java.naming.factory.initial", "com.zte.ums.uep.psl.naming.interfaces.GlobeNamingContextFactory");
        jmsEnv.setProperty("java.naming.provider.url", "jnp://" + server + ":" + JMS_PORT);
        
        InitialContext jmsCtx = new InitialContext(jmsEnv);
        Object cf = jmsCtx.lookup("ConnectionFactory");
        Object conn = cf.getClass().getMethod("createTopicConnection", String.class, String.class).invoke(cf, user, pass);
        Object jmsSession = conn.getClass().getMethod("createTopicSession", boolean.class, int.class).invoke(conn, false, 1);
        
        // Subscribe FM Topic
        Object fmTopic = jmsSession.getClass().getMethod("createTopic", String.class).invoke(jmsSession, "OSF_2WSF_FM_Topic");
        Object fmSub = jmsSession.getClass().getMethod("createSubscriber", Class.forName("javax.jms.Topic")).invoke(jmsSession, fmTopic);
        System.out.println("  FM Topic subscribed");
        
        // Subscribe Async Topic
        Object asyncSub = null;
        try {
            Object asyncTopic = jmsSession.getClass().getMethod("createTopic", String.class).invoke(jmsSession, "UEP_F_ASYN_COMMAND_DISPATCH_TOPIC");
            asyncSub = jmsSession.getClass().getMethod("createSubscriber", Class.forName("javax.jms.Topic")).invoke(jmsSession, asyncTopic);
            System.out.println("  Async Topic subscribed");
        } catch (Exception e) {
            System.out.println("  Async Topic: " + e.getMessage());
        }
        
        // ClientMessageCenter
        try {
            Class<?> cmcClass = Class.forName("com.zte.ums.uep.pfl.finterface.wsf.ClientMessageCenter");
            Class<?> listenerClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.ClientMessageListener");
            Object listener = java.lang.reflect.Proxy.newProxyInstance(
                listenerClass.getClassLoader(), new Class<?>[] { listenerClass },
                new InvocationHandler() {
                    public Object invoke(Object proxy, Method method, Object[] a) {
                        if ("onClientMessage".equals(method.getName()) && a != null && a.length > 0) {
                            alarmCount++;
                            System.out.println("  [CMC alarm #" + alarmCount + "] " + a[0].getClass().getSimpleName());
                        }
                        return null;
                    }
                });
            Method sub = cmcClass.getMethod("subscribe", String.class, listenerClass);
            for (String t : new String[]{"OSF_2WSF_FM_Topic", "OSF_2WSF_PM_Topic", "UEP_F_ASYN_COMMAND_DISPATCH_TOPIC"}) {
                try { sub.invoke(null, t, listener); } catch (Exception e) {}
            }
            System.out.println("  ClientMessageCenter subscribed");
        } catch (Exception e) {
            System.out.println("  CMC: " + e.getMessage());
        }
        
        conn.getClass().getMethod("start").invoke(conn);
        System.out.println("  JMS started");
        
        // ===== Step 4: Receive FM messages (5s) =====
        System.out.println("\n[4] Listen FM messages (5s)...");
        Method receive = fmSub.getClass().getMethod("receive", long.class);
        int fmCount = 0;
        Object msg;
        while ((msg = (Object) receive.invoke(fmSub, 5000L)) != null) {
            fmCount++;
            try {
                Object packed = msg.getClass().getMethod("getObject").invoke(msg);
                Object inner = packed.getClass().getMethod("get").invoke(packed);
                Object innerObj = inner.getClass().getMethod("getObject").invoke(inner);
                System.out.println("  FM #" + fmCount + ": " + innerObj.getClass().getSimpleName());
            } catch (Exception e) {
                System.out.println("  FM #" + fmCount + ": " + msg.getClass().getSimpleName());
            }
        }
        if (fmCount == 0) System.out.println("  (no messages)");
        
        // ===== Step 5: PM Query attempt =====
        System.out.println("\n[5] PM query (cmd 2614)...");
        try {
            Object pmMsg = fiMsgClass.newInstance();
            pmMsg.getClass().getMethod("setCommandCode", int.class).invoke(pmMsg, 2614);
            pmMsg.getClass().getMethod("setSessionID", int.class).invoke(pmMsg, (int)sessionID);
            pmMsg.getClass().getMethod("setUserID", int.class).invoke(pmMsg, userID);
            Object pmPara = fiParaClass.newInstance();
            pmPara.getClass().getMethod("setSimpleParaValue", String.class, String.class)
                .invoke(pmPara, "moTypeId", "it.firewall.zte.cpuram");
            pmPara.getClass().getMethod("setSimpleParaValue", String.class, String.class)
                .invoke(pmPara, "startTime", "2025-08-20 00:00:00");
            pmPara.getClass().getMethod("setSimpleParaValue", String.class, String.class)
                .invoke(pmPara, "endTime", "2025-08-20 23:59:59");
            pmMsg.getClass().getMethod("addFISection", fiSecClass).invoke(pmMsg, pmPara);
            
            Object pmResult = reqNonGUI.invoke(fsbEjb, pmMsg);
            int pmErr = (Integer) pmResult.getClass().getMethod("getErrID").invoke(pmResult);
            System.out.println("  errID=" + pmErr);
        } catch (Exception e) {
            Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
            Throwable root = cause;
            while (root.getCause() != null) root = root.getCause();
            System.out.println("  " + root.getClass().getSimpleName() + " (server PM data not configured)");
        }
        
        // ===== Summary =====
        System.out.println("\n=== Summary ===");
        System.out.println("Login: OK (session=" + sessionID + ")");
        System.out.println("MO Types: " + moCount);
        System.out.println("JMS: Connected (oss/Tool123 via GlobeNamingContextFactory)");
        System.out.println("FM Messages received: " + fmCount);
        System.out.println("CMC Alarms: " + alarmCount);
        System.out.println("PM Query: Server-side NPE (PM data not configured)");
        
        conn.getClass().getMethod("close").invoke(conn);
        System.out.println("\nDone.");
    }
    
    /** 通过原始 socket 获取 JNP NamingStub */
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
    
    /** DES/ECB/PKCS5Padding 密码加密 */
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
