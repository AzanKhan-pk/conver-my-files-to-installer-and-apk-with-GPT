// The native Qt desktop build uses a lighter rendering profile for older PCs.
if (new URLSearchParams(window.location.search).has("desktop")) {
  document.documentElement.classList.add("savevido-desktop");
}

const $ = (selector) => document.querySelector(selector);

const urlInput = $("#url");
const fetchButton = $("#fetchBtn");
const statusBox = $("#status");
const resultBox = $("#result");
const useBrowserSession = $("#useBrowserSession");
const browserChoice = $("#browserChoice");
const browserProfile = $("#browserProfile");
const browserChoiceWrap = $("#browserChoiceWrap");
const accountLink = $("#accountLink");
if (accountLink && new URLSearchParams(window.location.search).has("desktop")) {
  accountLink.addEventListener("click", (event) => { event.preventDefault(); window.location.href = "savevido://account"; });
}

let selectedMode = "video";
let selectedQuality = "720p";
let currentVideo = null;
let currentImages = null;
let currentImagePlatform = "";

function getImageSessionOptions() {
  return {
    use_browser_session: Boolean(useBrowserSession?.checked),
    browser: browserChoice?.value || "chrome",
    browser_profile: browserProfile?.value?.trim() || ""
  };
}

useBrowserSession?.addEventListener("change", () => {
  if (browserChoiceWrap) browserChoiceWrap.hidden = !useBrowserSession.checked;
  if (useBrowserSession.checked) {
    setStatus(
      "Your selected browser profile will be read locally by this desktop app only. Do not enable this on a shared computer.",
      "success"
    );
  }
});

function setStatus(message, type = "") {
  statusBox.textContent = message;
  statusBox.className = `status ${type}`.trim();
}

function setButtonLoading(button, loading, loadingText, normalText) {
  button.disabled = loading;
  button.textContent = loading ? loadingText : normalText;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;"
    };

    return entities[character];
  });
}

function updateQualityLabel() {
  const qualityLabel = $("#qualityLabel");

  if (selectedMode === "audio") {
    qualityLabel.textContent = "192 kbps high quality";
    return;
  }

  qualityLabel.textContent =
    selectedQuality === "720p"
      ? "720p recommended"
      : selectedQuality;
}

function renderImageResult(images) {
  currentImages = images;
  currentVideo = null;

  const thumbnails = images.map((image) => `
    <figure class="image-gallery-item">
      <label class="image-select-label">
        <input
          class="image-select-checkbox"
          type="checkbox"
          data-image-id="${Number(image.id)}"
          checked
          aria-label="Select image ${Number(image.id)}"
        >
        <span>Select</span>
      </label>
      <img
        src="${escapeHtml(image.url)}"
        alt="Album image ${Number(image.id)}"
        loading="lazy"
      >
      <figcaption>Image ${Number(image.id)}</figcaption>
    </figure>
  `).join("");

  resultBox.innerHTML = `
    <div class="image-gallery-result">
      <div class="image-gallery-heading">
        <div>
          <h3>${escapeHtml(currentImagePlatform || "Social media")} image gallery</h3>
          <p>${images.length} images found</p>
        </div>
        <span class="image-gallery-count">${images.length}</span>
      </div>
      <div class="image-gallery-selection">
        <label>
          <input id="selectAllImages" type="checkbox" checked>
          Select all
        </label>
        <span id="selectedImageCount">${images.length} selected</span>
      </div>
      <div class="image-gallery-grid">${thumbnails}</div>
      <button id="downloadSelectedImagesBtn" type="button">
        Download selected images (ZIP) ↗
      </button>
    </div>
  `;

  resultBox.hidden = false;

  const selectedImageIds = new Set(images.map((image) => Number(image.id)));
  const checkboxes = Array.from(
    resultBox.querySelectorAll(".image-select-checkbox")
  );
  const selectAll = $("#selectAllImages");
  const downloadButton = $("#downloadSelectedImagesBtn");

  const updateSelection = () => {
    const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
    selectedImageIds.clear();
    checkboxes.forEach((checkbox) => {
      if (checkbox.checked) selectedImageIds.add(Number(checkbox.dataset.imageId));
    });
    selectAll.checked = selectedCount === checkboxes.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
    $("#selectedImageCount").textContent = `${selectedCount} selected`;
    downloadButton.disabled = selectedCount === 0;
    downloadButton.textContent = selectedCount
      ? `Download selected images (${selectedCount}) ZIP ↗`
      : "Select images to download";
  };

  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", updateSelection);
  });

  selectAll.addEventListener("change", () => {
    checkboxes.forEach((checkbox) => {
      checkbox.checked = selectAll.checked;
    });
    updateSelection();
  });

  downloadButton.addEventListener("click", downloadSelectedImages);
  updateSelection();
}

