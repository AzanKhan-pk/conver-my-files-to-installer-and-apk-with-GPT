const $ = (selector) => document.querySelector(selector);

const urlInput = $("#url");
const fetchButton = $("#fetchBtn");
const statusBox = $("#status");
const resultBox = $("#result");
const useBrowserSession = $("#useBrowserSession");
const browserChoice = $("#browserChoice");
const browserChoiceWrap = $("#browserChoiceWrap");

let selectedMode = "video";
let selectedQuality = "720p";
let currentVideo = null;
let currentImages = null;
let currentImagePlatform = "";

function getImageSessionOptions() {
  return {
    use_browser_session: Boolean(useBrowserSession?.checked),
    browser: browserChoice?.value || "chrome"
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
    setStatus(error.message || "Image download failed.", "error");
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
        Download ${selectedMode === "audio" ? "MP3" : "MP4"} ↗
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

        // Try gallery extraction on every safe, supported image-capable host.
        // Video-only URLs simply fall back to the existing yt-dlp flow.
        const supportedImageSites = [
          "tiktok.com", "instagram.com", "facebook.com", "fb.com", "fb.watch",
          "pinterest.com", "pin.it", "x.com", "twitter.com", "reddit.com", "redd.it",
          "youtube.com", "youtube-nocookie.com", "youtu.be",
          "vimeo.com", "dailymotion.com", "dai.ly",
          "twitch.tv", "soundcloud.com", "snd.sc",
          "bilibili.com", "b23.tv", "imgur.com",
          "postimg.cc", "postimages.org", "imageshack.com",
          "i.pinimg.com", "images.pinimg.com", "fbcdn.net", "fbsbx.com",
          "cdninstagram.com", "tiktokcdn.com", "tiktokv.com",
          "byteoversea.com", "twimg.com", "redditmedia.com",
          "ytimg.com", "vimeocdn.com", "dmcdn.net",
          "ttvnw.net", "jtvnw.net", "twitchcdn.net", "sndcdn.com",
          "hdslb.com", "cloudinary.com", "cloudfront.net",
          "images.unsplash.com"
        ];

        // TikTok video links must go straight to yt-dlp. Sending every
        // TikTok URL through gallery-dl first adds a second slow request
        // before the actual video metadata lookup.
        const isTikTokVideo = isHostOrSubdomain("tiktok.com")
          && /\/video\/\d+/.test(path);
        if (isTikTokVideo) return false;

        // Keep direct image URLs and TikTok photo posts eligible for gallery extraction.
        return /\.(jpe?g|png|webp|gif|avif)$/i.test(path)
          || supportedImageSites.some(isHostOrSubdomain);
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
        body: JSON.stringify({ url })
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
    setStatus(
      error.message || "Something went wrong.",
      "error"
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

  setButtonLoading(downloadButton, true, "Starting...", `Download ${media.mode === "audio" ? "MP3" : "MP4"} ↗`);

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: media.url, mode: media.mode, quality: media.quality })
    });
    const data = await response.json();
    if (!response.ok || !data.ok || !data.job_id) {
      throw new Error(data.error || "Could not start the download.");
    }

    const panel = createDownloadPanel(data.job_id, media.title);
    setStatus("Download started. You can start another download while this one runs.", "success");
    monitorDownload(data.job_id, panel, media).catch(error => {
      console.error("Download monitor error:", error);
      setDownloadProgressMessage(panel, error.message || "Download failed.", true);
      disableDownloadControls(panel);
    });
  } catch (error) {
    console.error("Download start error:", error);
    setStatus(error.message || "Download failed.", "error");
  } finally {
    setButtonLoading(downloadButton, false, "Starting...", `Download ${media.mode === "audio" ? "MP3" : "MP4"} ↗`);
  }
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return index === 0 ? `${Math.round(value)} ${units[index]}` : `${value.toFixed(2)} ${units[index]}`;
}

