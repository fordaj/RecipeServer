"""Comments and ratings feedback sections.

Both sections share one skeleton: a heading with an add button, a hidden
add-form, and an empty list that ``comments.js`` / ``ratings.js`` fill in.
They differ only in naming and in the fields inside the form, so the
skeleton lives in ``_feedback_section`` and each section supplies its
form body.
"""

from textwrap import dedent

from .icons import PLUS_SVG, USER_ROUND_SVG, icon_html

_COMMENT_FORM_BODY = f"""\
        <div class="recipe-comment__avatar recipe-comment-form__avatar" aria-hidden="true">
            {icon_html(USER_ROUND_SVG)}
        </div>

        <div class="recipe-comment__content">
            <div class="recipe-comment__meta">
            <input id="comment-author" class="recipe-comment__author-input" type="text" placeholder="Your name" aria-label="Your name" required/>
            <span class="recipe-comment__date">Posting today</span>
            </div>

            <textarea id="comment-text" class="recipe-comment__text-input" placeholder="Write a comment..." aria-label="Comment" rows="3" required ></textarea>

            <div class="recipe-comment__actions recipe-comment-form__actions">
            <button id="cancel-comment" type="button">Cancel</button>
            <button id="save-comment" type="submit">Post comment</button>
            </div>

            <p id="comment-status" role="status" aria-live="polite"></p>
        </div>"""

_RATING_FORM_BODY = f"""\
        <div class="recipe-rating__avatar recipe-rating-form__avatar" aria-hidden="true">
            {icon_html(USER_ROUND_SVG)}
        </div>
        <div class="recipe-rating-form__content">
            <div class="recipe-rating-form__meta">
                <input id="rating-author" class="recipe-rating__author-input" type="text" placeholder="Your name" aria-label="Your name" maxlength="100" required />
            </div>
            <div class="recipe-rating__meter recipe-rating-form__meter">
                <input id="rating-score" type="text" inputmode="decimal" maxlength="16" value="5" aria-label="Rating out of 10" required />
                <span class="recipe-rating__stars" role="img" aria-label="5 out of 10">★★★★★</span>
                <output id="rating-score-value" class="recipe-rating__score">5/10</output>
            </div>
            <div class="recipe-rating__actions recipe-rating-form__actions">
                <button id="cancel-rating" type="button">Cancel</button>
                <button id="save-rating" type="submit">Post rating</button>
            </div>
            <p id="rating-status" role="status" aria-live="polite"></p>
        </div>"""


def comments_html(has_comments: bool = False) -> str:
    return _feedback_section(
        kind="comments",
        singular="comment",
        heading="Comments",
        add_label="Add a comment",
        has_items=has_comments,
        form_body=_COMMENT_FORM_BODY,
    )


def ratings_html(has_ratings: bool = False) -> str:
    return _feedback_section(
        kind="ratings",
        singular="rating",
        heading="Ratings",
        add_label="Add a rating",
        has_items=has_ratings,
        form_body=_RATING_FORM_BODY,
    )


def _feedback_section(*, kind: str, singular: str, heading: str, add_label: str, has_items: bool, form_body: str) -> str:
    empty_class = "" if has_items else " is-empty"
    return dedent(f"""\
        <section class="recipe-{kind}{empty_class} recipe-extras" id="recipe-{kind}">
            <h2 class="recipe-{kind}__heading">
                <span>{heading}</span>
                <button class="recipe-{kind}__add" type="button" aria-label="{add_label}" aria-expanded="false">
                {icon_html(PLUS_SVG)}
                </button>
            </h2>
            <form id="recipe-{singular}-form" class="recipe-{singular}-form" hidden>
{form_body}
            </form>
            <div class="recipe-{kind}__list" id="{singular}-list"></div>
        </section>""")
