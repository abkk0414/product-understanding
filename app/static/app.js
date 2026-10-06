const form = document.querySelector("#answer-form");
const questionInput = document.querySelector("#question");
const productSelect = document.querySelector("#product");
// Published-only is the safe default. Preview remains an explicit opt-in for
// future owner review work.
const publishedOnlyToggle = document.querySelector("#published-only");
const reviewModeToggle = document.querySelector("#review-mode");
const logMissesToggle = document.querySelector("#log-misses");
const previewWarning = document.querySelector("#preview-warning");
const reviewModeNote = document.querySelector("#review-mode-note");
const resultsRegion = document.querySelector("#results");
const emptyState = document.querySelector("#empty-state");
const emptyMessage = document.querySelector("#empty-message");
const exampleQuestions = document.querySelector("#example-questions");
const clarifyBox = document.querySelector("#clarify");
const errorBox = document.querySelector("#error");
const notServedBox = document.querySelector("#not-served");
const submitButton = form.querySelector("button[type='submit']");
const procedureSelect = document.querySelector("#procedure");
const showProcedureButton = document.querySelector("#show-procedure");
const procedureRegion = document.querySelector("#procedure-region");
const procedureTitle = document.querySelector("#procedure-title");
const procedureProgress = document.querySelector("#procedure-progress");
const procedureBanner = document.querySelector("#procedure-banner");
const stepStatus = document.querySelector("#step-status");
const stepNumber = document.querySelector("#step-number");
const stepAction = document.querySelector("#step-action");
const stepClaim = document.querySelector("#step-claim");
const pagePanel = document.querySelector("#page-panel");
const previousStepButton = document.querySelector("#previous-step");
const nextStepButton = document.querySelector("#next-step");

const EXAMPLES = {
  "graco-ready2jet-2212125": [
    "How do I fold the Ready2Jet stroller?",
    "Can I fold it with the car seat attached?",
    "Can I machine wash the stroller seat?",
  ],
  "graco-snugride-35-lite-lx": [
    "What is the max child weight for the SnugRide?",
    "How do I install the base with lower anchors?",
  ],
  "levoit-core-300s": [
    "How do I replace the filter?",
    "How quiet is it?",
  ],
  "apple-macbook-air-13-m3": [
    "How do I pair a Bluetooth device?",
    "Where is the headphone jack?",
  ],
  default: [
    "How do I fold the Ready2Jet stroller?",
    "Can I machine wash the stroller seat?",
    "How do I replace the Levoit filter?",
  ],
};

// Owner tools stay out of the customer answer. ?owner=1 shows the legacy
// review controls locally until P2 adds an authenticated owner workspace.
const OWNER_MODE = new URLSearchParams(window.location.search).get("owner") === "1";
document.querySelectorAll(".owner-controls").forEach((node) => { node.hidden = !OWNER_MODE; });
let answerContext = null;

// Official manufacturer photos from each product's source vault, served
// through the existing manifest-checked /media/ route.
const SHOWCASE = {
  "graco-ready2jet-2212125": { image: "images/view-01-front-3q.png", questions: ["How do I fold it?", "Can I machine wash the seat?"] },
  "levoit-core-300s": { image: "images/levoit-core-300s-three-quarter-view-2048.jpg", questions: ["How do I replace the filter?", "How quiet is it?"] },
  "apple-macbook-air-13-m3": { image: "images/store-color-midnight.jpg", questions: ["How do I pair a Bluetooth device?", "Where is the headphone jack?"] },
  "bose-qc-ultra-headphones": { image: "images/black-three-quarter-view.png", questions: ["What's the battery life?", "How do I put them in pairing mode?"] },
  "graco-snugride-35-lite-lx": { image: "images/front-3q-seat-in-base.jpg", questions: ["What is the max child weight?", "How do I install the base with lower anchors?"] },
};
const catalogRegion = document.querySelector("#product-cards");
const heroMedia = document.querySelector("#hero-media");

function productImageUrl(productDir) {
  const entry = SHOWCASE[productDir];
  return entry ? `/media/${productDir}/${entry.image}` : null;
}

function renderCatalog(products) {
  catalogRegion.replaceChildren();
  products.forEach((product) => {
    const entry = SHOWCASE[product.dir];
    if (!entry) return;
    const card = element("article", "product-card");
    const image = element("img");
    image.src = productImageUrl(product.dir);
    image.alt = `${product.brand} ${product.model}`;
    image.loading = "lazy";
    const body = element("div", "product-card-body");
    body.append(element("span", "product-card-brand", product.brand));
    body.append(element("h3", "product-card-name", product.model));
    entry.questions.forEach((question) => {
      const button = element("button", "", question);
      button.type = "button";
      button.addEventListener("click", async () => {
        productSelect.value = product.dir;
        answerContext = null;
        questionInput.value = question;
        await runSearch();
      });
      body.append(button);
    });
    card.append(image, body);
    catalogRegion.append(card);
  });
}

function renderHeroMedia() {
  const showPhoto = () => {
    heroMedia.replaceChildren();
    const image = element("img");
    image.src = productImageUrl("graco-ready2jet-2212125");
    image.alt = "Graco Ready2Jet stroller";
    const caption = element("figcaption");
    caption.append(element("span", "", "Manufacturer photo"), document.createTextNode("Graco Ready2Jet"));
    heroMedia.append(image, caption);
  };
  const video = element("video");
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.autoplay = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  video.setAttribute("aria-label", "Ready2Jet fold demonstration");
  video.addEventListener("error", showPhoto, { once: true });
  video.src = "/dev-media/r2j-fold-main";
  const caption = element("figcaption");
  caption.append(element("span", "", "Dev preview · unverified render"), document.createTextNode("How the Ready2Jet folds"));
  heroMedia.append(video, caption);
  heroMedia.hidden = false;
}

