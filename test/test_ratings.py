from functools import partial
from http.server import ThreadingHTTPServer
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import frontmatter

from recipeserver.server import RecipeRequestHandler, _validate_ratings


def valid_rating(name="Kailey Ford", rating=8.5, rating_id="rating-1"):
    return {
        "name": name,
        "created": "2026-10-27T01:38:21.996Z",
        "updated": "2026-10-27T01:38:21.996Z",
        "id": rating_id,
        "rating": rating,
    }


def test_validate_ratings_accepts_example_shape_and_decimal_score():
    ratings = [valid_rating()]

    assert _validate_ratings(ratings) == ratings


@pytest.mark.parametrize(
    "ratings",
    [
        None,
        [valid_rating(), valid_rating(name="kailey ford", rating_id="rating-2")],
        [valid_rating(rating=-0.5)],
        [valid_rating(rating=10.5)],
        [valid_rating(rating=True)],
        [valid_rating(rating_id="")],
        [valid_rating(), valid_rating(rating_id="rating-1", name="Andy Ford")],
        [{**valid_rating(), "created": "not a timestamp"}],
    ],
)
def test_validate_ratings_rejects_invalid_data(ratings):
    with pytest.raises(ValueError):
        _validate_ratings(ratings)


def test_ratings_metadata_endpoint_reads_saves_and_rejects_duplicate_names(tmp_path):
    recipe_path = tmp_path / "recipe.md"
    recipe_path.write_text("---\nmeals: []\n---\n# Test\n", encoding="utf-8")
    saved_paths = []
    handler = partial(
        RecipeRequestHandler,
        directory=str(tmp_path),
        source_directory=tmp_path,
        on_markdown_saved=saved_paths.append,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever)
    thread.start()

    url = f"http://127.0.0.1:{server.server_port}/api/metadata/ratings?path=recipe.md"
    try:
        with urlopen(url) as response:
            assert json.loads(response.read()) == {"value": []}

        rating = valid_rating()
        payload = json.dumps({"path": "recipe.md", "value": [rating]}).encode("utf-8")
        request = Request(
            url.split("?")[0],
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            assert json.loads(response.read())["success"] is True

        assert saved_paths == [recipe_path]
        assert frontmatter.loads(recipe_path.read_text(encoding="utf-8")).metadata["ratings"] == [rating]

        duplicate = valid_rating(name="kailey ford", rating_id="rating-2")
        request = Request(
            url.split("?")[0],
            data=json.dumps({"path": "recipe.md", "value": [rating, duplicate]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)

        assert error.value.code == 400
        assert saved_paths == [recipe_path]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
