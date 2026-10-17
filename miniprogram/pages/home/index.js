const { settings } = require('../../utils/api')

Page({
  data: { configured: false },
  onShow() {
    this.setData({ configured: Boolean(settings().token) })
  },
  openReport() { wx.navigateTo({ url: '/pages/report/index' }) },
  openReplay() { wx.navigateTo({ url: '/pages/replay/index' }) },
  openSettings() { wx.navigateTo({ url: '/pages/settings/index' }) }
})
