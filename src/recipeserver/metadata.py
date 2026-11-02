from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar, Dict, List, Optional
import statistics
import math
import unicodedata


@dataclass
class RecipeMetadata:
    """Single source of truth for recipe metadata."""

    meals: List[str] = field(default_factory=list)
    cuisine: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    makes: Optional[int] = None
    difficulty: Optional[float] = None
    ratings: List[Dict[str, Any]] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)
    title: Optional[str] = None
    author: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None
    contributor: Optional[str] = None
    createdOn: Optional[str] = None
    updatedOn: Optional[str] = None
    source: List[Dict[str, Any]] = field(default_factory=list)

    # The single source of truth for which metadata fields are required.
    REQUIRED_FIELDS: ClassVar[Dict[str, str]] = {
        "contributor": "Contributor",
        "meals": "Meals",
        "categories": "Category",
        "makes": "Makes",
        "difficulty": "Difficulty",
    }

    # Every metadata field the server understands.
    FIELD_NAMES: ClassVar[frozenset] = frozenset(
        {
            "meals",
            "cuisine",
            "categories",
            "tags",
            "makes",
            "difficulty",
            "ratings",
            "comments",
            "title",
            "author",
            "prep_time",
            "cook_time",
            "servings",
            "contributor",
            "createdOn",
            "updatedOn",
            "source",
        }
    )

    # Editor facing metadata fields and their expected value types.
    EDITOR_FIELDS: ClassVar[Dict[str, str]] = {
        "tags": "string_list",
        "cuisine": "string_list",
        "category": "string_list",
        "meals": "string_list",
        "makes": "integer",
        "difficulty": "number",
        "contributor": "string",
        "createdOn": "string",
        "updatedOn": "string",
        "source": "object",
    }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RecipeMetadata":
        """Create a RecipeMetadata object from a dictionary."""
        data = data or {}

        source_data = data.get("source") or []
        source = [source_data] if isinstance(source_data, dict) else list(source_data or [])

        return cls(
            meals=list(data.get("meals") or []),
            cuisine=list(data.get("cuisine") or []),
            categories=list(data.get("categories") or []),
            tags=list(data.get("tags") or []),
            makes=data.get("makes"),
            difficulty=data.get("difficulty"),
            ratings=list(data.get("ratings") or []),
            comments=list(data.get("comments") or []),
            title=data.get("title"),
            author=data.get("author"),
            prep_time=data.get("prep_time"),
            cook_time=data.get("cook_time"),
            servings=data.get("servings"),
            contributor=data.get("contributor"),
            createdOn=data.get("createdOn"),
            updatedOn=data.get("updatedOn"),
            source=source,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert the RecipeMetadata object to a dictionary."""
        return {
            "meals": self.meals,
            "cuisine": self.cuisine,
            "categories": self.categories,
            "tags": self.tags,
            "makes": self.makes,
            "difficulty": self.difficulty,
            "ratings": self.ratings,
            "comments": self.comments,
            "title": self.title,
            "author": self.author,
            "prep_time": self.prep_time,
            "cook_time": self.cook_time,
            "servings": self.servings,
            "contributor": self.contributor,
            "createdOn": self.createdOn,
            "updatedOn": self.updatedOn,
            "source": self.source,
        }

    def get(self, field_name: str, default: Any = None) -> Any:
        """Return a metadata value by field name."""
        return getattr(self, field_name, default)

    # Ratings

    def get_average_rating(self) -> Optional[float]:
        """Calculate the average rating from all ratings."""
        if not self.ratings:
            return None

        try:
            ratings_values = [
                rating["rating"]
                for rating in self.ratings
                if isinstance(rating, dict) and isinstance(rating.get("rating"), (int, float))
            ]
            if not ratings_values:
                return None

            return statistics.mean(ratings_values)
        except (statistics.StatisticsError, TypeError):
            return None

    def get_rating_count(self) -> int:
        """Get the number of ratings."""
        return len(self.ratings)

    # Comments

    def get_comment_count(self) -> int:
        """Get the number of comments."""
        return len(self.comments)

    # Tags

    def get_all_tags(self) -> List[str]:
        """Get a flattened list of all tags from meals, cuisine, categories and tags."""
        all_tags: List[str] = []
        seen: set = set()

        for field_name in ("meals", "cuisine", "categories", "tags"):
            for value in self.get(field_name) or []:
                text = str(value)
                if text and text not in seen:
                    seen.add(text)
                    all_tags.append(text)

        return all_tags

    def get_unique_tags(self) -> List[str]:
        """Get unique tags from all metadata fields."""
        return self.get_all_tags()

    def get_field_values(self, field_name: str) -> List[str]:
        """Return metadata values consistently as a list of strings."""
        value = self.get(field_name)

        if isinstance(value, str):
            value = [value]

        if not isinstance(value, list):
            return []

        values: List[str] = []
        seen: set = set()

        for item in value:
            if item is None:
                continue

            text = str(item)
            if not text or text in seen:
                continue

            seen.add(text)
            values.append(text)

        return values

    # Sources

    def get_sources(self) -> List[Dict[str, Any]]:
        """Return the recipe sources, normalizing a single source into a list."""
        sources = self.source

        if isinstance(sources, dict):
            sources = [sources]

        if not isinstance(sources, list):
            return []

        return [source for source in sources if isinstance(source, dict)]

    def get_source_title(self, source: Dict[str, Any]) -> str:
        """Return the display title of a recipe source."""
        source_format = str(source.get("format") or "").lower()
        if source_format not in {"website", "book"}:
            return ""

        title = source.get("title") or (source.get("company") if source_format == "website" else "")
        return str(title or "").strip()

    # Dates

    def get_contribution_date(self) -> Optional[date]:
        """Return the contribution date."""
        return self._parse_date(self.createdOn)

    def get_updated_date(self) -> Optional[datetime]:
        """Return the last updated date."""
        return self._parse_datetime(self.updatedOn)

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    # Validation

    def is_missing(self, field_name: str) -> bool:
        """Return whether a metadata field is missing."""
        value = self.get(field_name)

        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()

        if isinstance(value, list):
            return not value or all(_is_missing_value(item) for item in value)

        return False

    def get_missing_fields(self) -> List[str]:
        """Return the required metadata fields that are missing."""
        return [field_name for field_name in self.REQUIRED_FIELDS if self.is_missing(field_name)]

    def is_valid(self) -> bool:
        """Validate that the metadata has required fields and proper types."""
        if self.makes is not None and not isinstance(self.makes, int):
            return False

        if self.difficulty is not None and not isinstance(self.difficulty, (int, float)):
            return False

        for rating in self.ratings:
            if not isinstance(rating, dict) or "rating" not in rating:
                return False

        for comment in self.comments:
            if not isinstance(comment, dict) or "text" not in comment:
                return False

        return True

    @classmethod
    def validate_ratings(cls, ratings: Any) -> List[Dict[str, Any]]:
        """Validate and normalize a list of ratings."""
        if not isinstance(ratings, list):
            raise ValueError("'ratings' must be a list")

        validated = []
        names = set()
        ids = set()

        for index, rating in enumerate(ratings):
            if not isinstance(rating, dict):
                raise ValueError(f"Rating {index + 1} must be an object")

            name = rating.get("name")
            rating_id = rating.get("id")
            score = rating.get("rating")

            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError(f"Rating {index + 1} must have a name of 1 to 100 characters")

            normalized_name = unicodedata.normalize("NFKC", name.strip()).casefold()
            if normalized_name in names:
                raise ValueError("There can only be one rating per name")
            names.add(normalized_name)

            if not isinstance(rating_id, str) or not rating_id.strip() or rating_id != rating_id.strip():
                raise ValueError(f"Rating {index + 1} must have an ID")
            if rating_id in ids:
                raise ValueError("Rating IDs must be unique")
            ids.add(rating_id)

            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ValueError(f"Rating {index + 1} must have a numeric score")
            if score < 0 or score > 10 or not math.isfinite(score):
                raise ValueError(f"Rating {index + 1} must be between 0 and 10")

            for field_name in ("created", "updated"):
                timestamp = rating.get(field_name)
                if not isinstance(timestamp, str):
                    raise ValueError(f"Rating {index + 1} must have a {field_name} timestamp")
                try:
                    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError(f"Rating {index + 1} has an invalid {field_name} timestamp") from exc

            normalized_rating = rating.copy()
            normalized_rating["name"] = name.strip()
            validated.append(normalized_rating)

        return validated

    # Editor metadata

    @classmethod
    def validate_string_list(cls, field_name: str, value: Any) -> Optional[List[str]]:
        if value is None:
            return None

        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"'{field_name}' must be a list of strings or null")

        return value

    @classmethod
    def validate_string(cls, field_name: str, value: Any) -> Optional[str]:
        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError(f"'{field_name}' must be a string or null")

        return value

    @classmethod
    def validate_integer(cls, field_name: str, value: Any) -> Optional[int]:
        if value is None:
            return None

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{field_name}' must be an integer or null")

        return value

    @classmethod
    def validate_number(cls, field_name: str, value: Any) -> Optional[float]:
        if value is None:
            return None

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{field_name}' must be a number or null")

        return value

    @classmethod
    def validate_source(cls, value: Any) -> Optional[Dict[str, Any]]:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise ValueError("'source' must be an object or null")

        allowed_fields = {"author", "title", "format", "url"}

        return {
            key: (value.get(key).strip() or None if isinstance(value.get(key), str) else None)
            for key in allowed_fields
        }


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value or all(_is_missing_value(item) for item in value)
    return False


if __name__ == "__main__":
    # Create sample metadata
    sample_metadata = RecipeMetadata(
        meals=["Dessert"],
        cuisine=["American"],
        categories=["Cake"],
        tags=["Cinnamon", "Icing", "Cake"],
        makes=4,
        difficulty=6,
        ratings=[{"name": "Kailey Ford", "rating": 7}, {"name": "Andy Ford", "rating": 8.5}],
        comments=[
            {
                "author": "Andy Ford",
                "created": "2026-10-17",
                "text": "Scaled by 0.5x and made in a cast iron loaf pan.",
            },
            {"author": "Kailey Ford", "created": "2026-10-18", "text": "So yummy"},
        ],
        contributor="Andy Ford",
        createdOn="2026-10-17T12:00:00Z",
        updatedOn="2026-10-18T12:00:00Z",
    )

    print("Sample metadata:")
    print(sample_metadata.to_dict())
    print(f"Average rating: {sample_metadata.get_average_rating()}")
    print(f"Number of ratings: {sample_metadata.get_rating_count()}")
    print(f"Number of comments: {sample_metadata.get_comment_count()}")
