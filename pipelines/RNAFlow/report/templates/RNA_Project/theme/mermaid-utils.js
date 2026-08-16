/**
 * Mermaid Diagram Download Utilities
 * Automatically attaches a modern floating download button to all Mermaid diagrams.
 */
document.addEventListener("DOMContentLoaded", function() {
  
    // 核心逻辑：添加下载按钮
    const attachDownloadButtons = () => {
      // 查找所有可能的 Mermaid 容器
      const targets = document.querySelectorAll(".cell-output-display, .mermaid");
      
      targets.forEach((target, index) => {
        // 1. 检查是否包含 SVG
        const svg = target.querySelector("svg");
        // 判断是否是 mermaid 图
        if (!svg || (!svg.id.startsWith("mermaid") && !svg.classList.contains("mermaid"))) return;
  
        // 2. 避免重复添加
        if (target.querySelector(".mermaid-download-btn")) return;
  
        // 3. 创建按钮
        const btn = document.createElement("button");
        btn.className = "mermaid-download-btn";
        btn.title = "Save diagram as SVG";
        btn.innerHTML = `
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>SVG</span>
        `;
  
        // 4. 绑定点击下载
        btn.onclick = (e) => {
          e.stopPropagation(); 
          
          try {
            const serializer = new XMLSerializer();
            let source = serializer.serializeToString(svg);
            
            // 命名空间修复
            if(!source.match(/^<svg[^>]+xmlns="http\:\/\/www\.w3\.org\/2000\/svg"/)){
                source = source.replace(/^<svg/, '<svg xmlns="http://www.w3.org/2000/svg"');
            }
            if(!source.match(/^<svg[^>]+"http\:\/\/www\.w3\.org\/1999\/xlink"/)){
                source = source.replace(/^<svg/, '<svg xmlns:xlink="http://www.w3.org/1999/xlink"');
            }
  
            // 创建 Blob URL 并触发下载
            const blob = new Blob([source], {type: "image/svg+xml;charset=utf-8"});
            const url = URL.createObjectURL(blob);
            
            const downloadLink = document.createElement("a");
            downloadLink.href = url;
            downloadLink.download = `flowchart_${index + 1}.svg`;
            document.body.appendChild(downloadLink);
            downloadLink.click();
            
            document.body.removeChild(downloadLink);
            URL.revokeObjectURL(url);
          } catch (err) {
            console.error("Export failed:", err);
          }
        };
  
        // 5. 插入按钮
        target.appendChild(btn);
      });
    };
  
    // 初始执行
    setTimeout(attachDownloadButtons, 1000);
  
    // 监听 DOM 变化 (应对 Mermaid 延迟渲染)
    const observer = new MutationObserver((mutations) => {
      let shouldUpdate = false;
      for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
          shouldUpdate = true;
          break;
        }
      }
      if (shouldUpdate) attachDownloadButtons();
    });
  
    observer.observe(document.body, { childList: true, subtree: true });
  });