let procedureSteps = [];
let activeStepIndex = 0;
let procedureStatus = null;
let currentPayload = null;
let currentQuestion = "";
let activeVideoPolls = [];

function stopVideoPolls() {
  activeVideoPolls.forEach((timer) => clearInterval(timer));
  activeVideoPolls = [];
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusLabel(status) {
  if (status === "SUSPENDED") return "Suspended";
  if (status === "CANDIDATE") return "Pending";
  return "Published";
}

function readableName(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function renderCitation(citation) {
  const wrapper = element("div", "citation");
  wrapper.append(element("blockquote", "", `“${citation.quote || "No quote recorded"}”`));
  const sourceName = citation.source_name || "Recorded source";
  if (citation.origin_url) {
    const link = element("a", "", `Open ${sourceName} ↗`);
    link.href = citation.origin_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    wrapper.append(link);
  } else {
    wrapper.append(element("span", "source-name", sourceName));
  }
  return wrapper;
}

function mediaCaption(media) {
  const parts = [];
  if (media.awaiting_approval) parts.push("Pending media");
  if (media.label) parts.push(media.label);
  if (media.rationale) parts.push(media.rationale);
  if (media.provenance) parts.push(`Provenance: ${media.provenance}`);
  return parts.join(" · ");
}

function isGeneratedProcedureVideo(media) {
  return media.kind === "DERIVED_ASSET" && (
    media.asset_type === "PROCEDURE_VIDEO_MP4" ||
    String(media.label || "").startsWith("Generated ")
  );
}

function mediaModality(media) {
  return media.kind === "VIDEO_FILE" || media.kind === "VIDEO_URL" ||
    isGeneratedProcedureVideo(media) ? "video" : "image";
}

function renderMedia(media) {
  const wrapper = element("figure", "media-item");
  const isGeneratedVideo = isGeneratedProcedureVideo(media);
  if (isGeneratedVideo) {
    const frame = element("div", "media-frame generated-video-frame");
    const video = element("video", "bound-video generated-video");
    video.controls = true;
    video.autoplay = true;
    video.muted = true;
    video.defaultMuted = true;
    video.setAttribute("muted", "");
    video.playsInline = true;
    video.preload = "auto";
    if (media.poster_url) video.poster = media.poster_url;
    video.addEventListener("canplay", () => {
      video.play().catch(() => {
        // The poster and controls remain available if autoplay is blocked.
      });
    }, { once: true });
    video.src = media.url;
    frame.append(video);
    if (media.watermark) frame.append(element("span", "derived-watermark", media.watermark));
    wrapper.append(frame);
  } else if (media.kind === "IMAGE" || media.kind === "DERIVED_ASSET") {
    const frame = element("div", "media-frame");
    const image = element("img", "bound-image");
    image.src = media.url;
    image.alt = media.label || media.rationale;
    image.loading = "lazy";
    frame.append(image);
    if (media.watermark) frame.append(element("span", "derived-watermark", media.watermark));
    wrapper.append(frame);
  } else if (media.kind === "VIDEO_FILE") {
    const video = element("video", "bound-video");
    video.src = media.url;
    video.controls = true;
    video.preload = "metadata";
    if (media.poster_url) video.poster = media.poster_url;
    if (media.start_seconds !== null) video.currentTime = media.start_seconds;
    wrapper.append(video);
    wrapper.append(element("p", "rights-note", `Rights: ${media.rights_note}`));
  } else if (media.kind === "VIDEO_URL") {
    const link = element("a", "official-video-link", "Open official video ↗");
    const start = media.start_seconds === null ? "" : `#t=${media.start_seconds}`;
    link.href = `${media.url}${start}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    wrapper.append(link);
  } else if (media.kind === "PDF_PAGE") {
    const link = element("a", "manual-page-link", `Open manual page ${media.page} ↗`);
    link.href = `${media.url}#page=${media.page}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    wrapper.append(link);
  }
  wrapper.append(element("figcaption", "", mediaCaption(media)));
  return wrapper;
}

const VIDEO_POLL_INTERVAL_MS = 2500;
const VIDEO_POLL_MAX_ATTEMPTS = 240; // ~10 minutes; model generation can be slow

function pollVideoJob(job, slot) {
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts += 1;
    if (attempts > VIDEO_POLL_MAX_ATTEMPTS) {
      clearInterval(timer);
      renderVideoSlotFailure(slot);
      return;
    }
    try {
      const response = await fetch(job.poll_url);
      if (!response.ok) throw new Error("poll failed");
      const payload = await response.json();
      if (payload.state === "ready" && payload.media) {
        clearInterval(timer);
        slot.classList.remove("waiting");
        slot.replaceChildren(renderMedia(payload.media));
      } else if (payload.state === "failed") {
        clearInterval(timer);
        renderVideoSlotFailure(slot);
      }
    } catch {
      // Transient poll errors are retried until the attempt cap.
    }
  }, VIDEO_POLL_INTERVAL_MS);
  activeVideoPolls.push(timer);
}

function renderVideoSlotFailure(slot) {
  slot.classList.remove("waiting");
  slot.classList.add("failed");
  slot.replaceChildren(element(
    "p", "video-slot-sub",
    "No walkthrough video could be generated for this procedure yet."));
}

