# Feedback sections (`src/recipeserver/markdown_to_html/feedback.py`)

The comments and ratings sections rendered at the bottom of every recipe page. Both share one skeleton — a heading with an add button, a hidden add-form, and an empty list that `assets/comments.js` / `assets/ratings.js` populate — differing only in naming and form fields.

## Public surface

- `comments_html(has_comments=False)` — the `<section class="recipe-comments recipe-extras" id="recipe-comments">` fragment; the list is `#comment-list`, the form `#recipe-comment-form` (name + textarea).
- `ratings_html(has_ratings=False)` — the ratings counterpart; form ids `#recipe-rating-form`, `#rating-author`, `#rating-score` (a text field, not a number input — see the ratings conventions in `AGENTS.md`).
- `_feedback_section(kind=…, singular=…, heading=…, add_label=…, has_items=…, form_body=…)` — the shared builder; `has_items=False` adds an `is-empty` class.

`has_comments` / `has_ratings` are decided by [converter.md](converter.md) from the front matter (`_has_comments` / `_has_valid_ratings`); the lists themselves are filled client-side. The rating meter shows five stars (two points each) alongside the numeric score.

## Related pages

- [converter.md](converter.md) — computes `has_comments` / `has_ratings`
- [page.md](page.md) — where these sections land in the page shell
- [README.md](../README.md) — the package hub
