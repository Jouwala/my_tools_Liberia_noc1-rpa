import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.DESKeySpec;
import javax.crypto.SecretKeyFactory;

/**
 * EmsMmlTest2 - Direct EMB framework initialization + MML send
 *
 * Approach: Instantiate EmbServiceImpl, initialize BSF, then send MML.
 */
public class EmsMmlTest2 {

    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    static final int JNP_PORT = 21100;

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

        System.out.println("=== ZTE U31 EMS MML Test (Direct EMB) ===");
        System.out.println("Server=" + server + " user=" + user);
        System.out.println("MML: " + mmlCmd);

        // Step 1: Login
        Object namingStub = getNamingStub(server, JNP_PORT);
        Method lookupName = namingStub.getClass().getMethod("lookup", String.class, javax.naming.Name.class);
        Object resultPair = lookupName.invoke(namingStub, "jndi_client", new javax.naming.CompoundName("", new Properties()));
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

        // Heartbeat
        try {
            Object hbStub = lookupStr.invoke(namingCtx, "uep.fi.heartbeatreciever");
            hbStub.getClass().getMethod("setSessionStateOK", short.class).invoke(hbStub, (short) sessionID);
            System.out.println("[1b] heartbeat OK");
        } catch (Throwable t) { System.out.println("[1b] heartbeat: " + rootMsg(t)); }

        // Step 2: Try to instantiate EmbServiceImpl directly
        System.out.println("\n[2] Instantiating EmbServiceImpl...");
        Object embService = null;
        try {
            Class<?> embImplCls = Class.forName("com.zte.ums.uep.pfl.emb.service.EmbServiceImpl");
            embService = embImplCls.newInstance();
            System.out.println("[2] EmbServiceImpl created: " + embService.getClass().getName());
        } catch (Throwable t) {
            System.out.println("[2] EmbServiceImpl failed: " + rootMsg(t));
        }

        // Step 3: Try EMBMmlServiceImpl
        System.out.println("\n[3] Instantiating EMBMmlServiceImpl...");
        Object mmlService = null;
        try {
            Class<?> mmlImplCls = Class.forName("com.zte.ums.uep.pfl.embmml.service.EMBMmlServiceImpl");
            mmlService = mmlImplCls.newInstance();
            System.out.println("[3] EMBMmlServiceImpl created: " + mmlService.getClass().getName());
        } catch (Throwable t) {
            System.out.println("[3] EMBMmlServiceImpl failed: " + rootMsg(t));
        }

        // Step 4: Try to convert MML to EMessage
        if (mmlService != null) {
            System.out.println("\n[4] Converting MML to EMessage...");
            try {
                Method convertMethod = mmlService.getClass().getMethod("convertMmlToEMessage", String.class, String.class);
                Object eMsg = convertMethod.invoke(mmlService, mmlCmd, "emb");
                System.out.println("[4] EMessage: " + (eMsg == null ? "null" : eMsg.getClass().getName()));
                if (eMsg != null) {
                    // Print EMessage details
                    printEMessageDetails(eMsg);
                }
            } catch (Throwable t) {
                System.out.println("[4] convertMmlToEMessage: " + rootMsg(t));
                // Try with different appType
                for (String appType : new String[]{"LOCAL_VERSION", "emb", "uca-mml", ""}) {
                    try {
                        Method convertMethod = mmlService.getClass().getMethod("convertMmlToEMessage", String.class, String.class);
                        Object eMsg = convertMethod.invoke(mmlService, mmlCmd, appType);
                        System.out.println("[4] appType=" + appType + " -> success!");
                        if (eMsg != null) printEMessageDetails(eMsg);
                        break;
                    } catch (Throwable t2) {
                        System.out.println("[4] appType=" + appType + " -> " + rootMsg(t2));
                    }
                }
            }

            // Try getCommandCodeByMML
            try {
                Method getCode = Class.forName("com.zte.ums.uep.pfl.embmml.service.EMBMmlServiceImpl")
                    .getMethod("getCommandCodeByMML", String.class);
                Object code = getCode.invoke(null, mmlCmd);
                System.out.println("[4b] Command code for '" + mmlCmd + "': " + code);
            } catch (Throwable t) {
                System.out.println("[4b] getCommandCodeByMML: " + rootMsg(t));
            }
        }

        // Step 5: Try syncRequest
        if (embService != null) {
            System.out.println("\n[5] Trying EMBService methods...");
            // List methods
            for (Method m : embService.getClass().getMethods()) {
                if (m.getName().equals("syncRequest") || m.getName().equals("newEMessage")
                    || m.getName().equals("new3XEMessage")) {
                    System.out.println("[5]   " + m.getName() + "(" + Arrays.toString(m.getParameterTypes()) + ")");
                }
            }

            // Try newEMessage with different command codes
            for (int code : new int[]{5000010, 5000020, 5000002, 5000001, 5000000}) {
                try {
                    Method newMsg = embService.getClass().getMethod("newEMessage", int.class);
                    Object eMsg = newMsg.invoke(embService, code);
                    System.out.println("[5] newEMessage(" + code + ") -> " + (eMsg == null ? "null" : eMsg.getClass().getName()));
                    if (eMsg != null) {
                        // Try syncRequest
                        try {
                            Method syncReq = embService.getClass().getMethod("syncRequest",
                                Class.forName("com.zte.ums.uep.api.pfl.emb.EMessage"));
                            System.out.println("[5] Calling syncRequest with code=" + code + "...");
                            Object resp = syncReq.invoke(embService, eMsg);
                            System.out.println("[5] Response: " + (resp == null ? "null" : resp.getClass().getName()));
                            if (resp != null) printEMessageDetails(resp);
                        } catch (Throwable t) {
                            System.out.println("[5] syncRequest(" + code + "): " + rootMsg(t));
                        }
                    }
                } catch (Throwable t) {
                    System.out.println("[5] newEMessage(" + code + "): " + rootMsg(t));
                }
            }
        }

