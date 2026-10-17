const { settings } = require('../../utils/api')

Page({
  data: { baseUrl: '', token: '', saved: false },
  onLoad() {
    const current = settings()
    this.setData({ baseUrl: current.baseUrl, token: current.token })
  },
  setBase(event) { this.setData({ baseUrl: event.detail.value, saved: false }) },
  setToken(event) { this.setData({ token: event.detail.value, saved: false }) },
  save() {
    const baseUrl = this.data.baseUrl.trim().replace(/\/$/, '')
    const token = this.data.token.trim()
    if (!baseUrl || !token) {
      wx.showToast({ title: '请填写完整', icon: 'none' })
      return
    }
    wx.setStorageSync('riskpilot_api_base', baseUrl)
    wx.setStorageSync('riskpilot_dev_token', token)
    this.setData({ saved: true })
    wx.showToast({ title: '已保存在本机', icon: 'success' })
  }
})