function renderVideoSlot(videoJob) {
  const slot = element("div", "video-slot waiting");
  slot.setAttribute("role", "status");
  const shimmer = element("div", "video-shimmer");
  shimmer.append(element("span", "video-shimmer-icon", "▶"));
  slot.append(shimmer);
  const copy = element("div", "video-slot-copy");
  copy.append(element("p", "video-slot-title", "Video generating…"));
  copy.append(element(
    "p", "video-slot-sub",
    "The written answer is ready now. A real demonstration video is being generated in the background and will replace this placeholder automatically."));
  slot.append(copy);
  if (videoJob.state === "failed") {
    renderVideoSlotFailure(slot);
  } else {
    pollVideoJob(videoJob, slot);
  }
  return slot;
}

function renderClaimDetails(result) {
  const details = element("details", "claim-details");
  details.append(element("summary", "", "Details"));
  details.append(element("p", "meta", `Tier ${result.tier} · ${result.claim_id}`));
  if (result.raw_answer) details.append(element("p", "raw-answer", result.raw_answer));
  return details;
}

async function recordReview(productDir, claimId, disposition, rationale, controls) {
  controls.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: productDir, claim_id: claimId, disposition, rationale }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not record review.");
    await runSearch();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    controls.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function reviewControls(productDir, claimId, tier) {
  const controls = element("div", "review-actions");
  controls.append(element("p", "review-scope", `${tier} · one decision recorded to this pack`));
  const rationale = element("input", "review-rationale");
  rationale.type = "text";
  rationale.maxLength = 2000;
  rationale.placeholder = "Optional rationale";
  rationale.setAttribute("aria-label", `Review rationale for ${claimId}`);
  controls.append(rationale);
  const buttons = element("div", "review-buttons");
  [
    ["Approve for publish", "APPROVED_FOR_PUBLISH", "approve"],
    ["Reject for serving", "REJECTED_FOR_SERVING", "reject"],
    ["Needs rework", "NEEDS_REWORK", "rework"],
  ].forEach(([label, disposition, className]) => {
    const button = element("button", className, label);
    button.type = "button";
    button.addEventListener("click", () => recordReview(
      productDir, claimId, disposition, rationale.value, controls));
    buttons.append(button);
  });
  controls.append(buttons);
  return controls;
}

async function reportIssue(result, note, status) {
  try {
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: currentQuestion, product: result.product_dir, claim_id: result.claim_id, note }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not save feedback.");
    status.textContent = "Saved locally.";
  } catch (error) {
    status.textContent = error.message;
  }
}

function renderFeedback(result) {
  if (result.claim_id.startsWith("procedure:")) return null;
  const details = element("details", "feedback-control");
  details.append(element("summary", "", "Report an issue"));
  const note = element("input", "feedback-note");
  note.type = "text";
  note.maxLength = 2000;
  note.placeholder = "Optional note";
  note.setAttribute("aria-label", `Issue note for ${result.claim_id}`);
  const button = element("button", "secondary-button", "Save report locally");
  button.type = "button";
  const status = element("span", "feedback-status");
  button.addEventListener("click", () => reportIssue(result, note.value, status));
  details.append(note, button, status);
  return details;
}

async function openProcedure(productDir, procedure) {
  productSelect.value = productDir;
  await loadProcedures();
  procedureSelect.value = procedure;
  showProcedureButton.disabled = false;
  await showProcedure();
}

function renderResult(result, renderedMedia, presentation) {
  const unpublished = result.status !== "PUBLISHED";
  const card = element("article", `result-card${unpublished ? " unpublished" : ""}`);
  const topLine = element("div", "card-topline");
  topLine.append(element("span", `status-chip ${result.status}`, statusLabel(result.status)));
  topLine.append(element("span", "product-name", result.product));
  card.append(topLine);

  const heading = result.type === "STEP"
    ? `Step ${result.step_number} of ${readableName(result.procedure)}`
    : (result.type === "PROCEDURE" ? readableName(result.procedure) : readableName(result.predicate));
  card.append(element("h2", "predicate", heading));

  const unseenMedia = (result.media || []).filter((media) => {
    if (renderedMedia.has(media.id)) return false;
    renderedMedia.add(media.id);
    return true;
  });
  // The presentation plan's primary modality leads inside the media panel.
  const primaryModality = presentation &&
    ["image", "video"].includes(presentation.primary_modality)
    ? presentation.primary_modality : "video";
  const orderedMedia = [...unseenMedia].sort((left, right) =>
    Number(mediaModality(right) === primaryModality) -
    Number(mediaModality(left) === primaryModality));

  // Two fixed zones: the media panel (walkthrough video or its placeholder,
  // then supporting media) beside the always-available text panel.
  const columns = element("div", "card-columns");
  const mediaPanel = element("div", "card-media");
  const textPanel = element("div", "card-body");
  columns.append(mediaPanel, textPanel);

  const hasGeneratedWalkthrough = unseenMedia.some(isGeneratedProcedureVideo);
  if (result.video_job && !unseenMedia.some((media) => mediaModality(media) === "video")) {
    mediaPanel.append(element("h3", "panel-title", "Generated walkthrough"));
    mediaPanel.append(renderVideoSlot(result.video_job));
  } else if (unseenMedia.length) {
    mediaPanel.append(element("h3", "panel-title", hasGeneratedWalkthrough
      ? "Generated walkthrough"
      : "Evidence-linked media"));
  }
  orderedMedia.forEach((media) => mediaPanel.append(renderMedia(media)));
  if (!mediaPanel.childElementCount) card.classList.add("no-media");

  textPanel.append(element("p", "answer", result.display_text || result.answer));

  if (result.steps && result.steps.length) {
    const stepsBox = element("ol", "procedure-steps");
    result.steps.forEach((step) => {
      const item = element("li", "procedure-step-line", step.action || "");
      if (step.status !== result.status) {
        item.append(element("span", `status-chip inline ${step.status}`, statusLabel(step.status)));
      }
      const quote = (step.citations || [])[0];
      if (quote && quote.quote) {
        item.append(element("div", "step-quote", `“${quote.quote}” — ${quote.source_name || "Recorded source"}`));
      }
      if (reviewModeToggle.checked && step.status !== "PUBLISHED") {
        item.append(reviewControls(result.product_dir, step.claim_id, step.tier));
      }
      stepsBox.append(item);
    });
    textPanel.append(stepsBox);
  }

  if (result.type === "STEP" && result.procedure) {
    const procedureButton = element("button", "procedure-link", "View full ordered procedure");
    procedureButton.type = "button";
    procedureButton.addEventListener("click", () => openProcedure(result.product_dir, result.procedure));
    textPanel.append(procedureButton);
  }

  if (result.citations.length) {
    const citations = element("div", "citations");
    citations.append(element("h3", "", "Source evidence"));
    result.citations.forEach((citation) => citations.append(renderCitation(citation)));
    textPanel.append(citations);
  }

  textPanel.append(renderClaimDetails(result));
  if (reviewModeToggle.checked && unpublished && !result.claim_id.startsWith("procedure:")) {
    textPanel.append(reviewControls(result.product_dir, result.claim_id, result.tier));
  }
  const feedback = renderFeedback(result);
  if (feedback) textPanel.append(feedback);
  card.append(columns);
  return card;
}

