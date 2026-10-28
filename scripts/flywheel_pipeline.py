"""Normalize unmatched questions and merge duplicate gaps into the review queue."""
import asyncio
import sys

from app.core.flywheel import process_pending


async def main():
    stats = await process_pending(limit=200)
    print(f"Processed {stats['processed']} questions: created {stats['created']} gaps, "
          f"merged {stats['merged']}, skipped for retry {stats['skipped']}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
