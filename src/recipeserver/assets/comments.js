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
  const helpers = window.RecipeFeedback || {};
  const recipePath = (helpers.getMarkdownPath || getMarkdownPathFallback)();

  function getMarkdownPathFallback() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  // ----- Data helpers ----- //
  function getTimestamp() {
    return new Date().toISOString();
  }

  function createCommentId() {
    return helpers.createId ? helpers.createId() : `comment-${Date.now()}`;
  }

  function normalizeComments(comments) {
    return comments
      .filter((comment) => comment && typeof comment === "object" && !Array.isArray(comment))
      .map((comment, index) => ({
        ...comment,
        id: typeof comment.id === "string" && comment.id ? comment.id : `legacy-${index}`,
        author: typeof comment.author === "string" ? comment.author : "",
        text: typeof comment.text === "string" ? comment.text : "",
      }));
  }

  async function getComments() {
    let comments;
    if (helpers.fetchMetadata) {
      comments = await helpers.fetchMetadata("comments", recipePath);
    } else {
      const params = new URLSearchParams({ path: recipePath });
      const response = await fetch(`/api/metadata/comments?${params}`);
      if (!response.ok) {
        throw new Error(`Failed to load comments (${response.status})`);
      }
      const data = await response.json();
      if (!Array.isArray(data.value)) {
        throw new Error("Invalid comments response");
      }
      comments = data.value;
    }
    return normalizeComments(comments);
  }

  async function saveComments(comments) {
    if (helpers.saveMetadata) {
      return helpers.saveMetadata("comments", recipePath, comments);
    }
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

  // ----- Rendering ----- //
  function getInitials(name) {
    return helpers.getInitials ? helpers.getInitials(name) : String(name || "").slice(0, 2).toUpperCase();
  }

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

    const dateElement = helpers.createDateElement
      ? helpers.createDateElement(comment.updated || comment.created)
      : document.createElement("time");
    if (!helpers.createDateElement) {
      const timestamp = comment.updated || comment.created;
      if (typeof timestamp === "string" && timestamp) {
        dateElement.dateTime = timestamp;
        dateElement.textContent = timestamp;
      }
    }
    meta.append(authorElement, dateElement);

    const text = document.createElement("p");
    text.className = "recipe-comment__text";
    text.textContent = comment.text;

    const actions = document.createElement("div");
    actions.className = "recipe-comment__actions";
    for (const [action, label] of [["edit", "Edit"], ["delete", "Remove"]]) {
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
    const sort = helpers.sortByUpdatedDesc || ((items) => [...items]);
    list.replaceChildren(...sort(comments).map((comment) => createComment(comment)));
    root.classList.toggle("is-empty", comments.length === 0);
  }

  function setCommentBusy(article, busy) {
    article.querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
    });
  }

  // ----- Edit form ----- //
  function buildEditForm(comment) {
    const editForm = document.createElement("form");
    editForm.className = "recipe-comment__edit";

    const author = document.createElement("input");
    author.className = "recipe-comment__author-input";
    author.value = comment.author || "Anonymous";
    author.maxLength = 100;
    author.required = true;
    author.setAttribute("aria-label", "Comment author");

    const text = document.createElement("textarea");
    text.className = "recipe-comment__text-input";
    text.value = comment.text || "";
    text.maxLength = 5000;
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

  function showEditError(article, editForm, errorMessage) {
    let message = article.querySelector(".recipe-comment__status");
    if (!message) {
      message = document.createElement("p");
      message.className = "recipe-comment__status";
      message.setAttribute("role", "status");
      editForm.append(message);
    }
    message.textContent = errorMessage;
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
        comments[index] = {
          ...comments[index],
          author: newAuthor,
          text: newText,
          updated: getTimestamp(),
        };
        await saveComments(comments);
        renderAllComments(comments);
      } catch (error) {
        console.error("Unable to edit comment:", error);
        setCommentBusy(article, false);
        showEditError(article, controls.editForm, error.message);
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
      const index = comments.findIndex((comment) => comment.id === commentId);
      if (index === -1) {
        throw new Error("Comment no longer exists.");
      }
      comments.splice(index, 1);
      await saveComments(comments);
      renderAllComments(comments);
    } catch (error) {
      console.error("Unable to delete comment:", error);
      setCommentBusy(article, false);
      alert(error.message || "Unable to delete comment.");
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
        alert(error.message || "Unable to edit comment.");
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
      comments.push({
        id: createCommentId(),
        author,
        created: timestamp,
        updated: timestamp,
        text,
      });
      await saveComments(comments);
      renderAllComments(comments);
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
