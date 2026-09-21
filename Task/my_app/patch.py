import io
p = 'frontend/src/pages/MsContractKpiReport.tsx'

def rep(old, new):
    global s
    if old not in s:
        print('MISS:', old[:70].replace('\n','\\n'))
        return False
    s = s.replace(old, new, 1)
    return True

# ---- 卡片：分组标题 + 注册统计项 ----
rep("""    const cards = useMemo(() => {
    if (!ov) return []""".replace('    const','  const'),
"""  const cards = useMemo(() => {
    if (!ov) return []""")

rep("""      {
        key: 'kpi', label: t('msKpi.card.kpiCount'), value: (ov.kpi_count ?? 0).toLocaleString(loc),
        hint: t('msKpi.hint.kpiCount'),
      },""",
"""      {
        key: 'kpi', label: t('msKpi.card.kpiCount'), value: (ov.kpi_count ?? 0).toLocaleString(loc),
        hint: `${t('msKpi.grpScale')} · ${t('msKpi.hint.kpiCount')}`,
      },""")

ok = rep("""        hint: t('msKpi.hint.metKpi'), color: WH.ok,""",
"""        hint: `${t('msKpi.grpStatus')} · ${t('msKpi.hint.metKpi')}`, color: WH.ok,""")

rep("""        hint: t('msKpi.hint.belowKpi'),
        color: (ov.below_count ?? 0) > 0 ? WH.danger : WH.ok,""",
"""        hint: `${t('msKpi.grpStatus')} · ${t('msKpi.hint.belowKpi')}`,
        color: (ov.below_count ?? 0) > 0 ? WH.danger : WH.ok,""")

rep("""        hint: t('msKpi.hint.unknownKpi'), color: WH.textMuted,""",
"""        hint: `${t('msKpi.grpStatus')} · ${t('msKpi.hint.unknownKpi')}`, color: WH.textMuted,""")

rep("""        hint: `${ov.first_day || '-'} ~ ${ov.last_day || '-'}`,""",
"""        hint: `${t('msKpi.grpPeriod')} · ${ov.first_day || '-'} ~ ${ov.last_day || '-'}`,""")

rep("""      {
        key: 'worst', label: t('msKpi.card.worst'), value: worst.length ? worst[0].label : '-',
        hint: worst.length ? t('msKpi.hint.worst', { n: worst.length }) : '-',""",
"""      {
        key: 'worst', label: t('msKpi.card.worst'), value: worst.length ? worst[0].label : '-',
        hint: worst.length
          ? `${t('msKpi.grpPerf')} · ${t('msKpi.hint.worst', { n: worst.length })}`
          : `${t('msKpi.grpPerf')} · ${t('msKpi.hint.worstNone')}`,""")

# ---- 趋势卡片 ----
rep("""          <div style={{ marginTop: 10, fontSize: 12, color: WH.textMuted }}>
            {t('msKpi.trendHint')}
          </div>""",
"""          <div style={{ marginTop: 10, fontSize: 12, color: WH.textMuted }}>
            {`${t('msKpi.grpTrend')} · ${t('msKpi.trendHint')}`}
          </div>""")

# ---- 分布卡片 ----
rep("""          <div style={{ marginTop: 10, fontSize: 12, color: WH.textMuted }}>
            {t('msKpi.distHint')}
          </div>""",
"""          <div style={{ marginTop: 10, fontSize: 12, color: WH.textMuted }}>
            {`${t('msKpi.grpStatus')} · ${t('msKpi.distHint')}`}
          </div>""")

# ---- 分类达标 ----
rep("""      <div style={{ ...WH.card }}>
        <div style={{ fontSize: 13, color: WH.textMuted, marginBottom: 8 }}>{t('msKpi.cat.title')}</div>""",
"""      <div style={{ ...WH.card }}>
        <div style={{ fontSize: 13, color: WH.textMuted, marginBottom: 8 }}>
          {`${t('msKpi.grpPerf')} · ${t('msKpi.cat.title')}`}
        </div>""")

# ---- 缺口 Top ----
rep("""      <div style={{ ...WH.card }}>
        <div style={{ fontSize: 13, color: WH.textMuted, marginBottom: 8 }}>{t('msKpi.gap.title')}</div>""",
"""      <div style={{ ...WH.card }}>
        <div style={{ fontSize: 13, color: WH.textMuted, marginBottom: 8 }}>
          {`${t('msKpi.grpPerf')} · ${t('msKpi.gap.title')}`}
        </div>""")