async function downloadSelectedImages() {
  const selectedIds = Array.from(
    resultBox.querySelectorAll(".image-select-checkbox:checked")
  ).map((checkbox) => Number(checkbox.dataset.imageId));

  if (!selectedIds.length) {
    setStatus("Select at least one image first.", "error");
    return;
  }

  const button = $("#downloadSelectedImagesBtn");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Preparing ZIP...";

  try {
    const response = await fetch("/api/images/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: urlInput.value.trim(),
        image_ids: selectedIds,
        ...getImageSessionOptions()
      })
    });

    if (!response.ok) {
      let message = "Could not download the selected images.";
      try {
        const data = await response.json();
        message = data.error || message;
      } catch (_) {}
      throw new Error(message);
    }

    const blob = await response.blob();
    if (!blob.size) throw new Error("The ZIP file is empty.");

    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${(currentImagePlatform || "social").toLowerCase().replace(/[^a-z0-9]+/g, "-")}-images.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);

    setStatus(`${selectedIds.length} images downloaded as a ZIP file.`, "success");
  } catch (error) {
    showErrorWithFeedback(error.message || "Image download failed.", urlInput?.value || "");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function renderVideoResult(video) {
  const thumbnail = video.thumbnail
    ? `<img src="${escapeHtml(video.thumbnail)}" alt="Video thumbnail">`
    : `<div class="result-placeholder">AVD</div>`;

  resultBox.innerHTML = `
    ${thumbnail}
    <div>
      <h3>${escapeHtml(video.title)}</h3>
      <p>
        ${escapeHtml(video.creator)}
        · ${escapeHtml(video.duration)}
        · ${escapeHtml(video.views)} views
      </p>
      <p>${escapeHtml(video.platform)}</p>
      <button id="downloadBtn" type="button">
        Download ${selectedMode === "audio" ? "MP3" : "Video"} ↗
      </button>
    </div>
  `;

  resultBox.hidden = false;

  const downloadButton = $("#downloadBtn");

  if (downloadButton) {
    downloadButton.addEventListener("click", downloadMedia);
  }
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".mode").forEach((item) => {
      item.classList.remove("active");
    });

    button.classList.add("active");
    selectedMode = button.dataset.mode;
    updateQualityLabel();

    if (currentVideo && !resultBox.hidden) {
      renderVideoResult(currentVideo);
    }
  });
});

document.querySelectorAll(".quality-grid button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".quality-grid button").forEach((item) => {
      item.classList.remove("selected");
    });

    button.classList.add("selected");
    selectedQuality = button.dataset.quality;
    updateQualityLabel();
  });
});

fetchButton.addEventListener("click", async () => {
  const url = urlInput.value.trim();

  if (!url) {
    setStatus("Paste a public video URL first.", "error");
    urlInput.focus();
    return;
  }

  setButtonLoading(
    fetchButton,
    true,
    "Reading...",
    "Fetch media ↗"
  );

  setStatus("Reading public media details...");
  resultBox.hidden = true;
  currentVideo = null;
  currentImages = null;

  try {
    const isImageCandidate = (() => {
      try {
        const parsed = new URL(url);
        const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
        const path = parsed.pathname.toLowerCase();
        const isHostOrSubdomain = (domain) =>
          host === domain || host.endsWith("." + domain);

        // Only call gallery-dl for links likely to contain an image gallery.
        // Normal video links go directly to yt-dlp, avoiding a second slow request.
        const isDirectImage = /\.(jpe?g|png|webp|gif|avif)$/i.test(path);
        const isPinterestPin = isHostOrSubdomain("pinterest.com")
          || isHostOrSubdomain("pin.it");
        const isInstagramPost = isHostOrSubdomain("instagram.com")
          && /^\/p\//.test(path);
        const isFacebookPhotoPost = (
          isHostOrSubdomain("facebook.com") || isHostOrSubdomain("fb.com")
        ) && (/^\/(photo|photos)\//.test(path)
          || /^\/share\/p\//.test(path));
        const isTikTokPhotoPost = isHostOrSubdomain("tiktok.com")
          && /^\/photo\//.test(path);

        return isDirectImage || isPinterestPin || isInstagramPost
          || isFacebookPhotoPost || isTikTokPhotoPost;
      } catch (_) {
        return false;
      }
    })();

    let imageData = null;
    let imageExtractionError = "";

    if (isImageCandidate) {
      try {
        const imageResponse = await fetch("/api/images/info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url, ...getImageSessionOptions() })
        });
        const candidate = await imageResponse.json();

        if (imageResponse.ok && candidate.ok
            && Array.isArray(candidate.images) && candidate.images.length) {
          imageData = candidate;
        } else {
          imageExtractionError = candidate.error || "No images were returned for this post.";
        }
      } catch (error) {
        imageExtractionError = error.message || "Image extraction request failed.";
      }
    }

    if (imageData) {
      currentImagePlatform = imageData.platform || "Social media";
      renderImageResult(imageData.images);
      setStatus(
        `${currentImagePlatform} image gallery found: ${imageData.count || imageData.images.length} images.`,
        "success"
      );
    } else {
      const isFacebookPhotoPost = (() => {
        try {
          const parsed = new URL(url);
          const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
          const path = parsed.pathname.toLowerCase();
          return (
            (host === "facebook.com" || host.endsWith(".facebook.com") || host === "fb.com")
            && (path.startsWith("/share/p/") || path.startsWith("/photo/") || path.startsWith("/photos/") || path.startsWith("/posts/"))
          );
        } catch (_) {
          return false;
        }
      })();

      // These post URL types are image-first. Do not invoke yt-dlp as a
      // fallback when image extraction fails: it only adds another long
      // network request and produces a misleading video-format error.
      const socialPostKind = (() => {
        try {
          const parsed = new URL(url);
          const host = parsed.hostname.toLowerCase();
          const path = parsed.pathname.toLowerCase();
          const isFacebook = host === "facebook.com" || host === "www.facebook.com"
            || host.endsWith(".facebook.com") || host === "fb.com" || host === "fb.watch";
          const isInstagram = host === "instagram.com" || host === "www.instagram.com";
          if (isFacebook && (
            path.startsWith("/share/p/") || path.startsWith("/photo/")
            || path.startsWith("/photos/") || path.startsWith("/posts/")
          )) return "Facebook";
          if (isInstagram && path.startsWith("/p/")) return "Instagram";
          return "";
        } catch (_) {
          return "";
        }
      })();

      if (socialPostKind) {
        const reason = imageExtractionError || "The image extractor did not return a usable gallery.";
        throw new Error(
          socialPostKind + " image extraction: " + reason +
          " Video fallback was skipped to avoid a second slow request. The post may require authorized access, or the platform may not expose its images to the extractor."
        );
      }

      const response = await fetch("/api/info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, ...getImageSessionOptions() })
      });
      const data = await response.json();

      if (!response.ok || !data.ok) {
        const videoError = data.error || "Could not read this link.";
        if (isImageCandidate && imageExtractionError) {
          throw new Error(`Image extraction: ${imageExtractionError} Video fallback: ${videoError}`);
        }
        throw new Error(videoError);
      }

      currentVideo = data.video;
      renderVideoResult(currentVideo);
      setStatus(`${currentVideo.platform} media found.`, "success");
    }
  } catch (error) {
    resultBox.hidden = true;
    const message = error.message || "Something went wrong.";
    const needsLogin = /login|log in|sign.?in|authentication|cookies required|private video|not authorized/i.test(message);
    showErrorWithFeedback(
      needsLogin && !useBrowserSession?.checked
        ? message + " If this is your own account, open More Options, enable Use my browser session, and choose your browser. SaveVido reads the selected profile locally only after you opt in."
        : message,
      url
    );
  } finally {
    setButtonLoading(
      fetchButton,
      false,
      "Reading...",
      "Fetch media ↗"
    );
  }
});