function createDownloadPanel(jobId, title) {
  const panel = document.createElement("div");
  panel.className = "download-progress-panel";
  panel.dataset.jobId = jobId;
  panel.innerHTML = `
    <div class="download-progress-header">
      <strong class="download-progress-title">${escapeHtml(title || "Downloading...")}</strong>
      <span data-role="percent">0%</span>
    </div>
    <div class="download-progress-bar"><div data-role="fill" class="download-progress-fill" style="width:0%"></div></div>
    <div class="download-progress-info">
      <span data-role="size">0 B / 0 B</span>
      <span data-role="speed">0 B/s</span>
    </div>
    <div class="download-progress-actions">
      <button data-action="pause" type="button">⏸ Pause</button>
      <button data-action="resume" type="button" hidden>▶ Resume</button>
      <button data-action="cancel" type="button">✕ Cancel</button>
    </div>
    <div data-role="message" class="download-progress-message">Preparing download...</div>
  `;

  const activityList = $("#downloadActivityList");
  (activityList || $("#downloadBtn").parentElement).appendChild(panel);

  panel.querySelector('[data-action="pause"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "pause"));
  panel.querySelector('[data-action="resume"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "resume"));
  panel.querySelector('[data-action="cancel"]').addEventListener("click", () =>
    controlDownload(panel, jobId, "cancel"));
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
    await new Promise(resolve => setTimeout(resolve, 1000));
    const response = await fetch(`/api/download/${encodeURIComponent(jobId)}/status`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not read download status.");

    const job = data.job;
    const percent = Number(job.percent || 0);
    const downloaded = formatBytes(job.downloaded_bytes || 0);
    const total = formatBytes(job.total_bytes || 0);
    const speed = formatBytes(job.speed || 0);
    updateDownloadProgress(panel, percent, downloaded, total, speed);
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
      const fileResponse = await fetch(`/api/download/${encodeURIComponent(jobId)}/file`);
      if (!fileResponse.ok) {
        let message = "Could not retrieve the downloaded file.";
        try { const errorData = await fileResponse.json(); message = errorData.error || message; } catch (_) {}
        throw new Error(message);
      }
      const blob = await fileResponse.blob();
      if (!blob.size) throw new Error("Downloaded file is empty.");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const safeName = (job.title || media.title || "video").replace(/[^\w\s.-]/g, "").trim().slice(0, 90) || "video";
      link.href = url;
      link.download = `${safeName}.${media.mode === "audio" ? "mp3" : "mp4"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      setDownloadProgressMessage(panel, "✓ Download completed.");
      disableDownloadControls(panel);
      await showCompletedNotification(job);
      await loadDownloadHistory();
      return;
    }
  }
}

function updateDownloadProgress(panel, percent, downloaded, total, speed) {
  const percentElement = panel.querySelector('[data-role="percent"]');
  const fillElement = panel.querySelector('[data-role="fill"]');
  const sizeElement = panel.querySelector('[data-role="size"]');
  const speedElement = panel.querySelector('[data-role="speed"]');
  if (percentElement) percentElement.textContent = `${percent.toFixed(1)}%`;
  if (fillElement) fillElement.style.width = `${Math.min(percent, 100)}%`;
  if (sizeElement) sizeElement.textContent = `${downloaded} / ${total}`;
  if (speedElement) speedElement.textContent = `${speed}/s`;
}

function setDownloadProgressMessage(panel, message, error = false) {
  const element = panel.querySelector('[data-role="message"]');
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("error", error);
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

$("#commentForm").addEventListener("submit", async (event) => {
  event.preventDefault();

  const form = event.currentTarget;
  const submitButton = form.querySelector("button");
  const commentStatus = $("#commentStatus");

  const name = $("#name").value.trim();
  const comment = $("#comment").value.trim();

  if (!name || !comment) {
    commentStatus.textContent = "Please complete both fields.";
    commentStatus.className = "status error";
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "Saving...";

  commentStatus.textContent = "Saving your note...";
  commentStatus.className = "status";

  try {
    const response = await fetch("/api/comments", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        name,
        comment
      })
    });

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(
        data.error || "Could not save your feedback."
      );
    }

    commentStatus.textContent =
      data.message || "Thanks, your feedback is saved.";
    commentStatus.className = "status success";

    form.reset();
  } catch (error) {
    commentStatus.textContent =
      error.message || "Could not save your feedback.";
    commentStatus.className = "status error";
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Send feedback <span>↗</span>";
  }
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
    const progress = status === "completed"
      ? "Completed"
      : `${escapeHtml(status.replaceAll("_", " "))} · ${Number(item.percent || 0).toFixed(1)}% · ${formatBytes(item.downloaded_bytes || 0)} / ${formatBytes(item.total_bytes || 0)}`;
    return `
      <article class="history-item" data-history-id="${Number(item.id) || ""}" data-job-id="${jobId}">
        <div class="history-item-heading">
          <strong title="${title}">${title}</strong>
          ${removeButton}
        </div>
        <p>${meta}</p>
        <small>${date}</small>
        <div class="history-live-progress">${progress}</div>
        <div class="history-item-actions">${action}</div>
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
      if (statusElement) {
        statusElement.textContent =
          `${job.status} · ${Number(job.percent || 0).toFixed(1)}% · ${formatBytes(job.downloaded_bytes || 0)} / ${formatBytes(job.total_bytes || 0)}`;
      }
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
      await monitorHistoryJob(jobId, itemElement);
    } catch (error) {
      resumeButton.disabled = false;
      alert(error.message || "Could not resume download.");
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
  browseLocationButton.disabled = true;
  browseLocationButton.textContent = "Choose folder…";
  try {
    const response = await fetch("/api/browse-location", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not choose folder.");
    if (!data.cancelled && downloadLocationPath) {
      downloadLocationPath.textContent = data.path;
      downloadLocationPath.title = data.path;
      setStatus("Download folder updated.", "success");
    }
  } catch (error) {
    setStatus(error.message || "Folder selection is available in the local desktop app.", "error");
  } finally {
    browseLocationButton.disabled = false;
    browseLocationButton.textContent = "Browse location";
  }
});

refreshDownloadLocation();


// A shared Android link is prefilled for the user to review before fetching.
if (urlInput?.value?.trim()) {
  setStatus("Shared link received. Fetch media to review it before downloading.", "success");
}
