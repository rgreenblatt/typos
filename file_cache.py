"""
Simple file-based cache that stores each entry as an individual file.

This module is intended to be copied into your project and modified as needed.
You may want to customize the serialize/deserialize functions for your use case
(e.g., use pickle for Python objects, msgpack for performance, etc.).

Dependencies:
- aiofiles (for async operations): pip install aiofiles
"""

import hashlib
import json
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

# Optional import for async operations
try:
    import aiofiles
except ImportError:
    aiofiles = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import aiofiles

T = TypeVar("T")


# =============================================================================
# Serialization functions - modify these for your use case
# =============================================================================

def serialize(value: Any, *, deterministic: bool = False) -> str:
    """
    Serialize a value to a string.

    Args:
        value: The value to serialize (must be JSON-serializable by default).
        deterministic: If True, use sorted keys for consistent output.
                       Useful when the serialized output is used for hashing.

    Returns:
        The serialized string representation.

    Note:
        Modify this function if you need different serialization (e.g., pickle, msgpack).
    """
    return json.dumps(value, sort_keys=deterministic)


def deserialize(data: str) -> Any:
    """
    Deserialize a string back to a value.

    Args:
        data: The serialized string.

    Returns:
        The deserialized value.

    Note:
        Modify this function to match your serialize() implementation.
    """
    return json.loads(data)


# =============================================================================
# File Cache
# =============================================================================

class FileCache:
    """
    A simple file-based cache that stores each entry in a separate file.

    Keys are hashed to create filenames, values are serialized to file contents.

    Example:
        cache = FileCache("./my_cache")
        cache.set({"user": 123, "query": "hello"}, {"result": "world"})
        result = cache.get({"user": 123, "query": "hello"})
    """

    def __init__(self, cache_dir: str | Path):
        """
        Initialize the file cache.

        Args:
            cache_dir: Directory to store cache files. Created if it doesn't exist.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_to_filename(self, key: Any) -> Path:
        """Convert a key to a cache file path by hashing its serialized form."""
        key_str = serialize(key, deterministic=True)
        key_hash = hashlib.sha256(key_str.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"

    def get(self, key: Any, default: T = None) -> Any | T:
        """
        Retrieve a value from the cache.

        Args:
            key: The cache key (must be serializable).
            default: Value to return if key is not found.

        Returns:
            The cached value, or default if not found.
        """
        filepath = self._key_to_filename(key)
        if not filepath.exists():
            return default

        with open(filepath, "r", encoding="utf-8") as f:
            return deserialize(f.read())

    def set(self, key: Any, value: Any) -> None:
        """
        Store a value in the cache.

        Args:
            key: The cache key (must be serializable).
            value: The value to cache (must be serializable).
        """
        filepath = self._key_to_filename(key)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(serialize(value))

    def delete(self, key: Any) -> bool:
        """
        Delete an entry from the cache.

        Args:
            key: The cache key.

        Returns:
            True if the entry was deleted, False if it didn't exist.
        """
        filepath = self._key_to_filename(key)
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def exists(self, key: Any) -> bool:
        """Check if a key exists in the cache."""
        return self._key_to_filename(key).exists()

    def clear(self) -> int:
        """
        Clear all entries from the cache.

        Warning:
            This deletes ALL .cache files in the cache directory. If you're
            sharing the directory with other caches, they will also be cleared.

        Returns:
            Number of entries deleted.
        """
        count = 0
        for filepath in self.cache_dir.glob("*.cache"):
            filepath.unlink()
            count += 1
        if count > 0:
            warnings.warn(
                f"Cleared {count} cache entries from {self.cache_dir}",
                stacklevel=2,
            )
        return count

    # =========================================================================
    # Async methods (require aiofiles)
    # =========================================================================

    async def aget(self, key: Any, default: T = None) -> Any | T:
        """
        Async version of get().

        Requires: pip install aiofiles
        """
        if aiofiles is None:
            raise ImportError("aiofiles is required for async operations: pip install aiofiles")

        filepath = self._key_to_filename(key)
        if not filepath.exists():
            return default

        async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
            content = await f.read()
            return deserialize(content)

    async def aset(self, key: Any, value: Any) -> None:
        """
        Async version of set().

        Requires: pip install aiofiles
        """
        if aiofiles is None:
            raise ImportError("aiofiles is required for async operations: pip install aiofiles")

        filepath = self._key_to_filename(key)
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(serialize(value))

    async def adelete(self, key: Any) -> bool:
        """
        Async version of delete().

        Note: Uses sync unlink as it's typically fast enough.
        """
        return self.delete(key)

    async def aexists(self, key: Any) -> bool:
        """Async version of exists(). Uses sync check as it's typically fast enough."""
        return self.exists(key)


# =============================================================================
# Usage example
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import tempfile

    # Create a temporary cache directory for demo, use persistent path for real usage
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = FileCache(tmpdir)

        # Sync usage
        key = {"user_id": 42, "query": "weather"}
        value = {"temperature": 72, "conditions": "sunny"}

        cache.set(key, value)
        retrieved = cache.get(key)
        print(f"Sync - Stored: {value}")
        print(f"Sync - Retrieved: {retrieved}")
        print(f"Sync - Match: {value == retrieved}")

        # Async usage (if aiofiles is available)
        async def async_demo():
            key2 = {"user_id": 43, "query": "news"}
            value2 = {"headlines": ["Story 1", "Story 2"]}

            await cache.aset(key2, value2)
            retrieved2 = await cache.aget(key2)
            print(f"\nAsync - Stored: {value2}")
            print(f"Async - Retrieved: {retrieved2}")
            print(f"Async - Match: {value2 == retrieved2}")

        if aiofiles is not None:
            asyncio.run(async_demo())
        else:
            print("\n(Skipping async demo - install aiofiles for async support)")
