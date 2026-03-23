'use strict';

let _cvReady = false;
let _cvLoadPromise = null;

function _loadOpenCV() {
  if (_cvReady) return Promise.resolve();
  if (_cvLoadPromise) return _cvLoadPromise;
  _cvLoadPromise = new Promise((resolve, reject) => {
    window.Module = {
      onRuntimeInitialized() { _cvReady = true; resolve(); },
    };
    const script = document.createElement('script');
    script.src = 'https://docs.opencv.org/4.10.0/opencv.js';
    script.async = true;
    script.onerror = () => reject(new Error('Failed to load OpenCV.js'));
    document.head.appendChild(script);
  });
  return _cvLoadPromise;
}

/** Draw source into ctx simulating object-fit:cover */
function _drawCover(ctx, source, srcW, srcH, dstW, dstH) {
  const srcAspect = srcW / srcH;
  const dstAspect = dstW / dstH;
  let sx, sy, sw, sh;
  if (srcAspect > dstAspect) {
    sh = srcH; sw = srcH * dstAspect; sy = 0; sx = (srcW - sw) / 2;
  } else {
    sw = srcW; sh = srcW / dstAspect; sx = 0; sy = (srcH - sh) / 2;
  }
  ctx.drawImage(source, sx, sy, sw, sh, 0, 0, dstW, dstH);
}

class DocumentScanner {
  constructor() {
    this._dialog     = document.getElementById('scanner-modal');
    this._video      = document.getElementById('scanner-video');
    this._display    = document.getElementById('scanner-display');
    this._viewport   = document.querySelector('.scanner-viewport');
    this._status     = document.getElementById('scanner-status');
    this._captureBtn = document.getElementById('scanner-capture');
    this._loading    = document.getElementById('scanner-loading');
    this._scanBtn    = document.getElementById('scan-btn');

    this._stream     = null;
    this._rafId      = null;
    this._processing = false;
    this._stableCount = 0;
    this._lastCorners = null; // native video-space [TL,TR,BR,BL]
    this._STABLE_THRESHOLD = 8;

    this._scratch    = document.createElement('canvas');
    this._scratchCtx = this._scratch.getContext('2d');

    this._scanBtn.addEventListener('click', () => this.open());
    this._captureBtn.addEventListener('click', () => this._capture());
    document.getElementById('scanner-close').addEventListener('click', () => this.close());
    this._dialog.addEventListener('close', () => this._cleanup());
  }

  async open() {
    this._dialog.showModal();
    this._loading.hidden = false;
    this._captureBtn.disabled = true;
    this._stableCount = 0;
    this._lastCorners = null;
    this._status.textContent = 'Initializing…';

    try {
      await this._startCamera();
      await _loadOpenCV();
    } catch (err) {
      this._status.textContent = 'Error: ' + err.message;
      this._loading.hidden = true;
      return;
    }

    this._loading.hidden = true;
    this._startLoop();
  }

  close() { this._dialog.close(); }

  _cleanup() {
    if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
    if (this._stream) { this._stream.getTracks().forEach(t => t.stop()); this._stream = null; }
    this._video.srcObject = null;
    this._processing = false;
    this._stableCount = 0;
    this._lastCorners = null;
  }

