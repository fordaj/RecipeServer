"""Deterministic mock recipe library generator.

Builds a throwaway tree of realistic recipes — ``mock-000001/recipe.md`` …
``mock-N/recipe.md``, one generated ``image.png`` per recipe — for the scale
tests. The output is fully determined by ``(count, seed)`` so runs are
reproducible and diffable.

Generation is not timed as part of the build measurement; the harness records
the generator's wall time separately as context.

Images are generated once as a small pool of 320x200 hue-rotated variants and
copied into each recipe directory. That keeps 10,000-recipe generation cheap
while still forcing the accent-color quantization path to do real work on
every build.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import copy2

from PIL import Image

IMAGE_WIDTH = 320
IMAGE_HEIGHT = 200
IMAGE_VARIANT_COUNT = 8

_MEALS = ["Breakfast", "Lunch", "Dinner", "Dessert", "Snack", "Side"]
_CATEGORIES = [
    "Pasta",
    "Soup",
    "Salad",
    "Casserole",
    "Stir-fry",
    "Baked goods",
    "Grilled",
    "Slow cooker",
    "One-pan",
    "Vegetarian",
    "Seafood",
    "Chicken",
]
_CUISINES = ["Italian", "Mexican", "Thai", "Indian", "Japanese", "Mediterranean", "French", "Southern", "Greek", "Chinese"]
_TAGS = ["quick", "weeknight", "make-ahead", "kid-friendly", "spicy", "comfort", "seasonal", "batch-cooking", "freezer-friendly", "vegetarian"]
_STATUSES = ["Active", "Active", "Active", "Active", "Draft", "Archived"]
_CONTRIBUTORS = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Gray"]
_ADJECTIVES = ["Smoky", "Lemony", "Hearty", "Golden", "Rustic", "Spiced", "Creamy", "Zesty", "Toasted", "Herbed", "Caramelized", "Peppery"]
_DISHES = [
    "Tomato Pasta",
    "Chickpea Curry",
    "Garlic Chicken",
    "Mushroom Risotto",
    "Beef Stew",
    "Salmon Bake",
    "Vegetable Soup",
    "Pork Tacos",
    "Eggplant Parmesan",
    "Shrimp Stir-fry",
    "Lentil Dal",
    "Sausage Gnocchi",
    "Chicken Piccata",
    "Baked Oatmeal",
    "Greek Salad",
]
_INGREDIENTS = [
    ("flour", "cups", 1.0, 4.0),
    ("olive oil", "tbsp", 1.0, 4.0),
    ("garlic cloves", "cloves", 2.0, 8.0),
    ("onion", "medium", 0.5, 2.0),
    ("kosher salt", "tsp", 0.5, 2.0),
    ("black pepper", "tsp", 0.25, 1.0),
    ("crushed tomatoes", "cups", 1.0, 3.0),
    ("vegetable broth", "cups", 1.0, 4.0),
    ("parmesan", "cups", 0.25, 1.0),
    ("fresh basil", "tbsp", 1.0, 4.0),
    ("butter", "tbsp", 1.0, 4.0),
    ("lemon juice", "tbsp", 1.0, 3.0),
]
_QUANTITY_FRACTIONS = ["1/4", "1/3", "1/2", "2/3", "3/4", "1", "1 1/2", "2", "2 1/2", "3"]
_INSTRUCTIONS = [
    "Prep the ingredients: wash, chop, and measure everything before the heat goes on.",
    "Heat the oil in a large skillet over medium heat until shimmering.",
    "Add the aromatics and cook until softened and fragrant, about 3 minutes.",
    "Stir in the main ingredients and season generously.",
    "Simmer until the flavors come together and the sauce thickens slightly.",
    "Taste and adjust the seasoning.",
    "Rest for a few minutes off the heat.",
    "Serve warm and garnish as desired.",
]
_TIPS = [
    "Keeps well in the fridge for up to 3 days.",
    "Freezes well in airtight containers for up to 2 months.",
    "Double the batch and freeze half for a busy weeknight.",
    "Swap in whatever is in the crisper drawer.",
    "A squeeze of lemon at the end brightens the whole dish.",
]


@dataclass(frozen=True)
class MockLibraryInfo:
    """What the generator produced."""

    root: Path
    recipe_count: int
    seed: int
    generator_seconds: float

    @property
    def recipe_paths(self) -> list[Path]:
        return sorted(self.root.glob("mock-*/recipe.md"))


def _format_quantity(rng: random.Random) -> str:
    if rng.random() < 0.25:
        low, high = sorted(rng.sample(_QUANTITY_FRACTIONS, 2), key=lambda part: _QUANTITY_FRACTIONS.index(part))
        return f"{low}-{high}"
    return rng.choice(_QUANTITY_FRACTIONS)


def _recipe_markdown(rng: random.Random, index: int) -> str:
    meals = rng.sample(_MEALS, k=rng.choice([1, 1, 2]))
    categories = rng.sample(_CATEGORIES, k=rng.choice([1, 1, 2]))
    cuisine = rng.choice(_CUISINES)
    tags = rng.sample(_TAGS, k=rng.choice([1, 2, 3]))
    status = rng.choice(_STATUSES)
    contributor = rng.choice(_CONTRIBUTORS)
    makes = rng.choice([2, 4, 4, 6, 8, 12])
    difficulty = rng.randint(1, 10)
    created = f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T00:00:00.000Z"

    ratings = []
    for rating_index in range(rng.choice([0, 1, 2, 3])):
        name = rng.choice(_CONTRIBUTORS)
        created_at = f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T00:00:00.000Z"
        ratings.append(
            "\n".join(
                [
                    f"  - id: r{rating_index + 1}",
                    f"    name: {name}",
                    f"    rating: {rng.randint(6, 10)}",
                    f'    created: "{created_at}"',
                    f'    updated: "{created_at}"',
                ]
            )
        )

    lines = [
        "---",
        "meals:",
        *[f"  - {meal}" for meal in meals],
        "categories:",
        *[f"  - {category}" for category in categories],
        f"cuisine: {cuisine}",
        "tags:",
        *[f"  - {tag}" for tag in tags],
        f"status: {status}",
        f"contributor: {contributor}",
        f"makes: {makes}",
        f"difficulty: {difficulty}",
        f'createdOn: "{created}"',
    ]
    if ratings:
        lines.append("ratings:")
        lines.extend(ratings)
    lines.append("---")

    title = f"{rng.choice(_ADJECTIVES)} {rng.choice(_DISHES)}"

    lines.extend(["", f"# {title}", "", f"![{title}](image.png)", "", "## Ingredients", ""])
    for name, unit, low, high in rng.sample(_INGREDIENTS, k=rng.choice([8, 10, 12])):
        amount = _format_quantity(rng)
        lines.append(f"- [ ] `{amount} {unit}` {name}")

    lines.extend(["", "## Instructions", ""])
    for step, instruction in enumerate(rng.sample(_INSTRUCTIONS, k=rng.choice([5, 6, 7])), start=1):
        lines.append(f"{step}. {instruction}")

    lines.extend(["", "## Tips", ""])
    for tip in rng.sample(_TIPS, k=rng.choice([1, 2, 3])):
        lines.append(f"- {tip}")

    return "\n".join(lines) + "\n"


def _write_image_variants(variant_directory: Path) -> list[Path]:
    variant_directory.mkdir(parents=True, exist_ok=True)
    variants = []
    for index in range(IMAGE_VARIANT_COUNT):
        hue = (index * 47) % 360
        image = Image.new("HSV", (IMAGE_WIDTH, IMAGE_HEIGHT))
        pixels = image.load()
        for y in range(IMAGE_HEIGHT):
            for x in range(IMAGE_WIDTH):
                pixels[x, y] = ((hue + x // 8 + y // 12) % 180, 200, 140 + (x * 60) // IMAGE_WIDTH)
        variant = variant_directory / f"variant-{index:02d}.png"
        image.convert("RGB").save(variant, format="PNG", optimize=False)
        variants.append(variant)
    return variants


def build_mock_library(root: Path, count: int, *, seed: int) -> MockLibraryInfo:
    """Build ``count`` deterministic mock recipes under ``root``.

    The directory layout is ``root/mock-000001/recipe.md`` … with a generated
    ``image.png`` beside each one. Existing content under ``root`` is not
    cleaned up; pass a fresh temporary directory.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")

    start = time.perf_counter()
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)

    variants = _write_image_variants(root / ".image-variants")
    try:
        for index in range(1, count + 1):
            recipe_dir = root / f"mock-{index:06d}"
            recipe_dir.mkdir()
            (recipe_dir / "recipe.md").write_text(_recipe_markdown(rng, index), encoding="utf-8")
            copy2(variants[index % len(variants)], recipe_dir / "image.png")
    finally:
        for variant in variants:
            variant.unlink(missing_ok=True)
        try:
            (root / ".image-variants").rmdir()
        except OSError:
            pass

    return MockLibraryInfo(root=root, recipe_count=count, seed=seed, generator_seconds=time.perf_counter() - start)