function renderNotServed(counts, preview) {
  notServedBox.hidden = true;
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  if (!preview && entries.length) {
    const detail = entries.map(([status, count]) => `${count} ${status.toLowerCase()}`).join(", ");
    notServedBox.textContent = `Not served: ${detail} matching fact${entries.length === 1 && entries[0][1] === 1 ? "" : "s"}. Untick 'Published facts only' to see them, labeled.`;
    notServedBox.hidden = false;
  }
}

function renderExamples() {
  exampleQuestions.replaceChildren();
  (EXAMPLES[productSelect.value] || EXAMPLES.default).forEach((question) => {
    const button = element("button", "example-question", question);
    button.type = "button";
    button.addEventListener("click", async () => {
      questionInput.value = question;
      await runSearch();
    });
    exampleQuestions.append(button);
  });
}

function renderClarification(clarify) {
  clarifyBox.replaceChildren(element("h2", "", clarify.prompt));
  const choices = element("div", "clarify-buttons");
  clarify.candidates.forEach((candidate) => {
    const button = element("button", "", candidate.product);
    button.type = "button";
    button.addEventListener("click", async () => {
      productSelect.value = candidate.product_dir;
      await loadProcedures();
      await runSearch();
    });
    choices.append(button);
  });
  clarifyBox.append(choices);
  clarifyBox.hidden = false;
}

function resultsForDisplay(payload) {
  const results = [...payload.results];
  const mixedConnectionQuestion = /\bwir+ed\b/i.test(currentQuestion) &&
    /\bbluetooth\b/i.test(currentQuestion);
  if (mixedConnectionQuestion && results.some((result) =>
    result.procedure === "connect_wired_or_bluetooth_device")) {
    return results.filter((result) =>
      result.procedure === "connect_wired_or_bluetooth_device");
  }
  const proceduralQuestion = /\b(how do i|how to|show me how|steps? to)\b/i.test(currentQuestion);
  if (proceduralQuestion && results.some((result) => result.type === "PROCEDURE")) {
    results.sort((left, right) =>
      Number(right.type === "PROCEDURE") - Number(left.type === "PROCEDURE"));
  }
  return results;
}

function sourceMarkers(refs, sourcesPanel) {
  const wrapper = element("span", "source-markers");
  refs.forEach((ref) => {
    const marker = element("button", "source-marker", String(ref));
    marker.type = "button";
    marker.setAttribute("aria-label", `Show source ${ref}`);
    marker.addEventListener("click", () => {
      sourcesPanel.open = true;
      const target = sourcesPanel.querySelector(`[data-ref="${ref}"]`);
      if (target) {
        target.classList.add("source-highlight");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        setTimeout(() => target.classList.remove("source-highlight"), 1600);
      }
    });
    wrapper.append(marker);
  });
  return wrapper;
}

function answerItem(item, sourcesPanel, tag) {
  const node = element(tag || "p", item.unverified ? "answer-item unverified" : "answer-item");
  // Text and its source markers share one cell so step rows stay one line.
  const content = element("span", "answer-item-text");
  content.append(document.createTextNode(item.text + " "));
  if (item.source_refs && item.source_refs.length) content.append(sourceMarkers(item.source_refs, sourcesPanel));
  node.append(content);
  return node;
}

const BLOCK_CLASSES = {
  prerequisites: "answer-callout prerequisites",
  warnings: "answer-callout warnings",
  notes: "answer-callout notes",
  subprocedure: "answer-subprocedure",
  fact: "answer-fact",
  verdict: "answer-fact",
  steps: "answer-steps",
};

function renderSources(sources) {
  const panel = element("details", "answer-sources");
  panel.append(element("summary", "", `Sources (${sources.length})`));
  const list = element("ol", "source-list");
  sources.forEach((source) => {
    const entry = element("li", "source-entry");
    entry.dataset.ref = String(source.ref);
    const label = source.page ? `${source.source_name}, page ${source.page}` : source.source_name;
    entry.append(element("p", "source-name", label));
    entry.append(element("blockquote", "", `“${source.quote}”`));
    list.append(entry);
  });
  panel.append(list);
  return panel;
}

