import { Tabs } from 'antd'
import { useI18n } from '../i18n'
import CredentialSettings from './CredentialSettings'
import EmailRecipientsSettings from './EmailRecipientsSettings'
import RemoteHostSettings from './RemoteHostSettings'
import AIModelSettings from './AIModelSettings'
import WhatsAppSettings from './WhatsAppSettings'
import TaskConfigTab from './datasync/TaskConfigTab'

export default function Settings() {
  const { t } = useI18n()
  return (
    <Tabs
      defaultActiveKey="credentials"
      items={[
        {
          key: 'credentials',
          label: t('settings.credentialsTab'),
          children: <CredentialSettings />,
        },
        {
          key: 'email',
          label: t('settings.emailTab'),
          children: <EmailRecipientsSettings />,
        },
        {
          key: 'remoteHost',
          label: t('settings.remoteHostTab'),
          children: <RemoteHostSettings />,
        },
        {
          key: 'aiModel',
          label: t('settings.aiModelTab'),
          children: <AIModelSettings />,
        },
        {
          key: 'whatsapp',
          label: t('settings.whatsappTab'),
          children: <WhatsAppSettings />,
        },
        {
          key: 'taskConfig',
          label: t('settings.taskConfigTab'),
          children: <TaskConfigTab />,
        },
      ]}
    />
  )
}
