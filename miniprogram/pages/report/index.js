const { request, snapshotId } = require('../../utils/api')

Page({
  data: {
    stockCode: '601318', capital: '100000', maxLoss: '3000', date: '2025-04-30',
    loading: false, error: '', report: null, markdown: '', integrity: null,
    perspectives: [], chartRows: [], history: [], showHistory: false
  },
  onLoad(options) {
    if (options.stockCode) this.setData({ stockCode: options.stockCode })
  },
  setStock(event) { this.setData({ stockCode: event.detail.value.replace(/\D/g, '').slice(0, 6) }) },
  setCapital(event) { this.setData({ capital: event.detail.value }) },
  setMaxLoss(event) { this.setData({ maxLoss: event.detail.value }) },
  setDate(event) { this.setData({ date: event.detail.value }) },
  async generate() {
    const capital = Number(this.data.capital)
    const maxLoss = Number(this.data.maxLoss)
    if (this.data.stockCode.length !== 6 || capital <= 0 || maxLoss <= 0 || maxLoss > capital) {
      this.setData({ error: '请检查股票代码、本金和损失预算。' })
      return
    }
    const asOf = `${this.data.date}T15:00:00+08:00`
    this.setData({ loading: true, error: '', integrity: null })
    try {
      const data = await request('/api/v2/reports', {
        as_of: asOf,
        snapshot_id: snapshotId(this.data.stockCode, asOf),
        stock_code: this.data.stockCode,
        capital,
        max_loss: maxLoss,
        idempotency_key: `wx-${this.data.stockCode}-${this.data.date}-${capital}-${maxLoss}`
      })
      const report = data.report
      const labels = { technical: '技术面', fundamental: '基本面', news: '信息面' }
      const perspectives = Object.keys(labels).map(key => ({ key, label: labels[key], ...report.perspectives[key] }))
      const rows = (report.evidence.chart_data || []).slice(-8).map(row => ({
        date: row['日期'], shortDate: row['日期'].slice(5), close: row['收盘'], high: row['最高'], low: row['最低']
      }))
      this.setData({ report, markdown: data.markdown, perspectives, chartRows: rows })
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },
  async verify() {
    if (!this.data.report) return
    try {
      const data = await request('/api/v2/reports/integrity', {
        as_of: `${this.data.date}T15:00:00+08:00`, report_id: this.data.report.report_id
      })
      this.setData({ integrity: data })
    } catch (error) {
      this.setData({ error: error.message })
    }
  },
  copyMarkdown() {
    wx.setClipboardData({ data: this.data.markdown })
  },
  openChallenge() {
    wx.navigateTo({ url: `/pages/replay/index?stockCode=${this.data.report.stock.code}` })
  },
  async toggleHistory() {
    const showHistory = !this.data.showHistory
    this.setData({ showHistory })
    if (!showHistory) return
    try {
      const data = await request('/api/v2/reports/list', {
        as_of: `${this.data.date}T15:00:00+08:00`, limit: 20
      })
      this.setData({ history: data.reports })
    } catch (error) {
      this.setData({ error: error.message })
    }
  },
  async openHistory(event) {
    try {
      const data = await request('/api/v2/reports/query', {
        as_of: `${this.data.date}T15:00:00+08:00`, report_id: event.currentTarget.dataset.id
      })
      const report = data.report
      const labels = { technical: '技术面', fundamental: '基本面', news: '信息面' }
      this.setData({
        report, markdown: data.markdown, showHistory: false,
        perspectives: Object.keys(labels).map(key => ({ key, label: labels[key], ...report.perspectives[key] })),
        chartRows: (report.evidence.chart_data || []).slice(-8).map(row => ({ date: row['日期'], shortDate: row['日期'].slice(5), close: row['收盘'], high: row['最高'], low: row['最低'] }))
      })
    } catch (error) {
      this.setData({ error: error.message })
    }
  },
  reset() { this.setData({ report: null, markdown: '', integrity: null, perspectives: [], chartRows: [], error: '' }) }
})
