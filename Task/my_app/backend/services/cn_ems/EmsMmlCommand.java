import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;
import javax.naming.*;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.DESKeySpec;
import javax.crypto.SecretKeyFactory;

/**
 * EmsMmlCommand - ZTE U31 EMS MML Command Tool (Protocol-level)
 *
 * Login via RMI/JNP, then send MML commands via PPU service.
 *
 * Protocol flow:
 *   1. RMI/JNP login (FServerManager, DES password)
 *   2. Lookup MmlPPUServerService / MmlPPURouteServerService via JNDI
 *   3. Call execute(mml, netypeid, userid) or synSendMML(mml, path)
 *   4. Parse Outputmml / ICmdResponse result
 *
 * Usage:
 *   java EmsMmlCommand <server> <user> <password> "<MML command>"
 *   java EmsMmlCommand 10.100.2.240 oss Tool123 "SHOW UNIT_INFO;"
 */
public class EmsMmlCommand {

    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    static final int JNP_PORT = 21100;
    static final int EMB_MML_MSG_CODE = 5000010;

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
        String mmlCmd = args.length > 3 ? args[3] : "SHOW UNIT_INFO;";

        System.out.println("=== ZTE U31 EMS MML Command ===");
        System.out.println("Server=" + server + " user=" + user);
        System.out.println("MML: " + mmlCmd);

        // ===== Step 1: RMI Login (与 EmsKpiQuery 相同) =====
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

        // ===== Step 1b: Heartbeat =====
        Object heartbeatStub = null;
        try {
            heartbeatStub = lookupStr.invoke(namingCtx, "uep.fi.heartbeatreciever");
            Method hb = heartbeatStub.getClass().getMethod("setSessionStateOK", short.class);
            hb.invoke(heartbeatStub, (short) sessionID);
            System.out.println("[1b] heartbeat registered");
        } catch (Throwable t) {
            System.out.println("[1b] heartbeat: " + rootMsg(t));
        }
        if (heartbeatStub != null) {
            final Object stub = heartbeatStub;
            final short sid = (short) sessionID;
            Thread hbThread = new Thread(new Runnable() {
                public void run() {
                    while (true) {
                        try { stub.getClass().getMethod("setSessionStateOK", short.class).invoke(stub, sid); }
                        catch (Throwable ignore) {}
                        try { Thread.sleep(10000); } catch (InterruptedException e) { return; }
                    }
                }
            }, "hb");
            hbThread.setDaemon(true);
            hbThread.start();
        }

        // ===== Step 2: Send MML via PPU Service =====
        System.out.println("\n[2] Sending MML via PPU Service...");
        boolean success = false;

        // Method D: Via MmlPPUServerService.execute(mml, netypeid, userid) - DIRECT RMI
        if (!success) {
            try {
                success = sendViaPPUServerService(namingCtx, server, user, sessionID, userID, mmlCmd);
            } catch (Throwable t) {
                System.out.println("[2d] PPUServerService: " + rootMsg(t));
            }
        }

        // Method E: Via MmlPPURouteServerService.synSendMML(mml, path) - ROUTE
        if (!success) {
            try {
                success = sendViaRouteServer(namingCtx, server, user, sessionID, userID, mmlCmd);
            } catch (Throwable t) {
                System.out.println("[2e] RouteServer: " + rootMsg(t));
            }
        }

        // Method F: Via Inputmml + EMessage (EMB path, like GUI)
        if (!success) {
            try {
                success = sendViaInputmmlEMB(namingCtx, server, user, sessionID, userID, sessionCode, mmlCmd);
            } catch (Throwable t) {
                System.out.println("[2f] Inputmml+EMB: " + rootMsg(t));
            }
        }

        // Method G: Enumerate JNDI names to discover available services
        if (!success) {
            try {
                enumerateJndiServices(namingCtx);
            } catch (Throwable t) {
                System.out.println("[2g] JNDI enumerate: " + rootMsg(t));
            }
        }

        if (!success) {
            System.out.println("\n!! All MML send methods failed.");
        }