function renderDocumentClarification(documentPayload) {
  const clarification = documentPayload.clarification;
  clarifyBox.replaceChildren(element("h2", "", clarification.prompt));
  if (clarification.note) clarifyBox.append(element("p", "clarify-note", clarification.note));
  const choices = element("div", "clarify-buttons");
  clarification.options.forEach((option) => {
    const button = element("button", "", option.label);
    button.type = "button";
    button.addEventListener("click", async () => {
      if (option.product_dir) {
        productSelect.value = option.product_dir;
      } else if (documentPayload.interpretation.kind === "view" && documentPayload.product) {
        answerContext = { product_dir: documentPayload.product.product_dir, procedure_id: option.value };
      } else if (option.value) {
        questionInput.value = `${currentQuestion} using the ${option.value}`;
      }
      await runSearch();
    });
    choices.append(button);
  });
  clarifyBox.append(choices);
  clarifyBox.hidden = false;
}

function formatTime(seconds) {
  return `0:${String(Math.floor(seconds)).padStart(2, "0")}`;
}

// Dev-only clips (SHOWME_DEV_MEDIA=1): unverified research/generated video,
// always labeled. Real eligible media arrives with the P4 registry.
function renderDevPlayer(clips) {
  const wrapper = element("section", "dev-player");
  const video = element("video", "dev-video");
  video.controls = true;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.autoplay = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const research = clips.some((clip) => clip.audience === "research" || clip.audience === undefined);
  const badge = element("p", "dev-badge", research ? "RESEARCH PREVIEW · 3D MODEL, NOT YET REVIEWED" : "VIDEO");
  const caption = element("p", "dev-caption");
  const tabs = element("div", "dev-tabs");
  let active = null;
  const select = (clip) => {
    active = clip;
    video.src = clip.url;
    caption.textContent = `${clip.label}. ${clip.caveat}`;
    tabs.querySelectorAll("button").forEach((button) =>
      button.setAttribute("aria-pressed", String(button.dataset.id === clip.id)));
  };
  clips.forEach((clip) => {
    const button = element("button", "dev-tab", clip.view_label || (clip.view === "main" ? "Main view"
      : clip.view === "rear" ? "Rear view" : clip.view === "generated" ? "Generated (Seedance)" : "Slides"));
    button.type = "button";
    button.dataset.id = clip.id;
    button.addEventListener("click", () => select(clip));
    tabs.append(button);
  });
  if (clips[0].poster) video.poster = clips[0].poster;
  wrapper.append(badge, video);
  if (clips.length > 1) wrapper.append(tabs);
  wrapper.tabs = tabs;
  wrapper.append(caption);
  select(clips[0]);
  wrapper.seekTo = (claimId) => {
    const seconds = active && active.chapters ? active.chapters[claimId] : undefined;
    if (seconds === undefined) return false;
    video.currentTime = seconds;
    video.play().catch(() => {});
    wrapper.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return true;
  };
  wrapper.trackSteps = (root) => {
    video.addEventListener("timeupdate", () => {
      if (!active || !active.chapters) return;
      let current = null;
      Object.entries(active.chapters).forEach(([claimId, seconds]) => {
        if (video.currentTime + 0.05 >= seconds && (current === null || seconds >= active.chapters[current])) current = claimId;
      });
      root.querySelectorAll(".answer-steps li").forEach((row) =>
        row.classList.toggle("step-active", row.dataset.claim === current));
    });
  };
  wrapper.chapterFor = (claimId) => (active && active.chapters ? active.chapters[claimId] : undefined);
  return wrapper;
}

function renderAnswerDocument(documentPayload) {
  if (documentPayload.status === "needs_input") {
    renderDocumentClarification(documentPayload);
    if (documentPayload.video?.assets?.length) {
      const example = element("article", "answer-doc");
      example.append(element("h2", "", "Available video: connect with an analog audio cable"));
      example.append(renderDevPlayer(documentPayload.video.assets));
      resultsRegion.append(example);
    }
    return;
  }
  const article = element("article", `answer-doc status-${documentPayload.status}`);
  const sourcesPanel = renderSources(documentPayload.sources);
  const video = documentPayload.video;
  const devClips = video ? video.assets : (documentPayload.dev_media || []);
  const player = devClips.length ? renderDevPlayer(devClips) : null;
  if (player && video) addViewRequests(player, video);
  const photoUrl = documentPayload.product ? productImageUrl(documentPayload.product.product_dir) : null;
  if (player || photoUrl) {
    const media = element("div", "answer-media");
    if (player) {
      media.append(player);
    } else {
      const figure = element("figure", "product-photo");
      const image = element("img");
      image.src = photoUrl;
      image.alt = documentPayload.product.name;
      figure.append(image, element("figcaption", "", `${documentPayload.product.name} · manufacturer photo`));
      media.append(figure);
    }
    article.append(media);
  } else {
    article.classList.add("no-media");
  }
  const body = element("div", "answer-body");
  article.append(body);
  const container = article;
  const append = (node) => body.append(node);
  if (documentPayload.product) append(element("p", "answer-product", documentPayload.product.name));
  append(element("h2", "answer-headline", documentPayload.headline));
  append(element("p", "direct-answer", documentPayload.direct_answer));
  if (!player && documentPayload.visual && documentPayload.visual.message) {
    append(element("p", "answer-visual-note", documentPayload.visual.message));
  }
  const videoStatus = video ? renderVideoStatus(video) : null;
  if (videoStatus) append(videoStatus);
  documentPayload.blocks.forEach((block) => {
    if (block.kind === "verdict") {
      const cite = element("p", "answer-citation-line", "From the manual: ");
      block.items.forEach((item) => cite.append(answerItem(item, sourcesPanel, "span")));
      append(cite);
      return;
    }
    const section = element("section", BLOCK_CLASSES[block.kind] || "answer-fact");
    if (block.title && block.kind !== "steps") section.append(element("h3", "", block.title));
    if (block.condition) section.append(element("p", "answer-condition", block.condition));
    const ordered = block.kind === "steps" || block.kind === "subprocedure";
    const list = element(ordered ? "ol" : "ul", "answer-list");
    block.items.forEach((item) => {
      const row = answerItem(item, sourcesPanel, "li");
      if (item.claim_id) row.dataset.claim = item.claim_id;
      if (player && block.kind === "steps" && player.chapterFor(item.claim_id) !== undefined) {
        const jump = element("button", "chapter-jump", `▶ ${formatTime(player.chapterFor(item.claim_id))}`);
        jump.type = "button";
        jump.setAttribute("aria-label", "Play this step in the video");
        jump.addEventListener("click", () => player.seekTo(item.claim_id));
        row.append(jump);
      }
      list.append(row);
    });
    section.append(list);
    append(section);
  });
  if (documentPayload.status === "unsupported") {
    renderExamples();
    emptyMessage.textContent = "Try one of these questions:";
    emptyState.hidden = false;
  }
  if (documentPayload.sources.length) append(sourcesPanel);
  resultsRegion.append(container);
  if (player) player.trackSteps(body);
  answerContext = documentPayload.context && documentPayload.context.product_dir ? documentPayload.context : answerContext;
}

