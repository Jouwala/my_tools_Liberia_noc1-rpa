import LegacyToolFrame from '../components/LegacyToolFrame'
import { useI18n } from '../i18n'

export default function AlarmManagement() {
  const { t } = useI18n()
  return <LegacyToolFrame file="alarm-management.html" title={t('nav.alarmManagement')} />
}
