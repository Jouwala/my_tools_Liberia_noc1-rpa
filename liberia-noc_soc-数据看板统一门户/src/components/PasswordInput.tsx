import React, { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { useI18n } from '../i18n';

/**
 * 带「显示/隐藏」切换的密码输入框。
 * 说明：服务端只保存 scrypt 加盐哈希，任何地方都不存在明文密码可读；
 * 这里的显示仅作用在你正在输入的框里，方便确认没打错。
 *
 * 注意：className 建议自带 pr-10，给右侧眼睛按钮留出空间。
 */
type PasswordInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  /** 眼睛按钮的 aria-label / data-testid 后缀，便于端到端脚本定位 */
  toggleId?: string;
};

export const PasswordInput: React.FC<PasswordInputProps> = ({
  className = '',
  toggleId,
  ...rest
}) => {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const label = visible ? t('pwd.hide') : t('pwd.show');

  return (
    <div className="relative">
      <input {...rest} type={visible ? 'text' : 'password'} className={className} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        title={label}
        aria-label={label}
        aria-pressed={visible}
        data-password-toggle={toggleId ?? ''}
        tabIndex={-1}
        className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded-md text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
};
