const { request } = require('../../utils/api')

Page({
  data: {
    stockCode: '601318', asOf: '2025-04-30T15:00:00+08:00', mode: 'monthly',
    capital: '100000', maxLoss: '3000', experiment: null, targetValue: '',
    preview: null, loading: false, error: '', scored: false, leaderboard: []
  },
  onLoad(options) {
    if (options.stockCode) this.setData({ stockCode: options.stockCode })
  },
  onShow() {
    const experimentId = wx.getStorageSync('riskpilot_experiment_id')
    if (experimentId && !this.data.experiment) this.resume(experimentId)
  },
  setStock(event) { this.setData({ stockCode: event.detail.value.replace(/\D/g, '').slice(0, 6) }) },
  setTarget(event) { this.setData({ targetValue: event.detail.value, preview: null }) },
  setMode(event) { this.setData({ mode: event.detail.value }) },
  async start() {
    this.setData({ loading: true, error: '', scored: false, leaderboard: [] })
    try {
      const experiment = await request('/api/v2/replay/cases', {
        as_of: this.data.asOf, stock_code: this.data.stockCode,
        decision_mode: this.data.mode, capital: Number(this.data.capital),
        max_loss: Number(this.data.maxLoss)
      })
      wx.setStorageSync('riskpilot_experiment_id', experiment.experiment_id)
      this.setData({ experiment, preview: null, targetValue: '' })
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },
  async resume(experimentId) {
    try {
      const experiment = await request('/api/v2/replay/session', {
        as_of: this.data.asOf, experiment_id: experimentId
      })
      this.setData({ experiment })
    } catch (error) {
      wx.removeStorageSync('riskpilot_experiment_id')
    }
  },
  async preview() {
    const target = Number(this.data.targetValue)
    if (!this.data.experiment || target < 0) return
    try {
      const result = await request('/api/v2/replay/preview', {
        as_of: this.data.asOf, experiment_id: this.data.experiment.experiment_id,
        expected_step: this.data.experiment.step, target_value: target
      })
      this.setData({ preview: result.preview })
    } catch (error) {
      this.setData({ error: error.message })
    }
  },
  async submit(event) {
    if (!this.data.experiment) return
    const skip = event.currentTarget.dataset.skip === true
    const target = skip ? null : Number(this.data.targetValue)
    if (!skip && (this.data.targetValue === '' || target < 0)) {
      this.setData({ error: '请输入目标持仓金额，或选择本轮不操作。' })
      return
    }
    this.setData({ loading: true, error: '' })
    try {
      const step = this.data.experiment.step
      const experiment = await request('/api/v2/replay/actions', {
        as_of: this.data.asOf, experiment_id: this.data.experiment.experiment_id,
        expected_step: step, target_value: target,
        idempotency_key: `wx-${this.data.experiment.experiment_id}-${step}`
      })
      this.setData({ experiment, preview: null, targetValue: '' })
      if (experiment.finished) wx.removeStorageSync('riskpilot_experiment_id')
    } catch (error) {
      this.setData({ error: error.message })
    } finally {
      this.setData({ loading: false })
    }
  },
  async submitScore() {
    try {
      await request('/api/v2/replay/scores', {
        as_of: this.data.asOf, experiment_id: this.data.experiment.experiment_id,
        display_name: 'RiskPilot 玩家', avatar: '🧭', faction: 'jin'
      })
      const board = await request('/api/v2/leaderboard/query', { as_of: this.data.asOf, limit: 10 })
      this.setData({ scored: true, leaderboard: board.players })
    } catch (error) {
      this.setData({ error: error.message })
    }
  },
  restart() {
    wx.removeStorageSync('riskpilot_experiment_id')
    this.setData({ experiment: null, preview: null, targetValue: '', error: '', scored: false, leaderboard: [] })
  },
  openReport() { wx.navigateTo({ url: `/pages/report/index?stockCode=${this.data.stockCode}` }) }
})
