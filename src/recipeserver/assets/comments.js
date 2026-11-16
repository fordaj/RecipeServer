(() => {
  const root = document.querySelector("#recipe-comments");
  if (!root) return;

  // recipe-feedback.js is loaded before this file on recipe pages and is a
  // hard dependency; fail loudly if it is missing instead of silently
  // running with degraded helpers.
  const feedback = window.RecipeFeedback;
  if (!feedback) {
    throw new Error("recipe-feedback.js must load before comments.js");
  }

  const recipePath = feedback.getMarkdownPath();

  // ----- DOM references ----- //
  const form = root.querySelector("#recipe-comment-form");
  const addButton = root.querySelector(".recipe-comments__add");
  const cancelButton = root.querySelector("#cancel-comment");
  const saveButton = root.querySelector("#save-comment");
  const authorPicker = feedback.createNamePicker(
    root.querySelector("#recipe-comment-form .recipe-editor__picker"),
  );
  const textInput = root.querySelector("#comment-text");
  const status = root.querySelector("#comment-status");
  const list = root.querySelector("#comment-list");

  // The device remembers who it is talking to.
  const storedAuthor = feedback.getStoredName("lastCommenter");
  if (storedAuthor) {
    authorPicker.setValues([storedAuthor]);
  }

  // ----- Limits ----- //
  // Character limit for the comment message textarea. The author field is a
  // picker whose "Add new" input caps at the data-max-length on the element.
  const MAX_MESSAGE_LENGTH = 5000;

  // ----- Data helpers ----- //
  function getTimestamp() {
    return new Date().toISOString();
  }

  function fetchComments() {
    return feedback.fetchMetadata("comments", recipePath);
  }

  function saveComments(comments) {
    return feedback.saveMetadata("comments", recipePath, comments);
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
    article.dataset.feedbackId = comment.id;

    const author = (comment.author || "Anonymous").trim() || "Anonymous";
    const avatar = document.createElement("div");
    avatar.className = "recipe-comment__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = feedback.getInitials(author);

    const content = document.createElement("div");
    content.className = "recipe-comment__content";

    const meta = document.createElement("header");
    meta.className = "recipe-comment__meta";
    const authorElement = document.createElement("span");
    authorElement.className = "recipe-comment__author";
    authorElement.textContent = author;

    const dateElement = feedback.createDateElement(comment.updated || comment.created);
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

  // ----- Edit form ----- //
  function buildEditForm(comment) {
    const editForm = document.createElement("form");
    editForm.className = "recipe-comment__edit";

    const nameContainer = document.createElement("span");
    nameContainer.className = "recipe-editor__picker recipe-feedback__picker";
    nameContainer.setAttribute("data-field", "commenters");
    nameContainer.setAttribute("data-max-length", "100");

    const authorPicker = feedback.createNamePicker(nameContainer);
    authorPicker.setValues([comment.author || "Anonymous"]);
    feedback.refreshNameOptions(authorPicker, "commenters");

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

    editForm.append(nameContainer, text, actions);
    return { form: editForm, authorPicker, text, cancel, focus: () => authorPicker.focus() };
  }

  const { renderAll } = feedback.createFeedbackList({
    root,
    list,
    kind: "comment",
    confirmDeleteMessage: "Delete this comment? This cannot be undone.",
    fetchItems: getComments,
    saveItems: saveComments,
    createItem: createComment,
    buildEditForm,
    submitEdit: async ({ item, index, items, controls }) => {
      const newAuthor = (controls.authorPicker.getValues()[0] ?? "").trim();
      const newText = controls.text.value.trim();
      if (!newAuthor || !newText) {
        // The name dropdown has no native required state, so say what is missing.
        feedback.showInlineError(
          controls.form,
          !newAuthor ? "Please enter your name." : "Please enter a comment.",
          "recipe-comment__status",
        );
        return null;
      }

      return items.map((existing, existingIndex) =>
        existingIndex === index
          ? { ...existing, author: newAuthor, text: newText, updated: getTimestamp() }
          : existing,
      );
    },
  });

  // ----- Form controls ----- //
  function setFormOpen(open) {
    form.hidden = !open;
    addButton.setAttribute("aria-expanded", String(open));
    status.textContent = "";
    if (open) {
      feedback.refreshNameOptions(authorPicker, "commenters");
      const stored = feedback.getStoredName("lastCommenter");
      if (stored) authorPicker.setValues([stored]);
      textInput.focus();
    }
  }

  async function loadComments() {
    try {
      renderAll(await getComments());
    } catch (error) {
      console.error("Unable to load comments:", error);
      status.textContent = "Unable to load comments.";
    }
  }

  // ----- Event wiring ----- //
  addButton.addEventListener("click", () => {
    setFormOpen(true);
  });

  cancelButton.addEventListener("click", () => {
    form.reset();
    setFormOpen(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const author = (authorPicker.getValues()[0] ?? "").trim();
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
          id: feedback.createId(),
          author,
          created: timestamp,
          updated: timestamp,
          text,
        },
      ];
      await saveComments(updatedComments);
      renderAll(updatedComments);
      // form.reset() clears the textarea; the remembered name stays selected.
      form.reset();
      feedback.setStoredName("lastCommenter", author);
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
