import java.net.*;
import java.io.*;
import java.util.*;
import java.lang.reflect.*;
import javax.naming.*;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.DESKeySpec;
import javax.crypto.SecretKeyFactory;

/**
 * EMS KPI v4 - Wrap FIMessage + set parameters
 */
public class EmsKpiBroker4 {
    
    static final byte[] DES_RAW_KEY = {
        (byte)0xF1, (byte)0xF7, (byte)0xDF, (byte)0x9D,
        (byte)0x91, (byte)0xF7, (byte)0x3D, (byte)0xA7
    };
    
    public static void main(String[] args) throws Exception {
        String server = "10.100.2.240";
        System.out.println("=== EMS KPI v4 - Wrapped + Params ===");
        
        // Step 1: Bootstrap
        Object namingStub = getNamingStub(server, 21100);
        Method lookupName = namingStub.getClass().getMethod("lookup", String.class, Name.class);
        Object resultPair = lookupName.invoke(namingStub, "jndi_client", new CompoundName("", new Properties()));
        Object namingCtx = resultPair.getClass().getMethod("getResultValue").invoke(resultPair);
        
        // Step 2: Login
        System.out.println("[1] Login...");
        Object fsmObj = namingCtx.getClass().getMethod("lookup", String.class).invoke(namingCtx, "FServerManager");
        Object ejbObject = fsmObj.getClass().getMethod("create").invoke(fsmObj);
        Method loginMethod = null;
        for (Method m : ejbObject.getClass().getMethods()) {
            if (m.getName().equals("login")) { loginMethod = m; break; }
        }
        Class<?>[] paramTypes = loginMethod.getParameterTypes();
        Object[] params = new Object[paramTypes.length];
        params[0] = "oss";
        params[1] = desEncrypt("Tool123");
        for (int i = 2; i < paramTypes.length; i++) {
            if (paramTypes[i] == Integer.class || paramTypes[i] == int.class) params[i] = 1;
            else if (paramTypes[i] == Properties.class) params[i] = new Properties();
        }
        Object loginResult = loginMethod.invoke(ejbObject, params);
        int errID = (Integer) loginResult.getClass().getMethod("getErrID").invoke(loginResult);
        short sessionID = (Short) loginResult.getClass().getMethod("getSessionID").invoke(loginResult);
        int userID = (Integer) loginResult.getClass().getMethod("getUserID").invoke(loginResult);
        String sessionCode = (String) loginResult.getClass().getMethod("getSessionCode").invoke(loginResult);
        System.out.println("  errID=" + errID + " sessionID=" + sessionID + " userID=" + userID);
        System.out.println("  sessionCode=" + sessionCode);
        if (errID != 0) { System.out.println("  FAILED!"); return; }
        
        // Step 3: Lookup FServerBroker
        Object fsbObj = namingCtx.getClass().getMethod("lookup", String.class).invoke(namingCtx, "FServerBroker");
        Object fsbEjb = fsbObj.getClass().getMethod("create").invoke(fsbObj);
        
        Class<?> fiMsgClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIMessage");
        Class<?> fiParaClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIParaSection");
        Class<?> fiRecClass = Class.forName("com.zte.ums.uep.api.pfl.finterface.FIRecSection");
        Class<?> msgUtilClass = Class.forName("com.zte.ums.uep.pfl.finterface.common.MsgUtil");
        
        Method requestxMethod = null;
        for (Method m : fsbEjb.getClass().getMethods()) {
            if (m.getName().equals("requestx")) { requestxMethod = m; break; }
        }
        
        // Get command info
        Method getCmdInfo = null;
        for (Method m : ejbObject.getClass().getMethods()) {
            if (m.getName().equals("getCommandInfo")) { getCmdInfo = m; break; }
        }
        
        // Step A: Get all MO types via command 2600
        System.out.println("\n=== Step A: Get MO types (cmd 2600) ===");
        Object[] moTypes = null;
        try {
            Object cmdElem = getCmdInfo.invoke(ejbObject, 2600);
            String ver = (String) cmdElem.getClass().getMethod("getVersion").invoke(cmdElem);
            Object fiMsg = fiMsgClass.getConstructor(int.class, String.class, int.class)
                .newInstance(2600, ver, (int)sessionID);
            fiMsgClass.getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
            fiMsgClass.getMethod("setUserID", int.class).invoke(fiMsg, userID);
            fiMsgClass.getMethod("setUserName", String.class).invoke(fiMsg, "oss");
            fiMsgClass.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
            Object paraSection = fiParaClass.getConstructor().newInstance();
            fiMsgClass.getMethod("addFISection", Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection")).invoke(fiMsg, paraSection);
            Object wrappedMsg = msgUtilClass.getMethod("getWrappedMessage", fiMsgClass).invoke(null, fiMsg);
            Object response = requestxMethod.invoke(fsbEjb, wrappedMsg);
            Object unwrappedResp = msgUtilClass.getMethod("getUnwrappedMessage", fiMsgClass).invoke(null, response);
            // Extract MO types array
            Object section = fiMsgClass.getMethod("getFISectionAt", int.class).invoke(unwrappedResp, 0);
            Object obj = section.getClass().getMethod("getObject").invoke(section);
            if (obj instanceof Object[]) {
                moTypes = (Object[]) obj;
                System.out.println("  Got " + moTypes.length + " MO types");
                // Print first 20 with their IDs
                for (int i = 0; i < Math.min(moTypes.length, 20); i++) {
                    Object elem = moTypes[i];
                    String id = getFieldVal(elem, "id");
                    String name = getFieldVal(elem, "name");
                    int flag = 0;
                    try { flag = (Integer) elem.getClass().getDeclaredField("moTypeFlag").get(elem); } catch (Exception ex) {}
                    System.out.println("  [" + i + "] id=" + id + " name=" + name + " flag=" + flag);
                }
            }
        } catch (Exception e) {
            Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
            System.out.println("  ERROR: " + cause);
        }
        
        // Step B: Try command 2614 with various parameter names using actual MO type ID
        if (moTypes != null && moTypes.length > 0) {
            // Find a good MO type to test with (prefer NE type, flag=2 means FIXED_MOTYPE)
            String testMoTypeId = null;
            String testMoTypeName = null;
            for (Object mt : moTypes) {
                String id = getFieldVal(mt, "id");
                String name = getFieldVal(mt, "name");
                if (id != null && !id.contains("server") && !id.contains("firewall") && !id.contains("apache")) {
                    testMoTypeId = id;
                    testMoTypeName = name;
                    break;
                }
            }
            if (testMoTypeId == null) { testMoTypeId = getFieldVal(moTypes[0], "id"); testMoTypeName = getFieldVal(moTypes[0], "name"); }
            System.out.println("\n=== Step B: Try cmd 2614 with MO type: " + testMoTypeId + " (" + testMoTypeName + ") ===");
            
            // Try various parameter name combinations and formats
            String[][] paramNameVariants = {
                {"motypeid", testMoTypeId, "simple"},
                {"MoTypeId", testMoTypeId, "simple"},
                {"mo_type_id", testMoTypeId, "simple"},
                {"MOTypeId", testMoTypeId, "simple"},
                {"motype", testMoTypeId, "simple"},
                {"MoType", testMoTypeId, "simple"},
                {"motypeID", testMoTypeId, "simple"},
                {"MOTYPEID", testMoTypeId, "simple"},
                {"id", testMoTypeId, "simple"},
                {"MOType", testMoTypeName, "simple"},
                {"name", testMoTypeName, "simple"},
                {"motypeid", testMoTypeId, "array"},
                {"MoTypeId", testMoTypeId, "array"},
                {"moTypeId", testMoTypeId, "array"},
                {"MO_TYPE_ID", testMoTypeId, "array"},
                {"moType", testMoTypeId, "array"},
                {"MoType", testMoTypeName, "array"},
            };
            
            Object cmdElem2614 = getCmdInfo.invoke(ejbObject, 2614);
            String ver2614 = (String) cmdElem2614.getClass().getMethod("getVersion").invoke(cmdElem2614);
            
            for (String[] pv : paramNameVariants) {
                try {
                    Object fiMsg = fiMsgClass.getConstructor(int.class, String.class, int.class)
                        .newInstance(2614, ver2614, (int)sessionID);
                    fiMsgClass.getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
                    fiMsgClass.getMethod("setUserID", int.class).invoke(fiMsg, userID);
                    fiMsgClass.getMethod("setUserName", String.class).invoke(fiMsg, "oss");
                    fiMsgClass.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
                    
                    Object paraSection = fiParaClass.getConstructor().newInstance();
                    if ("array".equals(pv[2])) {
                        fiParaClass.getMethod("setParaValue", String.class, String[].class)
                            .invoke(paraSection, pv[0], new String[]{pv[1]});
                    } else {
                        fiParaClass.getMethod("setSimpleParaValue", String.class, String.class)
                            .invoke(paraSection, pv[0], pv[1]);
                    }
                    fiMsgClass.getMethod("addFISection", Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection"))
                        .invoke(fiMsg, paraSection);
                    
                    Object wrappedMsg = msgUtilClass.getMethod("getWrappedMessage", fiMsgClass).invoke(null, fiMsg);
                    
                    try {
                        Object response = requestxMethod.invoke(fsbEjb, wrappedMsg);
                        Object unwrappedResp = msgUtilClass.getMethod("getUnwrappedMessage", fiMsgClass).invoke(null, response);
                        int errID2 = (Integer) unwrappedResp.getClass().getMethod("getErrID").invoke(unwrappedResp);
                        int secCount = (Integer) unwrappedResp.getClass().getMethod("getSectionCount").invoke(unwrappedResp);
                        System.out.println("  param[" + pv[2] + "] " + pv[0] + "=" + pv[1] + " => errID=" + errID2 + " sections=" + secCount + " *** SUCCESS ***");
                        printResponse(unwrappedResp, fiMsgClass);
                        break;
                    } catch (Exception e) {
                        Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
                        String msg = cause.getMessage();
                        // Get the first line of the error
                        if (msg != null && msg.contains("\n")) msg = msg.substring(0, msg.indexOf('\n'));
                        System.out.println("  param[" + pv[2] + "] " + pv[0] + "=" + pv[1] + " => ERROR: " + cause.getClass().getSimpleName() + ": " + msg);
                        // Print first cause
                        Throwable c2 = cause.getCause();
                        if (c2 != null) {
                            StackTraceElement[] st = c2.getStackTrace();
                            String loc = st.length > 0 ? st[0].toString() : "";
                            System.out.println("    cause: " + c2.getClass().getSimpleName() + " at " + loc);
                        }
                    }
                } catch (Exception e) {
                    System.out.println("  param=" + pv[0] + " SETUP ERROR: " + e.getMessage());
                }
            }
        }
        
        // Step C: Try other approaches
        System.out.println("\n=== Step C: Try cmd 2611 (getPmIndexById) ===");
        try {
            Object cmdElem2611 = getCmdInfo.invoke(ejbObject, 2611);
            String ver2611 = (String) cmdElem2611.getClass().getMethod("getVersion").invoke(cmdElem2611);
            System.out.println("  Code 2611 ver=" + ver2611);
            
            Object fiMsg = fiMsgClass.getConstructor(int.class, String.class, int.class)
                .newInstance(2611, ver2611, (int)sessionID);
            fiMsgClass.getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
            fiMsgClass.getMethod("setUserID", int.class).invoke(fiMsg, userID);
            fiMsgClass.getMethod("setUserName", String.class).invoke(fiMsg, "oss");
            fiMsgClass.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
            
            Object paraSection = fiParaClass.getConstructor().newInstance();
            fiParaClass.getMethod("setSimpleParaValue", String.class, String.class)
                .invoke(paraSection, "indexid", "1");
            fiMsgClass.getMethod("addFISection", Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection"))
                .invoke(fiMsg, paraSection);
            
            Object wrappedMsg = msgUtilClass.getMethod("getWrappedMessage", fiMsgClass).invoke(null, fiMsg);
            try {
                Object response = requestxMethod.invoke(fsbEjb, wrappedMsg);
                Object unwrappedResp = msgUtilClass.getMethod("getUnwrappedMessage", fiMsgClass).invoke(null, response);
                printResponse(unwrappedResp, fiMsgClass);
            } catch (Exception e) {
                Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
                printException("2611", cause);
            }
        } catch (Exception e) {
            System.out.println("  ERROR: " + e.getMessage());
        }
        
        // Step D: Try cmd 2614 with requestxForNonGUI for better error details
        System.out.println("\n=== Step D: cmd 2614 via requestxForNonGUI ===");
        try {
            Method requestxNonGUI = null;
            for (Method m : fsbEjb.getClass().getMethods()) {
                if (m.getName().equals("requestxForNonGUI")) { requestxNonGUI = m; break; }
            }
            
            Object cmdElem2614 = getCmdInfo.invoke(ejbObject, 2614);
            String ver2614 = (String) cmdElem2614.getClass().getMethod("getVersion").invoke(cmdElem2614);
            
            Object fiMsg = fiMsgClass.getConstructor(int.class, String.class, int.class)
                .newInstance(2614, ver2614, (int)sessionID);
            fiMsgClass.getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
            fiMsgClass.getMethod("setUserID", int.class).invoke(fiMsg, userID);
            fiMsgClass.getMethod("setUserName", String.class).invoke(fiMsg, "oss");
            fiMsgClass.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
            
            Object paraSection = fiParaClass.getConstructor().newInstance();
            fiParaClass.getMethod("setSimpleParaValue", String.class, String.class)
                .invoke(paraSection, "motypeid", "cn.combommegngpsgsn.92018");
            fiMsgClass.getMethod("addFISection", Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection"))
                .invoke(fiMsg, paraSection);
            
            try {
                Object response = requestxNonGUI.invoke(fsbEjb, fiMsg);
                printResponse(response, fiMsgClass);
            } catch (Exception e) {
                Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
                System.out.println("  NonGUI ERROR: " + cause.getClass().getName() + ": " + cause.getMessage());
                // Print full stack trace
                cause.printStackTrace(System.out);
            }
        } catch (Exception e) {
            System.out.println("  ERROR: " + e.getMessage());
        }
        
        // Step E: Try cmd 2614 with FIRecSection instead of FIParaSection
        System.out.println("\n=== Step E: cmd 2614 with FIRecSection ===");
        try {
            Object cmdElem2614 = getCmdInfo.invoke(ejbObject, 2614);
            String ver2614 = (String) cmdElem2614.getClass().getMethod("getVersion").invoke(cmdElem2614);
            
            Object fiMsg = fiMsgClass.getConstructor(int.class, String.class, int.class)
                .newInstance(2614, ver2614, (int)sessionID);
            fiMsgClass.getMethod("setSessionID", int.class).invoke(fiMsg, (int)sessionID);
            fiMsgClass.getMethod("setUserID", int.class).invoke(fiMsg, userID);
            fiMsgClass.getMethod("setUserName", String.class).invoke(fiMsg, "oss");
            fiMsgClass.getMethod("setValue", String.class, String.class).invoke(fiMsg, "sessioncode", sessionCode);
            
            // Use FIRecSection with motypeid field
            Object recSection = fiRecClass.getConstructor().newInstance();
            fiRecClass.getMethod("setFields", String[].class)
                .invoke(recSection, (Object) new String[]{"motypeid"});
            fiRecClass.getMethod("addRecord", String[].class)
                .invoke(recSection, (Object) new String[]{"cn.combommegngpsgsn.92018"});
            fiMsgClass.getMethod("addFISection", Class.forName("com.zte.ums.uep.api.pfl.finterface.FISection"))
                .invoke(fiMsg, recSection);
            
            Object wrappedMsg = msgUtilClass.getMethod("getWrappedMessage", fiMsgClass).invoke(null, fiMsg);
            try {
                Object response = requestxMethod.invoke(fsbEjb, wrappedMsg);
                Object unwrappedResp = msgUtilClass.getMethod("getUnwrappedMessage", fiMsgClass).invoke(null, response);
                printResponse(unwrappedResp, fiMsgClass);
            } catch (Exception e) {
                Throwable cause = e instanceof InvocationTargetException ? ((InvocationTargetException)e).getTargetException() : e;
                printException("2614+FIRecSection", cause);
            }
        } catch (Exception e) {
            System.out.println("  ERROR: " + e.getMessage());
        }
        
        // Step F: Try cmd 2600 to list ALL MO types and find NE types (flag != 0)
        System.out.println("\n=== Step F: Find NE MO types (flag=2) ===");
        if (moTypes != null) {
            int neCount = 0;
            for (int i = 0; i < moTypes.length && neCount < 10; i++) {
                int flag = 0;
                try { flag = (Integer) moTypes[i].getClass().getDeclaredField("moTypeFlag").get(moTypes[i]); } catch (Exception ex) {}
                if (flag == 2) { // FIXED_MOTYPE
                    String id = getFieldVal(moTypes[i], "id");
                    String name = getFieldVal(moTypes[i], "name");
                    System.out.println("  [" + i + "] id=" + id + " name=" + name + " flag=" + flag);
                    neCount++;
                }
            }
            if (neCount == 0) {
                System.out.println("  No NE types found with flag=2, trying all flags:");
                Map<Integer,Integer> flagCounts = new HashMap<Integer,Integer>();
                for (Object mt : moTypes) {
                    int flag = 0;
                    try { flag = (Integer) mt.getClass().getDeclaredField("moTypeFlag").get(mt); } catch (Exception ex) {}
                    Integer cnt = flagCounts.get(flag);
                    flagCounts.put(flag, cnt == null ? 1 : cnt + 1);
                }
                System.out.println("  Flag distribution: " + flagCounts);
            }
        }
        
        System.out.println("\n=== Done ===");
    }
    
    static void printResponse(Object response, Class<?> fiMsgClass) throws Exception {
        if (response == null) { System.out.println("    Response: null"); return; }
        int respErrID = (Integer) response.getClass().getMethod("getErrID").invoke(response);
        String respErrDesc = (String) response.getClass().getMethod("getErrDesc").invoke(response);
        int sections = (Integer) response.getClass().getMethod("getSectionCount").invoke(response);
        System.out.println("    errID=" + respErrID + " sections=" + sections + " errDesc=" + respErrDesc);
        
        // Print all header values
        try {
            Method getHeaderNames = response.getClass().getMethod("getAllKey");
            Object keys = getHeaderNames.invoke(response);
            if (keys != null) {
                System.out.println("    Header keys: " + keys);
            }
        } catch (Exception e) { /* ignore */ }
        
        Method getSection = fiMsgClass.getMethod("getFISectionAt", int.class);
        for (int s = 0; s < Math.min(sections, 5); s++) {
            Object section = getSection.invoke(response, s);
            String secType = section.getClass().getName();
            System.out.println("    Section[" + s + "] type: " + secType);
            
            // Try FIRecSection methods
            try {
                Method getRecordCount = section.getClass().getMethod("getRecordCount");
                int recCount = (Integer) getRecordCount.invoke(section);
                String[] fields = (String[]) section.getClass().getMethod("getFields").invoke(section);
                System.out.println("    Records: " + recCount + " Fields: " + (fields != null ? Arrays.toString(fields) : "null"));
                Method getRecordAt = section.getClass().getMethod("getRecordAt", int.class);
                for (int r = 0; r < Math.min(recCount, 10); r++) {
                    String[] record = (String[]) getRecordAt.invoke(section, r);
                    if (record != null) {
                        StringBuilder sb = new StringBuilder("      [");
                        for (int j = 0; j < Math.min(record.length, 15); j++) {
                            if (j > 0) sb.append(", ");
                            sb.append(record[j] != null ? record[j] : "null");
                        }
                        if (record.length > 15) sb.append("...(total " + record.length + ")");
                        sb.append("]");
                        System.out.println(sb.toString());
                    }
                }
            } catch (Exception e1) {
                // Try FIParaSection methods
                try {
                    Method getParaNames = section.getClass().getMethod("getParaName");
                    String[] paraNames = (String[]) getParaNames.invoke(section);
                    System.out.println("    ParaNames: " + (paraNames != null ? Arrays.toString(paraNames) : "null"));
                    if (paraNames != null) {
                        for (String pn : paraNames) {
                            try {
                                String val = (String) section.getClass().getMethod("getSimpleParaValue", String.class).invoke(section, pn);
                                System.out.println("      " + pn + " = " + val);
                            } catch (Exception e2) {
                                String[] vals = (String[]) section.getClass().getMethod("getParaValue", String.class).invoke(section, pn);
                                System.out.println("      " + pn + " = [" + (vals != null ? Arrays.toString(vals) : "null") + "]");
                            }
                        }
                    }
                } catch (Exception e3) {
                    // Try FIObjectSection
                    try {
                        Object obj = section.getClass().getMethod("getObject").invoke(section);
                        if (obj != null) {
                            System.out.println("    Object type: " + obj.getClass().getName());
                            if (obj instanceof Object[]) {
                                Object[] arr = (Object[]) obj;
                                System.out.println("    Array length: " + arr.length);
                                // Print fields of first element using reflection
                                if (arr.length > 0 && arr[0] != null) {
                                    Class<?> elemClass = arr[0].getClass();
                                    System.out.println("    Element class: " + elemClass.getName());
                                    java.lang.reflect.Field[] fields = elemClass.getDeclaredFields();
                                    StringBuilder fieldNames = new StringBuilder("    Fields: ");
                                    for (java.lang.reflect.Field f : fields) {
                                        fieldNames.append(f.getName()).append("(").append(f.getType().getSimpleName()).append(") ");
                                    }
                                    System.out.println(fieldNames.toString());
                                    // Print toString of first element
                                    System.out.println("    toString[0]: " + arr[0]);
                                    // Check superclass fields
                                    Class<?> superClass = elemClass.getSuperclass();
                                    if (superClass != null && superClass != Object.class) {
                                        System.out.println("    Superclass: " + superClass.getName());
                                        java.lang.reflect.Field[] superFields = superClass.getDeclaredFields();
                                        StringBuilder sfNames = new StringBuilder("    SuperFields: ");
                                        for (java.lang.reflect.Field sf : superFields) {
                                            sfNames.append(sf.getName()).append("(").append(sf.getType().getSimpleName()).append(") ");
                                        }
                                        System.out.println(sfNames.toString());
                                        // Print super field values for first element
                                        for (java.lang.reflect.Field sf : superFields) {
                                            try {
                                                sf.setAccessible(true);
                                                Object sv = sf.get(arr[0]);
                                                System.out.println("      super." + sf.getName() + " = " + sv);
                                            } catch (Exception ex) {
                                                System.out.println("      super." + sf.getName() + " = ERROR: " + ex);
                                            }
                                        }
                                    }
                                    // Print all instance field values for first 3 elements
                                    for (int i = 0; i < Math.min(arr.length, 3); i++) {
                                        Object elem = arr[i];
                                        System.out.println("    --- Element[" + i + "] ---");
                                        // Print all fields including inherited
                                        Class<?> cls = elem.getClass();
                                        while (cls != null && cls != Object.class) {
                                            java.lang.reflect.Field[] flds = cls.getDeclaredFields();
                                            for (java.lang.reflect.Field f : flds) {
                                                try {
                                                    f.setAccessible(true);
                                                    Object fv = f.get(elem);
                                                    String fname = f.getName();
                                                    // Skip static fields
                                                    if (Modifier.isStatic(f.getModifiers())) continue;
                                                    if (fv instanceof java.util.Map) {
                                                        java.util.Map<?,?> map = (java.util.Map<?,?>) fv;
                                                        System.out.println("      " + cls.getSimpleName() + "." + fname + " = Map(size=" + map.size() + ")");
                                                        int cnt = 0;
                                                        for (java.util.Map.Entry<?,?> entry : map.entrySet()) {
                                                            if (cnt++ >= 5) { System.out.println("        ..."); break; }
                                                            System.out.println("        " + entry.getKey() + " = " + entry.getValue());
                                                        }
                                                    } else {
                                                        System.out.println("      " + cls.getSimpleName() + "." + fname + " = " + fv);
                                                    }
                                                } catch (Exception ex) {
                                                    System.out.println("      " + cls.getSimpleName() + "." + f.getName() + " = ERROR");
                                                }
                                            }
                                            cls = cls.getSuperclass();
                                        }
                                    }
                                }
                            } else if (obj instanceof java.util.List) {
                                java.util.List<?> list = (java.util.List<?>) obj;
                                System.out.println("    List size: " + list.size());
                                for (int i = 0; i < Math.min(list.size(), 10); i++) {
                                    System.out.println("      [" + i + "] " + list.get(i));
                                }
                            } else {
                                System.out.println("    Object: " + obj);
                            }
                        } else {
                            System.out.println("    Object: null");
                        }
                    } catch (Exception e4) {
                        System.out.println("    Section toString: " + section);
                    }
                }
            }
        }
    }
    
    static String getFieldVal(Object obj, String fieldName) {
        Class<?> cls = obj.getClass();
        while (cls != null && cls != Object.class) {
            try {
                java.lang.reflect.Field f = cls.getDeclaredField(fieldName);
                f.setAccessible(true);
                Object val = f.get(obj);
                return val != null ? val.toString() : "null";
            } catch (NoSuchFieldException e) {
                cls = cls.getSuperclass();
            } catch (Exception e) {
                return "?";
            }
        }
        return "?";
    }
    
    static void printException(String label, Throwable t) {
        System.out.println("    " + label + " ERROR: " + t.getClass().getName() + ": " + t.getMessage());
        Throwable cause = t.getCause();
        int depth = 0;
        while (cause != null && depth < 5) {
            System.out.println("    Caused by: " + cause.getClass().getName() + ": " + cause.getMessage());
            StackTraceElement[] st = cause.getStackTrace();
            for (int i = 0; i < Math.min(st.length, 3); i++) {
                System.out.println("      at " + st[i]);
            }
            cause = cause.getCause();
            depth++;
        }
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
}