        try { namingCtx.getClass().getMethod("close").invoke(namingCtx); } catch (Exception ignore) {}
        System.out.println("\n=== Done ===");
    }

    // ==================== MML Send Methods ====================

    /**
     * Method D: Via MmlPPUServerService.execute(mml, netypeid, userid)
     * Direct RMI call to PPU server service.
     */
    static boolean sendViaPPUServerService(Object namingCtx, String server, String user,
                                            int sessionID, int userID, String mmlCmd) throws Exception {
        System.out.println("  [D] Trying MmlPPUServerService...");
        Method lookupStr = namingCtx.getClass().getMethod("lookup", String.class);

        // Try multiple JNDI names for the PPU service
        Object ppuService = null;
        String[] jndiNames = {
            "MmlPPUServerService", "mmlPPUServerService",
            "ejb/MmlPPUServerService", "MmlPPU",
            "PPUServerService", "ppuServerService",
            "com.zte.ums.api.common.mml.ppu.service.MmlPPUServerService"
        };
        for (String name : jndiNames) {
            try {
                Object home = lookupStr.invoke(namingCtx, name);
                System.out.println("  [D] Found JNDI: " + name + " -> " + home.getClass().getName());
                // Try to call create() on the home
                try {
                    ppuService = home.getClass().getMethod("create").invoke(home);
                    System.out.println("  [D] Created EJB via " + name);
                    break;
                } catch (Throwable t) {
                    System.out.println("  [D] create() failed on " + name + ": " + rootMsg(t));
                    // Maybe the home itself is the service (non-EJB)
                    ppuService = home;
                    break;
                }
            } catch (Throwable t) {
                // Not found, try next
            }
        }
        if (ppuService == null) {
            System.out.println("  [D] MmlPPUServerService not found in JNDI");
            return false;
        }

        System.out.println("  [D] Service class: " + ppuService.getClass().getName());
        // List all methods
        for (Method m : ppuService.getClass().getMethods()) {
            if (m.getName().equals("execute") || m.getName().equals("synSendMML")
                || m.getName().equals("inputMML2Request")) {
                System.out.println("  [D]   " + m.getName() + "(" + Arrays.toString(m.getParameterTypes()) + ")");
            }
        }

        // Try execute(String mml, long netypeid, int userid)
        // netypeid=0 for EMS-level commands
        for (long netypeid : new long[]{0, 1, 100, 101}) {
            try {
                System.out.println("  [D] Trying execute(mml, netypeid=" + netypeid + ", userid=" + userID + ")...");
                Method execMethod = null;
                for (Method m : ppuService.getClass().getMethods()) {
                    if (m.getName().equals("execute")) {
                        Class<?>[] pt = m.getParameterTypes();
                        if (pt.length == 3 && pt[0] == String.class
                            && (pt[1] == long.class || pt[1] == Long.class)
                            && (pt[2] == int.class || pt[2] == Integer.class)) {
                            execMethod = m;
                            break;
                        }
                    }
                }
                if (execMethod == null) {
                    System.out.println("  [D] execute(String,long,int) not found");
                    break;
                }
                Object resp = execMethod.invoke(ppuService, mmlCmd, netypeid, userID);
                System.out.println("  [D] Got response: " + (resp == null ? "null" : resp.getClass().getName()));
                if (resp != null) {
                    parseCmdResponse(resp);
                    return true;
                }
            } catch (Throwable t) {
                System.out.println("  [D] execute(netypeid=" + netypeid + "): " + rootMsg(t));
            }
        }

        // Try execute(ICmdWriteRequest)
        try {
            System.out.println("  [D] Trying execute(ICmdWriteRequest)...");
            // Create ImplWsfCmdRequest
            Class<?> reqCls = Class.forName("com.zte.ums.mml.common.impl.ImplWsfCmdRequest");
            // Constructor: (int userId, int cmdno, String remoteAddr, long version,
            //               boolean iscancel, boolean isfinish, long sessionId, int randomkey)
            Object req = reqCls.getConstructor(int.class, int.class, String.class, long.class,
                boolean.class, boolean.class, long.class, int.class)
                .newInstance(userID, 1, getLocalIp(server), 0L, false, false, (long)sessionID, new Random().nextInt(999999));
            // Set MML
            reqCls.getMethod("setMML", String.class).invoke(req, mmlCmd);
            reqCls.getMethod("setUserName", String.class).invoke(req, user);
            System.out.println("  [D] Created ImplWsfCmdRequest, sending...");

            Method execReq = null;
            for (Method m : ppuService.getClass().getMethods()) {
                if (m.getName().equals("execute") && m.getParameterTypes().length == 1) {
                    Class<?> pt = m.getParameterTypes()[0];
                    if (pt.getName().contains("ICmdWriteRequest") || pt.getName().contains("CmdRequest")) {
                        execReq = m;
                        break;
                    }
                }
            }
            if (execReq != null) {
                Object resp = execReq.invoke(ppuService, req);
                System.out.println("  [D] Got response: " + (resp == null ? "null" : resp.getClass().getName()));
                if (resp != null) {
                    parseCmdResponse(resp);
                    return true;
                }
            } else {
                System.out.println("  [D] execute(ICmdWriteRequest) not found");
            }
        } catch (Throwable t) {
            System.out.println("  [D] execute(ICmdWriteRequest): " + rootMsg(t));
        }

        return false;
    }

    /**
     * Method E: Via MmlPPURouteServerService.synSendMML(mml, path)
     */
    static boolean sendViaRouteServer(Object namingCtx, String server, String user,
                                       int sessionID, int userID, String mmlCmd) throws Exception {
        System.out.println("  [E] Trying MmlPPURouteServerService...");
        Method lookupStr = namingCtx.getClass().getMethod("lookup", String.class);

        Object routeService = null;
        String[] jndiNames = {
            "MmlPPURouteServerService", "mmlPPURouteServerService",
            "ejb/MmlPPURouteServerService", "PPURouteServer",
            "RouteServerService"
        };
        for (String name : jndiNames) {
            try {
                Object home = lookupStr.invoke(namingCtx, name);
                System.out.println("  [E] Found JNDI: " + name + " -> " + home.getClass().getName());
                try {
                    routeService = home.getClass().getMethod("create").invoke(home);
                } catch (Throwable t2) {
                    routeService = home;
                }
                break;
            } catch (Throwable t) {
                // try next
            }
        }
        if (routeService == null) {
            System.out.println("  [E] MmlPPURouteServerService not found in JNDI");
            return false;
        }

        System.out.println("  [E] Service class: " + routeService.getClass().getName());

        // Try synSendMML(String mml, String path)
        for (String path : new String[]{"", "LOCAL_VERSION", "moc=EmbMml"}) {
            try {
                System.out.println("  [E] synSendMML(mml, path=\"" + path + "\")...");
                Method synMethod = null;
                for (Method m : routeService.getClass().getMethods()) {
                    if (m.getName().equals("synSendMML")) {
                        Class<?>[] pt = m.getParameterTypes();
                        if (pt.length == 2 && pt[0] == String.class && pt[1] == String.class) {
                            synMethod = m;
                            break;
                        }
                    }
                }
                if (synMethod == null) {
                    System.out.println("  [E] synSendMML(String,String) not found");
                    break;
                }
                Object resp = synMethod.invoke(routeService, mmlCmd, path);
                System.out.println("  [E] Got response: " + (resp == null ? "null" : resp.getClass().getName()));
                if (resp != null) {
                    parseOutputmml(resp);
                    return true;
                }
            } catch (Throwable t) {
                System.out.println("  [E] synSendMML(path=\"" + path + "\"): " + rootMsg(t));
            }
        }
        return false;
    }

    /**
     * Method F: Via Inputmml + EMessage (EMB path, like the GUI MML terminal)
     * Uses PPUServerService.inputMML2Request + execute + Response2OutputMML
     */
    static boolean sendViaInputmmlEMB(Object namingCtx, String server, String user,
                                       int sessionID, int userID, String sessionCode, String mmlCmd) throws Exception {
        System.out.println("  [F] Trying Inputmml + EMB path...");
        Method lookupStr = namingCtx.getClass().getMethod("lookup", String.class);

        // First find the PPU service
        Object ppuService = null;
        String[] jndiNames = {"MmlPPUServerService", "PPUServerService"};
        for (String name : jndiNames) {
            try {
                Object home = lookupStr.invoke(namingCtx, name);
                try { ppuService = home.getClass().getMethod("create").invoke(home); }
                catch (Throwable t) { ppuService = home; }
                break;
            } catch (Throwable t) { /* try next */ }
        }
        if (ppuService == null) {
            System.out.println("  [F] PPU service not found");
            return false;
        }

        // Create Inputmml
        Class<?> inputMmlCls = Class.forName("com.zte.ums.api.common.mml.ppu.entity.common.embentity.Inputmml");
        Object inputMml = inputMmlCls.newInstance();
        inputMmlCls.getMethod("setMml", String.class).invoke(inputMml, mmlCmd);
        inputMmlCls.getMethod("setUsername", String.class).invoke(inputMml, user);
        inputMmlCls.getMethod("setSessionid", long.class).invoke(inputMml, (long) sessionID);
        inputMmlCls.getMethod("setIsAsynCmd", boolean.class).invoke(inputMml, Boolean.FALSE);
        inputMmlCls.getMethod("setTimeout", int.class).invoke(inputMml, 60000);
        inputMmlCls.getMethod("setIsCheckDangerousCommand", boolean.class).invoke(inputMml, Boolean.FALSE);

        // Try inputMML2Request(Inputmml, EMessage)
        try {
            Method i2r = null;
            for (Method m : ppuService.getClass().getMethods()) {
                if (m.getName().equals("inputMML2Request")) { i2r = m; break; }
            }
            if (i2r != null) {
                System.out.println("  [F] inputMML2Request found, calling with null EMessage...");
                Object req = i2r.invoke(ppuService, inputMml, null);
                System.out.println("  [F] Request: " + (req == null ? "null" : req.getClass().getName()));
                if (req != null) {
                    // Execute the request
                    Method execMethod = null;
                    for (Method m : ppuService.getClass().getMethods()) {
                        if (m.getName().equals("execute") && m.getParameterTypes().length == 1) {
                            execMethod = m; break;
                        }
                    }
                    if (execMethod != null) {
                        Object resp = execMethod.invoke(ppuService, req);
                        if (resp != null) {
                            // Convert to Outputmml
                            try {
                                Method r2o = ppuService.getClass().getMethod("Response2OutputMML",
                                    Class.forName("com.zte.ums.api.common.mml.ppu.entity.common.ICmdResponse"));
                                Object outMml = r2o.invoke(ppuService, resp);
                                if (outMml != null) {
                                    parseOutputmml(outMml);
                                    return true;
                                }
                            } catch (Throwable t) {
                                parseCmdResponse(resp);
                                return true;
                            }
                        }
                    }
                }
            }
        } catch (Throwable t) {
            System.out.println("  [F] inputMML2Request: " + rootMsg(t));
        }
        return false;
    }

    /**
     * Method G: Enumerate JNDI to discover available MML-related services
     */
    static void enumerateJndiServices(Object namingCtx) throws Exception {
        System.out.println("  [G] Enumerating JNDI services...");
        Method lookupStr = namingCtx.getClass().getMethod("lookup", String.class);

        String[] candidates = {
            "MmlPPUServerService", "MmlPPURouteServerService",
            "MmlPPUInfoService", "MmlPPUMessageService", "MmlPPUClisClientService",
            "MmlPPUInfoLoadServerService",
            "PPUServerService", "PPURouteServerService", "PPUInfoService",
            "PPUMessageService", "PPUResManager",
            "mmlPPUServerService", "mmlPPURouteServerService",
            "ejb/MmlPPUServerService", "ejb/MmlPPURouteServerService",
            "FServerManager", "FServerBroker",
            "uep.fi.heartbeatreciever",
            "uep.pfl.embservice",
            "MmlPPU", "PPU"
        };

        for (String name : candidates) {
            try {
                Object obj = lookupStr.invoke(namingCtx, name);
                String cls = obj == null ? "null" : obj.getClass().getName();
                System.out.println("  [G] FOUND: " + name + " -> " + cls);
                // List methods for interesting ones
                if (obj != null && name.toLowerCase().contains("mml")) {
                    for (Method m : obj.getClass().getMethods()) {
                        if (m.getName().equals("create")) {
                            try {
                                Object ejb = m.invoke(obj);
                                System.out.println("  [G]   create() -> " + ejb.getClass().getName());
                            } catch (Throwable ignore) {}
                        }
                    }
                }
            } catch (Throwable t) {
                // Not found
            }
        }
    }

    // ==================== Response Parsing ====================

    static void parseOutputmml(Object outMml) {
        System.out.println("\n  === Outputmml Result ===");
        try {
            boolean ok = (Boolean) outMml.getClass().getMethod("getIsCheckSuccess").invoke(outMml);
            long errCode = (Long) outMml.getClass().getMethod("getErrorCode").invoke(outMml);
            String errInfo = (String) outMml.getClass().getMethod("getErrorInfo").invoke(outMml);
            String ackmml = (String) outMml.getClass().getMethod("getAckmml").invoke(outMml);
            String filePath = (String) outMml.getClass().getMethod("getLargeDataFileName").invoke(outMml);
            boolean isLarge = (Boolean) outMml.getClass().getMethod("getIsLargeData").invoke(outMml);
            long netypeid = (Long) outMml.getClass().getMethod("getNetypeid").invoke(outMml);
            long sessionid = (Long) outMml.getClass().getMethod("getSessionid").invoke(outMml);

            System.out.println("  success=" + ok);
            System.out.println("  errorCode=" + errCode);
            if (errInfo != null && !errInfo.isEmpty()) System.out.println("  errorInfo=" + errInfo);
            System.out.println("  netypeid=" + netypeid + " sessionid=" + sessionid);
            if (isLarge) System.out.println("  largeDataFile=" + filePath);
            if (ackmml != null && !ackmml.isEmpty()) {
                System.out.println("  --- MML Result ---");
                System.out.println(ackmml.length() > 5000 ? ackmml.substring(0, 5000) + "\n  ... (truncated, total " + ackmml.length() + " chars)" : ackmml);
            }
        } catch (Throwable t) {
            System.out.println("  parse error: " + t);
        }
    }

    static void parseCmdResponse(Object resp) {
        System.out.println("\n  === ICmdResponse Result ===");
        try {
            long resultCode = (Long) resp.getClass().getMethod("getResultCode").invoke(resp);
            String errDetail = (String) resp.getClass().getMethod("getErrorDetailInfo").invoke(resp);
            System.out.println("  resultCode=" + resultCode);
            if (errDetail != null && !errDetail.isEmpty()) System.out.println("  errorDetail=" + errDetail);

            // Try getAckMML
            try {
                String ack = (String) resp.getClass().getMethod("getAckMML").invoke(resp);
                if (ack != null && !ack.isEmpty()) {
                    System.out.println("  --- MML Result ---");
                    System.out.println(ack.length() > 5000 ? ack.substring(0, 5000) + "\n  ... (truncated)" : ack);
                }
            } catch (Throwable ignore) {}

            // Try getCmdno
            try {
                int cmdno = (Integer) resp.getClass().getMethod("getCmdno").invoke(resp);
                System.out.println("  cmdno=" + cmdno);
            } catch (Throwable ignore) {}
        } catch (Throwable t) {
            System.out.println("  parse error: " + t);
        }
        // Also try toString
        try {
            String ts = resp.toString();
            if (ts != null && !ts.contains("@")) {
                System.out.println("  toString: " + ts.substring(0, Math.min(2000, ts.length())));
            }
        } catch (Throwable ignore) {}
    }

    // ==================== 工具方法 ====================

    static String callStr(Object o, String getter) {
        try { Object v = o.getClass().getMethod(getter).invoke(o); return v == null ? "" : String.valueOf(v); }
        catch (Exception e) { return null; }
    }

    static String rootMsg(Throwable e) {
        if (e instanceof InvocationTargetException) e = ((InvocationTargetException) e).getTargetException();
        Throwable r = e; while (r.getCause() != null) r = r.getCause();
        return r.getClass().getSimpleName() + ": " + r.getMessage();
    }

    static Object decodeCompressedResponse(Object resp) {
        try {
            Object sec = resp.getClass().getMethod("getFISectionAt", int.class).invoke(resp, 0);
            Object payload = sec.getClass().getMethod("getObject").invoke(sec);
            if (!(payload instanceof byte[])) return null;
            byte[] raw = (byte[]) payload;
            java.io.ByteArrayInputStream bin = new java.io.ByteArrayInputStream(raw);
            InputStream src = bin;
            if (raw.length > 2 && (raw[0] & 0xFF) == 0x1F && (raw[1] & 0xFF) == 0x8B) {
                src = new java.util.zip.GZIPInputStream(bin);
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

    static String getLocalIp(String server) {
        try {
            java.net.Socket s = new java.net.Socket();
            s.connect(new java.net.InetSocketAddress(server, JNP_PORT), 3000);
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
        return System.getProperty("ems.clientmac", "FC4CEA20EE49");
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
}
