import io
import unittest
from bench.smoke import parse_stream


class StreamTests(unittest.TestCase):
    def test_chunks_and_done(self):
        stream = io.BytesIO(b': heartbeat\n\ndata: {"choices":[{"text":"one"}]}\n\ndata: {"choices":[{"text":", two"}]}\n\ndata: [DONE]\n')
        text, first, chunks = parse_stream(stream)
        self.assertEqual((text, chunks), ("one, two", 2))
        self.assertIsInstance(first, float)

    def test_truncated_stream_rejected(self):
        with self.assertRaises(ValueError):
            parse_stream(io.BytesIO(b'data: {"choices":[{"text":"partial"}]}\n'))

    def test_error_rejected(self):
        with self.assertRaises(ValueError):
            parse_stream(io.BytesIO(b'data: {"error":"unknown model"}\n'))

    def test_empty_stream_rejected(self):
        with self.assertRaises(ValueError):
            parse_stream(io.BytesIO(b'data: [DONE]\n'))