function renderPayload(payload) {
  stopVideoPolls();
  resultsRegion.replaceChildren();
  clarifyBox.hidden = true;
  emptyState.hidden = true;
  if (payload.answer_document) {
    renderAnswerDocument(payload.answer_document);
    return;
  }
  if (payload.mode === "clarify") {
    renderClarification(payload.clarify);
    return;
  }
  if (!payload.results.length) {
    if (payload.gap) {
      emptyMessage.textContent = `We don't have a verified answer for this — recorded gap: ${payload.gap.reason}`;
      emptyState.classList.add("gap-state");
    } else {
      emptyMessage.textContent = "No answers matched. Try one of these questions:";
      emptyState.classList.remove("gap-state");
    }
    renderExamples();
    emptyState.hidden = false;
  } else {
    const renderedMedia = new Set();
    resultsForDisplay(payload).forEach((result) =>
      resultsRegion.append(renderResult(result, renderedMedia, payload.presentation)));
  }
  renderNotServed(payload.not_served, !publishedOnlyToggle.checked);
}

async function loadProducts() {
  try {
    const response = await fetch("/api/products");
    const payload = await response.json();
    payload.products.forEach((product) => {
      const option = element("option", "", `${product.brand} ${product.model}`);
      option.value = product.dir;
      productSelect.append(option);
    });
    renderCatalog(payload.products);
    renderExamples();
  } catch {
    errorBox.textContent = "Could not load the product catalog.";
    errorBox.hidden = false;
  }
}

async function loadReviewConfig() {
  try {
    const response = await fetch("/api/review-config");
    const payload = await response.json();
    reviewModeToggle.disabled = !payload.enabled;
    reviewModeToggle.title = payload.enabled ? `Reviewing as ${payload.reviewer}` : "Restart the server with --reviewer owner@example.com";
    reviewModeNote.textContent = payload.enabled
      ? `Reviewing as ${payload.reviewer}. ${payload.recording_note}`
      : "Review writing is off. Restart with --reviewer owner@example.com to record decisions.";
  } catch {
    reviewModeToggle.disabled = true;
  }
}

async function loadProcedures() {
  procedureRegion.hidden = true;
  procedureSteps = [];
  activeStepIndex = 0;
  procedureSelect.replaceChildren();
  const placeholder = element("option", "", productSelect.value ? "Choose a procedure" : "Choose a product first");
  placeholder.value = "";
  procedureSelect.append(placeholder);
  procedureSelect.disabled = true;
  showProcedureButton.disabled = true;
  if (!productSelect.value) return;

  const query = new URLSearchParams({ product: productSelect.value, preview: publishedOnlyToggle.checked ? "0" : "1" });
  try {
    const response = await fetch(`/api/procedures?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load procedures.");
    payload.procedures.forEach((procedure) => {
      const suffix = procedure.publication_state === "partial" ? " · partially published" : "";
      const option = element("option", "", `${readableName(procedure.name)}${suffix}`);
      option.value = procedure.name;
      procedureSelect.append(option);
    });
    if (payload.procedures.length) {
      procedureSelect.disabled = false;
    } else {
      placeholder.textContent = publishedOnlyToggle.checked ? "No published procedures — untick 'Published facts only'" : "No procedures available";
    }
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

function renderProcedureStep() {
  const step = procedureSteps[activeStepIndex];
  stepStatus.className = `status-chip ${step.status}`;
  stepStatus.textContent = statusLabel(step.status);
  stepStatus.hidden = step.status === procedureStatus;
  stepNumber.textContent = `Step ${step.step_number}`;
  stepAction.textContent = step.action;
  stepClaim.textContent = step.claim_id;
  procedureProgress.textContent = `${activeStepIndex + 1} of ${procedureSteps.length}`;
  previousStepButton.disabled = activeStepIndex === 0;
  nextStepButton.disabled = activeStepIndex === procedureSteps.length - 1;
  pagePanel.replaceChildren();
  if (step.page_image_url) {
    const image = element("img", "manual-page");
    image.src = step.page_image_url;
    image.alt = `Authentic whole manual page for step ${step.step_number}`;
    pagePanel.append(image);
    pagePanel.append(element("figcaption", "", "Whole authentic manual page · 144 DPI · no crop or annotation"));
  } else {
    pagePanel.append(element("div", "no-page", "No approved page binding for this step. Showing verified step text only."));
  }
}

async function showProcedure() {
  if (!productSelect.value || !procedureSelect.value) return;
  errorBox.hidden = true;
  const query = new URLSearchParams({ product: productSelect.value, procedure: procedureSelect.value, preview: publishedOnlyToggle.checked ? "0" : "1" });
  try {
    const response = await fetch(`/api/procedure?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load procedure.");
    if (!payload.steps.length) throw new Error("No published steps are available for this procedure.");
    procedureSteps = payload.steps;
    activeStepIndex = 0;
    const statuses = new Set(payload.steps.map((step) => step.status));
    procedureStatus = statuses.size === 1 ? payload.steps[0].status : "MIXED";
    procedureTitle.textContent = readableName(payload.procedure);
    procedureBanner.textContent = payload.fully_published ? "" : "This procedure includes pending review decisions.";
    procedureBanner.hidden = payload.fully_published;
    procedureRegion.hidden = false;
    renderProcedureStep();
    procedureRegion.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  }
}

async function logMiss(question) {
  try {
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, product: productSelect.value, claim_id: null }),
    });
  } catch {
    // Logging is explicitly optional and must not obscure the honest miss.
  }
}