async function downloadMedia() {
  if (!currentVideo) {
    setStatus("Fetch the media details before downloading.", "error");
    return;
  }

  const downloadButton = $("#downloadBtn");
  const media = {
    url: currentVideo.url,
    title: currentVideo.title || "video",
    mode: selectedMode,
    quality: selectedQuality
  };

  setButtonLoading(downloadButton, true, "Starting...", `Download ${media.mode === "audio" ? "MP3" : "Video"} ↗`);

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: media.url, mode: media.mode, quality: media.quality, ...getImageSessionOptions() })
    });
    const data = await response.json();
    if (!response.ok || !data.ok || !data.job_id) {
      throw new Error(data.error || "Could not start the download.");
    }

    const panel = createDownloadPanel(data.job_id, media.title);
    panel.dataset.sourceUrl = media.url;
    setStatus("Download started. You can start another download while this one runs.", "success");
    monitorDownload(data.job_id, panel, media).catch(error => {
      console.error("Download monitor error:", error);
      setDownloadProgressMessage(panel, error.message || "Download failed.", true);
      disableDownloadControls(panel);
    });
  } catch (error) {
    console.error("Download start error:", error);
    const message = error.message || "Download failed.";
    const needsLogin = /login|log in|sign.?in|authentication|cookies required|private video|not authorized/i.test(message);
    showErrorWithFeedback(
      needsLogin && !useBrowserSession?.checked
        ? message + " If this is your own account, open More Options, enable Use my browser session, and choose your browser. SaveVido reads the selected profile locally only after you opt in."
        : message,
      media.url
    );
  } finally {
    setButtonLoading(downloadButton, false, "Starting...", `Download ${media.mode === "audio" ? "MP3" : "MP4"} ↗`);
  }
}

function formatEta(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "ETA —";
  let value = Math.max(0, Math.floor(Number(seconds)));
  const hours = Math.floor(value / 3600); value %= 3600;
  const minutes = Math.floor(value / 60); const secs = value % 60;
  return hours ? `ETA ${hours}h ${minutes}m` : minutes ? `ETA ${minutes}m ${secs}s` : `ETA ${secs}s`;
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return index === 0 ? `${Math.round(value)} ${units[index]}` : `${value.toFixed(2)} ${units[index]}`;
}