        // Step 6: Try FServerBroker with different command codes
        System.out.println("\n[6] Trying FServerBroker with different command codes...");
        try {
            Object fsbObj = lookupStr.invoke(namingCtx, "FServerBroker");
            Object fsbEjb = fsbObj.getClass().getMethod("create").invoke(fsbObj);
            System.out.println("[6] FServerBroker: " + fsbEjb.getClass().getName());

            for (int code : new int[]{5000010, 5000020, 5000002, 5000001, 5000000, 2720, 2700}) {
                try {
                    Class<?> fiMsgCls = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage");
                    Object fiMsg = fiMsgCls.getConstructor(int.class).newInstance(code);
                    fiMsgCls.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
                    fiMsgCls.getMethod("setValue", String.class, String.class).invoke(fiMsg, "SessionID", String.valueOf(sessionID));
                    fiMsgCls.getMethod("setValue", String.class, String.class).invoke(fiMsg, "UserID", String.valueOf(userID));
                    fiMsgCls.getMethod("setInvokeID", int.class).invoke(fiMsg, 200000 + new Random().nextInt(800000));

                    // Wrap
                    Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
                    Method wrapM = msgUtilCls.getMethod("getWrappedMessage", fiMsgCls, int.class);
                    Object outer = wrapM.invoke(null, fiMsg, 1);

                    // Send via requestx
                    Method reqM = null;
                    for (Method m : fsbEjb.getClass().getMethods())
                        if (m.getName().equals("requestx")) { reqM = m; break; }
                    System.out.println("[6] Trying code=" + code + "...");
                    Object resp = reqM.invoke(fsbEjb, outer);
                    System.out.println("[6] code=" + code + " -> response: " + (resp == null ? "null" : resp.getClass().getName()));
                    if (resp != null) {
                        printFIMessageDetails(resp, fiMsgCls);
                    }
                } catch (Throwable t) {
                    String msg = rootMsg(t);
                    if (msg.contains("Can not find command")) {
                        System.out.println("[6] code=" + code + " -> NOT FOUND");
                    } else {
                        System.out.println("[6] code=" + code + " -> " + msg);
                    }
                }
            }
        } catch (Throwable t) {
            System.out.println("[6] FServerBroker: " + rootMsg(t));
        }

        try { namingCtx.getClass().getMethod("close").invoke(namingCtx); } catch (Exception ignore) {}
        System.out.println("\n=== Done ===");
    }

    static void printEMessageDetails(Object eMsg) {
        try {
            System.out.println("  class: " + eMsg.getClass().getName());
            // Try common getters
            for (String getter : new String[]{"getCode", "getCommandCode", "getMsgCode",
                "getSource", "getDestination", "toString"}) {
                try {
                    Object v = eMsg.getClass().getMethod(getter).invoke(eMsg);
                    if (v != null) {
                        String s = String.valueOf(v);
                        System.out.println("  " + getter + " = " + (s.length() > 500 ? s.substring(0, 500) + "..." : s));
                    }
                } catch (Throwable ignore) {}
            }
            // List all methods
            for (Method m : eMsg.getClass().getMethods()) {
                String n = m.getName();
                if ((n.startsWith("get") || n.startsWith("is")) && m.getParameterTypes().length == 0) {
                    try {
                        Object v = m.invoke(eMsg);
                        if (v != null) {
                            String s = String.valueOf(v);
                            if (s.length() < 200 && !s.contains("@")) {
                                System.out.println("  " + n + " = " + s);
                            }
                        }
                    } catch (Throwable ignore) {}
                }
            }
        } catch (Throwable t) {
            System.out.println("  error: " + t);
        }
    }

    static void printFIMessageDetails(Object resp, Class<?> fiMsgCls) {
        try {
            // Try to unwrap
            Class<?> msgUtilCls = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
            try {
                Method unw = msgUtilCls.getMethod("getUnwrappedMessage", fiMsgCls);
                Object inner = unw.invoke(null, resp);
                if (inner != null) {
                    System.out.println("  unwrapped: " + inner.getClass().getName());
                    // Get values
                    for (String key : new String[]{"errID", "errDesc", "result", "ackmml", "SessionID"}) {
                        try {
                            Object v = inner.getClass().getMethod("getValue", String.class).invoke(inner, key);
                            if (v != null) System.out.println("  " + key + " = " + String.valueOf(v).substring(0, Math.min(200, String.valueOf(v).length())));
                        } catch (Throwable ignore) {}
                    }
                }
            } catch (Throwable ignore) {}
        } catch (Throwable ignore) {}
    }

    // ==================== Utility methods (same as EmsMmlCommand) ====================

    static String rootMsg(Throwable e) {
        if (e instanceof InvocationTargetException) e = ((InvocationTargetException) e).getTargetException();
        Throwable r = e; while (r.getCause() != null) r = r.getCause();
        return r.getClass().getSimpleName() + ": " + r.getMessage();
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
        byte[] encrypted = cipher.doFinal(input.getBytes("UTF-8"), 0, input.getBytes("UTF-8").length);
        StringBuffer sb = new StringBuffer();
        for (byte b : encrypted) {
            String hex = Integer.toHexString(b & 0xFF);
            if (hex.length() == 1) sb.append("0");
            sb.append(hex);
        }
        return sb.toString().toUpperCase();
    }
}
