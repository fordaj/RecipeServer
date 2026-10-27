(() => {
  const root = document.querySelector("#recipe-comments");
  if (!root) return;

  const recipePath = getMarkdownPath();
  const form = root.querySelector("#recipe-comment-form");
  const addButton = root.querySelector(".recipe-comments__add");
  const cancelButton = root.querySelector("#cancel-comment");
  const saveButton = root.querySelector("#save-comment");
  const authorInput = root.querySelector("#comment-author");
  const textInput = root.querySelector("#comment-text");
  const status = root.querySelector("#comment-status");
  const list = root.querySelector("#comment-list");
  const count = root.querySelector(".recipe-comments__count");

  async function saveComments(comments) {
    const response = await fetch("/api/metadata/comments", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path: getMarkdownPath(),
        value: comments,
      }),
    });

    const result = await response.json().catch(() => ({}));

    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save comments (HTTP ${response.status})`);
    }
  }

  function getTimestamp() {
    return new Date().toISOString();
  }

  function renderComment(comment, index) {
    const article = document.createElement("article");
    article.className = "recipe-comment";
    article.dataset.commentIndex = String(index);
    const commentId = article.dataset.commentId;
    const author = comment.author?.trim() || "Anonymous";
    const initials = author
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase())
      .join("");

    const avatar = document.createElement("div");
    avatar.className = "recipe-comment__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = initials;

    const content = document.createElement("div");
    content.className = "recipe-comment__content";

    const meta = document.createElement("header");
    meta.className = "recipe-comment__meta";

    const authorElement = document.createElement("span");
    authorElement.className = "recipe-comment__author";
    authorElement.textContent = author;

    const date = document.createElement("time");
    date.className = "recipe-comment__date";
    date.dateTime = comment.created;

    const [year, month, day] = comment.created.split("-").map(Number);
    date.textContent = new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    });

    meta.append(authorElement, date);

    const text = document.createElement("p");
    text.className = "recipe-comment__text";
    text.textContent = comment.text;

    const actions = document.createElement("div");
    actions.className = "recipe-comment__actions";

    for (const [action, label] of [
      ["edit", "Edit"],
      ["delete", "Delete"],
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
    const sortedComments = [...comments].sort((a, b) => {
      const timestampA = Date.parse(a.updated || a.created) || 0;
      const timestampB = Date.parse(b.updated || b.created) || 0;

      return timestampB - timestampA;
    });

    list.replaceChildren(...sortedComments.map((comment) => createComment(comment)));

    //   updateCount(sortedComments.length);
  }

  function updateCount(total) {
    count.textContent = total;
  }

  function setCommentBusy(article, busy) {
    article.querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
    });
  }

  function createCommentId() {
    if (typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }

    // UUID v4 fallback for browsers or contexts without randomUUID().
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
      const random = (Math.random() * 16) | 0;
      const value = character === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }

  async function editComment(article) {
    const commentId = article.dataset.commentId;
    const comments = await getComments();

    const index = comments.findIndex((comment) => comment.id === commentId);

    if (index === -1) {
      throw new Error("Comment no longer exists. Reload the page.");
    }

    const comment = comments[index];

    if (!comment) {
      throw new Error("Comment no longer exists. Reload the page.");
    }

    const content = article.querySelector(".recipe-comment__content");
    const form = document.createElement("form");
    form.className = "recipe-comment__edit";

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
    form.append(author, text, actions);
    content.replaceChildren(form);

    cancel.addEventListener("click", () => {
      article.replaceWith(renderComment(comment, index));
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const newAuthor = author.value.trim();
      const newText = text.value.trim();

      if (!newAuthor || !newText) return;

      setCommentBusy(article, true);

      try {
        // Read the latest data before updating the selected comment.
        const latest = await getComments();

        const latestIndex = latest.findIndex((item) => item.id === commentId);

        if (latestIndex === -1) {
          throw new Error("Comment no longer exists.");
        }

        latest[latestIndex] = {
          ...latest[latestIndex],
          author: newAuthor,
          text: newText,
          updated: getTimestamp(),
        };

        await saveComments(latest);
        renderAllComments(latest);
      } catch (error) {
        console.error("Unable to edit comment:", error);
        setCommentBusy(article, false);
        let message = article.querySelector(".recipe-comment__status");

        if (!message) {
          message = document.createElement("p");
          message.className = "recipe-comment__status";
          message.setAttribute("role", "status");
          form.append(message);
        }

        message.textContent = error.message;
      }
    });

    author.focus();
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

  // Event delegation also handles comments added after the page loads.
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

  if (!recipePath) {
    console.error("Missing data-recipe-path on #recipe-comments");
    return;
  }

  function setFormOpen(open) {
    form.hidden = !open;
    addButton.setAttribute("aria-expanded", String(open));
    status.textContent = "";

    if (open) {
      textInput.focus();
    }
  }

  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));

    return page.replace(/\.html$/i, ".md");
  }

  function createComment(comment) {
    const article = document.createElement("article");
    article.className = "recipe-comment";
    article.dataset.commentId = comment.id;

    const author = (comment.author || "Anonymous").trim() || "Anonymous";
    const initials = author
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase())
      .join("");

    const avatar = document.createElement("div");
    avatar.className = "recipe-comment__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = initials;

    const content = document.createElement("div");
    content.className = "recipe-comment__content";

    const meta = document.createElement("header");
    meta.className = "recipe-comment__meta";

    const authorElement = document.createElement("span");
    authorElement.className = "recipe-comment__author";
    authorElement.textContent = author;

    const dateElement = document.createElement("time");
    dateElement.dateTime = comment.updated || comment.created;

    const date = new Date(dateElement.dateTime);

    dateElement.textContent = Number.isNaN(date.getTime())
      ? dateElement.dateTime
      : date.toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
          day: "numeric",
        });

    meta.append(authorElement, dateElement);

    const text = document.createElement("p");
    text.className = "recipe-comment__text";
    text.textContent = comment.text;

    const actions = document.createElement("div");
    actions.className = "recipe-comment__actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.dataset.action = "edit";
    editButton.textContent = "Edit";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.dataset.action = "delete";
    removeButton.textContent = "Remove";

    actions.append(editButton, removeButton);
    content.append(meta, text, actions);
    article.append(avatar, content);

    return article;
  }

  async function getComments() {
    const params = new URLSearchParams({
      path: getMarkdownPath(),
    });

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

  async function loadComments() {
    try {
      const comments = await getComments();
      renderAllComments(comments);
    } catch (error) {
      console.error("Unable to load comments:", error);
      status.textContent = "Unable to load comments.";
    }
  }

  loadComments();

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

      const comment = {
        id: createCommentId(),
        author,
        created: timestamp,
        updated: timestamp,
        text,
      };

      const updatedComments = [...comments, comment];

      const response = await fetch("/api/metadata/comments", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          path: getMarkdownPath(),
          value: updatedComments,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to save comment (${response.status})`);
      }

      const result = await response.json();

      if (result.success !== true) {
        throw new Error("The server did not confirm the save.");
      }

      // Re-render all comments and update the count.
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
})();
