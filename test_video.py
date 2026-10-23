import io
import unittest
import wave
from fractions import Fraction

import av

from video import get_video_dimensions


def make_video(width, height, rotation=0, sar=Fraction(1)):
    content = io.BytesIO()
    with av.open(content, "w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.sample_aspect_ratio = sar
        stream.codec_context.sample_aspect_ratio = sar
        stream.set_display_rotation(rotation)
        frame = av.VideoFrame(width, height, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return content.getvalue()


class VideoDimensionsTests(unittest.TestCase):
    def test_native_dimensions(self):
        for width, height in [(360, 640), (640, 360), (360, 360), (480, 640)]:
            with self.subTest(size=(width, height)):
                self.assertEqual(get_video_dimensions(make_video(width, height)),
                                 {"width": width, "height": height})

    def test_rotation(self):
        for rotation in [90, -90, 180]:
            with self.subTest(rotation=rotation):
                expected = (360, 640) if abs(rotation) == 90 else (640, 360)
                self.assertEqual(get_video_dimensions(make_video(640, 360, rotation)),
                                 dict(zip(("width", "height"), expected)))

    def test_non_square_pixels(self):
        for sar, rotation, expected in [
            (Fraction(2), 0, (640, 240)),
            (Fraction(1, 2), 0, (320, 480)),
            (Fraction(2), 90, (240, 640)),
        ]:
            with self.subTest(sar=sar, rotation=rotation):
                self.assertEqual(get_video_dimensions(make_video(320, 240, rotation, sar)),
                                 dict(zip(("width", "height"), expected)))

    def test_invalid_content_preserves_upload_fallback(self):
        for content in [b"", b"not a video", b"<html>CDN error</html>"]:
            with self.subTest(content=content), self.assertLogs("video", level="WARNING"):
                self.assertEqual(get_video_dimensions(content), {})

    def test_audio_only_preserves_upload_fallback(self):
        content = io.BytesIO()
        with wave.open(content, "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(1600))
        with self.assertLogs("video", level="WARNING"):
            self.assertEqual(get_video_dimensions(content.getvalue()), {})


if __name__ == "__main__":
    unittest.main()
