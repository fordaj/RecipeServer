Text, a URL, or an image will be provided as input. Formatting will be pretty inconsistent, but I'm hoping you can sift through it and output a markdown file for me. Here are the requirements:

- When prompted with recipe text, ONLY reply with the markdown file. No additional text.
- Surround ingredient quantities and units with backticks with the intent of creating a <code> block that I can scale quantities of when I generate the HTML. Examples: `1 cup` water. `2 large eggs`. `1 3/4 tsp` salt. `2 pinches` of salt. Ranges should look like `3/4 cup`–`1 cup`. Don't surround temperatures or times! Only things we want to scale. Do surround servings.
- Ingredient sections don't have to be titled Ingredients, but they should be comprised of an unordered list of checkboxes.
- For ordered lists, lean on markdown's support of starting them all with 1., not 2., 3., etc.
- Each recipe should only have 1 H1 element at the beginning, the name of the recipe. Example: # Brownies
- That H1 element should be followed by a link to an image. I'll bring the image. Example: ![Brownies]\(image.png)
- After that, the recipe meta definitions section.

Here is your example to follow:

```markdown
---
meals:
  - Dessert
---

# Brownies

![Brownies](image.png)

/// html | div.recipe-meta

Prep Time
: 30 minutes

Cook Time
: 30 minutes

Servings
: `6 brownies`

/// <!-- recipe-meta -->

## Ingredients

- [ ] `1/2 cup` (`1 stick`) unsalted butter
- [ ] `1 cup` granulated sugar
- [ ] `2 eggs`
- [ ] `1 tsp` vanilla extract
- [ ] `1/3 cup` unsweetened cocoa powder
- [ ] `1/2 cup` all-purpose flour
- [ ] `1/4 tsp` salt
- [ ] `1/4 tsp` baking powder
- [ ] Optional: `1/2 cup` chocolate chips or chopped nuts

## Preparation

1. Preheat oven to 350°F (175°C). Grease or line an 8x8-inch baking pan with parchment paper.
1. In a medium saucepan, melt the butter over low heat. Once melted, remove from heat and mix in the sugar, eggs, and vanilla until smooth.
1. Stir in cocoa powder until fully combined.
1. Add flour, salt, and baking powder, and stir just until the batter is smooth. Avoid overmixing.
1. If using, fold in chocolate chips or nuts.
1. Pour the batter into the prepared pan, spreading it evenly.
1. Bake for 20–25 minutes, or until a toothpick inserted in the center comes out with a few moist crumbs (for fudgy brownies).
1. Allow the brownies to cool before cutting into squares.

## Tips

Cast Iron: Double for a 9”x13” pan. Preheat pan in oven. Add butter before pour.
```
