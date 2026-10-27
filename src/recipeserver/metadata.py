from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import statistics


@dataclass
class RecipeMetadata:
    """Data class for recipe metadata with helper methods."""

    # Basic fields from the example
    meals: List[str] = field(default_factory=list)
    cuisine: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    makes: Optional[int] = None
    difficulty: Optional[int] = None
    ratings: List[Dict[str, Any]] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)

    # Additional fields that might be useful
    title: Optional[str] = None
    author: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    servings: Optional[int] = None

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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecipeMetadata":
        """Create a RecipeMetadata object from a dictionary."""
        # Handle potential None values and type conversion
        return cls(
            meals=data.get("meals", []),
            cuisine=data.get("cuisine", []),
            categories=data.get("categories", []),
            tags=data.get("tags", []),
            makes=data.get("makes"),
            difficulty=data.get("difficulty"),
            ratings=data.get("ratings", []),
            comments=data.get("comments", []),
            title=data.get("title"),
            author=data.get("author"),
            prep_time=data.get("prep_time"),
            cook_time=data.get("cook_time"),
            servings=data.get("servings"),
        )

    def get_average_rating(self) -> float:
        """Calculate the average rating from all ratings."""
        if not self.ratings:
            return 0.0

        try:
            ratings_values = [
                rating["rating"] for rating in self.ratings if isinstance(rating, dict) and "rating" in rating
            ]
            if not ratings_values:
                return 0.0
            return statistics.mean(ratings_values)
        except statistics.StatisticsError, TypeError:
            return 0.0

    def get_rating_count(self) -> int:
        """Get the number of ratings."""
        return len(self.ratings)

    def get_comment_count(self) -> int:
        """Get the number of comments."""
        return len(self.comments)

    def get_all_tags(self) -> List[str]:
        """Get a flattened list of all tags from meals, cuisine, categories and tags."""
        all_tags = set()
        if self.meals:
            all_tags.update(self.meals)
        if self.cuisine:
            all_tags.update(self.cuisine)
        if self.categories:
            all_tags.update(self.categories)
        if self.tags:
            all_tags.update(self.tags)
        return list(all_tags)

    def get_unique_tags(self) -> List[str]:
        """Get unique tags from all metadata fields."""
        return self.get_all_tags()

    def is_valid(self) -> bool:
        """Validate that the metadata has required fields and proper types."""
        # Check basic data types
        if self.makes is not None and not isinstance(self.makes, int):
            return False
        if self.difficulty is not None and not isinstance(self.difficulty, (int, float)):
            return False

        # Validate ratings structure
        for rating in self.ratings:
            if not isinstance(rating, dict) or "rating" not in rating:
                return False

        # Validate comments structure
        for comment in self.comments:
            if not isinstance(comment, dict) or "text" not in comment:
                return False

        return True


# Example usage (for testing)
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
    )

    print("Sample metadata:")
    print(sample_metadata.to_dict())
    print(f"Average rating: {sample_metadata.get_average_rating()}")
    print(f"Number of ratings: {sample_metadata.get_rating_count()}")
    print(f"Number of comments: {sample_metadata.get_comment_count()}")