function enterSearchLayout() {
  const wasCompact = document.body.classList.contains("has-searched");
  const previousScroll = window.scrollY;
  document.body.classList.add("has-searched");
  requestAnimationFrame(() => window.scrollTo(0, wasCompact ? previousScroll : 0));
}

async function runSearch() {
  if (!questionInput.value.trim()) return;
  enterSearchLayout();
  stopVideoPolls();
  errorBox.hidden = true;
  notServedBox.hidden = true;
  resultsRegion.replaceChildren();
  emptyState.hidden = true;
  clarifyBox.hidden = true;
  submitButton.disabled = true;
  submitButton.textContent = "Searching…";
  currentQuestion = questionInput.value.trim();
  const query = new URLSearchParams({ q: currentQuestion, preview: publishedOnlyToggle.checked ? "0" : "1", product: productSelect.value, top: "10" });
  if (answerContext) query.set("context", JSON.stringify(answerContext));

  try {
    const response = await fetch(`/api/answer?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The answer request failed.");
    currentPayload = payload;
    renderPayload(payload);
    const unanswered = payload.answer_document ? payload.answer_document.status === "unsupported" : !payload.results.length;
    if (unanswered && payload.mode !== "clarify" && logMissesToggle.checked) await logMiss(currentQuestion);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Find answer";
  }
}

publishedOnlyToggle.addEventListener("change", () => {
  previewWarning.hidden = publishedOnlyToggle.checked;
  loadProcedures();
});
reviewModeToggle.addEventListener("change", () => {
  reviewModeNote.hidden = !reviewModeToggle.checked;
  if (currentPayload) renderPayload(currentPayload);
});
productSelect.addEventListener("change", () => {
  answerContext = null;
  renderExamples();
  loadProcedures();
});
procedureSelect.addEventListener("change", () => { showProcedureButton.disabled = !procedureSelect.value; });
showProcedureButton.addEventListener("click", showProcedure);
previousStepButton.addEventListener("click", () => {
  if (activeStepIndex > 0) { activeStepIndex -= 1; renderProcedureStep(); }
});
nextStepButton.addEventListener("click", () => {
  if (activeStepIndex < procedureSteps.length - 1) { activeStepIndex += 1; renderProcedureStep(); }
});
form.addEventListener("submit", (event) => { event.preventDefault(); runSearch(); });
// ---- Video requests and My Videos -------------------------------------

const myVideosButton = document.querySelector("#my-videos-button");
const myVideosBadge = document.querySelector("#my-videos-badge");
const myVideosPanel = document.querySelector("#my-videos");
const myVideosList = document.querySelector("#my-videos-list");
const myVideosPlayer = document.querySelector("#my-videos-player");
let myVideosTimer = null;
let myVideosState = { requests: [], unread: 0, active: 0 };

const REQUEST_STATE_TEXT = {
  queued: "Waiting to start",
  rendering: "Making your video",
  checking: "Checking the video",
  ready: "Ready to watch",
  failed: "Couldn't make it",
  needs_scene: "Video creation isn't available yet",
  needs_review: "Made, waiting for review",
};

const GENERATION_STAGE_TEXT = {
  authoring: "Building the product and its motion",
  refining: "Refining the demonstration",
  previewing: "Rendering a preview",
  checking: "Checking the instructions against references",
  rendering: "Rendering the final video",
  encoding: "Preparing playback",
  planning: "Planning the shots",
  replanning: "Re-planning after review",
  "reviewing the video": "Reviewing the video",
};

function requestProgressText(request) {
  const active = ["queued", "rendering", "checking"].includes(request.state);
  if (active && ["generate", "author"].includes(request.kind) && request.stage && request.stage !== "queued") {
    const text = GENERATION_STAGE_TEXT[request.stage]
      || request.stage.charAt(0).toUpperCase() + request.stage.slice(1);
    return `Making your video · ${text}`;
  }
  if (request.state === "rendering" && typeof request.progress === "number" && request.progress > 0) {
    return `${REQUEST_STATE_TEXT.rendering} · ${Math.round(request.progress * 100)}% of frames rendered`;
  }
  return REQUEST_STATE_TEXT[request.state] || request.state;
}

async function postJson(url, body) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Request failed.");
  return payload;
}

async function requestVideo(video, view, statusNode) {
  try {
    const payload = await postJson("/api/video-requests", {
      product_dir: video.product_dir, procedure_id: video.procedure_id, view, question: currentQuestion,
    });
    if (statusNode) statusNode.replaceWith(renderRequestCard(payload.request));
    await refreshMyVideos();
  } catch (error) {
    if (statusNode) statusNode.textContent = error.message;
  }
}

function addViewRequests(player, video) {
  const missing = video.views.filter((view) => !view.ready);
  missing.forEach((view) => {
    const button = element("button", "dev-tab view-request", `＋ ${view.label}`);
    button.type = "button";
    button.title = `Make a ${view.label.toLowerCase()} from the 3D model`;
    button.addEventListener("click", async () => {
      button.disabled = true;
      const holder = element("div");
      player.append(holder);
      await requestVideo(video, view.view, holder);
      button.remove();
    });
    player.tabs.append(button);
  });
  if (missing.length && !player.tabs.isConnected) {
    player.querySelector(".dev-caption").before(player.tabs);
  }
}

function renderRequestCard(request) {
  const card = element("div", `video-request state-${request.state}`);
  card.append(element("p", "video-request-title", `${request.procedure_label} · ${request.view_label}`));
  card.append(element("p", "video-request-state", requestProgressText(request)));
  if (request.message) card.append(element("p", "video-request-message", request.message));
  if (["queued", "rendering", "checking"].includes(request.state)) {
    card.append(element("p", "video-request-message",
      "We're making this video. You can keep browsing or leave; it will be in My Videos when it's ready."));
  }
  const open = element("button", "link-button", "Open My Videos");
  open.type = "button";
  open.addEventListener("click", openMyVideos);
  card.append(open);
  return card;
}

function renderVideoStatus(video) {
  if (video.state === "requested" && video.request) return renderRequestCard(video.request);
  if (video.state === "offer") {
    const box = element("div", "video-offer");
    const renderable = video.offer && video.offer.renderable;
    box.append(element("p", "", renderable
      ? "Want to see it? We can make a video of this."
      : "There's no video of this yet. You can ask for one and we'll keep the request in My Videos."));
    const button = element("button", "video-offer-button", renderable ? "Make a video" : "Request a video");
    button.type = "button";
    button.addEventListener("click", () => {
      button.disabled = true;
      requestVideo(video, (video.offer && video.offer.view) || "main", box);
    });
    box.append(button);
    return box;
  }
  return null;
}

function updateBadge() {
  myVideosBadge.textContent = String(myVideosState.unread);
  myVideosBadge.hidden = myVideosState.unread === 0;
  myVideosButton.classList.toggle("has-active", myVideosState.active > 0);
}

function renderMyVideos() {
  myVideosList.replaceChildren();
  if (!myVideosState.requests.length) {
    myVideosList.append(element("li", "my-videos-empty", "No video requests yet. Ask how to do something and choose “Make a video”."));
    return;
  }
  myVideosState.requests.forEach((request) => {
    const row = element("li", `my-video state-${request.state}${request.seen ? "" : " unread"}`);
    const text = element("div", "my-video-text");
    text.append(element("p", "my-video-title", `${request.product_name} · ${request.procedure_label}`));
    text.append(element("p", "my-video-meta", `${request.view_label} · “${request.question}”`));
    text.append(element("p", "my-video-state", requestProgressText(request)));
    if (request.message) text.append(element("p", "my-video-message", request.message));
    row.append(text);
    if (request.asset) {
      const watch = element("button", "video-offer-button", "Watch");
      watch.type = "button";
      watch.addEventListener("click", () => watchRequest(request));
      row.append(watch);
    } else if (request.state === "failed") {
      const retry = element("button", "video-offer-button", "Try again");
      retry.type = "button";
      retry.addEventListener("click", async () => {
        retry.disabled = true;
        try { await postJson("/api/my-videos/retry", { id: request.id }); } catch (error) { retry.textContent = error.message; }
        refreshMyVideos();
      });
      row.append(retry);
    }
    myVideosList.append(row);
  });
}

function watchRequest(request) {
  myVideosPlayer.replaceChildren(renderDevPlayer([request.asset]));
  myVideosPlayer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (!request.seen) postJson("/api/my-videos/seen", { id: request.id }).then(refreshMyVideos).catch(() => {});
}

async function refreshMyVideos() {
  try {
    const response = await fetch("/api/my-videos");
    if (!response.ok) return;
    const previous = new Map(myVideosState.requests.map((r) => [r.id, r.state]));
    myVideosState = await response.json();
    updateBadge();
    if (!myVideosPanel.hidden) renderMyVideos();
    const justFinished = myVideosState.requests.filter((r) => r.state === "ready" && previous.has(r.id) && previous.get(r.id) !== "ready");
    if (justFinished.length) showToast(`Your video is ready: ${justFinished[0].procedure_label} · ${justFinished[0].view_label}`);
  } catch (error) {
    // Network hiccup: keep the last known state; the next poll retries.
  } finally {
    clearTimeout(myVideosTimer);
    myVideosTimer = setTimeout(refreshMyVideos, myVideosState.active ? 3000 : 15000);
  }
}

function showToast(text) {
  const toast = element("button", "toast", `${text} — open My Videos`);
  toast.type = "button";
  toast.addEventListener("click", () => { toast.remove(); openMyVideos(); });
  document.body.append(toast);
  setTimeout(() => toast.remove(), 12000);
}

function openMyVideos() {
  myVideosPanel.hidden = false;
  renderMyVideos();
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (myVideosState.unread) postJson("/api/my-videos/seen", {}).then(refreshMyVideos).catch(() => {});
}

myVideosButton.addEventListener("click", openMyVideos);
document.querySelector("#my-videos-close").addEventListener("click", () => { myVideosPanel.hidden = true; });

loadProducts();
loadReviewConfig();
renderHeroMedia();
refreshMyVideos();
