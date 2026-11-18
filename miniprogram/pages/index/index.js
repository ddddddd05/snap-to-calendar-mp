const app = getApp();

Page({
  data: {
    mode: "auto",
    activeTab: "calendar",
    imagePath: "",
    imageBase64: "",
    text: "",
    loading: false,
    events: [],
    expenses: [],
    expenseTotal: "0.00",
  },

  setMode(e) {
    this.setData({ mode: e.currentTarget.dataset.mode });
  },

  switchTab(e) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
  },

  onTextInput(e) {
    this.setData({ text: e.detail.value });
  },

  chooseImage() {
    wx.chooseMedia({
      count: 1,
      mediaType: ["image"],
      sourceType: ["album", "camera"],
      success: (res) => {
        const tempFilePath = res.tempFiles[0].tempFilePath;
        const fs = wx.getFileSystemManager();
        fs.readFile({
          filePath: tempFilePath,
          encoding: "base64",
          success: (fileRes) => {
            this.setData({
              imagePath: tempFilePath,
              imageBase64: `data:image/jpeg;base64,${fileRes.data}`,
            });
          },
          fail: () => {
            wx.showToast({ title: "读取图片失败", icon: "none" });
          },
        });
      },
    });
  },

  clearImage() {
    this.setData({ imagePath: "", imageBase64: "" });
  },

  runExtract() {
    const { text, imageBase64, mode } = this.data;
    if (!text.trim() && !imageBase64) {
      wx.showToast({ title: "请先选择截图或输入文字", icon: "none" });
      return;
    }

    this.setData({ loading: true });
    wx.request({
      url: `${app.globalData.apiBase}/api/extract`,
      method: "POST",
      header: { "Content-Type": "application/json" },
      data: { text, imageBase64: imageBase64 || null, mode },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const events = res.data.events || [];
          const expenses = res.data.expenses || [];
          this.updateResult(events, expenses);
          wx.showToast({
            title: `提取到 ${events.length} 条日程, ${expenses.length} 笔账单`,
            icon: "none",
          });
        } else {
          wx.showModal({
            title: "提取失败",
            content: (res.data && res.data.detail) || `错误码 ${res.statusCode}`,
            showCancel: false,
          });
        }
      },
      fail: () => {
        wx.showModal({
          title: "连接后端失败",
          content: `请先启动 Python 后端（${app.globalData.apiBase}），或先点「快速体验」示例。`,
          showCancel: false,
        });
      },
      complete: () => {
        this.setData({ loading: false });
      },
    });
  },

  updateResult(events, expenses) {
    const total = expenses.reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
    const nextTab = expenses.length > 0 && events.length === 0 ? "expense" : "calendar";
    this.setData({
      events,
      expenses,
      expenseTotal: total.toFixed(2),
      activeTab: nextTab,
    });
  },

  loadDemo(e) {
    const type = e.currentTarget.dataset.type;
    const today = this.formatDate(new Date());
    const tomorrow = this.formatDate(new Date(Date.now() + 86400000));

    if (type === "meeting") {
      const events = [
        {
          title: "毕业设计开题答辩动员会",
          date: tomorrow,
          startTime: "14:30",
          endTime: "16:00",
          location: "教学楼A302",
          note: "提前15分钟到场签到",
        },
      ];
      this.setData({
        text: "【班级群通知】明天下午 14:30-16:00 在教学楼A302 召开毕业设计开题答辩动员会，请提前15分钟到场签到。",
      });
      this.updateResult(events, []);
    } else {
      const expenses = [
        { date: today, item: "二食堂黄焖鸡", category: "餐饮", amount: 22.5, note: "微信支付" },
        { date: today, item: "霸王茶姬奶茶", category: "餐饮", amount: 18.0, note: "支付宝" },
        { date: today, item: "地铁出行", category: "交通", amount: 4.0, note: "乘车码" },
      ];
      this.setData({
        text: "今天中午二食堂黄焖鸡22.5元，下午霸王茶姬奶茶18元，晚上坐地铁4元",
      });
      this.updateResult([], expenses);
    }
  },

  addOneToCalendar(e) {
    const ev = this.data.events[e.currentTarget.dataset.index];
    this.insertPhoneCalendar(ev);
  },

  addAllToCalendar() {
    const { events } = this.data;
    if (!events.length) return;
    events.forEach((ev) => this.insertPhoneCalendar(ev));
  },

  insertPhoneCalendar(ev) {
    const startUnix = this.toUnixSeconds(ev.date, ev.startTime);
    const endUnix = this.toUnixSeconds(ev.date, ev.endTime);

    wx.addPhoneCalendar({
      title: ev.title || "日程提醒",
      startTime: startUnix,
      endTime: endUnix,
      location: ev.location || "",
      description: ev.note || "",
      alarm: true,
      alarmOffset: 900, // 提前 15 分钟提醒
      success: () => {
        wx.showToast({ title: "已加入手机日历", icon: "success" });
      },
      fail: (err) => {
        wx.showModal({
          title: "未能写入日历",
          content: `说明：开发者工具模拟器不支持系统日历，请用「真机预览」测试。（${err.errMsg || ""}）`,
          showCancel: false,
        });
      },
    });
  },

  exportExcel() {
    const { expenses } = this.data;
    if (!expenses.length) return;

    wx.showLoading({ title: "生成表格中..." });
    wx.request({
      url: `${app.globalData.apiBase}/api/export-csv`,
      method: "POST",
      header: { "Content-Type": "application/json" },
      responseType: "arraybuffer",
      data: { expenses },
      success: (res) => {
        if (res.statusCode !== 200) {
          wx.showToast({ title: "导出失败", icon: "none" });
          return;
        }
        const filePath = `${wx.env.USER_DATA_PATH}/消费账单_${this.formatDate(new Date())}.csv`;
        const fs = wx.getFileSystemManager();
        fs.writeFile({
          filePath,
          data: res.data,
          success: () => {
            wx.openDocument({
              filePath,
              fileType: "csv",
              showMenu: true,
              fail: () => {
                wx.showToast({ title: "文件已保存，可在真机打开", icon: "none" });
              },
            });
          },
        });
      },
      fail: () => {
        wx.showToast({ title: "请先启动后端服务", icon: "none" });
      },
      complete: () => {
        wx.hideLoading();
      },
    });
  },

  toUnixSeconds(dateStr, timeStr) {
    const safeDate = (dateStr || this.formatDate(new Date())).replace(/-/g, "/");
    const safeTime = timeStr || "09:00";
    return Math.floor(new Date(`${safeDate} ${safeTime}:00`).getTime() / 1000);
  },

  formatDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  },
});
