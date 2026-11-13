(() => {
  const root = document.querySelector("#recipe-comments");
  if (!root) return;

  // ----- DOM references ----- //
  const form = root.querySelector("#recipe-comment-form");
  const addButton = root.querySelector(".recipe-comments__add");
  const cancelButton = root.querySelector("#cancel-comment");
  const saveButton = root.querySelector("#save-comment");
  const authorInput = root.querySelector("#comment-author");
  const textInput = root.querySelector("#comment-text");
  const status = root.querySelector("#comment-status");
  const list = root.querySelector("#comment-list");

  // ----- Limits ----- //
  // Character limits for the comment author input and message textarea.
  const MAX_AUTHOR_LENGTH = 100;
  const MAX_MESSAGE_LENGTH = 5000;

  // ----- Shared helpers ----- //
  // recipe-feedback.js exposes window.RecipeFeedback with shared helpers. When it
  // is not loaded, fall back to local implementations so comments still work.
  // Each helper is resolved exactly once here instead of forking at every call site.
  const feedback = window.RecipeFeedback || {};

  function getMarkdownPathFallback() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  // Fallback used only when recipe-feedback.js is not loaded. Prefer crypto.randomUUID();
  // otherwise build a random UUID v4 so comment ids remain unique either way.
  function createIdFallback() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
      const random = (Math.random() * 16) | 0;
      const value = character === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }

  function getInitialsFallback(name) {
    return String(name || "")
      .slice(0, 2)
      .toUpperCase();
  }

  function createDateElementFallback(timestamp) {
    const dateElement = document.createElement("time");
    if (typeof timestamp === "string" && timestamp) {
      dateElement.dateTime = timestamp;
      dateElement.textContent = timestamp;
    }
    return dateElement;
  }

  async function fetchCommentsFallback() {
    const params = new URLSearchParams({ path: recipePath });
    const response = await fetch(`/api/metadata/comments?${params}`);
    if (!response.ok) {
      throw new Error(`Failed to load comments (${response.status})`);
    }
    const data = await response.json();
    if (!Array.isArray(data.value)) {
      throw new Error("Invalid comments response");
    }
    return data.value;
  }

  async function saveCommentsFallback(comments) {
    const response = await fetch("/api/metadata/comments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: recipePath, value: comments }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save comments (HTTP ${response.status})`);
    }
  }

  function sortByUpdatedDescFallback(items) {
    // Without recipe-feedback.js there is no shared sort; keep the server's order.
    return [...items];
  }

  const recipePath = (feedback.getMarkdownPath || getMarkdownPathFallback)();
  const createId = feedback.createId || createIdFallback;
  const getInitials = feedback.getInitials || getInitialsFallback;
  const createDateElement = feedback.createDateElement || createDateElementFallback;
  const fetchComments = feedback.fetchMetadata
    ? () => feedback.fetchMetadata("comments", recipePath)
    : fetchCommentsFallback;
  const saveComments = feedback.saveMetadata
    ? (comments) => feedback.saveMetadata("comments", recipePath, comments)
    : saveCommentsFallback;
  const sortByUpdatedDesc = feedback.sortByUpdatedDesc || sortByUpdatedDescFallback;

  // ----- Data helpers ----- //
  function getTimestamp() {
    return new Date().toISOString();
  }

  function normalizeComments(comments) {
    return comments
      .filter((comment) => comment && typeof comment === "object" && !Array.isArray(comment))
      .map((comment, index) => ({
        ...comment,
        // Comments saved before ids existed get a stable positional id so edit and delete can target them.
        id: typeof comment.id === "string" && comment.id ? comment.id : `legacy-${index}`,
        author: typeof comment.author === "string" ? comment.author : "",
        text: typeof comment.text === "string" ? comment.text : "",
      }));
  }

  async function getComments() {
    return normalizeComments(await fetchComments());
  }

  // ----- Rendering ----- //
  function createComment(comment) {
    const article = document.createElement("article");
    article.className = "recipe-comment";
    article.dataset.commentId = comment.id;

    const author = (comment.author || "Anonymous").trim() || "Anonymous";
    const avatar = document.createElement("div");
    avatar.className = "recipe-comment__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = getInitials(author);

    const content = document.createElement("div");
    content.className = "recipe-comment__content";

    const meta = document.createElement("header");
    meta.className = "recipe-comment__meta";
    const authorElement = document.createElement("span");
    authorElement.className = "recipe-comment__author";
    authorElement.textContent = author;

    const dateElement = createDateElement(comment.updated || comment.created);
    meta.append(authorElement, dateElement);

    const text = document.createElement("p");
    text.className = "recipe-comment__text";
    text.textContent = comment.text;

    const actions = document.createElement("div");
    actions.className = "recipe-comment__actions";
    for (const [action, label] of [
      ["edit", "Edit"],
      ["delete", "Remove"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.action = action;
      button.textContent = label;
      actions.append(button);
    }

    content.append(meta, text, actions);
    article.append(avatar, content);
    return article;
  }

  function renderAllComments(comments) {
    list.replaceChildren(...sortByUpdatedDesc(comments).map((comment) => createComment(comment)));
    root.classList.toggle("is-empty", comments.length === 0);
  }

  function setCommentBusy(article, busy) {
    article.querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
    });
  }

  // Comment errors are shown inline, next to the comment or form they belong to,
  // instead of with blocking alert() dialogs.
  function showInlineError(container, errorMessage) {
    let message = container.querySelector(".recipe-comment__status");
    if (!message) {
      message = document.createElement("p");
      message.className = "recipe-comment__status";
      message.setAttribute("role", "status");
      container.append(message);
    }
    message.textContent = errorMessage;
  }

  function articleContent(article) {
    return article.querySelector(".recipe-comment__content") || article;
  }

  // ----- Edit form ----- //
  function buildEditForm(comment) {
    const editForm = document.createElement("form");
    editForm.className = "recipe-comment__edit";

    const author = document.createElement("input");
    author.className = "recipe-comment__author-input";
    author.value = comment.author || "Anonymous";
    author.maxLength = MAX_AUTHOR_LENGTH;
    author.required = true;
    author.setAttribute("aria-label", "Comment author");

    const text = document.createElement("textarea");
    text.className = "recipe-comment__text-input";
    text.value = comment.text || "";
    text.maxLength = MAX_MESSAGE_LENGTH;
    text.required = true;
    text.setAttribute("aria-label", "Comment text");

    const actions = document.createElement("div");
    actions.className = "recipe-comment__actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save";
    actions.append(cancel, save);

    editForm.append(author, text, actions);
    return { editForm, author, text, cancel };
  }

  async function editComment(article) {
    // Fetch once for the edit operation: load current comments, find the target, then save.
    const commentId = article.dataset.commentId;
    const comments = await getComments();
    const index = comments.findIndex((comment) => comment.id === commentId);
    if (index === -1) {
      throw new Error("Comment no longer exists. Reload the page.");
    }

    const comment = comments[index];
    const content = article.querySelector(".recipe-comment__content");
    const controls = buildEditForm(comment);
    content.replaceChildren(controls.editForm);

    controls.cancel.addEventListener("click", () => {
      article.replaceWith(createComment(comment));
    });

    controls.editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const newAuthor = controls.author.value.trim();
      const newText = controls.text.value.trim();
      if (!newAuthor || !newText) return;

      setCommentBusy(article, true);
      try {
        const updatedComments = comments.map((existing, existingIndex) =>
          existingIndex === index
            ? { ...existing, author: newAuthor, text: newText, updated: getTimestamp() }
            : existing,
        );
        await saveComments(updatedComments);
        renderAllComments(updatedComments);
      } catch (error) {
        console.error("Unable to edit comment:", error);
        setCommentBusy(article, false);
        showInlineError(controls.editForm, error.message);
      }
    });

    controls.author.focus();
  }

  async function deleteComment(article) {
    const commentId = article.dataset.commentId;
    if (!window.confirm("Delete this comment? This cannot be undone.")) {
      return;
    }

    setCommentBusy(article, true);
    try {
      const comments = await getComments();
      const updatedComments = comments.filter((comment) => comment.id !== commentId);
      if (updatedComments.length === comments.length) {
        throw new Error("Comment no longer exists.");
      }
      await saveComments(updatedComments);
      renderAllComments(updatedComments);
    } catch (error) {
      console.error("Unable to delete comment:", error);
      setCommentBusy(article, false);
      showInlineError(articleContent(article), error.message || "Unable to delete comment.");
    }
  }

  // ----- Form controls ----- //
  function setFormOpen(open) {
    form.hidden = !open;
    addButton.setAttribute("aria-expanded", String(open));
    status.textContent = "";
    if (open) {
      textInput.focus();
    }
  }

  async function loadComments() {
    try {
      renderAllComments(await getComments());
    } catch (error) {
      console.error("Unable to load comments:", error);
      status.textContent = "Unable to load comments.";
    }
  }

  // ----- Event wiring ----- //
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || !list.contains(button)) return;

    const article = button.closest(".recipe-comment");
    if (!article) return;

    if (button.dataset.action === "edit") {
      try {
        await editComment(article);
      } catch (error) {
        console.error("Unable to edit comment:", error);
        showInlineError(articleContent(article), error.message || "Unable to edit comment.");
      }
    } else if (button.dataset.action === "delete") {
      await deleteComment(article);
    }
  });

  addButton.addEventListener("click", () => {
    setFormOpen(true);
  });

  cancelButton.addEventListener("click", () => {
    form.reset();
    setFormOpen(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const author = authorInput.value.trim();
    const text = textInput.value.trim();

    if (!author || !text) {
      status.textContent = "Please enter your name and a comment.";
      return;
    }

    saveButton.disabled = true;
    status.textContent = "Saving comment…";
    try {
      const comments = await getComments();
      const timestamp = getTimestamp();
      const updatedComments = [
        ...comments,
        {
          id: createId(),
          author,
          created: timestamp,
          updated: timestamp,
          text,
        },
      ];
      await saveComments(updatedComments);
      renderAllComments(updatedComments);
      form.reset();
      setFormOpen(false);
    } catch (error) {
      console.error("Unable to save comment:", error);
      status.textContent = "Unable to save your comment. Please try again.";
    } finally {
      saveButton.disabled = false;
    }
  });

  loadComments();
})();