function createDownloadPanel(jobId, title) {
  const activityList = $("#downloadActivityList");
  const existingPanel = activityList?.querySelector(`.download-progress-panel[data-job-id="${CSS.escape(jobId)}"]`);
  if (existingPanel) {
    const existingTitle = existingPanel.querySelector(".download-progress-title");
    if (existingTitle && title) existingTitle.textContent = title;
    showRunningControls(existingPanel);
    return existingPanel;
  }

  const panel = document.createElement("div");
  panel.className = "download-progress-panel";
  panel.dataset.jobId = jobId;
  panel.innerHTML = `
    <div class="download-progress-header">
      <strong class="download-progress-title">${escapeHtml(title || "Downloading...")}</strong>
      <span class="download-progress-head-actions">
        <span data-role="percent">0%</span>
        <button data-action="dismiss" type="button" aria-label="Remove progress panel" title="Remove this panel (keeps History)" aria-label="Dismiss completed download">×</button>
      </span>
    </div>
    <div class="download-progress-bar"><div data-role="fill" class="download-progress-fill" style="width:0%"></div></div>
    <div class="download-progress-info">
      <span data-role="size">0 B / 0 B</span>
      <span data-role="speed">0 B/s</span>
      <span data-role="eta">ETA —</span>
    </div>
    <div class="download-progress-actions">
      <button data-action="pause" type="button">⏸ Pause</button>
      <button data-action="resume" type="button" hidden>▶ Resume</button>
      <button data-action="cancel" type="button">✕ Cancel</button>
    </div>
    <div data-role="message" class="download-progress-message">Preparing download...</div>
  `;

  (activityList || $("#downloadBtn").parentElement).appendChild(panel);

  panel.querySelector('[data-action="pause"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "pause"));
  panel.querySelector('[data-action="resume"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "resume"));
  panel.querySelector('[data-action="cancel"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "cancel"));
  panel.querySelector('[data-action="dismiss"]').addEventListener("click", () => panel.remove());
  return panel;
}

async function controlDownload(panel, jobId, action) {
  try {
    const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/${action}`, { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `Could not ${action} download.`);
    if (action === "pause" || action === "cancel") showPausedControls(panel);
    if (action === "resume") showRunningControls(panel);
    if (action === "cancel") {
      setDownloadProgressMessage(panel, "Download cancelled.", true);
      disableDownloadControls(panel);
    }
  } catch (error) {
    setDownloadProgressMessage(panel, error.message, true);
  }
}

async function monitorDownload(jobId, panel, media) {
  while (panel.isConnected) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/status`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not read download status.");

    const job = data.job;
    const percent = Number(job.percent || 0);
    const downloaded = formatBytes(job.downloaded_bytes || 0);
    const total = formatBytes(job.total_bytes || 0);
    const speed = formatBytes(job.speed || 0);
    updateDownloadProgress(panel, percent, downloaded, total, speed, job.eta);
    updateDownloadNotification(job);

    if (["starting", "preparing"].includes(job.status)) {
      setDownloadProgressMessage(panel, "Preparing download...");
      showRunningControls(panel);
    } else if (job.status === "downloading" || job.status === "processing") {
      setDownloadProgressMessage(panel, job.status === "processing" ? "Processing media..." : "Downloading...");
      showRunningControls(panel);
    } else if (job.status === "paused") {
      setDownloadProgressMessage(panel, "Download paused.");
      showPausedControls(panel);
    } else if (job.status === "network_error") {
      setDownloadProgressMessage(panel, "Network issue. Waiting to reconnect...", true);
      showPausedControls(panel);
      await new Promise(resolve => setTimeout(resolve, 5000));
      await controlDownload(panel, jobId, "resume");
      continue;
    } else if (job.status === "cancelled") {
      setDownloadProgressMessage(panel, "Download cancelled.", true);
      disableDownloadControls(panel);
      return;
    } else if (job.status === "error") {
      throw new Error(job.error || "Download failed.");
    } else if (job.status === "completed") {
      updateDownloadProgress(panel, 100, formatBytes(job.downloaded_bytes || 0), formatBytes(job.total_bytes || 0), "0 B");
      setDownloadProgressMessage(panel, "Download complete. Preparing file...");
      const isDesktopApp = new URLSearchParams(window.location.search).has("desktop");
      if (!isDesktopApp) {
        const fileResponse = await fetch(`/api/download/${encodeURIComponent(jobId)}/file`);
        if (!fileResponse.ok) {
          let message = "Could not retrieve the downloaded file.";
          try { const errorData = await fileResponse.json(); message = errorData.error || message; } catch (_) {}
          throw new Error(message);
        }
        const blob = await fileResponse.blob();
        if (!blob.size) throw new Error("Downloaded file is empty.");
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        const safeName = (job.title || media.title || "video").replace(/[^\w\s.-]/g, "").trim().slice(0, 90) || "video";
        link.href = objectUrl;
        link.download = job.filename || `${safeName}.${media.mode === "audio" ? "mp3" : "mp4"}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
      }
      // Completed jobs remain in History. Collapse the live panel to the
      // requested compact state: completion label plus the dismiss cross only.
      panel.classList.add("is-complete");
      const titleElement = panel.querySelector(".download-progress-title");
      if (titleElement) titleElement.textContent = "✓ Download completed";
      panel.querySelector(".download-progress-bar")?.setAttribute("hidden", "");
      panel.querySelector(".download-progress-info")?.setAttribute("hidden", "");
      panel.querySelector(".download-progress-actions")?.setAttribute("hidden", "");
      panel.querySelector('[data-role="percent"]')?.setAttribute("hidden", "");
      panel.querySelector('[data-role="message"]')?.setAttribute("hidden", "");
      disableDownloadControls(panel);
      await showCompletedNotification(job);
      await loadDownloadHistory();
      return;
    }
  }
}

function updateDownloadProgress(panel, percent, downloaded, total, speed, eta = null) {
  const percentElement = panel.querySelector('[data-role="percent"]');
  const fillElement = panel.querySelector('[data-role="fill"]');
  const sizeElement = panel.querySelector('[data-role="size"]');
  const speedElement = panel.querySelector('[data-role="speed"]');
  const etaElement = panel.querySelector('[data-role="eta"]');
  if (percentElement) percentElement.textContent = `${percent.toFixed(1)}%`;
  if (fillElement) fillElement.style.width = `${Math.min(percent, 100)}%`;
  if (sizeElement) sizeElement.textContent = `${downloaded} / ${total}`;
  if (speedElement) speedElement.textContent = `${speed}/s`;
  if (etaElement) etaElement.textContent = formatEta(eta);
}

function setDownloadProgressMessage(panel, message, error = false) {
  const element = panel.querySelector('[data-role="message"]');
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("error", error);
  element.querySelector(".download-feedback-action")?.remove();
  if (error) {
    const action = document.createElement("button");
    action.type = "button";
    action.className = "support-contact-link download-feedback-action";
    action.textContent = "If you want help resolving this, submit this error in Feedback ↗";
    action.addEventListener("click", () => openFeedbackForm(message, panel.dataset.sourceUrl || ""));
    element.appendChild(document.createElement("br"));
    element.appendChild(action);
  }
}

function showRunningControls(panel) {
  const pause = panel.querySelector('[data-action="pause"]');
  const resume = panel.querySelector('[data-action="resume"]');
  if (pause) { pause.hidden = false; pause.disabled = false; }
  if (resume) { resume.hidden = true; resume.disabled = false; }
}

function showPausedControls(panel) {
  const pause = panel.querySelector('[data-action="pause"]');
  const resume = panel.querySelector('[data-action="resume"]');
  if (pause) pause.hidden = true;
  if (resume) { resume.hidden = false; resume.disabled = false; }
}

function disableDownloadControls(panel) {
  panel.querySelectorAll(".download-progress-actions button").forEach(button => { button.disabled = true; });
}

const feedbackEndpoint = "https://savevido-owner-dashboard.vercel.app/api/feedback";
const feedbackForm = $("#commentForm");
const feedbackStatus = $("#commentStatus");
const supportFeedbackButton = $("#supportFeedbackBtn");
const LOCATION_DECISION_KEY = "savevido_location_decision_v1";
const LOCATION_PENDING_KEY = "savevido_feedback_location_pending_v1";

function openFeedbackForm(errorMessage = "", sourceUrl = "") {
  const lines = [
    "Url: " + (sourceUrl || "Not provided"),
    "Site/App: SaveVido desktop app",
    "Error: " + (errorMessage || "Please describe the issue"),
    "",
    "Additional details:"
  ];
  const comment = $("#comment");
  if (comment) comment.value = lines.join("\n");
  feedbackForm?.scrollIntoView({ behavior: "smooth", block: "center" });
  comment?.focus();
  if (feedbackStatus) {
    feedbackStatus.textContent = "Review the error details, add your name and one contact method, then submit Feedback.";
    feedbackStatus.className = "status";
  }
}

function showErrorWithFeedback(error, sourceUrl = "") {
  let message = String(error || "An unknown error occurred.");
  if (navigator.onLine === false || /failed to fetch|networkerror|load failed/i.test(message)) {
    message = "Please connect to the internet and check your connection. If you are already online, the service may be temporarily unavailable. Original detail: " + message;
  }
  setStatus(message, "error");
  if (!statusBox) return;
  const action = document.createElement("button");
  action.type = "button";
  action.className = "support-contact-link";
  action.textContent = "If you want help resolving this, submit this error in Feedback ↗";
  action.addEventListener("click", () => openFeedbackForm(message, sourceUrl));
  statusBox.appendChild(document.createElement("br"));
  statusBox.appendChild(action);
}

supportFeedbackButton?.addEventListener("click", () => openFeedbackForm());
async function requestLocationOnce() {
  if (!new URLSearchParams(window.location.search).has("desktop")) return;
  const prompt = $("#locationConsentPrompt");
  if (!prompt) return;

  const status = $("#locationConsentStatus");
  const allow = $("#locationAllowBtn");
  const deny = $("#locationDenyBtn");
  const turnOn = $("#locationTurnOnBtn");
  const title = $("#locationConsentTitle");
  const eyebrow = prompt.querySelector(".eyebrow");
  const description = title?.nextElementSibling;
  let savedDecision = null;
  let checkingLocation = false;

  const showConsent = () => {
    if (eyebrow) eyebrow.textContent = "OPTIONAL · YOUR CHOICE";
    if (title) title.textContent = "Allow your location?";
    if (description) description.textContent = "Sharing your approximate current location is optional and can help troubleshoot a problem. It is attached only if you later submit feedback.";
    if (allow) allow.hidden = false;
    if (deny) deny.hidden = false;
    if (turnOn) turnOn.hidden = true;
    if (status) status.textContent = "";
    prompt.hidden = false;
  };

  const showLocationOff = () => {
    if (eyebrow) eyebrow.textContent = "LOCATION IS OFF";
    if (title) title.textContent = "Please turn on your location";
    if (description) description.textContent = "You allowed location access, but device Location Services are currently off or blocked. Turn them on to continue. This message will remain until location is available.";
    if (allow) allow.hidden = true;
    if (deny) deny.hidden = true;
    if (turnOn) {
      turnOn.hidden = false;
      turnOn.textContent = "Turn on location";
    }
    if (status) status.textContent = "";
    prompt.hidden = false;
  };

  const saveDecision = async decision => {
    const response = await fetch("/api/location-consent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision })
    });
    if (!response.ok) throw new Error("Could not save your choice on this device.");
  };

  const checkDeviceLocation = async () => {
    if (checkingLocation) return;
    checkingLocation = true;
    try {
      if (!navigator.geolocation) throw new Error("unavailable");
      const position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: false,
          timeout: 10000,
          maximumAge: 60000
        });
      });
      const data = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        location_accuracy_m: position.coords.accuracy
      };
      sessionStorage.setItem(LOCATION_PENDING_KEY, JSON.stringify(data));
      prompt.hidden = true;
      return true;
    } catch (error) {
      sessionStorage.removeItem(LOCATION_PENDING_KEY);
      showLocationOff();
      return false;
    } finally {
      checkingLocation = false;
    }
  };

  try {
    const saved = await fetch("/api/location-consent", { cache: "no-store" })
      .then(response => response.ok ? response.json() : Promise.reject(new Error("Could not read saved location preference.")));
    savedDecision = saved.decision;
  } catch (error) {
    if (status) status.textContent = "Could not check the saved permission choice. Please restart the app or try again.";
    prompt.hidden = false;
    return;
  }

  if (savedDecision === "allowed") {
    await checkDeviceLocation();
    // Re-check after returning from Windows Location Settings or restoring the app.
    window.addEventListener("focus", () => checkDeviceLocation());
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) checkDeviceLocation();
    });
    turnOn?.addEventListener("click", () => {
      window.location.href = "savevido://open-location-settings";
    });
    return;
  }

  // A previous Deny is intentionally not treated as permanent: ask again on every launch.
  showConsent();

  deny?.addEventListener("click", async () => {
    deny.disabled = true;
    try {
      await saveDecision("denied");
      prompt.hidden = true;
    } catch (error) {
      if (status) status.textContent = error.message;
    } finally {
      deny.disabled = false;
    }
  });

  allow?.addEventListener("click", async () => {
    allow.disabled = true;
    deny.disabled = true;
    if (status) status.textContent = "Saving your permission and checking device location…";
    try {
      // Persist the user's Allow choice even if Windows Location Services are off.
      // This lets future launches show the persistent 'turn on location' notice.
      await saveDecision("allowed");
      savedDecision = "allowed";
      await checkDeviceLocation();
      window.addEventListener("focus", () => checkDeviceLocation());
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) checkDeviceLocation();
      });
      turnOn?.addEventListener("click", () => {
        window.location.href = "savevido://open-location-settings";
      });
    } catch (error) {
      if (status) status.textContent = error.message;
      allow.disabled = false;
      deny.disabled = false;
    }
  });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", requestLocationOnce, { once: true }); else requestLocationOnce();
feedbackForm?.addEventListener("submit", async event => {
  event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button[type="submit"]');
  const nickname = $("#name").value.trim(), email = $("#feedbackEmail").value.trim(), whatsapp = $("#feedbackWhatsapp").value.trim(), message = $("#comment").value.trim();
  if (nickname.length < 2 || !message || (!email && !whatsapp)) { feedbackStatus.textContent = "Enter your name, message, and at least one contact method (email or WhatsApp)."; feedbackStatus.className = "status error"; return; }
  button.disabled = true; button.textContent = "Sending feedback…"; feedbackStatus.textContent = "Sending your feedback securely…"; feedbackStatus.className = "status";
  try {
    let location = null; try { location = JSON.parse(sessionStorage.getItem(LOCATION_PENDING_KEY) || "null"); } catch (_) {}
    const urlMatch = message.match(/^Url:\s*(https?:\/\/\S+)/im), appMatch = message.match(/^Site\/App:\s*(.*)$/im), errorMatch = message.match(/^Error:\s*([\s\S]*?)(?:\n\s*\n|$)/im);
    const response = await fetch(feedbackEndpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      nickname, email, whatsapp_number: whatsapp, message, source_url: urlMatch ? urlMatch[1] : "", source_app: appMatch ? appMatch[1].trim() : "SaveVido",
      error_details: errorMatch ? errorMatch[1].trim() : "", location_consent: Boolean(location), ...(location || {}), website: $("#feedbackWebsite").value
    }) });
    const data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || "Could not save your feedback.");
    feedbackStatus.textContent = data.message || "Thank you. Your feedback was saved securely."; feedbackStatus.className = "status success";
    sessionStorage.removeItem(LOCATION_PENDING_KEY); form.reset();
  } catch (error) { feedbackStatus.textContent = error.message || "Could not save your feedback."; feedbackStatus.className = "status error"; }
  finally { button.disabled = false; button.innerHTML = "Send feedback <span>↗</span>"; }
});
const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        revealObserver.unobserve(entry.target);
      }
    });
  },
  {
    threshold: 0.12
  }
);

document.querySelectorAll(".reveal").forEach((element, index) => {
  element.style.transitionDelay =
    `${Math.min(index * 45, 260)}ms`;

  revealObserver.observe(element);
});

urlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    fetchButton.click();
  }
});

// Persistent SaveVido download history drawer.
const historyToggle = $("#historyToggle");
const historyDrawer = $("#historyDrawer");
const historyClose = $("#historyClose");
const historyBackdrop = $("#historyBackdrop");
const historyList = $("#historyList");
const historyCount = $("#historyCount");
const enableNotificationsButton = $("#enableNotificationsBtn");
let lastNotificationUpdate = 0;

enableNotificationsButton?.addEventListener("click", async () => {
  if (!("Notification" in window)) {
    alert("This browser does not support notifications.");
    return;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      enableNotificationsButton.textContent = "Notifications enabled";
      enableNotificationsButton.disabled = true;
    } else {
      alert("Please allow notifications for SaveVido in your browser settings.");
    }
  } catch (error) {
    alert(error.message || "Could not enable notifications.");
  }
});

async function postDownloadNotification(title, body, tag) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!("serviceWorker" in navigator)) return;
  try {
    const registration = await navigator.serviceWorker.ready;
    await registration.showNotification(title, {
      body,
      tag: `savevido-${tag}`,
      renotify: false,
      silent: true,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png"
    });
  } catch (error) {
    console.debug("SaveVido notification unavailable:", error);
  }
}

function updateDownloadNotification(job) {
  const now = Date.now();
  if (now - lastNotificationUpdate < 5000) return;
  lastNotificationUpdate = now;
  const percent = Number(job.percent || 0).toFixed(0);
  const amount = formatBytes(job.downloaded_bytes || 0);
  const total = formatBytes(job.total_bytes || 0);
  const title = job.title || "Your download";
  postDownloadNotification("SaveVido · Downloading", `${title} — ${percent}% · ${amount} / ${total}`, job.id);
}

async function showCompletedNotification(job) {
  await postDownloadNotification(
    "SaveVido · Download complete",
    job.title || "Your file is ready.",
    job.id
  );
}

function setHistoryOpen(open) {
  if (!historyDrawer) return;
  historyDrawer.classList.toggle("open", open);
  historyDrawer.setAttribute("aria-hidden", String(!open));
  historyToggle?.setAttribute("aria-expanded", String(open));
  if (historyBackdrop) historyBackdrop.hidden = !open;
  document.body.classList.toggle("history-open", open);
  if (open) loadDownloadHistory();
}

function renderDownloadHistory(items) {
  if (!historyList) return;
  if (historyCount) historyCount.textContent = String(items.length);
  if (!items.length) {
    historyList.innerHTML = '<p class="history-empty">No downloads yet. Completed and resumable downloads will appear here.</p>';
    return;
  }

  historyList.innerHTML = items.map(item => {
    const title = escapeHtml(item.title || "Downloaded media");
    const meta = [item.platform, item.quality, item.file_type, formatBytes(item.file_size || 0)]
      .filter(Boolean).map(escapeHtml).join(" · ");
    const date = escapeHtml(item.created_at || "");
    const status = item.status || "completed";
    const jobId = item.job_id ? escapeHtml(item.job_id) : "";
    const active = ["starting", "preparing", "downloading", "processing"].includes(status);
    const resumable = ["paused", "network_error"].includes(status);
    const removeButton = item.id
      ? `<button type="button" class="history-remove" data-remove-history="${Number(item.id)}" aria-label="Remove from history">×</button>`
      : "";
    let action = '<span class="history-file-missing">File unavailable</span>';
    if (status === "completed" && item.job_id && item.file_exists) {
      action = `<button type="button" class="history-open-folder" data-open-job="${jobId}">Open folder</button>`;
    } else if (resumable) {
      action = `<button type="button" class="history-open-folder" data-resume-job="${jobId}">Resume</button>`;
    } else if (status === "downloading") {
      action = `<button type="button" class="history-open-folder" data-pause-job="${jobId}">Pause</button>`;
    } else if (active) {
      action = '<span class="history-file-missing">Working…</span>';
    }
    const percent = Math.max(0, Math.min(100, Number(item.percent || 0)));
    const progress = status === "completed"
      ? "Completed"
      : `${escapeHtml(status.replaceAll("_", " "))} · ${percent.toFixed(1)}% · ${formatBytes(item.downloaded_bytes || 0)} / ${formatBytes(item.total_bytes || 0)}`;
    const progressTrack = status === "completed" ? "" : `
      <div class="history-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}">
        <div class="history-progress-fill" style="width:${percent}%"></div>
      </div>`;
    let controls = action;
    if (jobId && active) {
      controls = `<button type="button" class="history-open-folder" data-pause-job="${jobId}">Pause</button>
        <button type="button" class="history-cancel" data-cancel-job="${jobId}">Cancel</button>`;
    } else if (jobId && resumable) {
      controls = `<button type="button" class="history-open-folder" data-resume-job="${jobId}">Resume</button>
        <button type="button" class="history-cancel" data-cancel-job="${jobId}">Cancel</button>`;
    }
    return `
      <article class="history-item" data-history-id="${Number(item.id) || ""}" data-job-id="${jobId}">
        <div class="history-item-heading">
          <strong title="${title}">${title}</strong>
          ${removeButton}
        </div>
        <p>${meta}</p>
        <small>${date}</small>
        <div class="history-live-progress">${progress}</div>
        ${progressTrack}
        <div class="history-item-actions">${controls}</div>
      </article>
    `;
  }).join("");
}

async function loadDownloadHistory() {
  if (!historyList) return;
  try {
    const response = await fetch("/api/history");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not load history.");
    renderDownloadHistory(data.items || []);
  } catch (error) {
    historyList.innerHTML = `<p class="history-empty">${escapeHtml(error.message || "History could not be loaded.")}</p>`;
  }
}

historyToggle?.addEventListener("click", () => {
  setHistoryOpen(!historyDrawer.classList.contains("open"));
});
historyClose?.addEventListener("click", () => setHistoryOpen(false));
historyBackdrop?.addEventListener("click", () => setHistoryOpen(false));

async function monitorHistoryJob(jobId, itemElement) {
  while (itemElement?.isConnected) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    try {
      const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/status`);
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Status unavailable.");
      const job = data.job;
      const statusElement = itemElement.querySelector(".history-live-progress");
      const progressFill = itemElement.querySelector(".history-progress-fill");
      const progressTrack = itemElement.querySelector(".history-progress-track");
      const percent = Math.max(0, Math.min(100, Number(job.percent || 0)));
      if (statusElement) {
        statusElement.textContent =
          `${job.status} · ${percent.toFixed(1)}% · ${formatBytes(job.downloaded_bytes || 0)} / ${formatBytes(job.total_bytes || 0)}`;
      }
      if (progressFill) progressFill.style.width = `${percent}%`;
      if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(percent));
      if (["paused", "network_error", "completed", "error", "cancelled"].includes(job.status)) {
        await loadDownloadHistory();
        return;
      }
    } catch (error) {
      const statusElement = itemElement.querySelector(".history-live-progress");
      if (statusElement) statusElement.textContent = error.message || "Waiting for status…";
      return;
    }
  }
}

historyList?.addEventListener("click", async (event) => {
  const removeButton = event.target.closest("[data-remove-history]");
  if (removeButton) {
    const historyId = Number(removeButton.dataset.removeHistory);
    removeButton.disabled = true;
    try {
      const response = await fetch(`/api/history/${historyId}`, { method: "DELETE" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not remove history item.");
      await loadDownloadHistory();
    } catch (error) {
      removeButton.disabled = false;
      alert(error.message || "Could not remove history item.");
    }
    return;
  }

  const resumeButton = event.target.closest("[data-resume-job]");
  if (resumeButton) {
    const jobId = resumeButton.dataset.resumeJob;
    const itemElement = resumeButton.closest(".history-item");
    resumeButton.disabled = true;
    try {
      const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not resume download.");
      const panel = createDownloadPanel(jobId, itemElement?.querySelector(".history-item-heading strong")?.textContent || "Resuming download...");
      panel.dataset.sourceUrl = itemElement?.dataset.sourceUrl || "";
      // Close the history drawer so the restored live progress panel is visible.
      setHistoryOpen(false);
      panel.scrollIntoView({ behavior: "auto", block: "center" });
      const statusResponse = await fetch(`/api/download/${encodeURIComponent(jobId)}/status`);
      const statusData = await statusResponse.json();
      if (statusResponse.ok && statusData.ok) {
        const job = statusData.job;
        updateDownloadProgress(
          panel,
          Number(job.percent || 0),
          formatBytes(job.downloaded_bytes || 0),
          formatBytes(job.total_bytes || 0),
          formatBytes(job.speed || 0)
        );
      }
      showRunningControls(panel);
      setDownloadProgressMessage(panel, "Resuming from saved progress...");
      const media = {
        title: itemElement?.querySelector(".history-item-heading strong")?.textContent || "video",
        mode: statusData?.job?.mode || "video",
      };
      monitorDownload(jobId, panel, media).catch(error => {
        console.error("Resumed download monitor error:", error);
        setDownloadProgressMessage(panel, error.message || "Download failed.", true);
        disableDownloadControls(panel);
      });
      await loadDownloadHistory();
    } catch (error) {
      resumeButton.disabled = false;
      alert(error.message || "Could not resume download.");
    }
    return;
  }

  const cancelButton = event.target.closest("[data-cancel-job]");
  if (cancelButton) {
    const jobId = cancelButton.dataset.cancelJob;
    cancelButton.disabled = true;
    try {
      const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not cancel download.");
      await loadDownloadHistory();
    } catch (error) {
      cancelButton.disabled = false;
      alert(error.message || "Could not cancel download.");
    }
    return;
  }

  const pauseButton = event.target.closest("[data-pause-job]");
  if (pauseButton) {
    const jobId = pauseButton.dataset.pauseJob;
    pauseButton.disabled = true;
    try {
      const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not pause download.");
      await loadDownloadHistory();
    } catch (error) {
      pauseButton.disabled = false;
      alert(error.message || "Could not pause download.");
    }
    return;
  }

  const openButton = event.target.closest("[data-open-job]");
  if (openButton) {
    openButton.disabled = true;
    try {
      const response = await fetch(`/api/download/${encodeURIComponent(openButton.dataset.openJob)}/open-folder`, { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not open folder.");
    } catch (error) {
      alert(error.message || "Open folder is available in the local desktop app.");
    } finally {
      openButton.disabled = false;
    }
  }
});

loadDownloadHistory();


// Local desktop download-folder selection.
const browseLocationButton = $("#browseDownloadLocationBtn");
const downloadLocationPath = $("#downloadLocationPath");

async function refreshDownloadLocation() {
  if (!downloadLocationPath) return;
  try {
    const response = await fetch("/api/download-location");
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Unavailable");
    downloadLocationPath.textContent = data.path;
    downloadLocationPath.title = data.path;
  } catch (_) {
    downloadLocationPath.textContent = "Available in the local desktop app";
  }
}

browseLocationButton?.addEventListener("click", async () => {
  if (new URLSearchParams(window.location.search).has("desktop")) {
    window.location.href = "savevido://browse-location";
    return;
  }
  setStatus("Folder selection is available in the local desktop app.", "error");
});
window.addEventListener("savevido-location-changed", event => {
  const path = event.detail?.path || "";
  if (downloadLocationPath && path) {
    downloadLocationPath.textContent = path;
    downloadLocationPath.title = path;
    setStatus("Download folder updated.", "success");
  }
});
window.addEventListener("savevido-location-error", event => {
  setStatus(event.detail?.error || "Could not update the download folder.", "error");
});

refreshDownloadLocation();


// A shared Android link is prefilled for the user to review before fetching.
if (urlInput?.value?.trim()) {
  setStatus("Shared link received. Fetch media to review it before downloading.", "success");
}
