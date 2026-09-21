import io
p = 'src/App.tsx'
s = io.open(p, encoding='utf-8').read()

s = s.replace(
  "import PortalToast from '../../portal/src/components/PortalToast';",
  "import { ToastCtx } from '../../portal/src/components/Toast';", 1)

s = s.replace(
  "import { ToastCtx } from '../../portal/src/components/Toast';",
  "import { ToastCtx } from '../../portal/src/components/Toast';\nconst TOAST_STORAGE_KEY = 'portal.toast.history';", 1)

s = s.replace("""      <ToastCtx.Provider value={{ toast: showToast, notify, dismissNotify, confirm: askConfirm }}>
        {children}
        <PortalToast />
      </ToastCtx.Provider>""",
"""      <ToastCtx.Provider value={{ toast: showToast, notify, dismissNotify, confirm: askConfirm }}>
        {children}
        <ToastStack />
      </ToastCtx.Provider>""", 1)

io.open(p, 'w', encoding='utf-8', newline='').write(s)
print('import', "PortalToast" in s, 'TOAST_STORAGE_KEY', 'TOAST_STORAGE_KEY' in s, 'ToastStack', '<ToastStack />' in s)
