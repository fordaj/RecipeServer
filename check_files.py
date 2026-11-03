#!/usr/bin/env python3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Test imports and basic functionality
try:
    from recipeserver.image_handler import IMAGE_EXTENSIONS
    print("✓ IMAGE_EXTENSIONS imported successfully")
except Exception as e:
    print(f"✗ IMAGE_EXTENSIONS import failed: {e}")

try:
    from recipeserver.index_html_generator import Recipe, IndexHTMLGenerator
    print("✓ IndexHTMLGenerator imports successfully")
except Exception as e:
    print(f"✗ IndexHTMLGenerator import failed: {e}")

try:
    from recipeserver.markdown_to_html import MarkdownToHTMLConverter
    print("✓ MarkdownToHTMLConverter imports successfully")
except Exception as e:
    print(f"✗ MarkdownToHTMLConverter import failed: {e}")

try:
    from recipeserver.core import Core
    print("✓ Core imports successfully")
except Exception as e:
    print(f"✗ Core import failed: {e}")

print("\nChecking cache implementations...")

# Check if lru_cache replacement is done correctly  
try:
    import recipeserver.image_handler as ih
    import inspect
    source = inspect.getsource(ih)
    if 'maxsize=None' in source:
        print("✗ Found maxsize=None in image_handler - this should be replaced")
    else:
        print("✓ No maxsize=None found in image_handler")
        
    # Check if there's proper cache size management
    lines = source.split('\n')
    cache_lines = [line for line in lines if 'lru_cache' in line]
    print(f"✓ Found {len(cache_lines)} lru_cache entries in image_handler")
except Exception as e:
    print(f"✗ Error inspecting image_handler: {e}")

try:
    import recipeserver.index_html_generator as ihg
    import inspect
    source = inspect.getsource(ihg)
    if 'maxsize=None' in source:
        print("✗ Found maxsize=None in index_html_generator - this should be replaced")
    else:
        print("✓ No maxsize=None found in index_html_generator")
        
    # Check the Recipe class definition
    has_recipe_class = 'class Recipe' in source
    print(f"✓ Recipe class defined: {has_recipe_class}")
except Exception as e:
    print(f"✗ Error inspecting index_html_generator: {e}")

print("\nAll checks completed.")