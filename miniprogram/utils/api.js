const DEFAULT_BASE = 'http://127.0.0.1:8001'

function settings() {
  return {
    baseUrl: wx.getStorageSync('riskpilot_api_base') || DEFAULT_BASE,
    token: wx.getStorageSync('riskpilot_dev_token') || ''
  }
}

function request(path, data) {
  const config = settings()
  if (!config.token) {
    return Promise.reject(new Error('请先在联调设置中填写本地开发令牌'))
  }
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${config.baseUrl}${path}`,
      method: 'POST',
      data,
      timeout: 20000,
      header: {
        'content-type': 'application/json',
        'Authorization': `Bearer ${config.token}`,
        'X-Trace-ID': `wx-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
      },
      success(response) {
        const body = response.data || {}
        if (response.statusCode >= 200 && response.statusCode < 300 && body.success) {
          resolve(body.data)
          return
        }
        const error = body.error || body.detail || {}
        reject(new Error(error.message || `请求失败（${response.statusCode}）`))
      },
      fail(error) {
        reject(new Error(error.errMsg || '无法连接 RiskPilot 服务'))
      }
    })
  })
}

function snapshotId(stockCode, asOf) {
  return `${stockCode}-${asOf.slice(0, 10)}`
}

module.exports = { request, settings, snapshotId }
