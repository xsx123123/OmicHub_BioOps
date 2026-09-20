// CygnusX Element 兼容补丁：
// 平台页面以 http://<域名> 访问时不是 secure context，内嵌 iframe 会被祖先降级，
// 导致 window.crypto.randomUUID 不存在，Element 的 Matrix session lock 初始化抛错
// （表现为 iframe 内永远停在黑色加载页）。crypto.getRandomValues 在 insecure
// context 中仍可用，用它补一个 RFC4122 v4 实现。
// 本文件经 nginx sub_filter 注入到 index.html 的 </head> 前，早于 Element bundle 执行。
(function () {
  try {
    if (window.crypto && typeof window.crypto.randomUUID !== 'function') {
      window.crypto.randomUUID = function () {
        var bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        var hex = [];
        for (var i = 0; i < 16; i++) hex.push((bytes[i] < 16 ? '0' : '') + bytes[i].toString(16));
        var s = hex.join('');
        return s.slice(0, 8) + '-' + s.slice(8, 12) + '-' + s.slice(12, 16) + '-' +
               s.slice(16, 20) + '-' + s.slice(20);
      };
    }
  } catch (error) {
    // crypto 对象不可扩展（罕见）：让 Element 自身的兼容性提示接管。
  }
})();
