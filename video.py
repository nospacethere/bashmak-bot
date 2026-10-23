"""Read display dimensions without changing the downloaded video."""

import io
import logging

import av

logger = logging.getLogger(__name__)


def get_video_dimensions(content: bytes) -> dict:
    try:
        with av.open(io.BytesIO(content)) as container:
            if not container.streams.video:
                raise ValueError("No video stream")
            stream = container.streams.video[0]
            frame = next(container.decode(stream))
            width, height = frame.width, frame.height
            # Telegram needs display dimensions, including non-square pixels.
            sar = stream.sample_aspect_ratio
            if sar and sar > 0:
                if sar > 1:
                    width = round(width * sar)
                else:
                    height = round(height / sar)
            if abs(frame.rotation) % 180 == 90:
                width, height = height, width
            if width <= 0 or height <= 0:
                raise ValueError("Invalid video dimensions")
            return {"width": width, "height": height}
    except (av.FFmpegError, ValueError, StopIteration, OverflowError):
        # Preserve the existing upload path if this format cannot be inspected.
        logger.warning("Could not determine video dimensions; using Telegram detection")
        return {}