  async _startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('Camera requires HTTPS. Open this page over https:// or use localhost.');
    }
    this._stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    this._video.srcObject = this._stream;
    await new Promise((resolve, reject) => {
      this._video.onloadedmetadata = () => this._video.play().then(resolve).catch(reject);
      this._video.onerror = reject;
    });
  }

  _startLoop() {
    const loop = () => { this._rafId = requestAnimationFrame(loop); this._processFrame(); };
    this._rafId = requestAnimationFrame(loop);
  }

  _processFrame() {
    if (this._processing || !_cvReady) return;
    if (this._video.readyState < 2) return;

    const vw = this._video.videoWidth;
    const vh = this._video.videoHeight;
    if (!vw || !vh) return;

    const rect = this._viewport.getBoundingClientRect();
    const W = Math.round(rect.width);
    const H = Math.round(rect.height);
    if (!W || !H) return;

    this._processing = true;

    // Resize canvas buffer to match viewport (avoid thrashing if unchanged)
    if (this._display.width !== W || this._display.height !== H) {
      this._display.width = W;
      this._display.height = H;
    }

    // Grab frame at native resolution for accurate CV
    this._scratch.width = vw;
    this._scratch.height = vh;
    this._scratchCtx.drawImage(this._video, 0, 0, vw, vh);

    let corners = null;
    let warped = false;
    let ox = 0, oy = 0, outW = 0, outH = 0;

    let src, gray, blurred, edges, dilated, contours, hierarchy, kernel;
    let warpDst = null, srcPts = null, dstPts = null, M = null;
    try {
      src = cv.imread(this._scratch);
      gray = new cv.Mat(); blurred = new cv.Mat();
      edges = new cv.Mat(); dilated = new cv.Mat();
      contours = new cv.MatVector(); hierarchy = new cv.Mat();
      kernel = cv.Mat.ones(3, 3, cv.CV_8U);

      cv.cvtColor(src, gray, cv.COLOR_RGBA2GRAY);
      cv.GaussianBlur(gray, blurred, new cv.Size(5, 5), 0);
      cv.Canny(blurred, edges, 75, 200);
      cv.dilate(edges, dilated, kernel);
      cv.findContours(dilated, contours, hierarchy, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE);

      const imageArea = vw * vh;
      let bestQuad = null, bestArea = 0;
      for (let i = 0; i < contours.size(); i++) {
        const cnt = contours.get(i);
        const peri = cv.arcLength(cnt, true);
        const approx = new cv.Mat();
        cv.approxPolyDP(cnt, approx, 0.02 * peri, true);
        cnt.delete();
        if (approx.rows === 4) {
          const area = cv.contourArea(approx);
          if (area >= 0.15 * imageArea && area > bestArea) {
            bestArea = area;
            if (bestQuad) bestQuad.delete();
            bestQuad = approx;
          } else { approx.delete(); }
        } else { approx.delete(); }
      }

      if (bestQuad) {
        const d = bestQuad.data32S;
        const pts = [
          { x: d[0], y: d[1] }, { x: d[2], y: d[3] },
          { x: d[4], y: d[5] }, { x: d[6], y: d[7] },
        ];
        bestQuad.delete();
        corners = this._orderPoints(pts); // native video space

        // Compute document aspect (mirrors image.py lines 49-62)
        const [tl, tr, br, bl] = corners;
        const wTop   = Math.hypot(tr.x - tl.x, tr.y - tl.y);
        const wBot   = Math.hypot(br.x - bl.x, br.y - bl.y);
        const hLeft  = Math.hypot(bl.x - tl.x, bl.y - tl.y);
        const hRight = Math.hypot(br.x - tr.x, br.y - tr.y);
        const outWf  = Math.max(wTop, wBot);
        const outHf  = Math.max(hLeft, hRight);
        let aspect = outWf > 0 ? outHf / outWf : 1.0;
        aspect = Math.max(0.8, Math.min(2.0, aspect));

        // Fit document rect into display canvas (letterbox)
        if (aspect >= H / W) {
          outH = H; outW = Math.round(H / aspect);
        } else {
          outW = W; outH = Math.round(W * aspect);
        }
        ox = Math.round((W - outW) / 2);
        oy = Math.round((H - outH) / 2);

        // Warp native frame → display-sized canvas
        srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
          tl.x, tl.y, tr.x, tr.y, br.x, br.y, bl.x, bl.y,
        ]);
        dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [
          ox, oy,
          ox + outW - 1, oy,
          ox + outW - 1, oy + outH - 1,
          ox, oy + outH - 1,
        ]);
        M = cv.getPerspectiveTransform(srcPts, dstPts);
        warpDst = new cv.Mat(H, W, src.type());
        warpDst.setTo(new cv.Scalar(0, 0, 0, 255));
        cv.warpPerspective(src, warpDst, M, new cv.Size(W, H));
        cv.imshow(this._display, warpDst);
        warped = true;
      }
    } catch (e) {
      console.error('[scanner] CV error:', e);
    } finally {
      if (src)       src.delete();
      if (gray)      gray.delete();
      if (blurred)   blurred.delete();
      if (edges)     edges.delete();
      if (dilated)   dilated.delete();
      if (contours)  contours.delete();
      if (hierarchy) hierarchy.delete();
      if (kernel)    kernel.delete();
      if (warpDst)   warpDst.delete();
      if (srcPts)    srcPts.delete();
      if (dstPts)    dstPts.delete();
      if (M)         M.delete();
    }

    const ctx = this._display.getContext('2d');

    if (corners) {
      this._stableCount = Math.min(this._stableCount + 1, this._STABLE_THRESHOLD + 4);
      this._lastCorners = corners;

      // Draw stability border around the rectified document
      if (warped) {
        const stable = this._stableCount >= this._STABLE_THRESHOLD;
        ctx.strokeStyle = stable ? 'rgba(34,197,94,0.9)' : 'rgba(234,179,8,0.7)';
        ctx.lineWidth = 4;
        ctx.strokeRect(ox + 2, oy + 2, outW - 4, outH - 4);
      }

      if (this._stableCount >= this._STABLE_THRESHOLD) {
        this._status.textContent = 'Document detected — tap Capture';
        this._captureBtn.disabled = false;
      } else {
        this._status.textContent = 'Hold steady…';
        this._captureBtn.disabled = true;
      }
    } else {
      this._stableCount = Math.max(0, this._stableCount - 2);
      if (this._stableCount === 0) this._lastCorners = null;

      // Raw camera feed with dashed guide rect
      _drawCover(ctx, this._video, vw, vh, W, H);
      const mx = W * 0.08, my = H * 0.12;
      ctx.strokeStyle = 'rgba(200,200,200,0.6)';
      ctx.lineWidth = 2;
      ctx.setLineDash([10, 8]);
      ctx.strokeRect(mx, my, W - mx * 2, H - my * 2);
      ctx.setLineDash([]);

      this._status.textContent = 'Point camera at a document…';
      this._captureBtn.disabled = true;
    }

    this._processing = false;
  }

  /** Mirror image.py _order_points: sum→TL(min)/BR(max), diff(y-x)→TR(min)/BL(max) */
  _orderPoints(pts) {
    const sums  = pts.map(p => p.x + p.y);
    const diffs = pts.map(p => p.y - p.x);
    return [
      pts[sums.indexOf(Math.min(...sums))],  // TL
      pts[diffs.indexOf(Math.min(...diffs))], // TR
      pts[sums.indexOf(Math.max(...sums))],  // BR
      pts[diffs.indexOf(Math.max(...diffs))], // BL
    ];
  }

  async _capture() {
    if (!this._lastCorners || !_cvReady) return;
    this._captureBtn.disabled = true;

    // Cap longest side at 1920px to prevent WASM OOM
    const vw = this._video.videoWidth;
    const vh = this._video.videoHeight;
    const downScale = Math.max(vw, vh) > 1920 ? 1920 / Math.max(vw, vh) : 1;
    const fw = Math.round(vw * downScale);
    const fh = Math.round(vh * downScale);

    const fullCanvas = document.createElement('canvas');
    fullCanvas.width = fw; fullCanvas.height = fh;
    fullCanvas.getContext('2d').drawImage(this._video, 0, 0, fw, fh);

    const sc = this._lastCorners.map(p => ({ x: p.x * downScale, y: p.y * downScale }));
    const [tl, tr, br, bl] = sc;

    let src, dst, srcPts, dstPts, M;
    let blob = null;
    try {
      src = cv.imread(fullCanvas);

      const wTop   = Math.hypot(tr.x-tl.x, tr.y-tl.y);
      const wBot   = Math.hypot(br.x-bl.x, br.y-bl.y);
      const hLeft  = Math.hypot(bl.x-tl.x, bl.y-tl.y);
      const hRight = Math.hypot(br.x-tr.x, br.y-tr.y);
      let aspect = Math.max(Math.max(wTop,wBot),0.001) > 0
        ? Math.max(hLeft,hRight) / Math.max(wTop,wBot) : 1.0;
      aspect = Math.max(0.8, Math.min(2.0, aspect));
      const outW = 794;
      const outH = Math.round(outW * aspect);

      srcPts = cv.matFromArray(4, 1, cv.CV_32FC2, [tl.x,tl.y, tr.x,tr.y, br.x,br.y, bl.x,bl.y]);
      dstPts = cv.matFromArray(4, 1, cv.CV_32FC2, [0,0, outW-1,0, outW-1,outH-1, 0,outH-1]);
      M = cv.getPerspectiveTransform(srcPts, dstPts);
      dst = new cv.Mat();
      cv.warpPerspective(src, dst, M, new cv.Size(outW, outH));

      const outCanvas = document.createElement('canvas');
      outCanvas.width = outW; outCanvas.height = outH;
      cv.imshow(outCanvas, dst);
      blob = await new Promise(resolve => outCanvas.toBlob(resolve, 'image/jpeg', 0.92));
    } catch (e) {
      console.error('[scanner] Capture error:', e);
      this._captureBtn.disabled = false;
      return;
    } finally {
      if (src)    src.delete();
      if (dst)    dst.delete();
      if (srcPts) srcPts.delete();
      if (dstPts) dstPts.delete();
      if (M)      M.delete();
    }

    if (blob) this._submit(blob);
  }

  async _submit(blob) {
    this.close();
    const spinner = document.getElementById('spinner');
    spinner.classList.add('htmx-request');
    const fd = new FormData();
    fd.append('files', blob, 'scan.jpg');
    try {
      const resp = await fetch('/upload', { method: 'POST', body: fd });
      const html = await resp.text();
      const result = document.getElementById('result');
      result.innerHTML = html;
      if (window.htmx) htmx.process(result);
    } catch (e) {
      document.getElementById('result').innerHTML =
        '<div class="result-error"><strong>Upload failed</strong> ' + e.message + '</div>';
    } finally {
      spinner.classList.remove('htmx-request');
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('scan-btn')) new DocumentScanner();
});
