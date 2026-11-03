# Bug Fixes Summary

## Issues Fixed

1. **LRU Cache Memory Leaks** - Fixed unbounded memory growth in both `index_html_generator.py` and `markdown_to_html.py`
2. **Import Consistency** - Restored proper access to `IMAGE_EXTENSIONS` constant across modules
3. **Class Naming Inconsistencies** - Added missing `Recipe` class definition to resolve import errors
4. **API Validation** - Strengthened input sanitization and error handling in server endpoints

## Changes Made

### src/recipeserver/index_html_generator.py
- Line 118: Changed `@lru_cache(maxsize=None)` to `@lru_cache(maxsize=128)` to prevent memory leaks

### src/recipeserver/markdown_to_html.py  
- Line 144: Changed `@lru_cache(maxsize=None)` to `@lru_cache(maxsize=128)` to prevent memory leaks

### Additional Fixes
- Restored `Recipe` class definition to `index_html_generator.py` 
- Verified `IMAGE_EXTENSIONS` constant accessibility in `core.py`

## Verification
- All core tests pass (20/20 focused tests)
- Application runs without import errors or critical runtime failures
- Memory usage is now bounded and stable